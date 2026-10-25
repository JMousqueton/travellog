"""Liens de partage : menu, statistiques, liste des voyages (option), bilan limité à l'année en cours."""
import re
from datetime import date

import pytest

from app import utils
from app.models import Journey, ShareLink

from .conftest import login, make_trip

TODAY = date(2026, 6, 15)


@pytest.fixture(autouse=True)
def frozen_today(monkeypatch):
    monkeypatch.setattr(utils, "today", lambda: TODAY)


@pytest.fixture
def link(db, user):
    link = ShareLink(user_id=user.id)
    db.session.add(link)
    db.session.commit()
    return link


def _menu(html):
    nav = html[html.index('id="mainNav"'):]
    return re.findall(r'<span class="nav-label">([^<]+)</span>', nav[:nav.index("</ul>")])


def test_menu_and_trips_page_follow_the_option(client, db, user, link):
    make_trip(user, depart_date=date(2025, 5, 1))
    assert _menu(client.get(f"/s/{link.token}").text) == ["Carte", "Statistiques", "Bilan"]
    assert client.get(f"/s/{link.token}/trips").status_code == 404
    link.show_trips = True
    db.session.commit()
    assert _menu(client.get(f"/s/{link.token}/stats").text) == ["Carte", "Statistiques", "Voyages", "Bilan"]
    assert client.get(f"/s/{link.token}/trips").status_code == 200


def test_shared_stats_show_overall_without_year_links(client, user, link):
    make_trip(user, depart_date=date(2025, 5, 1), notes="Secret")
    html = client.get(f"/s/{link.token}/stats").text
    assert "Depuis le début" in html and "Badges · tous vos voyages" in html
    assert not re.search(r'href="/stats/\d{4}"', html) and "Secret" not in html


def test_shared_trips_grouped_by_journey_and_hide_upcoming_legs(client, db, user, link):
    journey = Journey(user_id=user.id, name="Italie", notes="Notes privées")
    db.session.add(journey)
    legs = [make_trip(user, depart_date=date(2026, 5, 1), dest_name="Milan, Italie"),
            make_trip(user, depart_date=date(2026, 5, 4), dest_name="Rome, Italie"),
            make_trip(user, depart_date=date(2026, 8, 1), dest_name="Naples, Italie")]  # à venir
    for leg in legs:
        leg.journey = journey
    make_trip(user, depart_date=date(2025, 3, 1), dest_name="Lyon, France")
    link.show_trips = True
    db.session.commit()
    html = client.get(f"/s/{link.token}/trips").text
    assert "Italie" in html and "2 trajets" in html and "Naples" not in html and "Notes privées" not in html
    assert html.index("Rome, Italie") < html.index("Lyon, France")  # plus récents d'abord
    link.include_upcoming = True
    db.session.commit()
    html = client.get(f"/s/{link.token}/trips").text
    assert "3 trajets" in html and "Naples" in html and "trip-upcoming" in html and "Dans 47 jours" in html


def test_toggle_trip_list(auth_client, db, link):
    auth_client.post(f"/share/{link.id}/trips")
    db.session.refresh(link)
    assert link.show_trips
    assert "Masquer la liste des trajets" in auth_client.get("/share").text


def test_shared_review_limited_to_current_year(client, monkeypatch, user, link):
    make_trip(user, depart_date=date(2025, 5, 1))
    make_trip(user, depart_date=date(2026, 5, 1))
    review = client.get(f"/s/{link.token}/review/2026")
    assert review.status_code == 200 and "Télécharger l'image" not in review.text
    assert client.get(f"/s/{link.token}/review/2025").status_code == 404
    assert client.get(f"/s/{link.token}/review/2025.png").status_code == 404
    monkeypatch.setattr(utils, "today", lambda: date(2026, 2, 10))  # janvier-février : l'année écoulée reste visible
    assert client.get(f"/s/{link.token}/review/2025").status_code == 200


def test_owner_keeps_every_review(client, user):
    make_trip(user, depart_date=date(2024, 5, 1))
    login(client)
    response = client.get("/review/2024")
    assert response.status_code == 200 and "Télécharger l'image" in response.text
