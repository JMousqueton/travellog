"""Les migrations ne doivent jamais perdre de données et doivent aboutir au schéma des modèles."""
import pytest
from flask_migrate import upgrade
from sqlalchemy import create_engine, text

from app import create_app
from app.extensions import db
from config import TestingConfig

BEFORE_USERS_REBUILD = "af441a0a75ff"  # la révision suivante modifie la table users


def test_migrations_keep_existing_trips(empty_database, monkeypatch):
    monkeypatch.setattr(TestingConfig, "SQLALCHEMY_DATABASE_URI", empty_database)
    app = create_app("testing")
    with app.app_context():
        upgrade(revision=BEFORE_USERS_REBUILD)
        with db.engine.begin() as conn:
            conn.execute(text("INSERT INTO users (id, email, password_hash, locale, is_admin, created_at) "
                              "VALUES (1, 'a@example.com', 'x', 'fr', false, '2025-01-01')"))
            conn.execute(text("INSERT INTO journeys (id, user_id, created_at) VALUES (1, 1, '2025-01-01')"))
            conn.execute(text(
                "INSERT INTO trips (user_id, origin_name, origin_lat, origin_lon, dest_name, dest_lat, dest_lon, "
                "depart_date, transport_mode, is_round_trip, journey_id, created_at) VALUES "
                "(1, 'Paris', 48.85, 2.35, 'Lyon', 45.76, 4.83, '2025-05-01', 'train', false, 1, '2025-01-01')"))
            conn.execute(text("INSERT INTO share_links (user_id, token, created_at) VALUES (1, 'tok', '2025-01-01')"))

        upgrade()  # jusqu'à la dernière révision

        with db.engine.connect() as conn:
            counts = {t: conn.execute(text(f"SELECT count(*) FROM {t}")).scalar()
                      for t in ("users", "trips", "journeys", "share_links")}
            tables = set(conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")).scalars())
        db.engine.dispose()
    assert counts == {"users": 1, "trips": 1, "journeys": 1, "share_links": 1}
    assert {"tickets", "ticket_messages"} <= tables


def test_migrations_match_models(empty_database, monkeypatch):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    monkeypatch.setattr(TestingConfig, "SQLALCHEMY_DATABASE_URI", empty_database)
    app = create_app("testing")
    with app.app_context():
        upgrade()
        with db.engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn), db.metadata)
        db.engine.dispose()
    assert diff == []


@pytest.mark.parametrize("url", ["", "sqlite:///travel.db"])
def test_database_must_be_postgresql(monkeypatch, url):
    monkeypatch.setattr(TestingConfig, "SQLALCHEMY_DATABASE_URI", url)
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        create_app("testing")


def test_postgres_scheme_uses_psycopg(monkeypatch):
    from config import _database_url

    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@localhost/travel")
    assert _database_url("DATABASE_URL") == "postgresql+psycopg://u:p@localhost/travel"
    assert create_engine(_database_url("DATABASE_URL")).dialect.driver == "psycopg"
