import re
from datetime import timedelta

import pytest

from app import create_app, geo
from app.extensions import limiter
from app.models import GeocodeCache, ShareLink, Trip, User, utcnow

from .conftest import login, make_trip, make_user


# --- En-têtes de sécurité -------------------------------------------------------------------

def test_security_headers(client):
    response = client.get("/")
    headers = response.headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    csp = headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
    assert "Strict-Transport-Security" not in headers  # HTTP en clair


def test_inline_script_nonce_matches_csp(client):
    response = client.get("/")
    nonce = re.search(r"'nonce-([^']+)'", response.headers["Content-Security-Policy"]).group(1)
    assert f'<script nonce="{nonce}">' in response.text
    assert nonce not in client.get("/").headers["Content-Security-Policy"]  # un nonce par requête


def test_matomo_on_every_page_and_allowed_by_csp(client):
    for path in ("/", "/auth/login", "/privacy", "/does-not-exist"):
        response = client.get(path)
        assert "setSiteId', '13'" in response.text, path
        csp = response.headers["Content-Security-Policy"]
        assert "https://stats.mousqueton.io" in csp.split("script-src")[1].split(";")[0]
        assert "https://stats.mousqueton.io" in csp.split("connect-src")[1].split(";")[0]


def test_matomo_masks_secret_tokens(client):
    assert "(s|signup|reset)" in client.get("/").text


def test_cdn_assets_have_integrity(auth_client):
    html = auth_client.get("/").text
    for tag in re.findall(r"<(?:script|link)[^>]+(?:src|href)=\"https://(?:cdn\.jsdelivr|unpkg|cdnjs)[^>]+>", html):
        assert 'integrity="sha384-' in tag, tag


def test_leaflet_is_self_hosted(auth_client):
    html = auth_client.get("/").text
    assert "/static/vendor/leaflet-1.9.4/leaflet.js" in html and "unpkg" not in html
    assert "unpkg" not in auth_client.get("/").headers["Content-Security-Policy"]
    assert auth_client.get("/static/vendor/leaflet-1.9.4/images/layers-2x.png").status_code == 200


def test_hsts_on_https(app, client):
    app.config["HSTS_MAX_AGE"] = 600
    response = client.get("/", base_url="https://localhost")
    assert response.headers["Strict-Transport-Security"] == "max-age=600"


@pytest.mark.parametrize("key", ["", "dev-insecure-change-me", "change-me"])
def test_production_refuses_insecure_secret_key(monkeypatch, key):
    from config import ProductionConfig

    monkeypatch.setattr(ProductionConfig, "SECRET_KEY", key)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app("production")


# --- Limitation de débit --------------------------------------------------------------------

@pytest.fixture
def rate_limited(app):
    app.config["LOGIN_RATE_LIMIT"] = "5 per minute;30 per hour"
    limiter.reset()
    yield
    limiter.reset()


def test_login_rate_limited_after_failures(client, user, rate_limited):
    for _ in range(5):
        assert login(client, password="wrong-password").status_code == 200
    response = login(client, password="wrong-password")
    assert response.status_code == 429
    assert "Trop de tentatives" in response.text


def test_successful_logins_are_not_counted(client, user, rate_limited):
    for _ in range(7):
        assert login(client).status_code == 302
        client.post("/auth/logout")


def test_login_rate_limit_per_email(app, user, rate_limited):
    # Adresses IP différentes, même compte visé.
    for i in range(5):
        app.test_client().post("/auth/login", data={"email": user.email, "password": "x" * 9},
                               environ_base={"REMOTE_ADDR": f"10.0.0.{i}"})
    response = app.test_client().post("/auth/login", data={"email": user.email, "password": "x" * 9},
                                      environ_base={"REMOTE_ADDR": "10.0.1.1"})
    assert response.status_code == 429


# --- Liens de partage : expiration ----------------------------------------------------------

def test_share_link_with_expiry(auth_client, db, user):
    auth_client.post("/share", data={"label": "Famille", "expires_in": "7"})
    link = db.session.execute(db.select(ShareLink)).scalar_one()
    expires = link.expires_at.replace(tzinfo=None)
    assert timedelta(days=6, hours=23) < expires - utcnow().replace(tzinfo=None) <= timedelta(days=7)
    assert "expire le" in auth_client.get("/share").text


def test_expired_share_link_is_rejected(client, db, user):
    make_trip(user)
    link = ShareLink(user_id=user.id, expires_at=utcnow() - timedelta(minutes=1))
    db.session.add(link)
    db.session.commit()
    assert client.get(f"/s/{link.token}").status_code == 404
    assert client.get(f"/api/shared/{link.token}/trips").status_code == 404
    assert client.get(f"/api/shared/{link.token}/stats").status_code == 404


def test_share_link_records_last_use(client, db, user):
    link = ShareLink(user_id=user.id)
    db.session.add(link)
    db.session.commit()
    assert link.last_used_at is None
    assert client.get(f"/s/{link.token}").status_code == 200
    db.session.refresh(link)
    assert link.last_used_at is not None


def test_purge_share_links_command(app, db, user):
    db.session.add_all([ShareLink(user_id=user.id, expires_at=utcnow() - timedelta(days=1)),
                        ShareLink(user_id=user.id, expires_at=utcnow() + timedelta(days=1)),
                        ShareLink(user_id=user.id)])
    db.session.commit()
    result = app.test_cli_runner().invoke(args=["purge-share-links"])
    assert "1 lien" in result.output
    assert db.session.scalar(db.select(db.func.count(ShareLink.id))) == 2


# --- Gestion du compte ----------------------------------------------------------------------

def test_change_password_requires_current_password(auth_client, db, user):
    response = auth_client.post("/auth/password", data={
        "pw-current_password": "nope", "pw-password": "newpassword1", "pw-confirm": "newpassword1"})
    assert response.status_code == 400
    assert "Mot de passe actuel incorrect." in response.text
    db.session.refresh(user)
    assert user.check_password("password123")


def test_change_password_logs_out_other_sessions(app, auth_client, db, user):
    other = app.test_client()
    login(other)
    assert other.get("/trips").status_code == 200
    response = auth_client.post("/auth/password", data={
        "pw-current_password": "password123", "pw-password": "newpassword1", "pw-confirm": "newpassword1"})
    assert response.status_code == 302
    db.session.refresh(user)
    assert user.check_password("newpassword1")
    assert auth_client.get("/trips").status_code == 200  # session courante renouvelée
    assert other.get("/trips").status_code == 302  # autre session déconnectée


def test_delete_account(auth_client, db, user):
    make_trip(user)
    response = auth_client.post("/auth/delete", data={"del-delete_password": "wrong"})
    assert response.status_code == 400
    assert db.session.get(User, user.id) is not None
    response = auth_client.post("/auth/delete", data={"del-delete_password": "password123"})
    assert response.status_code == 302
    db.session.expire_all()
    assert db.session.get(User, user.id) is None
    assert db.session.scalar(db.select(db.func.count(Trip.id))) == 0
    assert auth_client.get("/trips").status_code == 302


def test_last_admin_cannot_delete_own_account(auth_client, db, user):
    user.is_admin = True
    db.session.commit()
    auth_client.post("/auth/delete", data={"del-delete_password": "password123"})
    assert db.session.get(User, user.id) is not None


def test_profile_page_shows_account_forms(auth_client):
    html = auth_client.get("/auth/profile").text
    assert 'name="pw-current_password"' in html and 'name="del-delete_password"' in html


# --- Mot de passe oublié --------------------------------------------------------------------

def _outbox(app):
    return app.extensions.setdefault("mail_outbox", [])


def test_forgot_password_sends_link_and_reset_works_once(app, client, db, user):
    response = client.post("/auth/forgot", data={"email": "ALICE@example.com"})
    assert response.status_code == 302
    (message,) = _outbox(app)
    assert message["To"] == user.email
    url = re.search(r"http://localhost(/auth/reset/\S+)", message.get_content()).group(1)
    assert client.get(url).status_code == 200
    response = client.post(url, data={"password": "brandnew123", "confirm": "brandnew123"})
    assert response.status_code == 302 and response.location.endswith("/auth/login")
    db.session.refresh(user)
    assert user.check_password("brandnew123")
    # Le lien ne sert qu'une fois.
    assert client.get(url).location.endswith("/auth/forgot")


def test_forgot_password_unknown_email_sends_nothing(app, client):
    response = client.post("/auth/forgot", data={"email": "nobody@example.com"}, follow_redirects=True)
    assert "Si un compte correspond" in response.text
    assert _outbox(app) == []


def test_reset_link_uses_app_base_url(app, client, user):
    app.config["APP_BASE_URL"] = "https://voyages.example.org"
    client.post("/auth/forgot", data={"email": user.email}, headers={"Host": "evil.example"})
    assert "https://voyages.example.org/auth/reset/" in _outbox(app)[0].get_content()


def test_reset_email_in_user_language(app, client, db):
    make_user("carla@example.com", locale="it")
    client.post("/auth/forgot", data={"email": "carla@example.com"})
    message = _outbox(app)[0]
    assert message["Subject"] == "Reimpostazione della password"
    assert "Buongiorno," in message.get_content()


def test_invalid_reset_token(client):
    assert client.get("/auth/reset/garbage").location.endswith("/auth/forgot")


def test_forgot_password_disabled_without_mail_server(app, client):
    app.config.update(TESTING=False, DEBUG=False, MAIL_SERVER="")
    assert client.get("/auth/forgot").status_code == 404
    assert "/auth/forgot" not in client.get("/auth/login").text


def test_sessions_from_old_id_format_are_rejected(app, user):
    from app.models import load_user

    assert load_user(str(user.id)) is None
    assert load_user(user.get_id()) == user


# --- Géocodage : verrou inter-processus et purge --------------------------------------------

class _EmptyResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return []


def test_nominatim_file_lock_shares_last_call(app, monkeypatch, tmp_path):
    sleeps = []
    monkeypatch.setattr(geo.time, "sleep", sleeps.append)
    monkeypatch.setattr(geo.requests, "get", lambda *a, **k: _EmptyResponse())
    lock = tmp_path / "nominatim.lock"
    app.config.update(NOMINATIM_LOCK_FILE=str(lock), NOMINATIM_MIN_INTERVAL=1.0)
    with app.test_request_context():
        geo.NominatimClient().search("a", "fr")
        assert float(lock.read_text()) == pytest.approx(geo.time.time(), abs=5)
        geo.NominatimClient().search("b", "fr")  # autre instance : même fichier, donc même limite
    assert len(sleeps) == 1 and 0 < sleeps[0] <= 1.0


def test_geocode_purge_command(app, db):
    old = utcnow() - timedelta(days=app.config["GEOCODE_CACHE_DAYS"] + 1)
    db.session.add_all([GeocodeCache(query="old", lang="fr", results=[], created_at=old),
                        GeocodeCache(query="new", lang="fr", results=[])])
    db.session.commit()
    result = app.test_cli_runner().invoke(args=["geocode", "purge"])
    assert "1 entrée" in result.output
    assert [c.query for c in db.session.execute(db.select(GeocodeCache)).scalars()] == ["new"]
    app.test_cli_runner().invoke(args=["geocode", "purge", "--all"])
    assert db.session.scalar(db.select(db.func.count(GeocodeCache.id))) == 0
