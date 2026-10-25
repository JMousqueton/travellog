from datetime import date

import pytest

from app import utils
from app.models import ShareLink
from app.trips.badges import compute_badges, continent_summary
from app.trips.places import visited_places

from .conftest import make_trip


@pytest.fixture(autouse=True)
def frozen_today(monkeypatch):
    monkeypatch.setattr(utils, "today", lambda: date(2025, 6, 1))


# --- Voyages à venir et liens de partage ------------------------------------------------------

def _link(db, user, include_upcoming):
    link = ShareLink(user_id=user.id, include_upcoming=include_upcoming)
    db.session.add(link)
    db.session.commit()
    return link


def test_share_links_hide_upcoming_trips_by_default(auth_client, client, db, user):
    make_trip(user, depart_date=date(2025, 5, 1))
    make_trip(user, depart_date=date(2025, 9, 1), dest_name="Nice, France")
    auth_client.post("/share", data={"label": "Famille"})
    link = db.session.execute(db.select(ShareLink)).scalar_one()
    assert link.include_upcoming is False
    shared = client.get(f"/api/shared/{link.token}/trips").get_json()
    assert shared["count"] == 1
    assert client.get(f"/api/shared/{link.token}/trips?when=upcoming").get_json()["count"] == 0
    assert client.get(f"/api/shared/{link.token}/stats").get_json()["next_trip"] is None
    assert "voyages à venir masqués" in auth_client.get("/share").text
    auth_client.post(f"/share/{link.id}/upcoming")
    assert client.get(f"/api/shared/{link.token}/trips").get_json()["count"] == 2


def test_new_link_can_include_upcoming(auth_client, db, user):
    auth_client.post("/share", data={"label": "", "include_upcoming": "y"})
    assert db.session.execute(db.select(ShareLink)).scalar_one().include_upcoming is True


def test_toggle_requires_owner(auth_client, db, other_user):
    link = _link(db, other_user, False)
    assert auth_client.post(f"/share/{link.id}/upcoming").status_code == 404


# --- Badges et continents -------------------------------------------------------------------

def _world_tour(user):
    stops = [("FR", "JP", "plane", 35.68, 139.65), ("FR", "US", "plane", 40.71, -74.0), ("FR", "BR", "plane", -22.9, -43.2),
             ("FR", "AU", "plane", -33.87, 151.21), ("FR", "ZA", "plane", -33.92, 18.42)]
    for day, (o, d, mode, lat, lon) in enumerate(stops, start=1):
        make_trip(user, origin_country=o, dest_country=d, transport_mode=mode, dest_lat=lat, dest_lon=lon,
                  dest_name=d, depart_date=date(2024, day, 1))


def test_badges_earned_with_dates(app, user):
    _world_tour(user)
    rows = {r["badge"].id: r for r in compute_badges(user.trips.all())}
    assert rows["countries_5"]["earned"] == date(2024, 4, 1)  # 5e pays (FR, JP, US, BR, AU)
    assert rows["continents_3"]["earned"] == date(2024, 2, 1)  # Europe, Asie, Amérique du Nord
    assert rows["continents_6"]["earned"] == date(2024, 5, 1)  # l'Afrique complète les continents habités
    assert rows["continents_7"]["earned"] is None
    assert rows["long_haul"]["earned"] == date(2024, 1, 1)  # Paris-Tokyo > 8 000 km
    assert rows["km_earth"]["earned"] is not None
    assert rows["countries_10"]["progress"] == pytest.approx(0.6)


def test_journey_counts_once_and_upcoming_ignored(app, db, user):
    from app.models import Journey

    legs = [make_trip(user, depart_date=date(2025, 1, d)) for d in range(1, 13)]
    journey = Journey(user_id=user.id)
    db.session.add(journey)
    for leg in legs:
        leg.journey = journey
    make_trip(user, depart_date=date(2025, 12, 1))  # à venir
    db.session.commit()
    rows = {r["badge"].id: r for r in compute_badges(user.trips.all())}
    assert rows["trips_10"]["earned"] is None and rows["trips_10"]["value"] == 1
    assert rows["low_carbon_10"]["earned"] == date(2025, 1, 10)


def test_continent_summary(app, user):
    _world_tour(user)
    with app.test_request_context():
        summary = {c["code"]: c for c in continent_summary(user.trips.all(), "fr")}
    assert summary["EU"]["countries"] == ["FR"] and summary["AN"]["countries"] == []
    assert summary["SA"]["name"] == "Amérique du Sud" and summary["SA"]["countries"] == ["BR"]


def test_stats_page_shows_badges_continents_places(auth_client, user):
    _world_tour(user)
    html = auth_client.get("/stats").text
    for text in ("Badges", "Long-courrier", "Continents", "Amérique du Sud", "Lieux visités"):
        assert text in html


# --- Lieux visités --------------------------------------------------------------------------

def test_places_merge_nearby_points_and_skip_home(app, db, user):
    make_trip(user, origin_name="Paris", dest_name="Lyon", depart_date=date(2025, 1, 1))
    make_trip(user, origin_name="Aéroport CDG", origin_lat=49.0097, origin_lon=2.5479, dest_name="Lyon Part-Dieu",
              dest_lat=45.7606, dest_lon=4.8594, depart_date=date(2025, 2, 1))
    places = visited_places(user.trips.all())
    assert [(p.visits, p.name in ("Lyon", "Lyon Part-Dieu")) for p in places][:1] == [(2, True)]
    assert len(places) == 3  # Lyon (2 trajets), Paris, CDG (à 25 km de Paris : lieu distinct)
    user.home_lat, user.home_lon = 48.8566, 2.3522
    db.session.commit()
    assert len(visited_places(user.trips.all(), user)) == 1  # Paris et CDG sont dans le rayon du domicile


def test_places_api(auth_client, client, db, user):
    make_trip(user, origin_country="FR", dest_country="FR", depart_date=date(2025, 1, 1))
    data = auth_client.get("/api/places").get_json()
    assert data["count"] == 2 and data["places"][0]["country"]["code"] == "FR"
    link = _link(db, user, False)
    assert client.get(f"/api/shared/{link.token}/places").get_json()["count"] == 2
    assert client.get("/api/shared/nope/places").status_code == 404
