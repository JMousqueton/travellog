"""Badges : paliers de pays, continents, distance, voyages… avec la date à laquelle chacun a été atteint.

Les trajets déjà commencés sont rejoués dans l'ordre chronologique ; un badge est daté du jour du trajet
qui a fait franchir le palier. Les badges non obtenus indiquent la progression.

Deux séries : BADGES sur tous les voyages, YEAR_BADGES (paliers plus bas) sur ceux de l'année en cours.
"""
from dataclasses import dataclass

from flask_babel import lazy_gettext as _l

from .. import countries as geo_countries
from ..transport import TRANSPORT_MODES
from .stats import happened

LOW_CARBON_MODES = {"train", "bike", "walk"}


@dataclass(frozen=True)
class BadgeDef:
    id: str
    icon: str
    metric: str
    threshold: float
    title: object
    text: object


BADGES = [
    BadgeDef("trips_10", "fa-suitcase", "trips", 10, _l("Globe-trotter"), _l("10 voyages")),
    BadgeDef("trips_50", "fa-suitcase-rolling", "trips", 50, _l("Grand voyageur"), _l("50 voyages")),
    BadgeDef("trips_100", "fa-crown", "trips", 100, _l("Voyageur légendaire"), _l("100 voyages")),
    BadgeDef("countries_5", "fa-flag", "countries", 5, _l("Explorateur"), _l("5 pays visités")),
    BadgeDef("countries_10", "fa-flag-checkered", "countries", 10, _l("Collectionneur de pays"), _l("10 pays visités")),
    BadgeDef("countries_25", "fa-passport", "countries", 25, _l("Passeport bien rempli"), _l("25 pays visités")),
    BadgeDef("countries_50", "fa-stamp", "countries", 50, _l("Citoyen du monde"), _l("50 pays visités")),
    BadgeDef("countries_100", "fa-medal", "countries", 100, _l("Centurion"), _l("100 pays visités")),
    BadgeDef("continents_3", "fa-earth-europe", "inhabited", 3, _l("Trois continents"), _l("3 continents visités")),
    BadgeDef("continents_6", "fa-earth-asia", "inhabited", 6, _l("Tous les continents habités"),
             _l("Europe, Asie, Afrique, Amériques et Océanie")),
    BadgeDef("continents_7", "fa-snowflake", "continents", 7, _l("Les sept continents"), _l("Antarctique compris")),
    BadgeDef("km_10000", "fa-route", "km", 10_000, _l("10 000 km"), _l("10 000 km parcourus")),
    BadgeDef("km_earth", "fa-earth-americas", "km", 40_075, _l("Tour du monde"),
             _l("L'équivalent d'un tour de la Terre (40 075 km)")),
    BadgeDef("km_100000", "fa-infinity", "km", 100_000, _l("100 000 km"), _l("100 000 km parcourus")),
    BadgeDef("km_moon", "fa-moon", "km", 384_400, _l("Jusqu'à la Lune"), _l("La distance Terre-Lune (384 400 km)")),
    BadgeDef("all_modes", "fa-shuffle", "modes", len(TRANSPORT_MODES), _l("Tous les moyens sont bons"),
             _l("Avion, train, voiture, bus, bateau, vélo et marche")),
    BadgeDef("low_carbon_10", "fa-leaf", "low_carbon", 10, _l("Voyageur sobre"), _l("10 trajets en train, à vélo ou à pied")),
    BadgeDef("long_haul", "fa-plane-up", "longest", 8_000, _l("Long-courrier"), _l("Un trajet de plus de 8 000 km")),
]


YEAR_BADGES = [
    BadgeDef("year_trips_5", "fa-suitcase", "trips", 5, _l("Bien parti"), _l("5 voyages dans l'année")),
    BadgeDef("year_trips_12", "fa-calendar-days", "trips", 12, _l("Un voyage par mois"), _l("12 voyages dans l'année")),
    BadgeDef("year_trips_25", "fa-suitcase-rolling", "trips", 25, _l("Toujours en vadrouille"),
             _l("25 voyages dans l'année")),
    BadgeDef("year_countries_3", "fa-flag", "countries", 3, _l("Escapades"), _l("3 pays visités dans l'année")),
    BadgeDef("year_countries_10", "fa-passport", "countries", 10, _l("Année passeport"),
             _l("10 pays visités dans l'année")),
    BadgeDef("year_continents_2", "fa-earth-europe", "inhabited", 2, _l("Changement de continent"),
             _l("2 continents visités dans l'année")),
    BadgeDef("year_continents_3", "fa-earth-asia", "inhabited", 3, _l("Trois continents en un an"),
             _l("3 continents visités dans l'année")),
    BadgeDef("year_km_10000", "fa-route", "km", 10_000, _l("10 000 km dans l'année"),
             _l("10 000 km parcourus dans l'année")),
    BadgeDef("year_km_earth", "fa-earth-americas", "km", 40_075, _l("Tour du monde en un an"),
             _l("L'équivalent d'un tour de la Terre dans l'année")),
    BadgeDef("year_modes_4", "fa-shuffle", "modes", 4, _l("Multimodal"),
             _l("4 moyens de transport différents dans l'année")),
    BadgeDef("year_low_carbon_5", "fa-leaf", "low_carbon", 5, _l("Année sobre"),
             _l("5 trajets en train, à vélo ou à pied dans l'année")),
    BadgeDef("year_long_haul", "fa-plane-up", "longest", 8_000, _l("Long-courrier de l'année"),
             _l("Un trajet de plus de 8 000 km dans l'année")),
]


def compute_year_badges(trips, year):
    """Badges de l'année : YEAR_BADGES calculés sur les seuls trajets partis cette année-là."""
    return compute_badges([t for t in trips if t.depart_date.year == year], YEAR_BADGES)


def compute_badges(trips, definitions=BADGES):
    """[{badge, earned (date ou None), value, progress (0 à 1)}], dans l'ordre des définitions."""
    ordered = sorted(happened(trips), key=lambda t: (t.depart_date, t.id))
    earned, journeys = {}, set()
    state = {"trips": 0, "countries": set(), "continents": set(), "inhabited": set(), "km": 0.0, "modes": set(), "low_carbon": 0,
             "longest": 0.0}
    for trip in ordered:
        if trip.journey_id is None or trip.journey_id not in journeys:
            state["trips"] += 1  # un voyage en plusieurs trajets compte pour un
            if trip.journey_id is not None:
                journeys.add(trip.journey_id)
        for code in trip.countries:
            state["countries"].add(code)
            continent = geo_countries.continent(code)
            if continent:
                state["continents"].add(continent)
                if continent != "AN":
                    state["inhabited"].add(continent)
        state["km"] += trip.total_distance_km
        state["modes"].add(trip.transport_mode)
        state["low_carbon"] += trip.transport_mode in LOW_CARBON_MODES
        state["longest"] = max(state["longest"], trip.distance_km)
        for badge in definitions:
            if badge.id not in earned and _value(state, badge.metric) >= badge.threshold:
                earned[badge.id] = trip.depart_date
    rows = []
    for badge in definitions:
        value = _value(state, badge.metric)
        rows.append({"badge": badge, "earned": earned.get(badge.id), "value": value,
                     "progress": min(1.0, value / badge.threshold)})
    return rows


def _value(state, metric):
    value = state[metric]
    return len(value) if isinstance(value, set) else value


def continent_summary(trips, locale):
    """Les sept continents, avec les pays visités de chacun (liste vide si jamais visité)."""
    visited = {}
    for trip in happened(trips):
        for code in trip.countries:
            visited.setdefault(geo_countries.continent(code), set()).add(code)
    return [{"code": code, "name": geo_countries.continent_name(code, locale),
             "countries": sorted(visited.get(code, ()), key=lambda c: geo_countries.country_name(c, locale))}
            for code in geo_countries.CONTINENTS]
