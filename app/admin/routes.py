from datetime import timedelta

from flask import abort, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user

from ..auth.forms import PublicProfileForm
from ..extensions import db
from ..mail_import.processing import forget_user
from ..models import Setting, Ticket, Trip, User, registration_open, utcnow
from ..support.forms import ReplyForm
from ..support.notify import notify_user
from . import admin_required, bp
from .forms import SettingsForm


@bp.route("/")
@admin_required
def users():
    trip_count = db.func.count(Trip.id).label("trip_count")
    rows = db.session.execute(
        db.select(User, trip_count).outerjoin(Trip).group_by(User.id).order_by(User.created_at.desc())
    ).all()
    return render_template("admin/users.html", rows=rows)


@bp.route("/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def delete_user(user_id):
    """Supprime un compte et toutes ses données (voyages et trajets)."""
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)
    if user.id == current_user.id:
        flash(_("Vous ne pouvez pas supprimer votre propre compte."), "danger")
        return redirect(url_for("admin.users"))
    email = user.email
    forget_user(user)
    db.session.delete(user)
    db.session.commit()
    flash(_("Le compte %(email)s a été supprimé.", email=email), "success")
    return redirect(url_for("admin.users"))


def _user_or_404(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)
    return user


@bp.route("/users/<int:user_id>/block", methods=["POST"])
@admin_required
def toggle_block(user_id):
    """Bloque ou débloque un compte : bloqué, il ne peut plus se connecter et ses sessions sont fermées."""
    user = _user_or_404(user_id)
    if user.id == current_user.id:
        flash(_("Vous ne pouvez pas bloquer votre propre compte."), "danger")
        return redirect(url_for("admin.users"))
    user.is_blocked = not user.is_blocked
    db.session.commit()
    flash(_("Le compte %(email)s est bloqué.", email=user.email) if user.is_blocked
          else _("Le compte %(email)s est débloqué.", email=user.email), "success")
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:user_id>/name", methods=["POST"])
@admin_required
def set_public_name(user_id):
    """Change ou retire (nom vide) le nom du profil public d'un utilisateur."""
    user = _user_or_404(user_id)
    form = PublicProfileForm(prefix="name", user=user)
    if form.validate_on_submit():
        user.public_name = form.public_name.data or None
        db.session.commit()
        flash(_("Nom du profil public de %(email)s : %(name)s.", email=user.email, name=user.public_name)
              if user.public_name else _("Profil public de %(email)s désactivé.", email=user.email), "success")
    else:
        for error in form.public_name.errors or [_("Requête invalide")]:
            flash(error, "danger")
    return redirect(url_for("admin.users"))


@bp.route("/settings", methods=["GET", "POST"])
@admin_required
def settings():
    form = SettingsForm()
    if request.method == "GET":
        form.registration_open.data = registration_open()
    if form.validate_on_submit():
        Setting.set("registration_open", "1" if form.registration_open.data else "0")
        db.session.commit()
        flash(_("Paramètres enregistrés."), "success")
        return redirect(url_for("admin.settings"))
    return render_template("admin/settings.html", form=form)


@bp.route("/jobs")
@admin_required
def jobs():
    """Tâches périodiques : dernière exécution, retards, échecs, et les dernières exécutions."""
    from ..jobs import job_overview
    from ..models import JobRun, MailImport

    recent = db.session.execute(
        db.select(JobRun).filter(db.or_(JobRun.name != "mail-import", JobRun.status != "ok"))
        .order_by(JobRun.started_at.desc(), JobRun.id.desc()).limit(30)).scalars().all()
    since = utcnow() - timedelta(days=1)
    mail_counts = dict(db.session.execute(
        db.select(MailImport.status, db.func.count(MailImport.id)).filter(MailImport.created_at >= since)
        .group_by(MailImport.status)).all())
    return render_template("admin/jobs.html", overview=job_overview(), recent=recent, mail_counts=mail_counts)


# Onglets de la liste des tickets : « à traiter » d'abord.
TICKET_FILTERS = ("open", "answered", "closed", "all")


@bp.app_context_processor
def inject_ticket_count():
    # Fonction : la requête n'est faite que là où le gabarit l'appelle (onglet Tickets).
    def open_ticket_count():
        return db.session.scalar(db.select(db.func.count(Ticket.id)).filter_by(status="open"))
    return {"open_ticket_count": open_ticket_count}


@bp.route("/tickets")
@admin_required
def tickets():
    status = request.args.get("status", "open")
    if status not in TICKET_FILTERS:
        status = "open"
    query = db.select(Ticket).order_by(Ticket.updated_at.desc())
    if status != "all":
        query = query.filter_by(status=status)
    return render_template("admin/tickets.html", tickets=db.session.execute(query).scalars().all(),
                           status=status, filters=TICKET_FILTERS)


def _ticket_or_404(ticket_id):
    ticket = db.session.get(Ticket, ticket_id)
    if ticket is None:
        abort(404)
    return ticket


@bp.route("/tickets/<int:ticket_id>", methods=["GET", "POST"])
@admin_required
def ticket(ticket_id):
    ticket = _ticket_or_404(ticket_id)
    form = ReplyForm()
    if form.validate_on_submit():
        message = ticket.add_message(current_user, form.body.data.strip(), from_staff=True)
        db.session.commit()
        notify_user(ticket, message)
        flash(_("Réponse envoyée à %(email)s.", email=ticket.user.email), "success")
        return redirect(url_for("admin.ticket", ticket_id=ticket.id))
    return render_template("admin/ticket.html", ticket=ticket, form=form)


@bp.route("/tickets/<int:ticket_id>/status", methods=["POST"])
@admin_required
def ticket_status(ticket_id):
    """Ferme ou rouvre un ticket (sans prévenir l'utilisateur)."""
    ticket = _ticket_or_404(ticket_id)
    status = request.form.get("status")
    if status not in ("open", "closed"):
        abort(400)
    ticket.status = status
    ticket.updated_at = utcnow()
    db.session.commit()
    flash(_("Ticket fermé.") if status == "closed" else _("Ticket rouvert."), "success")
    return redirect(url_for("admin.tickets") if status == "closed" else url_for("admin.ticket", ticket_id=ticket.id))


@bp.route("/tickets/notifications", methods=["POST"])
@admin_required
def ticket_notifications():
    """Active ou coupe, pour l'administrateur connecté, les e-mails des nouveaux messages de tickets."""
    current_user.ticket_emails = request.form.get("enabled") == "1"
    db.session.commit()
    flash(_("Vous recevrez un e-mail à chaque nouveau message de ticket.") if current_user.ticket_emails
          else _("Vous ne recevrez plus d'e-mail pour les tickets."), "success")
    return redirect(url_for("admin.tickets"))
