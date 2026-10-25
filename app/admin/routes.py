from flask import abort, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user

from ..extensions import db
from ..models import Setting, Trip, User, registration_open
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
    db.session.delete(user)
    db.session.commit()
    flash(_("Le compte %(email)s a été supprimé.", email=email), "success")
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
