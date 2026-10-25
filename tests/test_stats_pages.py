"""Statistiques : vue d'ensemble, pages par année (évolution, graphiques), filtres par année, page 404."""
import json
import re
from datetime import date

import pytest

from app import utils
from app.trips.stats import year_comparison

from .conftest import make_trip

TODAY = date(2026, 6, 15)


@pytest.fixture(autouse=True)
def frozen_today(monkeypatch):
    monkeypatch.setattr(utils, "today", lambda: TODAY)


def _years(user):
    make_trip(user, depart_date=date(2024, 3, 1))
    make_trip(user, depart_date=date(2025, 2, 1), origin_country="FR", dest_country="FR")
    make_trip(user, depart_date=date(2025, 8, 1), dest_name="Rome, Italie", dest_lat=41.9, dest_lon=12.5,
              dest_country="IT", transport_mode="plane")
    make_trip(user, depart_date=date(2026, 3, 1), dest_name="Madrid, Espagne", dest_lat=40.4, dest_lon=-3.7,
              dest_country="ES", transport_mode="plane")
    make_trip(user, depart_date=date(2026, 5, 1), origin_country="FR", dest_country="FR")


def test_overview_shows_overall_figures_and_one_card_per_year(auth_client, user):
    _years(user)
    html = auth_client.get("/stats").text
    titles = re.findall(r'<h2[^>]*id="(\w+)"', html)
    assert titles.index("overallTitle") < titles.index("previousTitle") < titles.index("badgesTitle")
    assert re.findall(r'href="/stats/(\d{4})"', html) == ["2026", "2025", "2024"]
    assert "En cours" in html  # carte de l'année en cours
    assert "yearTotals2026" not in html  # l'année en cours a sa propre page
    chart = json.loads(re.search(r'id="chart-years-count">(.*?)</script>', html, re.S).group(1))
    assert chart["labels"] == [2024, 2025, 2026] and chart["series"]["plane"] == [0, 1, 1]


def test_year_page_details_and_navigation(auth_client, user):
    _years(user)
    html = auth_client.get("/stats/2025").text
    assert "Statistiques 2025" in html and "Bilan 2025" in html
    assert 'href="/stats/2024"' in html and 'href="/stats/2026"' in html  # années voisines
    months = json.loads(re.search(r'id="chart-months-2025">(.*?)</script>', html, re.S).group(1))
    assert months["series"]["train"][1] == 1 and months["series"]["plane"][7] == 1  # février, août
    assert "Nouveau" in html  # l'Italie, découverte en 2025
    assert "Évolution par rapport à 2024." in html


def test_year_pages_for_unknown_years(auth_client, user):
    _years(user)
    assert auth_client.get("/stats/1990").status_code == 404
    make_trip(user, depart_date=date(2027, 1, 1))  # voyage à venir : pas encore de statistiques
    assert auth_client.get("/stats/2027").status_code == 404


def test_comparison_uses_same_date_for_current_year(app, user):
    _years(user)
    make_trip(user, depart_date=date(2025, 11, 1))  # après le 15 juin : hors de la comparaison 2026
    trips = user.trips.all()
    current = year_comparison(trips, 2026)
    assert current["same_date"] and current["year"] == 2025
    assert current["count"] == {"text": "+1", "trend": "up", "tone": "good"}  # 2 voyages contre 1
    past = year_comparison(trips, 2025)
    assert not past["same_date"] and past["count"]["text"] == "+2"  # 3 voyages contre 1
    assert past["co2"]["tone"] == "bad"  # plus de CO₂ : défavorable
    assert year_comparison(trips, 2024) is None  # pas d'année précédente


def test_comparison_shown_in_tiles(auth_client, user):
    _years(user)
    html = auth_client.get("/stats/2026").text
    assert "Évolution par rapport à 2025 à la même date." in html
    assert re.search(r'stat-delta tone-good">\s*<i[^>]*></i>\+1<', html)


def test_transport_stats_filtered_by_year(auth_client, user):
    make_trip(user, transport_mode="plane", carrier="Air France", depart_date=date(2025, 3, 1))
    make_trip(user, transport_mode="plane", carrier="KLM", depart_date=date(2026, 3, 1))
    html = auth_client.get("/stats/plane?year=2026").text
    assert "KLM" in html and "Air France" not in html and "Statistiques 2026" in html


def test_trip_list_year_filter(auth_client, user):
    _years(user)
    html = auth_client.get("/trips?year=2025").text
    assert 'aria-current="page">2025</a>' in html
    assert "Rome, Italie" in html and "Madrid, Espagne" not in html
    assert "year=2025" in html.split('class="sort-link"')[1][:200]  # le tri garde l'année
    everything = auth_client.get("/trips?year=1990").text  # année inconnue : tous les voyages
    assert "Rome, Italie" in everything and "Madrid, Espagne" in everything


def test_map_year_buttons(auth_client, user):
    _years(user)
    html = auth_client.get("/").text
    assert re.findall(r'<button[^>]*data-year="(\d*)"', html) == ["", "2026", "2025", "2024"]


def test_passport_404_page(client):
    response = client.get("/une-page-perdue")
    assert response.status_code == 404
    assert "Destination introuvable" in response.text and 'class="world-map"' in response.text
    assert client.get("/api/inexistant").get_json() == {"error": "Page introuvable"}  # l'API reste en JSON
