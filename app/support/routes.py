from flask import abort, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user

from ..billing import premium_required
from ..extensions import db, limiter
from ..models import Ticket, utcnow
from . import bp
from .forms import ReplyForm, TicketForm
from .notify import notify_staff

# Contre l'envoi en masse (chaque message part par e-mail aux administrateurs).
POST_LIMIT = "20 per hour"


def _own_ticket(ticket_id):
    ticket = db.session.get(Ticket, ticket_id)
    if ticket is None or ticket.user_id != current_user.id:
        abort(404)
    return ticket


@bp.route("/support", methods=["GET", "POST"])
@premium_required
@limiter.limit(POST_LIMIT, methods=["POST"])
def index():
    """Mes demandes, et le formulaire pour en ouvrir une nouvelle."""
    form = TicketForm()
    if form.validate_on_submit():
        ticket = Ticket(user_id=current_user.id, subject=form.subject.data.strip(), notify=form.notify.data)
        db.session.add(ticket)
        message = ticket.add_message(current_user, form.body.data.strip(), from_staff=False)
        db.session.commit()
        notify_staff(ticket, message)
        flash(_("Votre demande a été envoyée. Vous recevrez la réponse par e-mail.") if ticket.notify
              else _("Votre demande a été envoyée. La réponse apparaîtra sur cette page."), "success")
        return redirect(url_for("support.ticket", ticket_id=ticket.id))
    tickets = current_user.tickets.order_by(Ticket.updated_at.desc()).all()
    return render_template("support/index.html", form=form, tickets=tickets)


@bp.route("/support/<int:ticket_id>", methods=["GET", "POST"])
@premium_required
@limiter.limit(POST_LIMIT, methods=["POST"])
def ticket(ticket_id):
    ticket = _own_ticket(ticket_id)
    form = ReplyForm()
    if form.validate_on_submit():
        message = ticket.add_message(current_user, form.body.data.strip(), from_staff=False)  # rouvre si fermé
        db.session.commit()
        notify_staff(ticket, message)
        flash(_("Message envoyé."), "success")
        return redirect(url_for("support.ticket", ticket_id=ticket.id))
    return render_template("support/ticket.html", ticket=ticket, form=form)


@bp.route("/support/<int:ticket_id>/close", methods=["POST"])
@premium_required
def close(ticket_id):
    ticket = _own_ticket(ticket_id)
    ticket.status = "closed"
    ticket.updated_at = utcnow()
    db.session.commit()
    flash(_("Demande fermée. Vous pouvez la rouvrir en y répondant."), "success")
    return redirect(url_for("support.ticket", ticket_id=ticket.id))


@bp.route("/support/<int:ticket_id>/notify", methods=["POST"])
@premium_required
def notify(ticket_id):
    """Active ou coupe les e-mails de réponse pour ce ticket."""
    ticket = _own_ticket(ticket_id)
    ticket.notify = request.form.get("notify") == "1"
    db.session.commit()
    flash(_("Vous recevrez les réponses à cette demande par e-mail.") if ticket.notify
          else _("Vous ne recevrez plus d'e-mail pour cette demande."), "success")
    return redirect(url_for("support.ticket", ticket_id=ticket.id))
