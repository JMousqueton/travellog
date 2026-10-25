"""Itinéraire d'un vol d'après son numéro (« AF1148 » → Air France, Paris-CDG → Barcelone).

La compagnie se déduit hors ligne du préfixe (app/data/airlines.csv) ; l'itinéraire vient d'adsbdb
(https://www.adsbdb.com, gratuit, sans clé), interrogé par le serveur et gardé en cache (table geocode_cache,
langue « flight »). C'est l'itinéraire habituel du numéro aujourd'hui : un vol ancien ou saisonnier peut différer.
"""
import re
from datetime import datetime, timedelta, timezone

import requests
from flask import current_app
from sqlalchemy.exc import IntegrityError

from .airports import find_airline, find_airline_by_iata, find_airport, place_name

# Préfixe OACI (3 lettres) ou IATA (2 caractères, dont au moins une lettre), puis 1 à 4 chiffres (+ suffixe).
NUMBER = re.compile(r"^(?:(?P<icao>[A-Z]{3})|(?P<iata>[A-Z][A-Z0-9]|[0-9][A-Z]))(?P<digits>\d{1,4})(?P<suffix>[A-Z]?)$")
CACHE_LANG = "flight"


def parse_number(text):
    """« af 1148 » → (compagnie ou None, chiffres+suffixe, préfixe saisi) ; None si ce n'est pas un numéro de vol."""
    compact = re.sub(r"[\s-]", "", text or "").upper()
    match = NUMBER.match(compact)
    if not match:
        return None
    airline = find_airline(match["icao"]) if match["icao"] else find_airline_by_iata(match["iata"])
    return airline, str(int(match["digits"])) + match["suffix"], match["icao"] or match["iata"]


def _place(airport, fallback):
    """Lieu du formulaire : l'aéroport de notre base si possible (mêmes noms qu'à l'import), sinon adsbdb."""
    known = find_airport(airport.get("iata_code") or airport.get("icao_code"))
    if known:
        return {"name": place_name(known), "lat": known["lat"], "lon": known["lon"], "country": known["country"]}
    return {"name": f"{airport.get('name') or fallback} ({airport.get('iata_code') or airport.get('icao_code')})",
            "lat": airport["latitude"], "lon": airport["longitude"], "country": airport.get("country_iso_name")}


def _fetch_route(callsign):
    """Itinéraire brut d'adsbdb, ou None (inconnu). Lève requests.RequestException si le service est injoignable."""
    from .extensions import db
    from .models import GeocodeCache

    cfg = current_app.config
    cached = db.session.execute(db.select(GeocodeCache).filter_by(query=callsign, lang=CACHE_LANG)).scalar_one_or_none()
    max_age = timedelta(days=cfg["GEOCODE_CACHE_DAYS"])
    if cached and datetime.now(timezone.utc) - cached.created_at.replace(tzinfo=timezone.utc) < max_age:
        return cached.results or None
    response = requests.get(cfg["FLIGHT_LOOKUP_URL"] + callsign, timeout=cfg["FLIGHT_LOOKUP_TIMEOUT"],
                            headers={"User-Agent": cfg["NOMINATIM_USER_AGENT"], "Accept": "application/json"})
    if response.status_code == 404:
        route = None
    else:
        response.raise_for_status()
        route = (response.json().get("response") or {}).get("flightroute") if response.content else None
        if not isinstance(route, dict):
            route = None
    if cached:
        db.session.delete(cached)
        db.session.flush()
    db.session.add(GeocodeCache(query=callsign, lang=CACHE_LANG, results=route or []))
    try:
        db.session.commit()
    except IntegrityError:  # requête identique en parallèle
        db.session.rollback()
    return route


def lookup_flight(text):
    """{service_number, carrier, origin, dest} (origin et dest : None si inconnus), ou None si numéro invalide."""
    parsed = parse_number(text)
    if parsed is None:
        return None
    airline, digits, prefix = parsed
    result = {
        "service_number": ((airline and airline["iata"]) or prefix) + digits,
        "carrier": airline["name"] if airline else None,
        "origin": None,
        "dest": None,
    }
    if airline and current_app.config["FLIGHT_LOOKUP_URL"]:
        try:
            route = _fetch_route(airline["icao"] + digits)
        except (requests.RequestException, ValueError) as exc:
            current_app.logger.warning("Recherche de vol indisponible : %s", exc)
            route = None
        if route:
            # Compagnie et numéro : ceux de notre table (compagnies actives), plus sûrs que ceux d'adsbdb.
            for key, end in (("origin", "origin"), ("dest", "destination")):
                if isinstance(route.get(end), dict) and route[end].get("latitude") is not None:
                    result[key] = _place(route[end], end)
    return result
