import os
from datetime import date

import pytest
from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po
from flask import g
from flask_babel import refresh

from app import create_app
from app.extensions import db as _db
from app.models import Trip, User

TRANSLATIONS = os.path.join(os.path.dirname(__file__), "..", "app", "translations")


@pytest.fixture(scope="session", autouse=True)
def compiled_translations():
    """Compile les .po en .mo (les .mo ne sont pas versionnés)."""
    for lang in os.listdir(TRANSLATIONS):
        po = os.path.join(TRANSLATIONS, lang, "LC_MESSAGES", "messages.po")
        if not os.path.isfile(po):
            continue
        with open(po, "rb") as fh:
            catalog = read_po(fh, locale=lang)
        with open(po[:-3] + ".mo", "wb") as fh:
            write_mo(fh, catalog)


@pytest.fixture
def app(tmp_path):
    app = create_app("testing")
    app.config["UPLOAD_FOLDER"] = str(tmp_path / "uploads")
    # Le contexte d'application reste actif pendant tout le test, et Flask-Babel garde la
    # locale en cache dans `g` : on l'invalide à chaque requête, comme en production.
    app.before_request(refresh)
    # Idem pour l'utilisateur mis en cache par Flask-Login (sinon partagé entre deux clients).
    app.before_request(lambda: g.pop("_login_user", None) and None)
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    return _db


def make_user(email="alice@example.com", password="password123", locale="fr"):
    user = User(email=email, locale=locale)
    user.set_password(password)
    _db.session.add(user)
    _db.session.commit()
    return user


def make_trip(user, **overrides):
    values = dict(
        origin_name="Paris, France", origin_lat=48.8566, origin_lon=2.3522,
        dest_name="Lyon, France", dest_lat=45.764, dest_lon=4.8357,
        depart_date=date(2025, 5, 1), transport_mode="train", is_round_trip=False, return_date=None,
    )
    values.update(overrides)
    trip = Trip(user_id=user.id, **values)
    _db.session.add(trip)
    _db.session.commit()
    return trip


@pytest.fixture
def user(app):
    return make_user()


@pytest.fixture
def other_user(app):
    return make_user("bob@example.com", locale="en")


def login(client, email="alice@example.com", password="password123"):
    return client.post("/auth/login", data={"email": email, "password": password})


@pytest.fixture
def auth_client(client, user):
    login(client)
    return client
