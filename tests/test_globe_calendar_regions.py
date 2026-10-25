"""Globe de la carte, calendrier de l'année et couverture du monde (continents, régions des grands pays)."""
import json
import os
from datetime import date

import pytest

from app import regions, utils
from app.i18n import js_strings
from app.trips.absences import compute_absences
from app.trips.activity import AWAY, HOME, TRAVEL, year_calendar
from app.trips.badges import continent_summary
from app.trips.stats import region_summary

from .conftest import make_trip

TODAY = date(2025, 6, 15)
STATIC = os.path.join(os.path.dirname(__file__), "..", "app", "static")


@pytest.fixture(autouse=True)
def frozen_today(monkeypatch):
    monkeypatch.setattr(utils, "today", lambda: TODAY)


@pytest.fixture
def home(db, user):
    user.home_name, user.home_lat, user.home_lon, user.home_country = "Paris", 48.8566, 2.3522, "FR"
    db.session.commit()
    return user


def cells(calendar):
    return {c["date"]: c for week in calendar["weeks"] for c in week if c}


# --- Globe ---------------------------------------------------------------------------------

def test_map_page_loads_the_globe(auth_client):
    html = auth_client.get("/").text
    assert "vendor/d3-geo-3.1.1/d3-geo.min.js" in html and "vendor/d3-array-3.2.4/d3-array.min.js" in html
    assert 'data-world-url="/static/data/world.json' in html


def test_globe_strings_are_translated(app):
    with app.test_request_context(headers={"Accept-Language": "en"}):
        strings = js_strings()
    assert strings["view_globe"] == "Globe" and strings["zoom_in"] == "Zoom in"


def test_world_outlines_keep_every_country():
    with open(os.path.join(STATIC, "data", "world.json"), encoding="utf-8") as fh:
        world = json.load(fh)
    codes = {f["properties"]["code"] for f in world["features"]}
    assert {"FR", "US", "MC", "AD", "SG"} <= codes  # micro-États compris
    assert all(f["geometry"]["type"] == "MultiPolygon" for f in world["features"])


# --- Calendrier ---------------------------------------------------------------------------------

def test_calendar_structure(app, user):
    with app.test_request_context():
        calendar = year_calendar([], 2025)
    assert all(len(week) == 7 for week in calendar["weeks"])
    assert len(cells(calendar)) == 365
    assert [m["name"] for m in calendar["months"]][0] == "janv."
    assert len(calendar["months"]) == 12 and len(calendar["weekdays"]) == 7
    # 2025 commence un mercredi ; en français, la semaine commence le lundi.
    assert calendar["weeks"][0][:2] == [None, None] and calendar["weeks"][0][2]["date"] == date(2025, 1, 1)


def test_calendar_without_home_uses_round_trips(app, user):
    make_trip(user, dest_name="Lisbonne", depart_date=date(2025, 3, 1), is_round_trip=True,
              return_date=date(2025, 3, 5))
    make_trip(user, depart_date=date(2025, 4, 2))  # aller simple : un jour de voyage, sans absence
    with app.test_request_context():
        calendar = year_calendar(user.trips.all(), 2025)
    days = cells(calendar)
    assert days[date(2025, 3, 1)]["level"] == TRAVEL and days[date(2025, 3, 5)]["level"] == TRAVEL
    assert days[date(2025, 3, 3)]["level"] == AWAY and "Lisbonne" in days[date(2025, 3, 3)]["title"]
    assert days[date(2025, 4, 2)]["level"] == TRAVEL and days[date(2025, 4, 3)]["level"] == HOME
    assert calendar["travel_days"] == 3 and calendar["away_days"] == 6 and not calendar["from_absences"]


def test_calendar_with_home_uses_absences_and_flags_upcoming_trips(app, home):
    # Paris -> Lisbonne puis Lisbonne -> Paris, en allers simples : une absence du 1er au 10 mars.
    make_trip(home, dest_name="Lisbonne", dest_lat=38.72, dest_lon=-9.14, depart_date=date(2025, 3, 1))
    make_trip(home, origin_name="Lisbonne", origin_lat=38.72, origin_lon=-9.14, dest_name="Paris",
              dest_lat=48.8566, dest_lon=2.3522, depart_date=date(2025, 3, 10))
    make_trip(home, depart_date=date(2025, 8, 1), is_round_trip=True, return_date=date(2025, 8, 3))  # à venir
    trips = home.trips.all()
    with app.test_request_context():
        calendar = year_calendar(trips, 2025, compute_absences(home, trips))
    days = cells(calendar)
    assert days[date(2025, 3, 5)]["level"] == AWAY and "Lisbonne" in days[date(2025, 3, 5)]["title"]
    assert days[date(2025, 3, 10)]["level"] == TRAVEL
    assert days[date(2025, 8, 2)]["upcoming"] and days[date(2025, 8, 2)]["future"]
    assert days[TODAY]["today"]
    assert calendar["away_days"] == 10 and calendar["planned_days"] == 3 and calendar["from_absences"]


def test_year_page_shows_the_calendar(auth_client, user):
    make_trip(user, depart_date=date(2025, 3, 1))
    html = auth_client.get("/stats/2025").text
    assert "Calendrier 2025" in html and 'class="activity-day level-2' in html
    assert "seuls les allers-retours comptent" in html  # pas de domicile


# --- Couverture du monde ------------------------------------------------------------------------

@pytest.mark.parametrize("lat, lon, country, expected", [
    (48.8566, 2.3522, "FR", "FR:Île-de-France"),
    (49.0097, 2.5479, "FR", "FR:Île-de-France"),  # aéroport CDG
    (40.7128, -74.006, "US", "US-NY"),
    (41.3874, 2.1686, "ES", "ES:Cataluña"),
    (55.95, -3.19, "GB", "GB:Scotland"),
    (38.72, -9.14, "PT", None),  # pays sans régions
    (None, None, "FR", None),
])
def test_region_at(lat, lon, country, expected):
    assert regions.region_at(lat, lon, country) == expected


def test_region_names_are_localised(app):
    assert regions.region_name("US-CA", "fr") == "Californie"
    assert regions.region_name("US-CA", "en") == "California"
    with app.test_request_context(headers={"Accept-Language": "fr"}):
        assert regions.region_name("GB:Scotland", "fr") == "Écosse"


def test_region_summary(app, user):
    make_trip(user, origin_country="FR", dest_country="FR")  # Paris -> Lyon
    make_trip(user, dest_name="New York", dest_lat=40.7128, dest_lon=-74.006, dest_country="US",
              transport_mode="plane", depart_date=date(2025, 2, 1))
    make_trip(user, dest_name="Boston", dest_lat=42.36, dest_lon=-71.06, dest_country="US",
              depart_date=date(2030, 1, 1))  # à venir : pas encore visité
    with app.test_request_context():
        rows = {r["code"]: r for r in region_summary(user.trips.all())}
    assert rows["FR"]["regions"] == ["Auvergne-Rhône-Alpes", "Île-de-France"] and rows["FR"]["total"] == 18
    assert rows["US"]["regions"] == ["État de New York"] and rows["US"]["total"] == 51
    assert rows["US"]["unit"] == "États"


def test_continent_totals(app, user):
    make_trip(user, origin_country="FR", dest_country="FR")
    europe = {c["code"]: c for c in continent_summary(user.trips.all(), "fr")}["EU"]
    assert europe["countries"] == ["FR"] and europe["total"] >= 40
    assert europe["share"] == pytest.approx(1 / europe["total"])


def test_stats_page_shows_coverage_and_regions(auth_client, user):
    make_trip(user, origin_country="FR", dest_country="FR")
    html = auth_client.get("/stats").text
    assert "1 pays et territoires sur" in html
    assert 'id="regionsTitle"' in html and "Île-de-France" in html and "2 / 18" in html
