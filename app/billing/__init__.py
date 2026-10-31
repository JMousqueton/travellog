from functools import wraps

from flask import Blueprint, current_app, flash, jsonify, redirect, request, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required

bp = Blueprint("billing", __name__, url_prefix="/billing")


def billing_enabled():
    return bool(current_app.config.get("STRIPE_SECRET_KEY"))


def premium_required(view):
    """Réserve une vue aux comptes Premium. Sans Stripe configuré, rien n'est réservé."""
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if billing_enabled() and not current_user.is_premium:
            if request.path.startswith("/api/"):
                return jsonify(error=_("Fonction réservée aux abonnés Premium.")), 402
            flash(_("Cette fonction est réservée aux abonnés Premium."), "info")
            return redirect(url_for("billing.index"))
        return view(*args, **kwargs)
    return wrapper


from . import routes  # noqa: E402,F401
