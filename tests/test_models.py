from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.geo import haversine_km
from app.models import GeocodeCache, Trip, User

from .conftest import make_trip, make_user


def test_password_is_hashed(app):
    user = make_user(password="s3cret-pass")
    assert user.password_hash != "s3cret-pass"
    assert user.check_password("s3cret-pass")
    assert not user.check_password("wrong")


def test_user_defaults(app):
    user = make_user()
    assert user.locale == "fr"
    assert user.theme is None
    assert user.created_at is not None


def test_email_is_unique(app, db):
    make_user("same@example.com")
    with pytest.raises(IntegrityError):
        make_user("same@example.com")


def test_haversine_paris_new_york():
    assert haversine_km(48.8566, 2.3522, 40.7128, -74.0060) == pytest.approx(5837, abs=10)
    assert haversine_km(10, 10, 10, 10) == 0


def test_trip_distances(app, user):
    one_way = make_trip(user)
    round_trip = make_trip(user, is_round_trip=True, return_date=date(2025, 5, 3))
    assert one_way.straight_km == pytest.approx(392, abs=5)
    # Train : distance estimée = vol d'oiseau × 1,25 tant qu'aucun itinéraire n'est calculé.
    assert one_way.distance_km == pytest.approx(one_way.straight_km * 1.25)
    assert one_way.distance_source == "estimate"
    assert round_trip.total_distance_km == pytest.approx(2 * round_trip.distance_km)
    one_way.route_distance_km = 465.0
    assert (one_way.distance_km, one_way.distance_source) == (465.0, "route")
    one_way.route_distance_km, one_way.transport_mode = None, "plane"
    assert (one_way.distance_km, one_way.distance_source) == (one_way.straight_km, "direct")


@pytest.mark.parametrize("overrides", [
    {"is_round_trip": True, "return_date": None},                       # retour manquant
    {"is_round_trip": True, "return_date": date(2025, 4, 30)},          # retour avant départ
    {"is_round_trip": False, "return_date": date(2025, 5, 2)},          # retour sans aller-retour
    {"transport_mode": "rocket"},                                       # mode inconnu
    {"origin_lat": 123.0},                                              # latitude hors bornes
])
def test_trip_check_constraints(app, db, user, overrides):
    with pytest.raises(IntegrityError):
        make_trip(user, **overrides)
    db.session.rollback()


def test_round_trip_same_day_is_valid(app, user):
    trip = make_trip(user, is_round_trip=True, return_date=date(2025, 5, 1))
    assert trip.id


def test_deleting_user_deletes_trips(app, db, user):
    make_trip(user)
    db.session.delete(user)
    db.session.commit()
    assert db.session.query(Trip).count() == 0


def test_geocode_cache_unique_per_lang(app, db):
    db.session.add(GeocodeCache(query="paris", lang="fr", results=[]))
    db.session.add(GeocodeCache(query="paris", lang="en", results=[]))
    db.session.commit()
    db.session.add(GeocodeCache(query="paris", lang="fr", results=[]))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
    assert db.session.query(User).count() == 0
