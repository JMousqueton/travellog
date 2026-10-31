from functools import wraps

from flask import Blueprint, current_app, flash, jsonify, redirect, request, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required

bp = Blueprint("billing", __name__, url_prefix="/billing")


def billing_enabled():
    return bool(current_app.config.get("STRIPE_SECRET_KEY"))


def premium_access(user=None):
    """Le compte a-t-il accès aux fonctions Premium ? Toujours vrai si Stripe n'est pas configuré."""
    user = current_user if user is None else user
    return not billing_enabled() or (user.is_authenticated and user.has_premium_access)


def premium_prices():
    """Prix affichés (« 2,00 € », « 12,00 € »), d'après .env."""
    from flask_babel import format_currency

    from .stripe_sync import plan_price

    currency = current_app.config["PREMIUM_CURRENCY"].upper()
    return {plan: format_currency(plan_price(plan), currency) for plan in ("monthly", "yearly")}


def init_app(app):
    # Globals (et non context processor) : utilisables aussi dans les macros importées.
    app.jinja_env.globals.update(billing_enabled=billing_enabled, premium_access=premium_access,
                                 premium_prices=premium_prices)


def premium_required(view):
    """Réserve une vue aux comptes Premium. Sans Stripe configuré, rien n'est réservé."""
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if not premium_access():
            if request.path.startswith("/api/"):
                return jsonify(error=_("Fonction réservée aux abonnés Premium.")), 402
            flash(_("Cette fonction est réservée aux abonnés Premium."), "info")
            return redirect(url_for("billing.index"))
        return view(*args, **kwargs)
    return wrapper


from . import routes  # noqa: E402,F401
