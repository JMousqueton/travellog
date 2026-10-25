from datetime import date

from flask import abort, current_app, jsonify, redirect, render_template, request, url_for
from flask_login import current_user

from ..extensions import db
from ..countries import country_name
from ..i18n import LANGUAGES, current_locale
from ..utils import is_safe_redirect
from . import bp


@bp.route("/lang/<code>")
def set_language(code):
    """Change la langue et revient sur la page d'origine (filtres compris)."""
    if code not in LANGUAGES:
        abort(404)
    target = request.args.get("next", "")
    if not is_safe_redirect(target):
        target = url_for("trips.index")
    if current_user.is_authenticated:
        current_user.locale = code
        db.session.commit()
    response = redirect(target)
    response.set_cookie(
        current_app.config["LANG_COOKIE_NAME"],
        code,
        max_age=current_app.config["LANG_COOKIE_MAX_AGE"],
        samesite="Lax",
        secure=request.is_secure,
    )
    return response


@bp.route("/theme", methods=["POST"])
def set_theme():
    """Mémorise le thème dans le profil (le navigateur le garde aussi en localStorage)."""
    data = request.get_json(silent=True) or {}
    theme = data.get("theme")
    if theme not in ("light", "dark", None):
        abort(400)
    if current_user.is_authenticated:
        current_user.theme = theme
        db.session.commit()
    return jsonify(theme=theme)


def _legal_context():
    cfg = current_app.config
    country = cfg["LEGAL_DATA_COUNTRY"].upper()
    location = ", ".join(p for p in (cfg["LEGAL_DATA_CITY"], country_name(country, current_locale()) if country else "") if p)
    return {
        "publisher": cfg["LEGAL_PUBLISHER_NAME"],
        "contact": cfg["LEGAL_CONTACT_EMAIL"],
        "host": {"name": cfg["LEGAL_HOST_NAME"], "address": cfg["LEGAL_HOST_ADDRESS"], "phone": cfg["LEGAL_HOST_PHONE"]},
        "location": location,
        "source_url": cfg["SOURCE_URL"],
        "updated": date.fromisoformat(cfg["LEGAL_UPDATED"]),
        "log_days": cfg["LEGAL_LOG_RETENTION_DAYS"],
        "backup_days": cfg["BACKUP_KEEP"],
        "geocode_days": cfg["GEOCODE_CACHE_DAYS"],
        "signup_minutes": cfg["SIGNUP_LINK_MAX_AGE"] // 60,
        "reset_minutes": cfg["PASSWORD_RESET_MAX_AGE"] // 60,
        "routing": bool(cfg["ROUTING_URL"]),
        "tile_host": _host(cfg["MAP_TILE_URL"]),
    }


def _host(url):
    from urllib.parse import urlsplit

    return urlsplit(url.replace("{s}.", "")).hostname or url


@bp.route("/legal")
def legal():
    """Mentions légales (loi pour la confiance dans l'économie numérique, art. 6)."""
    return render_template("legal/notice.html", **_legal_context())


@bp.route("/privacy")
def privacy():
    """Politique de confidentialité (RGPD, art. 13)."""
    return render_template("legal/privacy.html", **_legal_context())
