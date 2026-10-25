from datetime import date

import pytest

from app import utils
from app.models import User

from .conftest import login, make_trip

TODAY = date(2025, 6, 10)


@pytest.fixture(autouse=True)
def frozen_today(monkeypatch):
    monkeypatch.setattr(utils, "today", lambda: TODAY)


@pytest.mark.parametrize("start,end,status", [
    (date(2025, 6, 11), date(2025, 6, 11), "upcoming"),
    (date(2025, 6, 10), date(2025, 6, 10), "ongoing"),
    (date(2025, 6, 1), date(2025, 6, 20), "ongoing"),
    (date(2025, 6, 1), date(2025, 6, 9), "past"),
])
def test_trip_status(start, end, status):
    assert utils.trip_status(start, end) == status


def test_api_status_and_countdown(auth_client, user):
    make_trip(user, depart_date=date(2025, 6, 22))
    make_trip(user, depart_date=date(2025, 6, 11))
    make_trip(user, depart_date=date(2025, 6, 5), is_round_trip=True, return_date=date(2025, 6, 15))
    make_trip(user, depart_date=date(2025, 1, 1))
    trips = auth_client.get("/api/trips").get_json()["trips"]
    assert [(t["status"], t["countdown"]) for t in trips] == [
        ("upcoming", "Dans 12 jours"), ("upcoming", "Demain"), ("ongoing", "En cours"), ("past", "")]


def test_countdown_is_translated(client, db, user):
    user.locale = "en"
    db.session.commit()
    make_trip(user, depart_date=date(2025, 6, 13))
    login(client)
    assert client.get("/api/trips").get_json()["trips"][0]["countdown"] == "In 3 days"


def test_when_filter(auth_client, user):
    make_trip(user, depart_date=date(2025, 7, 1))
    make_trip(user, depart_date=TODAY)
    make_trip(user, depart_date=date(2024, 7, 1))
    count = lambda q: auth_client.get(f"/api/trips?{q}").get_json()["count"]
    assert (count(""), count("when=past"), count("when=upcoming")) == (3, 2, 1)
    assert auth_client.get("/api/trips?when=soon").status_code == 400


def test_next_trip_in_stats(auth_client, user):
    make_trip(user, depart_date=date(2025, 8, 1), dest_name="Lille, France")
    soonest = make_trip(user, depart_date=date(2025, 6, 20), dest_name="Nantes, France")
    stats = auth_client.get("/api/stats").get_json()
    assert stats["next_trip"]["id"] == soonest.id and stats["next_trip"]["countdown"] == "Dans 10 jours"
    assert auth_client.get("/api/stats?when=past").get_json()["next_trip"] is None


def test_stats_page_excludes_upcoming(auth_client, user):
    make_trip(user, origin_country="FR", dest_country="FR", depart_date=date(2025, 1, 1))
    make_trip(user, origin_country="FR", dest_country="JP", depart_date=date(2026, 3, 1),
              dest_name="Tokyo, Japon", dest_lat=35.68, dest_lon=139.65, transport_mode="plane")
    html = auth_client.get("/stats").text
    assert "Tokyo, Japon" in html and "Dans 264 jours" in html  # section « À venir »
    assert "Japon" not in html.split('id="countriesTitle"')[1]  # pas compté comme visité
    assert "2026" not in html.split('id="yearsTitle"')[1].split("</table>")[0]


def test_badges_on_list_and_detail(auth_client, user):
    trip = make_trip(user, depart_date=date(2025, 6, 12))
    assert "Dans 2 jours" in auth_client.get("/trips").text
    assert "Dans 2 jours" in auth_client.get(f"/trips/{trip.id}").text


# --- Agenda ----------------------------------------------------------------------------------

def _unfold(text):
    return text.replace("\r\n ", "")


def test_trip_ics_download(auth_client, user):
    trip = make_trip(user, depart_date=date(2025, 7, 1), is_round_trip=True, return_date=date(2025, 7, 4),
                     origin_name="Paris; France, \\ test")
    response = auth_client.get(f"/trips/{trip.id}.ics")
    assert response.mimetype == "text/calendar"
    body = _unfold(response.data.decode())
    assert "DTSTART;VALUE=DATE:20250701" in body and "DTEND;VALUE=DATE:20250705" in body
    assert "SUMMARY:🚆 Paris\; France\\, \\\\ test → Lyon\\, France" in body
    assert all(len(line.encode()) <= 75 for line in response.data.decode().split("\r\n"))


def test_ics_of_other_user_is_404(auth_client, other_user):
    trip = make_trip(other_user)
    assert auth_client.get(f"/trips/{trip.id}.ics").status_code == 404


def test_calendar_subscription(app, auth_client, client, db, user):
    make_trip(user, notes="code porte 1234")
    assert auth_client.post("/auth/calendar").status_code == 302
    token = db.session.get(User, user.id).calendar_token
    assert token and token in auth_client.get("/auth/profile").text
    anonymous = app.test_client()
    feed = anonymous.get(f"/calendar/{token}.ics")
    assert feed.status_code == 200 and "BEGIN:VEVENT" in feed.text
    assert "1234" not in feed.text  # les notes ne sont pas publiées
    # Nouvelle adresse : l'ancienne ne marche plus ; désactivation : plus rien.
    auth_client.post("/auth/calendar")
    assert anonymous.get(f"/calendar/{token}.ics").status_code == 404
    auth_client.post("/auth/calendar/disable")
    assert db.session.get(User, user.id).calendar_token is None
    assert anonymous.get("/calendar/.ics").status_code == 404


def test_stats_upcoming_shows_departure_and_return(auth_client, user):
    make_trip(user, depart_date=date(2025, 7, 1), is_round_trip=True, return_date=date(2025, 7, 9),
              dest_name="Nantes, France")
    make_trip(user, depart_date=date(2025, 8, 2), dest_name="Brest, France")
    section = auth_client.get("/stats").text.split('id="upcomingTitle"')[1].split("</section>")[0]
    assert "1 juil. 2025" in section and "9 juil. 2025" in section  # départ et retour
    assert "2 août 2025" in section and "Aller simple" in section
