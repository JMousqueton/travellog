"""Tâches périodiques : `flask jobs run <tâche>`, lancée par un timer systemd (deploy/systemd).

Chaque exécution est notée dans job_runs (début, fin, résultat, erreur) : l'onglet Tâches de l'administration
montre la dernière exécution de chacune et signale celles en échec ou en retard. L'historique est purgé
après JOB_HISTORY_DAYS jours.
"""
import traceback
from dataclasses import dataclass
from datetime import timedelta

from flask import current_app
from flask_babel import lazy_gettext as _l

from .extensions import db
from .models import JobRun, as_utc, utcnow

JOB_HISTORY_DAYS = 14


class Skipped(Exception):
    """Tâche sans objet (fonction désactivée par la configuration) : notée « skipped », pas en échec."""


@dataclass(frozen=True)
class Job:
    name: str
    every: timedelta   # intervalle prévu par le timer : au-delà de deux fois, la tâche est « en retard »
    func: callable
    description: object  # texte traduit à l'affichage (lazy_gettext)


def _mail_import():
    from .mail_import import run

    if not current_app.config["IMAP_SERVER"]:
        raise Skipped("IMAP_SERVER n'est pas configuré")
    counts = run()
    return " · ".join(f"{status} : {n}" for status, n in sorted(counts.items())) or "Boîte vide"


def _backup():
    import os

    from .backup import create_backup, read_manifest

    path = create_backup(None, current_app.config["BACKUP_KEEP"])
    counts = read_manifest(path)["counts"]
    return (f"{os.path.basename(path)} ({os.path.getsize(path) // 1024} Ko) : "
            + ", ".join(f"{n} {t}" for t, n in counts.items() if n is not None))


def _maintenance():
    from .geo import purge_geocode_cache
    from .models import ShareLink

    from .mail_import.processing import purge_log

    geocode = purge_geocode_cache()
    mails = purge_log(current_app.config["MAIL_IMPORT_LOG_DAYS"])
    links = db.session.execute(db.delete(ShareLink).where(ShareLink.expires_at <= utcnow())).rowcount
    history = db.session.execute(
        db.delete(JobRun).where(JobRun.started_at < utcnow() - timedelta(days=JOB_HISTORY_DAYS))).rowcount
    db.session.commit()
    summary = (f"{geocode} géocodage(s) expiré(s), {links} lien(s) de partage expiré(s), {mails} e-mail(s) d'import "
               f"anciens, {history} exécution(s) anciennes")
    if current_app.config["STRIPE_SECRET_KEY"]:
        summary += f", {_resync_expired_subscriptions()} abonnement(s) relu(s)"
    return summary


def _resync_expired_subscriptions():
    """Filet de sécurité si un webhook s'est perdu : les abonnements « en cours » dont la période est passée
    sont relus chez Stripe (renouvelés, ou terminés)."""
    from .billing.stripe_sync import sync_customer
    from .models import User

    stale = db.session.execute(db.select(User.stripe_customer_id).filter(
        User.stripe_customer_id.is_not(None), User.subscription_status.in_(User.PREMIUM_STATUSES),
        User.premium_until < utcnow())).scalars().all()
    for customer_id in stale:
        sync_customer(customer_id)
    db.session.commit()
    return len(stale)


JOBS = {job.name: job for job in (
    Job("mail-import", timedelta(minutes=5), _mail_import, _l("Import par e-mail (boîte IMAP)")),
    Job("backup", timedelta(days=1), _backup, _l("Sauvegarde complète (base + photos)")),
    Job("maintenance", timedelta(days=1), _maintenance,
        _l("Purge du cache de géocodage, des liens de partage expirés, du journal des imports par e-mail et de l'historique des tâches")),
)}


def run_job(name):
    """Exécute la tâche et note son résultat ; renvoie l'exécution (JobRun)."""
    job = JOBS[name]
    record = JobRun(name=name, status="running")
    db.session.add(record)
    db.session.commit()
    try:
        summary = job.func()
        status = "ok"
        error = None
    except Skipped as exc:
        db.session.rollback()
        status, summary, error = "skipped", str(exc), None
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Tâche %s en échec", name)
        status, summary, error = "failed", f"{type(exc).__name__} : {exc}", traceback.format_exc()
    record = db.session.get(JobRun, record.id)
    record.status, record.summary, record.error = status, (summary or "")[:255] or None, error
    record.finished_at = utcnow()
    db.session.commit()
    return record


def job_overview(now=None):
    """Pour chaque tâche : (tâche, dernière exécution, dernier succès, en retard ?, échecs sur 24 h)."""
    now = now or utcnow()
    rows = []
    for job in JOBS.values():
        runs = db.select(JobRun).filter_by(name=job.name).order_by(JobRun.started_at.desc(), JobRun.id.desc())
        last = db.session.execute(runs.limit(1)).scalar_one_or_none()
        last_ok = db.session.execute(runs.filter(JobRun.status.in_(("ok", "skipped"))).limit(1)).scalar_one_or_none()
        late = last_ok is None or as_utc(last_ok.started_at) < now - 2 * job.every - timedelta(minutes=5)
        failures = db.session.execute(db.select(db.func.count(JobRun.id)).filter(
            JobRun.name == job.name, JobRun.status == "failed",
            JobRun.started_at >= now - timedelta(days=1))).scalar()
        rows.append((job, last, last_ok, late, failures))
    return rows
