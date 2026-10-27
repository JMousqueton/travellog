import re

import pytest

from app.models import Setting, User

from .conftest import login


def _outbox(app):
    return app.extensions.setdefault("mail_outbox", [])


def _link(app):
    return re.search(r"http://localhost(/auth/signup/\S+)", _outbox(app)[-1].get_content()).group(1)


def test_signup_by_magic_link(app, client, db):
    page = client.get("/auth/register").text
    assert 'name="password"' not in page  # seule l'adresse est demandée
    response = client.post("/auth/register", data={"email": "New@Example.com"})
    assert response.status_code == 200 and "Vérifiez votre messagerie" in response.text
    message = _outbox(app)[0]
    assert message["To"] == "new@example.com" and "15 minutes" in message.get_content()
    assert db.session.execute(db.select(User)).first() is None  # pas de compte avant le clic

    link = _link(app)
    page = client.get(link)
    assert page.status_code == 200 and "new@example.com" in page.text
    assert db.session.execute(db.select(User)).first() is None  # un simple GET (robot de messagerie) ne crée rien
    response = client.post(link, data={"password": "longpassword", "confirm": "longpassword"})
    assert response.status_code == 302
    assert client.get("/trips").status_code == 200  # connecté
    client.post("/auth/logout")
    assert login(client, "new@example.com", "longpassword").status_code == 302

    # Le lien ne sert qu'une fois.
    assert client.get(link).location.endswith("/auth/login")


def test_signup_link_expires_after_15_minutes(app, client, db, monkeypatch):
    import itsdangerous.timed

    client.post("/auth/register", data={"email": "late@example.com"})
    link = _link(app)
    real_now = itsdangerous.timed.TimestampSigner.get_timestamp
    monkeypatch.setattr(itsdangerous.timed.TimestampSigner, "get_timestamp", lambda self: real_now(self) + 14 * 60)
    assert client.get(link).status_code == 200  # encore valable à 14 minutes
    monkeypatch.setattr(itsdangerous.timed.TimestampSigner, "get_timestamp", lambda self: real_now(self) + 16 * 60)
    response = client.get(link)
    assert response.location.endswith("/auth/register")
    assert "expiré" in client.get("/auth/register").text


def test_signup_password_rules(app, client, db):
    client.post("/auth/register", data={"email": "x@example.com"})
    response = client.post(_link(app), data={"password": "short", "confirm": "nope"})
    assert "au moins 8 caractères" in response.text and "ne correspondent pas" in response.text
    assert db.session.execute(db.select(User)).first() is None


def test_existing_address_gets_login_email_not_a_link(app, client, user):
    response = client.post("/auth/register", data={"email": user.email.upper()})
    assert "Vérifiez votre messagerie" in response.text  # même réponse : l'adresse n'est pas révélée
    body = _outbox(app)[0].get_content()
    assert "/auth/signup/" not in body and "déjà un compte" in body and "/auth/forgot" in body


def test_tampered_link_rejected(client):
    assert client.get("/auth/signup/forged-token").location.endswith("/auth/register")


def test_signup_respects_closed_registration(app, client, db):
    client.post("/auth/register", data={"email": "y@example.com"})
    link = _link(app)
    Setting.set("registration_open", "0")
    db.session.commit()
    assert client.post(link, data={"password": "longpassword", "confirm": "longpassword"}).location.endswith("/auth/login")
    assert db.session.execute(db.select(User)).first() is None


def test_signup_link_uses_app_base_url(app, client):
    app.config["APP_BASE_URL"] = "https://travel.example.org"
    client.post("/auth/register", data={"email": "d@example.com"}, headers={"Host": "evil.example"})
    assert "https://travel.example.org/auth/signup/" in _outbox(app)[0].get_content()


def test_signup_email_and_account_use_visitor_language(app, client, db):
    client.get("/lang/de")
    client.post("/auth/register", data={"email": "d@example.com"})
    message = _outbox(app)[0]
    assert message["Subject"] == "Deine Registrierung bei Voyage Voyage"
    client.post(_link(app), data={"password": "longpassword", "confirm": "longpassword"})
    assert db.session.execute(db.select(User)).scalar_one().locale == "de"


def test_magic_link_requests_are_rate_limited(app, client):
    from app.extensions import limiter

    app.config["REGISTER_RATE_LIMIT"] = "2 per hour"
    limiter.reset()
    for _ in range(2):
        assert client.post("/auth/register", data={"email": "spam@example.com"}).status_code == 200
    assert client.post("/auth/register", data={"email": "spam@example.com"}).status_code == 429
    limiter.reset()
