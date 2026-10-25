from functools import wraps

from flask import Blueprint, abort
from flask_login import current_user, login_required

bp = Blueprint("admin", __name__)


def admin_required(view):
    """Réserve une vue aux administrateurs (403 pour les autres utilisateurs connectés)."""
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)
    return wrapper


from . import routes  # noqa: E402,F401
