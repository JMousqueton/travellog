from flask import Blueprint

bp = Blueprint("trips", __name__)

from . import routes  # noqa: E402,F401
