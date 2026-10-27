"""Les migrations ne doivent jamais perdre de données (régression : la reconstruction SQLite de `users`
vidait les tables enfants par ON DELETE CASCADE)."""
import sqlite3

from flask_migrate import upgrade

from app import create_app
from config import TestingConfig

BEFORE_USERS_REBUILD = "af441a0a75ff"  # la révision suivante recrée la table users


def test_migrations_keep_existing_trips(tmp_path, monkeypatch):
    path = tmp_path / "travel.db"
    monkeypatch.setattr(TestingConfig, "SQLALCHEMY_DATABASE_URI", f"sqlite:///{path}")
    app = create_app("testing")
    with app.app_context():
        upgrade(revision=BEFORE_USERS_REBUILD)
        db = sqlite3.connect(path)
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("INSERT INTO users (id, email, password_hash, locale, is_admin, created_at) "
                   "VALUES (1, 'a@example.com', 'x', 'fr', 0, '2025-01-01')")
        db.execute("INSERT INTO journeys (id, user_id, created_at) VALUES (1, 1, '2025-01-01')")
        db.execute("INSERT INTO trips (user_id, origin_name, origin_lat, origin_lon, dest_name, dest_lat, dest_lon, "
                   "depart_date, transport_mode, is_round_trip, journey_id, created_at) VALUES "
                   "(1, 'Paris', 48.85, 2.35, 'Lyon', 45.76, 4.83, '2025-05-01', 'train', 0, 1, '2025-01-01')")
        db.execute("INSERT INTO share_links (user_id, token, created_at) VALUES (1, 'tok', '2025-01-01')")
        db.commit()
        db.close()

        upgrade()  # jusqu'à la dernière révision

    db = sqlite3.connect(path)
    counts = {t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("users", "trips", "journeys", "share_links")}
    assert counts == {"users": 1, "trips": 1, "journeys": 1, "share_links": 1}
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert {"tickets", "ticket_messages"} <= {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
