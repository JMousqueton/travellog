"""E-mails des tickets : aux administrateurs pour un message d'utilisateur, à l'utilisateur pour une réponse.
Chacun peut les désactiver : l'utilisateur pour chaque ticket, l'administrateur pour tous."""
from flask import current_app, render_template
from flask_babel import force_locale
from flask_babel import gettext as _

from ..auth.routes import _external_url
from ..extensions import db
from ..mail import send_email
from ..models import User


def notify_staff(ticket, message):
    """Prévient chaque administrateur (dans sa langue) d'un nouveau ticket ou d'une réponse de l'utilisateur."""
    admins = db.session.execute(
        db.select(User).filter(User.is_admin, User.ticket_emails, User.id != message.author_id)
    ).scalars()
    url = _external_url("admin.ticket", ticket_id=ticket.id)
    for admin in admins:
        with force_locale(admin.locale):
            subject = _("[Support] Ticket n° %(id)s : %(subject)s", id=ticket.id, subject=ticket.subject)
            body = render_template("support/email/to_staff.txt", ticket=ticket, message=message, url=url,
                                   new=len(ticket.messages) == 1)
        send_email(admin.email, subject, body)


def notify_user(ticket, message):
    """Prévient l'utilisateur, dans sa langue, d'une réponse du support (s'il l'a demandé pour ce ticket)."""
    if not ticket.notify:
        return
    user = ticket.user
    with force_locale(user.locale):
        subject = _("Réponse du support : %(subject)s", subject=ticket.subject)
        body = render_template("support/email/to_user.txt", ticket=ticket, message=message,
                               url=_external_url("support.ticket", ticket_id=ticket.id),
                               site=current_app.config["SITE_NAME"])
    send_email(user.email, subject, body)
