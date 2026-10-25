from flask import Blueprint

bp = Blueprint("transfer", __name__)

from . import routes  # noqa: E402,F401
