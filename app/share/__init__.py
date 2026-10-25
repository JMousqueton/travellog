from flask import Blueprint

bp = Blueprint("share", __name__)

from . import routes  # noqa: E402,F401
