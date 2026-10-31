from datetime import date

import pytest

from app.models import Trip

from .conftest import login, make_trip

VALID = {
    "origin_name": "Paris, France", "origin_lat": "48.8566", "origin_lon": "2.3522",
    "dest_name": "Rome, Italie", "dest_lat": "41.9028", "dest_lon": "12.4964",
    "depart_date": "2025-06-01", "transport_mode": "plane",
}


def post_trip(client, url="/trips/new", **changes):
    data = {**VALID, **changes}
    data = {k: v for k, v in data.items() if v is not None}
    return client.post(url, data=data)


def test_pages_require_login(client):
    for url in ("/trips", "/trips/new", "/trips/1/edit", "/auth/profile"):
        response = client.get(url)
        assert response.status_code == 302
        assert "/auth/login" in response.location


def test_create_one_way_trip(auth_client, db):
    response = post_trip(auth_client)
    assert response.status_code == 302
    trip = db.session.query(Trip).one()
    assert trip.dest_name == "Rome, Italie"
    assert trip.is_round_trip is False and trip.return_date is None
    assert f"focus={trip.id}" in response.location


def test_create_round_trip(auth_client, db):
    post_trip(auth_client, is_round_trip="y", return_date="2025-06-10")
    trip = db.session.query(Trip).one()
    assert trip.is_round_trip and trip.return_date == date(2025, 6, 10)


def test_round_trip_requires_return_date(auth_client, db):
    response = post_trip(auth_client, is_round_trip="y")
    assert response.status_code == 200
    assert "La date de retour est obligatoire pour un aller-retour." in response.text
    assert db.session.query(Trip).count() == 0


def test_return_date_cannot_precede_departure(auth_client, db):
    response = post_trip(auth_client, is_round_trip="y", return_date="2025-05-20")
    assert "La date de retour doit être postérieure ou égale à la date de départ." in response.text
    assert db.session.query(Trip).count() == 0


def test_return_date_ignored_for_one_way(auth_client, db):
    post_trip(auth_client, return_date="2025-05-20")
    assert db.session.query(Trip).one().return_date is None


def test_validation_messages_are_translated(client, user, db):
    user.locale = "de"
    db.session.commit()
    login(client)
    response = post_trip(client, is_round_trip="y", origin_name="")
    assert "Für eine Hin- und Rückfahrt ist ein Rückreisedatum erforderlich." in response.text
    assert "Start ist erforderlich." in response.text


def test_invalid_mode_rejected(auth_client, db):
    response = post_trip(auth_client, transport_mode="rocket")
    assert response.status_code == 200
    assert db.session.query(Trip).count() == 0


def test_missing_coordinates_are_geocoded(auth_client, db, monkeypatch):
    calls = []

    def fake_geocode(query, lang):
        calls.append((query, lang))
        return [{"name": query, "label": query, "lat": 1.5, "lon": 2.5}]

    monkeypatch.setattr("app.trips.routes.geocode", fake_geocode)
    post_trip(auth_client, dest_lat=None, dest_lon=None)
    trip = db.session.query(Trip).one()
    assert (trip.dest_lat, trip.dest_lon) == (1.5, 2.5)
    assert calls == [("Rome, Italie", "fr")]


def test_unknown_place_shows_error(auth_client, db, monkeypatch):
    monkeypatch.setattr("app.trips.routes.geocode", lambda q, lang: [])
    response = post_trip(auth_client, dest_lat=None, dest_lon=None)
    assert "Lieu introuvable" in response.text
    assert db.session.query(Trip).count() == 0


def test_edit_own_trip(auth_client, db, user):
    trip = make_trip(user)
    response = post_trip(auth_client, url=f"/trips/{trip.id}/edit", transport_mode="car")
    assert response.status_code == 302
    db.session.refresh(trip)
    assert trip.transport_mode == "car" and trip.dest_name == "Rome, Italie"


def test_edit_can_turn_round_trip_into_one_way(auth_client, db, user):
    trip = make_trip(user, is_round_trip=True, return_date=date(2025, 5, 4))
    post_trip(auth_client, url=f"/trips/{trip.id}/edit", return_date="2025-06-04")
    db.session.refresh(trip)
    assert trip.is_round_trip is False and trip.return_date is None


def test_delete_own_trip(auth_client, db, user):
    trip = make_trip(user)
    response = auth_client.post(f"/trips/{trip.id}/delete", data={"next": "/trips"})
    assert response.status_code == 302 and response.location == "/trips"
    assert db.session.query(Trip).count() == 0


def test_delete_rejects_external_redirect(auth_client, user):
    trip = make_trip(user)
    response = auth_client.post(f"/trips/{trip.id}/delete", data={"next": "//evil.example"})
    assert response.location == "/"


def test_delete_requires_post(auth_client, user):
    trip = make_trip(user)
    assert auth_client.get(f"/trips/{trip.id}/delete").status_code == 405


@pytest.mark.parametrize("method,url", [
    ("get", "/trips/{id}/edit"),
    ("post", "/trips/{id}/edit"),
    ("post", "/trips/{id}/delete"),
])
def test_cannot_touch_other_users_trips(client, db, user, other_user, method, url):
    foreign = make_trip(other_user, dest_name="Secret")
    login(client)
    response = getattr(client, method)(url.format(id=foreign.id), data=VALID)
    assert response.status_code == 404
    db.session.refresh(foreign)
    assert foreign.dest_name == "Secret"


def test_list_shows_only_own_trips(client, user, other_user):
    make_trip(user, dest_name="Mine")
    make_trip(other_user, dest_name="NotMine")
    login(client)
    html = client.get("/trips").text
    assert "Mine" in html and "NotMine" not in html


def test_list_dims_upcoming_trips(client, user):
    make_trip(user, depart_date=date(2099, 5, 1), return_date=None)
    login(client)
    assert 'class="trip-upcoming"' in client.get("/trips").text


def test_csrf_enforced_when_enabled(app, client, user):
    app.config["WTF_CSRF_ENABLED"] = True
    response = login(client)
    assert response.status_code == 400


@pytest.fixture
def no_mail(app):
    """Sans serveur d'e-mail, l'inscription se fait directement avec un mot de passe."""
    app.config.update(TESTING=False, MAIL_SERVER="", DEBUG=False)
    yield
    app.config["TESTING"] = True


def test_register_login_logout(client, db, no_mail):
    response = client.post("/auth/register", data={
        "email": "New@Example.com", "password": "longpassword", "confirm": "longpassword",
    })
    assert response.status_code == 302
    assert client.get("/trips").status_code == 200
    client.post("/auth/logout")
    assert client.get("/trips").status_code == 302
    assert login(client, "new@example.com", "longpassword").status_code == 302


def test_register_rejects_duplicate_and_short_password(client, user, no_mail):
    response = client.post("/auth/register", data={"email": user.email, "password": "short", "confirm": "nope"})
    text = response.text
    assert "Un compte existe déjà" in text
    assert "au moins 8 caractères" in text
    assert "ne correspondent pas" in text


def test_login_rejects_bad_password(client, user):
    response = login(client, password="wrong-password")
    assert response.status_code == 200
    assert "Adresse e-mail ou mot de passe incorrect." in response.text


def test_login_next_is_safe(client, user):
    response = client.post("/auth/login?next=https://evil.example/", data={"email": user.email, "password": "password123"})
    assert response.location == "/"
    client.post("/auth/logout")
    response = client.post("/auth/login?next=/trips", data={"email": user.email, "password": "password123"})
    assert response.location == "/trips"
