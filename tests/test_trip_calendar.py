"""Mes voyages en calendrier (Premium) : grille du mois, barres du départ au retour, voyages regroupés."""
import re
from datetime import date

import pytest

from app.models import Journey
from .conftest import make_trip


@pytest.fixture
def billing(app):
    app.config.update(STRIPE_SECRET_KEY="sk_test_x", PREMIUM_PRICE_MONTHLY="2", PREMIUM_PRICE_YEARLY="12")
    return app


def _bars(html):
    return re.findall(r'<a class="trip-bar[^"]*"[^>]*style="grid-column: (\d) / span (\d); grid-row: (\d)', html)


def test_calendar_month_grid_and_round_trip_bar(auth_client, user):
    make_trip(user, depart_date=date(2025, 5, 1), is_round_trip=True, return_date=date(2025, 5, 4))
    html = auth_client.get("/trips/calendar?month=2025-05").text
    assert "Mai 2025" in html and 'aria-current="page"' in html
    # Locale fr : semaines du lundi ; le 1er mai 2025 est un jeudi (colonne 4), retour le dimanche 4 (colonne 7).
    assert _bars(html) == [("4", "4", "2")]
    assert "Paris, France → Lyon, France" in html and 'href="/trips/1"' in html
    assert 'month=2025-04' in html and 'month=2025-06' in html


def test_calendar_bar_spans_weeks_and_months(auth_client, user):
    make_trip(user, depart_date=date(2025, 4, 28), is_round_trip=True, return_date=date(2025, 5, 13))
    html = auth_client.get("/trips/calendar?month=2025-05").text
    # Visible du lundi 28 avril au dimanche 1er juin : la barre couvre trois semaines.
    assert _bars(html) == [("1", "7", "2"), ("1", "7", "2"), ("1", "2", "2")]
    assert "cont-after" in html and "cont-before" in html


def test_calendar_overlapping_trips_use_lanes(auth_client, user):
    make_trip(user, depart_date=date(2025, 5, 5), is_round_trip=True, return_date=date(2025, 5, 8))
    make_trip(user, depart_date=date(2025, 5, 6), dest_name="Nice, France", transport_mode="plane")
    make_trip(user, depart_date=date(2025, 5, 9), dest_name="Lille, France")
    html = auth_client.get("/trips/calendar?month=2025-05").text
    assert sorted(_bars(html)) == [("1", "4", "2"), ("2", "1", "3"), ("5", "1", "2")]


def test_calendar_journey_is_one_bar(auth_client, user, db):
    a = make_trip(user, depart_date=date(2025, 5, 5))
    b = make_trip(user, depart_date=date(2025, 5, 7), origin_name="Lyon, France", dest_name="Paris, France")
    journey = Journey(user_id=user.id, name="Tour de France")
    a.journey = b.journey = journey
    db.session.add(journey)
    db.session.commit()
    html = auth_client.get("/trips/calendar?month=2025-05").text
    assert _bars(html) == [("1", "3", "2")] and "Tour de France" in html and "is-journey" in html


def test_calendar_invalid_month_falls_back_and_empty_state(auth_client, user):
    assert auth_client.get("/trips/calendar?month=2025-13").status_code == 200
    html = auth_client.get("/trips/calendar").text
    assert "Aucun voyage pour l'instant" in html


def test_list_has_calendar_toggle_and_premium_redirect(auth_client, user, billing):
    make_trip(user)
    html = auth_client.get("/trips").text
    assert 'href="/trips/calendar"' in html and "fa-gem" in html
    response = auth_client.get("/trips/calendar")
    assert response.status_code == 302 and response.location.endswith("/billing/")


def test_calendar_only_shows_own_trips(auth_client, user, other_user):
    make_trip(other_user, depart_date=date(2025, 5, 1), dest_name="Secret, France")
    html = auth_client.get("/trips/calendar?month=2025-05").text
    assert "Secret" not in html
