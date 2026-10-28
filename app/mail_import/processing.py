"""Traitement d'un e-mail : expéditeur reconnu et authentifié, trajets ajoutés ou ticket d'échec, compte rendu."""
import email
import hashlib
from dataclasses import dataclass, field
from email import policy
from email.utils import parseaddr

from flask import current_app
from sqlalchemy import func

from ..extensions import db
from ..geo import haversine_km
from ..models import ImportAddress, MailImport, Ticket, User
from ..transfer.formats import SAME_PLACE_KM
from .authentication import dkim_aligned
from .extract import extract_trips

MAX_RAW_CHARS = 100_000  # e-mail brut recopié dans le ticket (au-delà : tronqué)


@dataclass
class Outcome:
    status: str                      # imported, failed, ignored ou done (déjà traité)
    delete: bool = False             # supprimer l'e-mail de la boîte
    reason: str = ""
    records: list = field(default_factory=list)


def message_key(message_id, raw):
    if message_id and message_id.strip():
        return hashlib.sha256(b"mid:" + message_id.strip().encode("utf-8", "replace")).hexdigest()
    return hashlib.sha256(raw).hexdigest() if raw is not None else None


def process(raw, dry_run=False):
    msg = email.message_from_bytes(raw, policy=policy.default)
    key = message_key(msg.get("Message-ID"), raw)
    done = db.session.execute(db.select(MailImport).filter_by(message_key=key)).scalar_one_or_none()
    if done is not None:
        return Outcome("done", delete=done.status == "imported")

    sender = parseaddr(str(msg.get("From", "")))[1].strip().lower()
    subject = str(msg.get("Subject", "")).strip()
    user = account_for(sender)
    if not sender or user is None or user.email == current_app.config["MAIL_IMPORT_ERROR_EMAIL"]:
        return _finish(Outcome("ignored", reason="expéditeur inconnu"), key, sender, subject, None, dry_run)
    if current_app.config["MAIL_IMPORT_REQUIRE_DKIM"] and not dkim_aligned(raw, sender.rpartition("@")[2]):
        return _finish(Outcome("ignored", reason="signature DKIM absente, invalide ou d'un autre domaine"),
                       key, sender, subject, user, dry_run)

    try:
        records, problems = extract_trips(msg, user.locale)
    except Exception as exc:  # e-mail inattendu : traité comme un échec (un ticket, une fois)
        current_app.logger.exception("Lecture de l'e-mail %s impossible", key)
        records, problems = [], [f"erreur interne : {exc!r}"]
    if not records:
        reason = "; ".join(problems) or "aucun trajet reconnu dans l'e-mail"
        outcome = Outcome("failed", reason=reason[:255])
    else:
        outcome = Outcome("imported", delete=True, records=records)
    if dry_run:
        return outcome

    entry = None
    if outcome.status == "imported":
        entry = _save_trips(user, records)
    else:
        entry = _open_ticket(raw, sender, subject, user, outcome.reason)
    return _finish(outcome, key, sender, subject, user, dry_run, **entry)


def account_for(sender):
    """Compte de l'expéditeur : celui dont c'est l'adresse, ou à qui elle est confirmée comme adresse d'import."""
    user = db.session.execute(db.select(User).filter(func.lower(User.email) == sender)).scalar_one_or_none()
    if user is None:
        address = db.session.execute(db.select(ImportAddress).filter_by(email=sender)).scalar_one_or_none()
        user = address.user if address else None
    return user


def _finish(outcome, key, sender, subject, user, dry_run, added=(), duplicates=(), ticket=None):
    if dry_run:
        return outcome
    db.session.add(MailImport(message_key=key, status=outcome.status, sender=sender[:255] or None,
                              subject=subject[:200] or None, reason=outcome.reason[:255] or None,
                              trip_count=len(added), user_id=user.id if user else None,
                              ticket_id=ticket.id if ticket else None))
    db.session.commit()
    if outcome.status in ("imported", "failed"):
        # Lancé par cron, hors requête : les liens sont construits sur l'adresse publique.
        with current_app.test_request_context(base_url=current_app.config["APP_BASE_URL"] or None):
            if ticket is not None:
                from ..support.notify import notify_staff

                notify_staff(ticket, ticket.messages[0])
            _reply(sender, subject, user, added, duplicates, failed=ticket is not None)
    return outcome


def _reply(sender, subject, user, added, duplicates, failed):
    """Compte rendu à l'expéditeur, dans la langue du compte : trajets ajoutés, déjà enregistrés, ou e-mail
    transmis à l'équipe pour un import manuel. Jamais aux expéditeurs ignorés (pas de rétrodiffusion)."""
    from flask import render_template
    from flask_babel import force_locale
    from flask_babel import gettext as _

    from ..auth.routes import _external_url
    from ..mail import send_email

    with force_locale(user.locale):
        if failed:
            title = _("Import impossible : %(subject)s", subject=subject)
        elif added:
            title = _("Voyages importés : %(subject)s", subject=subject)
        else:
            title = _("Voyages déjà enregistrés : %(subject)s", subject=subject)
        body = render_template("mail_import/result.txt", subject=subject, failed=failed,
                               added=[_trip_line(r) for r in added], duplicates=[_trip_line(r) for r in duplicates],
                               url=_external_url("trips.list_view"), site=current_app.config["SITE_NAME"])
    send_email(sender, title[:200], body, headers={"Auto-Submitted": "auto-replied"})


def _trip_line(record):
    """« 10 nov. 2026 → 10 nov. 2026 · CDG ⇄ MUC · AF1722 / AF1823 » dans la langue active."""
    from flask_babel import format_date

    from ..trips.stats import short_place

    days = format_date(record["depart_date"], "medium")
    if record["return_date"] and record["return_date"] != record["depart_date"]:
        days += " → " + format_date(record["return_date"], "medium")
    arrow = " ⇄ " if record["return_date"] else " → "
    parts = [days, short_place(record["origin_name"]) + arrow + short_place(record["dest_name"])]
    return " · ".join(parts + [v for v in (record["service_number"], record["carrier"]) if v])


def _legs(trip):
    """Sens effectués [(mode, date, (lat, lon) de départ, d'arrivée)] d'un trajet ou d'une ligne validée."""
    get = trip.get if isinstance(trip, dict) else lambda key: getattr(trip, key)
    origin, dest = (get("origin_lat"), get("origin_lon")), (get("dest_lat"), get("dest_lon"))
    legs = [(get("transport_mode"), get("depart_date"), origin, dest)]
    if get("return_date"):
        legs.append((get("transport_mode"), get("return_date"), dest, origin))
    return legs


def _same_leg(a, b):
    return (a[0] == b[0] and a[1] == b[1] and haversine_km(*a[2], *b[2]) <= SAME_PLACE_KM
            and haversine_km(*a[3], *b[3]) <= SAME_PLACE_KM)


def _save_trips(user, records):
    """Ajoute les trajets, sauf ceux dont un sens est déjà enregistré (même mode, même jour, mêmes lieux à
    SAME_PLACE_KM près, aller ou retour d'un aller-retour compris) : l'import est quand même réussi."""
    from ..transfer.routes import new_trip

    existing = [leg for trip in user.trips for leg in _legs(trip)]
    added, duplicates = [], []
    for record in records:
        legs = _legs(record)
        if any(_same_leg(leg, known) for leg in legs for known in existing):
            duplicates.append(record)
            continue
        existing.extend(legs)
        db.session.add(new_trip(user, record))
        added.append(record)
    db.session.flush()
    return {"added": added, "duplicates": duplicates}


def import_error_account():
    """Compte « Import Error » qui ouvre les tickets d'échec. Il ne peut pas se connecter (mot de passe
    inutilisable) et son adresse en .invalid ne reçoit rien."""
    address = current_app.config["MAIL_IMPORT_ERROR_EMAIL"]
    account = db.session.execute(db.select(User).filter_by(email=address)).scalar_one_or_none()
    if account is None:
        account = User(email=address, password_hash="!", ticket_emails=False)
        db.session.add(account)
        db.session.flush()
    return account


def _open_ticket(raw, sender, subject, user, reason):
    account = import_error_account()
    text = raw.decode("utf-8", "replace")
    if len(text) > MAX_RAW_CHARS:
        text = text[:MAX_RAW_CHARS] + f"\n[… e-mail tronqué : {len(raw)} octets au total]"
    body = (f"Import par e-mail impossible : {reason}\n\n"
            f"Expéditeur : {sender}\nCompte : {user.email} (n° {user.id})\nObjet : {subject}\n\n"
            f"--- E-mail brut ---\n{text}")
    ticket = Ticket(user_id=account.id, subject=f"Import Error : {subject or '(sans objet)'}"[:200], notify=False)
    db.session.add(ticket)
    ticket.add_message(account, body, from_staff=False)
    db.session.flush()
    return {"ticket": ticket}


def forget_user(user):
    """À la suppression d'un compte : ses entrées du journal d'import et les tickets d'échec qui contiennent
    ses e-mails bruts sont supprimés aussi."""
    entries = db.session.execute(db.select(MailImport).filter_by(user_id=user.id)).scalars().all()
    for entry in entries:
        if entry.ticket_id is not None:
            ticket = db.session.get(Ticket, entry.ticket_id)
            if ticket is not None:
                db.session.delete(ticket)
        db.session.delete(entry)


def purge_log(days):
    """Supprime les entrées « imported » et « ignored » de plus de `days` jours ; renvoie leur nombre."""
    from datetime import timedelta

    from ..models import utcnow

    return db.session.execute(db.delete(MailImport).where(
        MailImport.status.in_(("imported", "ignored")),
        MailImport.created_at < utcnow() - timedelta(days=days))).rowcount
