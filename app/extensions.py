import sqlite3

from flask_babel import Babel
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from sqlalchemy import MetaData, event
from sqlalchemy.engine import Engine

# Nommage explicite des contraintes : indispensable pour les migrations SQLite (mode batch).
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

db = SQLAlchemy(metadata=MetaData(naming_convention=NAMING_CONVENTION))
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()
babel = Babel()
# Aucune limite globale : seules les vues décorées (connexion, inscription…) sont limitées.
limiter = Limiter(key_func=get_remote_address)


# Attente maximale d'un verrou d'écriture (gunicorn à plusieurs threads, tâches cron en parallèle).
SQLITE_BUSY_TIMEOUT_MS = 15_000


@event.listens_for(Engine, "connect")
def _configure_sqlite(dbapi_connection, _record):
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        # WAL : les lectures ne bloquent plus l'écriture (et inversement). Le mode est enregistré dans le fichier
        # (une base en mémoire reste en « memory ») ; synchronous=NORMAL suffit en WAL, sans risque de corruption.
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()
