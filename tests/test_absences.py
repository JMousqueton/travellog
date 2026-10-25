from datetime import date

import pytest

from app import utils
from app.trips.absences import absence_summary, compute_absences

from .conftest import login, make_trip

PARIS = dict(origin_name="Paris", origin_lat=48.8566, origin_lon=2.3522, origin_country="FR")
CDG = dict(origin_name="Aéroport CDG", origin_lat=49.0097, origin_lon=2.5479, origin_country="FR")


def place(prefix, name, lat, lon, country):
    return {f"{prefix}_name": name, f"{prefix}_lat": lat, f"{prefix}_lon": lon, f"{prefix}_country": country}


LISBON = place("dest", "Lisbonne", 38.72, -9.14, "PT")
LYON = place("dest", "Lyon", 45.764, 4.8357, "FR")


@pytest.fixture(autouse=True)
def frozen_today(monkeypatch):
    monkeypatch.setattr(utils, "today", lambda: date(2025, 12, 31))


@pytest.fixture
def home(db, user):
    user.home_name, user.home_lat, user.home_lon, user.home_country = "Paris", 48.8566, 2.3522, "FR"
    db.session.commit()
    return user


def test_no_home_no_absences(user):
    make_trip(user)
    assert compute_absences(user, user.trips.all()) == []


def test_round_trip_absence(home):
    make_trip(home, **PARIS, **LISBON, transport_mode="plane", depart_date=date(2025, 3, 1),
              is_round_trip=True, return_date=date(2025, 3, 8))
    (absence,) = compute_absences(home, home.trips.all())
    assert (absence.start, absence.end, absence.days, absence.nights) == (date(2025, 3, 1), date(2025, 3, 8), 8, 7)
    assert absence.nights_abroad("FR") == 7


def test_chained_one_way_trips_from_airport(home):
    # Départ de l'aéroport (dans le rayon du domicile), étape, puis retour à Paris.
    make_trip(home, **CDG, **LISBON, transport_mode="plane", depart_date=date(2025, 5, 1))
    make_trip(home, **place("origin", "Lisbonne", 38.72, -9.14, "PT"), **place("dest", "Madrid", 40.42, -3.70, "ES"),
              transport_mode="train", depart_date=date(2025, 5, 4))
    make_trip(home, **place("origin", "Madrid", 40.42, -3.70, "ES"), **place("dest", "Paris", 48.85, 2.35, "FR"),
              transport_mode="plane", depart_date=date(2025, 5, 7))
    (absence,) = compute_absences(home, home.trips.all())
    assert (absence.start, absence.end, absence.days) == (date(2025, 5, 1), date(2025, 5, 7), 7)
    assert [d[0] for d in absence.destinations] == ["Lisbonne", "Madrid"]
    assert absence.nights_abroad("FR") == 6


def test_domestic_trip_counts_days_but_not_nights_abroad(home):
    make_trip(home, **PARIS, **LYON, depart_date=date(2025, 6, 1), is_round_trip=True, return_date=date(2025, 6, 3))
    summary = absence_summary(home, home.trips.all())
    assert summary["days"] == 3 and summary["nights_abroad"] == 0


def test_ongoing_and_open_absences(home, monkeypatch):
    monkeypatch.setattr(utils, "today", lambda: date(2025, 8, 10))
    make_trip(home, **PARIS, **LISBON, depart_date=date(2025, 8, 5), is_round_trip=True, return_date=date(2025, 8, 20))
    (ongoing,) = compute_absences(home, home.trips.all())
    assert ongoing.ongoing and ongoing.end == date(2025, 8, 10) and ongoing.days == 6
    make_trip(home, **PARIS, **LYON, depart_date=date(2025, 1, 10))  # aller simple sans retour
    first, second = compute_absences(home, home.trips.all())
    # Le départ suivant depuis Paris prouve un retour : la première absence s'arrête à son dernier trajet.
    assert first.open and first.days == 1 and second.ongoing


def test_absence_split_across_years(home):
    make_trip(home, **PARIS, **LISBON, depart_date=date(2024, 12, 28), is_round_trip=True, return_date=date(2025, 1, 3))
    summary = absence_summary(home, home.trips.all())
    by_year = summary["by_year"]
    assert by_year[2024]["days"] == 4 and by_year[2025]["days"] == 3
    assert by_year[2024]["nights_abroad"] == 4 and by_year[2025]["nights_abroad"] == 2
    assert summary["days"] == 7


def test_upcoming_trips_are_ignored(home):
    make_trip(home, **PARIS, **LISBON, depart_date=date(2026, 2, 1), is_round_trip=True, return_date=date(2026, 2, 5))
    assert compute_absences(home, home.trips.all()) == []


def test_home_setting_and_stats_page(client, db, user, monkeypatch):
    from app.trips import routes

    login(client)
    make_trip(user, **PARIS, **LYON, depart_date=date(2024, 1, 1))
    assert "Définir mon domicile" in client.get("/stats").text
    response = client.post("/auth/home", data={"home_name": "Paris", "home_lat": "48.8566", "home_lon": "2.3522"})
    assert response.status_code == 302
    db.session.refresh(user)
    assert (user.home_name, user.home_country) == ("Paris", "FR")  # pays déduit des coordonnées
    make_trip(user, **PARIS, **LISBON, depart_date=date(2025, 3, 1), is_round_trip=True, return_date=date(2025, 3, 8))
    html = client.get("/stats").text
    assert "jours loin de chez moi" in html and "nuits à l'étranger" in html
    assert "8 jours loin de chez moi" in client.get("/review/2025").text
    # Sans suggestion choisie : géocodage côté serveur.
    monkeypatch.setattr(routes, "geocode", lambda q, lang: [{"name": "Lyon", "label": "Lyon", "lat": 45.76,
                                                            "lon": 4.83, "type": "city", "country_code": "FR"}])
    client.post("/auth/home", data={"home_name": "Lyon"})
    db.session.refresh(user)
    assert (user.home_lat, user.home_name) == (45.76, "Lyon")
    client.post("/auth/home/clear")
    db.session.refresh(user)
    assert not user.has_home


def test_absence_starting_elsewhere_ends_back_there(home):
    # Bordeaux -> Saint-Sébastien en aller-retour : le trajet Paris -> Bordeaux n'a pas été saisi.
    make_trip(home, **place("origin", "Bordeaux", 44.84, -0.58, "FR"), **place("dest", "San Sebastián", 43.32, -1.98, "ES"),
              transport_mode="car", depart_date=date(2025, 7, 19), is_round_trip=True, return_date=date(2025, 7, 27))
    make_trip(home, **PARIS, **LISBON, depart_date=date(2025, 9, 5))
    first, second = compute_absences(home, home.trips.all())
    assert (first.start, first.end, first.days) == (date(2025, 7, 19), date(2025, 7, 27), 9)
    assert first.nights_abroad("FR") == 8 and not first.open
    assert second.start == date(2025, 9, 5)


def test_unrelated_one_way_trips_are_not_chained(home):
    # Amsterdam -> Utrecht puis Berlin -> Prague : rien ne relie Utrecht à Berlin, ce ne sont pas
    # 6 jours d'absence continue mais deux absences d'un jour sans retour renseigné.
    make_trip(home, **place("origin", "Amsterdam", 52.37, 4.90, "NL"), **place("dest", "Utrecht", 52.09, 5.12, "NL"),
              transport_mode="bike", depart_date=date(2024, 5, 4))
    make_trip(home, **place("origin", "Berlin", 52.52, 13.40, "DE"), **place("dest", "Prague", 50.08, 14.44, "CZ"),
              transport_mode="bus", depart_date=date(2024, 5, 9))
    absences = compute_absences(home, home.trips.all())
    assert [(a.start, a.days, a.open) for a in absences] == [(date(2024, 5, 4), 1, True), (date(2024, 5, 9), 1, True)]


def test_local_round_trip_away_from_home(home):
    # Aller-retour Nice -> Monaco dans la journée (les deux villes sont à moins de 30 km).
    make_trip(home, **place("origin", "Nice", 43.71, 7.26, "FR"), **place("dest", "Monaco", 43.74, 7.42, "MC"),
              transport_mode="bus", depart_date=date(2025, 9, 6), is_round_trip=True, return_date=date(2025, 9, 6))
    (absence,) = compute_absences(home, home.trips.all())
    assert absence.days == 1 and [d[0] for d in absence.destinations] == ["Monaco"]


def test_shared_day_counted_once(home):
    make_trip(home, **PARIS, **LYON, depart_date=date(2025, 3, 1), is_round_trip=True, return_date=date(2025, 3, 3))
    make_trip(home, **PARIS, **LISBON, depart_date=date(2025, 3, 3), is_round_trip=True, return_date=date(2025, 3, 5))
    summary = absence_summary(home, home.trips.all())
    assert summary["days"] == 5  # du 1er au 5 mars, le 3 n'est compté qu'une fois
