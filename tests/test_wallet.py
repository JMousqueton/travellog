"""Cartes d'embarquement Apple Wallet (.pkpass) : par e-mail et depuis la page Importer / exporter."""
import io
import json
import zipfile
from datetime import date

from app import mail_import
from app.mail_import.wallet import julian_to_date, parse_bcbp, pass_rows

from .conftest import import_file
from .test_mail_import import make_mail, no_dkim  # noqa: F401 (fixture)

# Aller CDG → BCN AF1148 le 72e jour, retour BCN → CDG AF1549 le 75e (deux vols dans un même code-barres).
BCBP = ("M2DUPONT/JEAN         EABC123 CDGBCNAF 1148 072Y012A0042 100"
        "ABC123 BCNCDGAF 1549 075Y014C0007 100")


def pkpass(document):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("pass.json", json.dumps(document))
        archive.writestr("manifest.json", "{}")
    return buffer.getvalue()


def boarding_pass(barcode=BCBP, transit="PKTransitTypeAir", **extra):
    document = {"formatVersion": 1, "organizationName": "Air France", "relevantDate": "2026-03-12T09:20+01:00",
                "boardingPass": {"transitType": transit,
                                 "primaryFields": [{"key": "origin", "label": "Paris", "value": "CDG"},
                                                   {"key": "destination", "label": "Barcelone", "value": "BCN"}],
                                 "auxiliaryFields": [{"key": "flight", "label": "Vol", "value": "AF 1148"}]}}
    if barcode:
        document["barcodes"] = [{"format": "PKBarcodeFormatPDF417", "message": barcode}]
    document.update(extra)
    return document


def test_parse_bcbp_reads_every_leg():
    legs = parse_bcbp(BCBP)
    assert [(leg["origin"], leg["dest"], leg["number"], leg["julian"]) for leg in legs] == [
        ("CDG", "BCN", "AF1148", 72), ("BCN", "CDG", "AF1549", 75)]
    assert parse_bcbp("not a boarding pass") == []


def test_julian_date_closest_to_reference():
    assert julian_to_date(72, date(2026, 3, 1)) == date(2026, 3, 13)
    assert julian_to_date(2, date(2026, 12, 30)) == date(2027, 1, 2)
    assert julian_to_date(360, date(2027, 1, 3)) == date(2026, 12, 26)


def test_barcode_gives_both_flights(app):
    rows = pass_rows(pkpass(boarding_pass()), date(2026, 3, 1), "fr")
    assert [(r["depart_date"], r["service_number"], r["carrier"]) for r in rows] == [
        ("2026-03-13", "AF1148", "Air France"), ("2026-03-16", "AF1549", "Air France")]
    assert "(CDG)" in rows[0]["origin_name"] and "(BCN)" in rows[0]["dest_name"]


def test_fields_used_without_barcode(app):
    rows = pass_rows(pkpass(boarding_pass(barcode=None)), date(2026, 1, 1), "fr")
    assert [(r["depart_date"], r["service_number"]) for r in rows] == [("2026-03-12", "AF1148")]


def test_semantics_for_train(app):
    document = boarding_pass(barcode=None, transit="PKTransitTypeTrain", semantics={
        "originalDepartureDate": "2026-05-02T08:10+02:00", "vehicleNumber": "9241", "transitProvider": "SNCF",
        "departureStationName": "Paris Gare de Lyon", "departureLocation": {"latitude": 48.844, "longitude": 2.374},
        "arrivalStationName": "Lyon Part-Dieu", "arrivalLocation": {"latitude": 45.760, "longitude": 4.859}})
    rows = pass_rows(pkpass(document), date(2026, 1, 1), "fr")
    assert [(r["transport_mode"], r["depart_date"], r["origin_name"], r["dest_name"], r["carrier"], r["service_number"])
            for r in rows] == [("train", "2026-05-02", "Paris Gare de Lyon", "Lyon Part-Dieu", "SNCF", "9241")]


def test_pkpasses_bundle_and_non_boarding_passes(app):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("1.pkpass", pkpass(boarding_pass()))
        archive.writestr("2.pkpass", pkpass({"eventTicket": {}, "organizationName": "Stade"}))
    assert len(pass_rows(buffer.getvalue(), date(2026, 3, 1), "fr")) == 2


def test_email_with_wallet_attachment_imports_round_trip(app, db, user):
    msg = make_mail(text="Votre carte d'embarquement est jointe.")
    msg.add_attachment(pkpass(boarding_pass()), maintype="application", subtype="vnd.apple.pkpass",
                       filename="boardingpass.pkpass")
    outcome = mail_import.process(msg.as_bytes())
    assert outcome.status == "imported"
    trip = user.trips.one()
    assert (trip.depart_date, trip.return_date, trip.service_number) == (
        date(2026, 3, 13), date(2026, 3, 16), "AF1148 / AF1549")


def test_invalid_wallet_attachment_opens_ticket(app, db, user):
    msg = make_mail(text="Rien ici.")
    msg.add_attachment(b"not a zip", maintype="application", subtype="octet-stream", filename="pass.pkpass")
    outcome = mail_import.process(msg.as_bytes())
    assert outcome.status == "failed" and "archive zip invalide" in outcome.reason


def test_upload_pkpass_imports_round_trip(auth_client, user):
    assert import_file(auth_client, pkpass(boarding_pass()), "AF1148.pkpass").status_code == 302
    trip = user.trips.one()
    assert (trip.transport_mode, trip.is_round_trip, trip.service_number) == ("plane", True, "AF1148 / AF1549")


def test_upload_invalid_pkpass(auth_client):
    response = import_file(auth_client, b"garbage", "x.pkpass")
    assert response.status_code == 400 and "Carte Wallet illisible" in response.text
