"""Relève de la boîte IMAP : chaque e-mail est traité une fois, supprimé s'il a été importé."""
import email
import imaplib
import ssl
from email import policy

from flask import current_app

from ..extensions import db
from ..models import MailImport
from .processing import Outcome, message_key, process


def run(dry_run=False):
    """Traite chaque e-mail de la boîte ; renvoie le nombre d'e-mails par statut.
    En simulation (dry_run), rien n'est écrit ni supprimé et la boîte est ouverte en lecture seule."""
    cfg = current_app.config
    counts = {}
    conn = imaplib.IMAP4_SSL(cfg["IMAP_SERVER"], cfg["IMAP_PORT"], timeout=cfg["IMAP_TIMEOUT"],
                             ssl_context=ssl.create_default_context())
    with conn:
        conn.login(cfg["IMAP_USERNAME"], cfg["IMAP_PASSWORD"])
        conn.select(cfg["IMAP_FOLDER"], readonly=dry_run)
        _typ, data = conn.uid("SEARCH", None, "ALL")
        deleted = []
        for uid in data[0].split():
            outcome = _process_uid(conn, uid, dry_run)
            counts[outcome.status] = counts.get(outcome.status, 0) + 1
            if dry_run:
                current_app.logger.info("E-mail %s : %s %s %s", uid.decode(), outcome.status, outcome.reason,
                                        [_summary(r) for r in outcome.records])
            elif outcome.delete:
                conn.uid("STORE", uid, "+FLAGS", r"(\Deleted)")
                deleted.append(uid)
        if deleted:
            if "UIDPLUS" in conn.capabilities:
                conn.uid("EXPUNGE", b",".join(deleted))
            else:
                conn.expunge()
    return counts


def _summary(record):
    return f"{record['depart_date']} {record['origin_name']} → {record['dest_name']} ({record['transport_mode']})"


def _fetch(conn, uid, what):
    _typ, parts = conn.uid("FETCH", uid, f"(BODY.PEEK[{what}])")
    return next((p[1] for p in parts or [] if isinstance(p, tuple)), b"")


def _process_uid(conn, uid, dry_run):
    # L'en-tête suffit pour reconnaître un e-mail déjà traité, sans retélécharger ses pièces jointes.
    header = email.message_from_bytes(_fetch(conn, uid, "HEADER.FIELDS (MESSAGE-ID)"), policy=policy.default)
    key = message_key(header.get("Message-ID"), None)
    if key is not None:
        done = db.session.execute(db.select(MailImport).filter_by(message_key=key)).scalar_one_or_none()
        if done is not None:  # e-mail importé dont la suppression avait échoué : on le supprime maintenant
            return Outcome("done", delete=done.status == "imported")
    return process(_fetch(conn, uid, ""), dry_run=dry_run)
