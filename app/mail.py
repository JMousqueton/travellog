"""Envoi d'e-mails texte par SMTP (bibliothèque standard, sans dépendance)."""
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr

from flask import current_app


def mail_enabled():
    cfg = current_app.config
    return bool(cfg["MAIL_SERVER"]) or cfg.get("DEBUG") or cfg.get("TESTING")


def send_email(to, subject, body, headers=None):
    """Envoie un e-mail (avec d'éventuels en-têtes supplémentaires). Sans MAIL_SERVER : conservé en mémoire
    (tests) ou écrit dans les logs (développement). Renvoie False en cas d'échec, sans lever d'exception."""
    cfg = current_app.config
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = cfg["MAIL_FROM"] or cfg["MAIL_USERNAME"] or "no-reply@localhost"
    message["To"] = to
    # Sans Date ni Message-ID (que le serveur de soumission n'ajoute pas toujours), les filtres
    # anti-spam (rspamd…) rejettent le message.
    message["Date"] = formatdate(localtime=False, usegmt=True)
    message["Message-ID"] = make_msgid(domain=parseaddr(message["From"])[1].rpartition("@")[2] or "localhost")
    for name, value in (headers or {}).items():
        message[name] = value
    message.set_content(body)

    if not cfg["MAIL_SERVER"]:
        if cfg.get("TESTING"):
            current_app.extensions.setdefault("mail_outbox", []).append(message)
        else:
            current_app.logger.warning("MAIL_SERVER non configuré, e-mail non envoyé à %s :\n%s", to, body)
        return True

    try:
        if cfg["MAIL_USE_SSL"]:
            smtp = smtplib.SMTP_SSL(cfg["MAIL_SERVER"], cfg["MAIL_PORT"], timeout=cfg["MAIL_TIMEOUT"],
                                    context=ssl.create_default_context())
        else:
            smtp = smtplib.SMTP(cfg["MAIL_SERVER"], cfg["MAIL_PORT"], timeout=cfg["MAIL_TIMEOUT"])
        with smtp:
            if cfg["MAIL_USE_TLS"] and not cfg["MAIL_USE_SSL"]:
                smtp.starttls(context=ssl.create_default_context())
            if cfg["MAIL_USERNAME"]:
                smtp.login(cfg["MAIL_USERNAME"], cfg["MAIL_PASSWORD"])
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException):
        current_app.logger.exception("Échec de l'envoi d'un e-mail à %s", to)
        return False
    return True
