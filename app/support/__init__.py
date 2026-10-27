from flask import Blueprint

bp = Blueprint("support", __name__)

from . import routes  # noqa: E402,F401
