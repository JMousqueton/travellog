from datetime import date

import pytest

from app import geo
from app.models import GeocodeCache

from .conftest import login, make_trip


@pytest.fixture
def trips(user, other_user):
    return [
        make_trip(user, dest_name="Lyon", transport_mode="train", depart_date=date(2024, 3, 1)),
        make_trip(user, dest_name="New York", dest_lat=40.71, dest_lon=-74.0, transport_mode="plane",
                  depart_date=date(2025, 4, 1), is_round_trip=True, return_date=date(2025, 4, 10)),
        make_trip(user, dest_name="Nantes", transport_mode="car", depart_date=date(2025, 8, 1)),
        make_trip(other_user, dest_name="Hidden", transport_mode="train"),
    ]


def names(response):
    return [t["destination"]["name"] for t in response.get_json()["trips"]]


def test_api_requires_auth(client):
    for url in ("/api/trips", "/api/stats", "/api/geocode?q=paris"):
        response = client.get(url)
        assert response.status_code == 401
        assert response.get_json()["error"]


def test_trips_only_own_sorted_desc(auth_client, trips):
    response = auth_client.get("/api/trips")
    assert response.status_code == 200
    assert names(response) == ["Nantes", "New York", "Lyon"]
    data = response.get_json()
    assert data["count"] == 3 and data["count_label"] == "3 voyages"


def test_trip_payload(auth_client, trips):
    trip = next(t for t in auth_client.get("/api/trips").get_json()["trips"] if t["destination"]["name"] == "New York")
    assert trip["is_round_trip"] is True
    assert trip["return_date"] == "2025-04-10"
    assert trip["depart_date_fmt"] == "1 avr. 2025"
    assert trip["mode_label"] == "Avion"
    assert trip["total_distance_km"] == pytest.approx(2 * trip["distance_km"], abs=0.2)
    assert trip["distance_fmt"].endswith("km")
    assert trip["edit_url"] == f"/trips/{trip['id']}/edit"


@pytest.mark.parametrize("query,expected", [
    ("modes=train", ["Lyon"]),
    ("modes=train,car", ["Nantes", "Lyon"]),
    ("kind=round", ["New York"]),
    ("kind=oneway", ["Nantes", "Lyon"]),
    ("from=2025-01-01", ["Nantes", "New York"]),
    ("from=2025-01-01&to=2025-06-30", ["New York"]),
    ("to=2024-12-31&modes=plane", []),
])
def test_trip_filters(auth_client, trips, query, expected):
    assert names(auth_client.get(f"/api/trips?{query}")) == expected


@pytest.mark.parametrize("query", ["from=yesterday", "from=2025-02-01&to=2025-01-01", "modes=rocket", "kind=maybe"])
def test_invalid_filters(auth_client, trips, query):
    response = auth_client.get(f"/api/trips?{query}")
    assert response.status_code == 400
    assert response.get_json()["error"]


def test_invalid_filter_error_is_translated(client, user, db):
    user.locale = "it"
    db.session.commit()
    login(client)
    response = client.get("/api/trips?modes=rocket")
    assert response.get_json()["error"] == "Mezzo di trasporto sconosciuto: rocket"


def test_stats(auth_client, trips):
    stats = auth_client.get("/api/stats").get_json()
    assert stats["count"] == 3
    assert stats["round_trips"] == 1
    assert {m["mode"] for m in stats["by_mode"]} == {"train", "plane", "car"}
    assert sum(m["count"] for m in stats["by_mode"]) == 3
    assert stats["total_distance_km"] == pytest.approx(sum(m["distance_km"] for m in stats["by_mode"]), abs=0.5)
    filtered = auth_client.get("/api/stats?modes=plane").get_json()
    assert filtered["count"] == 1 and filtered["by_mode"][0]["share_fmt"] == "100\xa0%"


def test_stats_empty(auth_client):
    stats = auth_client.get("/api/stats").get_json()
    assert stats["count"] == 0 and stats["by_mode"] == [] and stats["total_distance_fmt"] == "0 km"


class FakeClient:
    def __init__(self, results=None, error=False):
        self.calls = []
        self.results = results if results is not None else [
            {"name": "Paris, France", "label": "Paris, Île-de-France, France", "lat": 48.85, "lon": 2.35, "type": "city"}
        ]
        self.error = error

    def search(self, query, lang):
        self.calls.append((query, lang))
        if self.error:
            raise geo.GeocodingError("down")
        return self.results


def test_geocode_uses_cache(auth_client, db, monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(geo, "client", fake)
    first = auth_client.get("/api/geocode?q=Paris").get_json()
    second = auth_client.get("/api/geocode?q=  paris ").get_json()
    assert first == second and first["results"][0]["lat"] == 48.85
    assert fake.calls == [("Paris", "fr")]
    entry = db.session.query(GeocodeCache).one()
    assert (entry.query, entry.lang, entry.name) == ("paris", "fr", "Paris, France")


def test_geocode_cache_is_per_language(auth_client, monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(geo, "client", fake)
    auth_client.get("/api/geocode?q=Londres&lang=fr")
    auth_client.get("/api/geocode?q=Londres&lang=en")
    auth_client.get("/api/geocode?q=Londres&lang=xx")  # langue inconnue -> langue active (fr), déjà en cache
    assert fake.calls == [("Londres", "fr"), ("Londres", "en")]


def test_geocode_short_query(auth_client, monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(geo, "client", fake)
    assert auth_client.get("/api/geocode?q=pa").get_json() == {"results": []}
    assert fake.calls == []


def test_geocode_service_unavailable(auth_client, monkeypatch):
    monkeypatch.setattr(geo, "client", FakeClient(error=True))
    response = auth_client.get("/api/geocode?q=Paris")
    assert response.status_code == 503
    assert response.get_json()["error"] == "La recherche de lieux est momentanément indisponible."


def test_nominatim_request_parameters(app, monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"display_name": "Roma, Lazio, Italia", "name": "Roma", "lat": "41.9", "lon": "12.5",
                     "type": "city", "address": {"country": "Italia", "country_code": "it"}}]

    def fake_get(url, params, headers, timeout):
        captured.update(url=url, params=params, headers=headers)
        return Response()

    monkeypatch.setattr(geo.requests, "get", fake_get)
    with app.test_request_context():
        results = geo.NominatimClient().search("Rome", "it")
    assert captured["params"]["accept-language"] == "it"
    assert captured["params"]["format"] == "jsonv2"
    # Le User-Agent configuré (obligatoire selon la politique Nominatim) est bien transmis.
    assert captured["headers"]["User-Agent"] == app.config["NOMINATIM_USER_AGENT"]
    assert results == [{"name": "Roma, Italia", "label": "Roma, Lazio, Italia", "lat": 41.9, "lon": 12.5, "type": "city",
                        "country_code": "IT"}]


def test_nominatim_rate_limit(app, monkeypatch):
    sleeps = []
    monkeypatch.setattr(geo.time, "sleep", sleeps.append)
    monkeypatch.setattr(geo.NominatimClient, "_last_call", geo.time.time())

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return []

    monkeypatch.setattr(geo.requests, "get", lambda *a, **k: Response())
    app.config["NOMINATIM_MIN_INTERVAL"] = 1.0
    with app.test_request_context():
        geo.NominatimClient().search("x", "fr")
    assert sleeps and 0 < sleeps[0] <= 1.0
