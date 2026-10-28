"""Données schema.org (JSON-LD) des confirmations : https://developers.google.com/gmail/markup/reference"""
import html
import json
import re

from flask import current_app

from ..airports import find_airline_by_iata, find_airport
from .rows import airport_place, make_row

LD_JSON = re.compile(r"<script[^>]*type=[\"']?application/ld\+json[\"']?[^>]*>(.*?)</script>", re.S | re.I)
# type de trajet schema.org → (mode, lieu de départ, lieu d'arrivée, numéro)
LD_TRIPS = {
    "Flight": ("plane", "departureAirport", "arrivalAirport", "flightNumber"),
    "TrainTrip": ("train", "departureStation", "arrivalStation", "trainNumber"),
    "BusTrip": ("bus", "departureBusStop", "arrivalBusStop", "busNumber"),
    "BoatTrip": ("boat", "departureBoatTerminal", "arrivalBoatTerminal", None),
}


def _ld_nodes(node):
    if isinstance(node, list):
        for item in node:
            yield from _ld_nodes(item)
    elif isinstance(node, dict):
        yield node
        if "@graph" in node:
            yield from _ld_nodes(node["@graph"])


def _ld_types(node):
    types = node.get("@type") if isinstance(node, dict) else None
    return [str(t).rpartition("/")[2] for t in (types if isinstance(types, list) else [types]) if t]


def json_ld_rows(page, lang):
    rows = []
    for block in LD_JSON.findall(page):
        try:
            data = json.loads(html.unescape(block) if "&quot;" in block else block)
        except ValueError:
            continue
        for node in _ld_nodes(data):
            if not any(t.endswith("Reservation") for t in _ld_types(node)):
                continue
            targets = node.get("reservationFor")
            for trip in targets if isinstance(targets, list) else [targets]:
                row = _ld_row(trip, lang)
                if row:
                    rows.append(row)
    return rows


def _ld_row(trip, lang):
    kind = next((LD_TRIPS[t] for t in _ld_types(trip) if t in LD_TRIPS), None)
    if kind is None:
        return None
    mode, origin_key, dest_key, number_key = kind
    day = str(trip.get("departureTime") or trip.get("departureDay") or "")[:10]
    places = [_ld_place(trip.get(origin_key), lang), _ld_place(trip.get(dest_key), lang)]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", day) or None in places:
        return None
    carrier, number = "", str(trip.get(number_key) or "").strip() if number_key else ""
    if mode == "plane":
        airline = trip.get("airline") or {}
        code = str(airline.get("iataCode") or "").strip().upper() if isinstance(airline, dict) else ""
        known = find_airline_by_iata(code) if code else None
        carrier = (known and known["name"]) or (airline.get("name") if isinstance(airline, dict) else str(airline))
        if number and number.isdigit() and code:
            number = code + number
    else:
        provider = trip.get("provider") or trip.get("trainCompany") or {}
        carrier = provider.get("name", "") if isinstance(provider, dict) else str(provider)
    return make_row(day, mode, *places, carrier=carrier, number=number)


def _ld_place(node, lang):
    """{name, lat, lon, country} d'un aéroport, d'une gare ou d'un arrêt ; None si introuvable."""
    if isinstance(node, str):
        node = {"name": node}
    if not isinstance(node, dict):
        return None
    for code in (node.get("iataCode"), node.get("icaoCode")):
        airport = find_airport(code) if code else None
        if airport:
            return airport_place(airport)
    name = str(node.get("name") or "").strip()
    geo = node.get("geo") if isinstance(node.get("geo"), dict) else {}
    try:
        return {"name": name, "lat": float(geo["latitude"]), "lon": float(geo["longitude"]), "country": ""}
    except (KeyError, TypeError, ValueError):
        pass
    if not name:
        return None
    from ..geo import geocode

    try:
        found = geocode(name, lang)
    except Exception:  # Nominatim injoignable : l'e-mail finira en ticket
        current_app.logger.warning("Géocodage impossible pour « %s »", name, exc_info=True)
        return None
    if not found:
        return None
    return {"name": name, "lat": found[0]["lat"], "lon": found[0]["lon"], "country": found[0].get("country_code") or ""}
