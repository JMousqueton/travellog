import pytest
import requests

from app import routing
from app.models import Trip

from .conftest import make_trip


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


@pytest.fixture
def osrm(app, monkeypatch):
    """Serveur OSRM simulé : renvoie 465,2 km et mémorise les URL appelées."""
    calls = []

    def fake_get(url, params, timeout, headers):
        calls.append(url)
        return _Response({"code": "Ok", "routes": [{"distance": 465_200.0}]})

    app.config["ROUTING_URL"] = "https://osrm.example"
    monkeypatch.setattr(routing.requests, "get", fake_get)
    return calls


def _form(**overrides):
    data = dict(origin_name="Paris", origin_lat="48.8566", origin_lon="2.3522",
                dest_name="Lyon", dest_lat="45.764", dest_lon="4.8357", depart_date="2025-04-01", transport_mode="car")
    data.update(overrides)
    return data


def test_car_trip_gets_road_distance(auth_client, db, osrm):
    auth_client.post("/trips/new", data=_form())
    trip = db.session.execute(db.select(Trip)).scalar_one()
    assert trip.route_distance_km == 465.2 and trip.distance_source == "route"
    assert osrm == ["https://osrm.example/route/v1/driving/2.352200,48.856600;4.835700,45.764000"]
    assert "par la route" in auth_client.get(f"/trips/{trip.id}").text


def test_train_is_estimated_not_routed(auth_client, db, osrm):
    auth_client.post("/trips/new", data=_form(transport_mode="train"))
    trip = db.session.execute(db.select(Trip)).scalar_one()
    assert trip.route_distance_km is None and osrm == []
    assert trip.distance_km == pytest.approx(trip.straight_km * 1.25)


def test_route_only_recomputed_when_places_or_mode_change(auth_client, db, osrm):
    auth_client.post("/trips/new", data=_form())
    trip = db.session.execute(db.select(Trip)).scalar_one()
    auth_client.post(f"/trips/{trip.id}/edit", data=_form(depart_date="2025-05-01", notes="x"))
    assert len(osrm) == 1
    auth_client.post(f"/trips/{trip.id}/edit", data=_form(transport_mode="train"))
    db.session.refresh(trip)
    assert trip.route_distance_km is None  # le train n'est pas routé : l'ancienne distance routière disparaît


def test_routing_failure_falls_back_to_estimate(app, auth_client, db, monkeypatch):
    app.config["ROUTING_URL"] = "https://osrm.example"

    def boom(*args, **kwargs):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(routing.requests, "get", boom)
    assert auth_client.post("/trips/new", data=_form()).status_code == 302
    trip = db.session.execute(db.select(Trip)).scalar_one()
    assert trip.route_distance_km is None and trip.distance_source == "estimate"


def test_no_route_found(app, auth_client, db, monkeypatch):
    app.config["ROUTING_URL"] = "https://osrm.example"
    monkeypatch.setattr(routing.requests, "get", lambda *a, **k: _Response({"code": "NoRoute", "routes": []}))
    auth_client.post("/trips/new", data=_form())
    assert db.session.execute(db.select(Trip)).scalar_one().route_distance_km is None


def test_compute_routes_command(app, db, user, osrm, monkeypatch):
    monkeypatch.setattr("app.cli.time.sleep", lambda s: None)
    make_trip(user, transport_mode="car")
    make_trip(user, transport_mode="train")
    result = app.test_cli_runner().invoke(args=["trips", "compute-routes"])
    assert "1 distance(s) calculée(s)" in result.output
    assert len(osrm) == 1


def test_compute_routes_requires_configuration(app):
    result = app.test_cli_runner().invoke(args=["trips", "compute-routes"])
    assert result.exit_code != 0 and "ROUTING_URL" in result.output


def test_api_exposes_distance_source(auth_client, user):
    make_trip(user)
    trip = auth_client.get("/api/trips").get_json()["trips"][0]
    assert trip["distance_source"] == "estimate"
    assert trip["distance_km"] == pytest.approx(trip["straight_km"] * 1.25, abs=0.2)
