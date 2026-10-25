"""Numéro de vol : compagnie d'après le préfixe, itinéraire via adsbdb (simulé, sans appel réseau), cache."""
from datetime import date

import pytest
import requests

from app import flights
from app.carriers import vehicle_suggestions
from app.flights import lookup_flight, parse_number

from .conftest import make_trip

ADSBDB = {"response": {"flightroute": {
    "callsign": "AFR1148", "callsign_iata": "AF1148",
    "airline": {"name": "Air France", "icao": "AFR", "iata": "AF"},
    "origin": {"iata_code": "CDG", "icao_code": "LFPG", "latitude": 49.0128, "longitude": 2.55, "name": "Charles de Gaulle"},
    "destination": {"iata_code": "BCN", "icao_code": "LEBL", "latitude": 41.2971, "longitude": 2.07846, "name": "El Prat"},
}}}


class FakeResponse:
    def __init__(self, status, payload=None):
        self.status_code, self._payload = status, payload
        self.content = b"x" if payload else b""

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


@pytest.fixture
def adsbdb(app, monkeypatch):
    """Active la recherche et enregistre les indicatifs demandés à adsbdb."""
    app.config["FLIGHT_LOOKUP_URL"] = "https://adsbdb.test/v0/callsign/"
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url.rsplit("/", 1)[-1])
        return FakeResponse(200, ADSBDB) if url.endswith("AFR1148") else FakeResponse(404)

    monkeypatch.setattr(flights.requests, "get", fake_get)
    return calls


@pytest.mark.parametrize("text,expected", [
    ("AF1148", ("AFR", "1148", "AF")), ("af 1148", ("AFR", "1148", "AF")), ("AFR1148", ("AFR", "1148", "AFR")),
    ("AF0072", ("AFR", "72", "AF")), ("U2 4867", ("EZY", "4867", "U2")),
])
def test_parse_number(app, text, expected):
    airline, digits, prefix = parse_number(text)
    assert (airline["icao"], digits, prefix) == expected


@pytest.mark.parametrize("text", ["hello", "1148", "", "AF12345"])
def test_parse_number_rejects(app, text):
    assert parse_number(text) is None


def test_lookup_fills_route_from_our_airports(app, adsbdb):
    flight = lookup_flight("af 1148")
    assert (flight["service_number"], flight["carrier"]) == ("AF1148", "Air France")
    assert flight["origin"]["name"] == "Charles de Gaulle International Airport (CDG)"
    assert flight["dest"]["country"] == "ES"
    lookup_flight("AF1148")
    assert adsbdb == ["AFR1148"]  # deuxième recherche : depuis le cache


def test_unknown_route_keeps_airline(app, adsbdb):
    flight = lookup_flight("AF9999")
    assert flight["carrier"] == "Air France" and flight["origin"] is None


def test_service_down_keeps_airline(app, adsbdb, monkeypatch):
    def broken(url, **kwargs):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(flights.requests, "get", broken)
    flight = lookup_flight("AF1148")
    assert flight["carrier"] == "Air France" and flight["dest"] is None


def test_disabled_lookup_makes_no_call(app, monkeypatch):
    monkeypatch.setattr(flights.requests, "get", lambda *a, **k: pytest.fail("appel réseau"))
    assert lookup_flight("AF1148")["origin"] is None  # FLIGHT_LOOKUP_URL vide en test


def test_flight_api(auth_client, adsbdb):
    data = auth_client.get("/api/flight?number=AF1148").get_json()
    assert data["dest"]["name"].endswith("(BCN)")
    assert auth_client.get("/api/flight?number=ZZ999").status_code == 404
    assert auth_client.get("/api/flight?number=hello").status_code == 404


def test_flight_api_requires_login(client):
    assert client.get("/api/flight?number=AF1148").status_code == 401


def test_vehicle_suggestions(app, user):
    make_trip(user, transport_mode="plane", vehicle="Airbus A321 / Embraer 190", is_round_trip=True,
              return_date=date(2025, 5, 3))
    make_trip(user, transport_mode="plane", vehicle="Embraer 190")
    suggestions = vehicle_suggestions(user, "plane")
    assert suggestions[:2] == ["Embraer 190", "Airbus A321"] and "Boeing 787-9" in suggestions
    assert suggestions.count("Airbus A321") == 1 and vehicle_suggestions(user, "train") == []
