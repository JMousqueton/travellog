"""Compagnie, numéro et appareil des vols et des trains : formulaire, fiche, export et statistiques."""
from datetime import date

from app.models import Trip
from app.trips.stats import service_stats

from .conftest import make_trip
from .test_trips import post_trip


def test_train_keeps_only_operator(auth_client, db):
    post_trip(auth_client, transport_mode="train", carrier=" SNCF ", service_number="TGV 6201", vehicle="TGV inOui")
    trip = db.session.execute(db.select(Trip)).scalar_one()
    assert (trip.carrier, trip.service_number, trip.vehicle) == ("SNCF", None, None)
    html = auth_client.get(f"/trips/{trip.id}").text
    assert "Opérateur" in html and "SNCF" in html


def test_flight_details_saved_and_shown(auth_client, db):
    post_trip(auth_client, carrier="Air France", service_number="AF1148", vehicle="Airbus A321")
    trip = db.session.execute(db.select(Trip)).scalar_one()
    assert (trip.carrier, trip.service_number, trip.vehicle) == ("Air France", "AF1148", "Airbus A321")
    html = auth_client.get(f"/trips/{trip.id}").text
    assert "Numéro de vol" in html and "AF1148" in html


def test_details_cleared_for_other_modes(auth_client, db):
    post_trip(auth_client, transport_mode="car", carrier="Air France", service_number="AF1")
    trip = db.session.execute(db.select(Trip)).scalar_one()
    assert trip.carrier is None and trip.service_number is None


def test_form_labels_follow_mode(auth_client):
    html = auth_client.get("/trips/new").text
    assert 'data-label-plane="Compagnie aérienne"' in html and 'data-label-train="Opérateur"' in html
    assert 'data-label-plane="Numéro de vol"' in html and "data-label-train=\"Numéro" not in html


def test_details_survive_export_and_import(auth_client, db, user):
    make_trip(user, transport_mode="plane", carrier="Air France", service_number="AF1148", vehicle="Airbus A321")
    csv_text = auth_client.get("/export.csv").data.decode("utf-8-sig")
    assert "carrier,service_number,vehicle" in csv_text.splitlines()[0]
    assert "Air France,AF1148,Airbus A321" in csv_text


def test_service_stats_split_round_trips(app, user):
    make_trip(user, transport_mode="plane", carrier="Air France", service_number="AF1 / AF2",
              vehicle="Airbus A321 / Airbus A320", is_round_trip=True, return_date=date(2025, 5, 3),
              dest_name="Rome, Italie")
    make_trip(user, transport_mode="plane", carrier="KLM", vehicle="Airbus A321", dest_name="Rome, Italie")
    make_trip(user, transport_mode="train", carrier="SNCF")
    rows = {r["mode"]: r for r in service_stats(user.trips.all())}
    assert rows["plane"]["legs"] == 3
    assert rows["plane"]["carriers"] == [("Air France", 2), ("KLM", 1)]
    assert rows["plane"]["vehicles"] == [("Airbus A321", 2), ("Airbus A320", 1)]
    assert rows["plane"]["places"][0] == ("Paris, France", 3)
    assert rows["train"]["carriers"] == [("SNCF", 1)]


def test_stats_page_shows_services(auth_client, user):
    make_trip(user, transport_mode="plane", carrier="Air France")
    html = auth_client.get("/stats").text
    assert "Avion et train" in html and "Air France" in html and "Aéroports" in html


def test_carrier_suggestions_put_users_own_first(app, user):
    from app.carriers import carrier_suggestions

    make_trip(user, transport_mode="plane", carrier="Air Serbia / Air France", is_round_trip=True,
              return_date=date(2025, 5, 3))
    make_trip(user, transport_mode="plane", carrier="Air Serbia")
    make_trip(user, transport_mode="train", carrier="Eurostar")
    planes = carrier_suggestions(user, "plane")
    assert planes[:2] == ["Air Serbia", "Air France"] and planes.count("Air France") == 1
    assert "KLM" in planes and "Eurostar" not in planes
    assert carrier_suggestions(user, "train")[0] == "Eurostar" and "SNCF" in carrier_suggestions(user, "train")


def test_form_offers_carrier_lists(auth_client):
    html = auth_client.get("/trips/new").text
    assert 'list="carriers-plane"' in html
    assert '<datalist id="carriers-train">' in html and '<option value="Trenitalia">' in html


def test_transport_details_per_leg(app, user):
    from app.trips.stats import transport_details

    make_trip(user, transport_mode="plane", origin_name="Charles de Gaulle International Airport (CDG)",
              dest_name="Montpellier-Méditerranée Airport (MPL)", carrier="Air France", service_number="AF1 / AF2",
              vehicle="Airbus A321 / Embraer 190", is_round_trip=True, depart_date=date(2025, 3, 1),
              return_date=date(2025, 3, 4))
    make_trip(user, transport_mode="plane", origin_name="Montpellier-Méditerranée Airport (MPL)",
              dest_name="Charles de Gaulle International Airport (CDG)", carrier="Air France",
              vehicle="Boeing 777-300 ER", depart_date=date(2024, 6, 1))
    make_trip(user, transport_mode="plane", carrier=None, depart_date=date(2025, 1, 1))
    with app.test_request_context():
        details = transport_details(user.trips.all(), "plane")
    assert details["legs"] == 4 and details["missing_carrier"] == 1 and details["missing_vehicle"] == 1
    air_france = details["carriers"][0]
    assert (air_france["name"], air_france["count"], air_france["share"]) == ("Air France", 3, 1.0)
    assert (air_france["first"], air_france["last"]) == (date(2024, 6, 1), date(2025, 3, 4))
    assert [(r["name"], r["count"]) for r in details["manufacturers"]] == [("Airbus", 1), ("Boeing", 1), ("Embraer", 1)]
    assert details["routes"][0]["name"] == "CDG – MPL" and details["routes"][0]["count"] == 3


def test_transport_stats_pages(auth_client, user):
    make_trip(user, transport_mode="plane", carrier="Air France", vehicle="Airbus A321")
    html = auth_client.get("/stats/plane").text
    assert "Vols : compagnies et appareils" in html and "Constructeurs" in html and "Airbus" in html
    train = auth_client.get("/stats/train").text
    assert "Trains : opérateurs" in train and "Constructeurs" not in train
    assert auth_client.get("/stats/car").status_code == 404
    assert 'href="/stats/plane"' in auth_client.get("/stats").text
