from flask import abort, current_app, jsonify, redirect, request, url_for
from flask_login import current_user

from ..extensions import db
from ..i18n import LANGUAGES
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
