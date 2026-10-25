import csv
import io
import json
import os
from datetime import date

import pytest
from PIL import Image

from app.countries import country_at, country_name, flag
from app.models import Journey, Photo, ShareLink, Trip
from app.trips.stats import compute_stats, yearly_stats
from app.transport import co2_kg

from .conftest import login, make_trip, make_user

PARIS = dict(origin_name="Paris, France", origin_lat=48.8566, origin_lon=2.3522)
TOKYO = dict(dest_name="Tokyo, Japon", dest_lat=35.6762, dest_lon=139.6503)


# --- Pays -----------------------------------------------------------------------------------

@pytest.mark.parametrize("lat,lon,code", [
    (48.8566, 2.3522, "FR"), (40.7128, -74.0060, "US"), (43.7384, 7.4246, "MC"),
    (43.7102, 7.2620, "FR"),  # Nice : sur la côte, juste hors du tracé simplifié
    (1.29, 103.85, "SG"), (-33.87, 151.21, "AU"), (30.0, -40.0, None),
])
def test_country_lookup(lat, lon, code):
    assert country_at(lat, lon) == code


def test_country_names_and_flags():
    assert country_name("DE", "fr") == "Allemagne"
    assert country_name("DE", "en") == "Germany"
    assert flag("FR") == "\U0001F1EB\U0001F1F7"


def _trip_form(**overrides):
    data = dict(origin_name="Paris", origin_lat="48.8566", origin_lon="2.3522",
                dest_name="Tokyo", dest_lat="35.6762", dest_lon="139.6503",
                depart_date="2025-04-01", transport_mode="plane")
    data.update(overrides)
    return data


def test_trip_country_from_suggestion_or_coordinates(auth_client, db):
    auth_client.post("/trips/new", data=_trip_form(origin_country="fr", dest_country="JP"))
    auth_client.post("/trips/new", data=_trip_form(depart_date="2025-05-01"))
    first, second = db.session.execute(db.select(Trip).order_by(Trip.id)).scalars()
    assert (first.origin_country, first.dest_country) == ("FR", "JP")
    assert (second.origin_country, second.dest_country) == ("FR", "JP")  # déduits hors ligne


def test_geocoded_country_used_when_no_suggestion_chosen(auth_client, db, monkeypatch):
    from app.trips import routes

    monkeypatch.setattr(routes, "geocode", lambda q, lang: [
        {"name": q, "label": q, "lat": 41.9, "lon": 12.45, "type": "city", "country_code": "VA"}])
    auth_client.post("/trips/new", data=_trip_form(origin_lat="", origin_lon=""))
    trip = db.session.execute(db.select(Trip)).scalar_one()
    assert trip.origin_country == "VA"


def test_api_trip_includes_localized_countries(auth_client, db, user):
    make_trip(user, **PARIS, **TOKYO, origin_country="FR", dest_country="JP", transport_mode="plane")
    trip = auth_client.get("/api/trips").get_json()["trips"][0]
    assert [c["name"] for c in trip["countries"]] == ["France", "Japon"]
    assert trip["detail_url"].endswith(f"/trips/{trip['id']}")


def test_countries_geojson(auth_client, db, user):
    make_trip(user, origin_country="FR", dest_country="FR")
    make_trip(user, **PARIS, **TOKYO, origin_country="FR", dest_country="JP", transport_mode="plane")
    data = auth_client.get("/api/countries").get_json()
    assert data["type"] == "FeatureCollection"
    props = {f["properties"]["code"]: f["properties"] for f in data["features"]}
    assert set(props) == {"FR", "JP"}
    assert props["FR"]["trips"] == 2 and props["FR"]["name"] == "France"
    assert data["features"][0]["geometry"]["type"] == "MultiPolygon"
    filtered = auth_client.get("/api/countries?modes=train").get_json()
    assert [f["properties"]["code"] for f in filtered["features"]] == ["FR"]


def test_shared_countries_and_privacy(client, db, user):
    trip = make_trip(user, origin_country="FR", dest_country="FR", notes="secret")
    link = ShareLink(user_id=user.id)
    db.session.add(link)
    db.session.commit()
    assert client.get(f"/api/shared/{link.token}/countries").get_json()["features"][0]["properties"]["code"] == "FR"
    shared = client.get(f"/api/shared/{link.token}/trips").get_json()["trips"][0]
    assert shared["detail_url"] is None and "notes" not in shared and shared["photo_count"] == 0
    assert client.get(f"/trips/{trip.id}").status_code == 302  # fiche privée


def test_backfill_countries_command(app, db, user):
    trip = make_trip(user)
    assert trip.origin_country is None
    result = app.test_cli_runner().invoke(args=["trips", "backfill-countries"])
    assert "1 trajet" in result.output
    db.session.refresh(trip)
    assert (trip.origin_country, trip.dest_country) == ("FR", "FR")


# --- Statistiques ---------------------------------------------------------------------------

def test_co2_factors():
    assert co2_kg("train", 100) == pytest.approx(3.0)
    assert co2_kg("plane", 500) == pytest.approx(500 * 0.258)
    assert co2_kg("plane", 2000) == pytest.approx(2000 * 0.187)
    assert co2_kg("plane", 9000) == pytest.approx(9000 * 0.152)
    assert co2_kg("bike", 100) == 0


def test_stats_include_co2_and_countries(app, db, user):
    lyon = make_trip(user, origin_country="FR", dest_country="FR")
    tokyo = make_trip(user, **PARIS, **TOKYO, origin_country="FR", dest_country="JP", transport_mode="plane",
                      is_round_trip=True, depart_date=date(2024, 3, 1), return_date=date(2024, 3, 10))
    with app.test_request_context():
        stats = compute_stats([lyon, tokyo])
    assert stats["countries"] == 2
    assert stats["co2_kg"] == pytest.approx(lyon.distance_km * 0.03 + tokyo.distance_km * 0.152 * 2, rel=1e-3)
    assert 0 < stats["land_share"] < 0.01  # France + Japon : environ 0,6 % des terres
    by_mode = {m["mode"]: m for m in stats["by_mode"]}
    assert by_mode["plane"]["co2_kg"] > by_mode["train"]["co2_kg"]


def test_yearly_stats_new_countries(app, db, user):
    a = make_trip(user, origin_country="FR", dest_country="FR", depart_date=date(2024, 1, 1))
    b = make_trip(user, **PARIS, **TOKYO, origin_country="FR", dest_country="JP", transport_mode="plane",
                  depart_date=date(2025, 1, 1))
    with app.test_request_context():
        rows = yearly_stats([a, b])
    assert [r["year"] for r in rows] == [2025, 2024]
    assert rows[0]["new_countries"] == ["JP"] and rows[1]["new_countries"] == ["FR"]
    assert rows[0]["modes"]["plane"] == 1


def test_stats_page(auth_client, db, user):
    make_trip(user, origin_country="FR", dest_country="IT", depart_date=date(2023, 6, 1))
    html = auth_client.get("/stats").text
    assert "2023" in html and "Italie" in html and "ADEME" in html


def test_stats_page_empty(auth_client):
    assert auth_client.get("/stats").status_code == 200


# --- Import / export ------------------------------------------------------------------------

def _sample_data(db, user):
    a = make_trip(user, origin_country="FR", dest_country="FR", notes="=HYPERLINK(\"x\")", depart_date=date(2025, 1, 1))
    b = make_trip(user, origin_name="Lyon, France", origin_lat=45.764, origin_lon=4.8357,
                  dest_name="Milan, Italie", dest_lat=45.4642, dest_lon=9.19, depart_date=date(2025, 1, 3),
                  is_round_trip=True, return_date=date(2025, 1, 9))
    journey = Journey(user_id=user.id, name="Hiver", notes="Neige")
    db.session.add(journey)
    a.journey = b.journey = journey
    make_trip(user, **PARIS, **TOKYO, transport_mode="plane", depart_date=date(2024, 5, 5))
    db.session.commit()


def _import(client, content, filename):
    data = content.encode() if isinstance(content, str) else content
    return client.post("/import", data={"file": (io.BytesIO(data), filename)}, content_type="multipart/form-data")


@pytest.mark.parametrize("fmt", ["csv", "geojson", "gpx"])
def test_export_then_import_roundtrip(app, client, db, user, fmt):
    _sample_data(db, user)
    login(client)
    response = client.get(f"/export.{fmt}")
    assert response.status_code == 200
    assert "attachment" in response.headers["Content-Disposition"]
    exported = response.data
    client.post("/auth/logout")

    make_user("carol@example.com")
    login(client, "carol@example.com")
    response = _import(client, exported, f"backup.{fmt}")
    assert response.status_code == 302
    carol_trips = db.session.execute(
        db.select(Trip).join(Trip.user).filter_by(email="carol@example.com").order_by(Trip.depart_date)).scalars().all()
    assert [(t.origin_name, t.dest_name, t.depart_date, t.transport_mode) for t in carol_trips] == [
        ("Paris, France", "Tokyo, Japon", date(2024, 5, 5), "plane"),
        ("Paris, France", "Lyon, France", date(2025, 1, 1), "train"),
        ("Lyon, France", "Milan, Italie", date(2025, 1, 3), "train"),
    ]
    assert carol_trips[2].is_round_trip and carol_trips[2].return_date == date(2025, 1, 9)
    assert carol_trips[1].notes == '=HYPERLINK("x")'
    assert carol_trips[1].journey is carol_trips[2].journey is not None
    assert (carol_trips[1].journey.name, carol_trips[1].journey.notes) == ("Hiver", "Neige")
    assert carol_trips[0].dest_country == "JP"  # déduit des coordonnées

    # Réimporter le même fichier n'ajoute rien.
    response = _import(client, exported, f"backup.{fmt}")
    assert len(db.session.execute(db.select(Trip).join(Trip.user).filter_by(email="carol@example.com")).all()) == 3
    assert "3 doublons ignorés" in client.get("/trips").text


def test_csv_export_neutralizes_formulas(auth_client, db, user):
    _sample_data(db, user)
    text = auth_client.get("/export.csv").data.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    assert any(r["notes"] == "'=HYPERLINK(\"x\")" for r in rows)


def test_import_semicolon_csv_with_decimal_commas(auth_client, db):
    content = ("depart_date;transport_mode;origin_name;origin_lat;origin_lon;dest_name;dest_lat;dest_lon\n"
               "2025-02-01;Bus;Berlin;52,52;13,405;Prague;50,0755;14,4378\n")
    assert _import(auth_client, content, "trips.csv").status_code == 302
    trip = db.session.execute(db.select(Trip)).scalar_one()
    assert (trip.transport_mode, trip.origin_lat, trip.dest_country) == ("bus", 52.52, "CZ")


def test_import_errors_import_nothing(auth_client, db):
    content = ("depart_date,transport_mode,origin_name,origin_lat,origin_lon,dest_name,dest_lat,dest_lon,return_date\n"
               "2025-02-01,train,Paris,48.8,2.3,Lyon,45.7,4.8,\n"
               "01/02/2025,rocket,Paris,95,2.3,,45.7,4.8,2020-01-01\n")
    response = _import(auth_client, content, "trips.csv")
    assert response.status_code == 400
    assert "Ligne 3" in response.text and "rocket" in response.text and "Ligne 2" not in response.text
    assert db.session.execute(db.select(Trip)).first() is None


def test_import_rejects_unknown_files(auth_client):
    assert "En-têtes CSV manquants" in _import(auth_client, "a,b\n1,2\n", "x.csv").text
    assert "GeoJSON invalide" in _import(auth_client, "{not json", "x.geojson").text
    assert "GPX invalide" in _import(auth_client, '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><gpx/>', "x.gpx").text
    assert "Aucun itinéraire" in _import(auth_client, '<gpx xmlns="http://www.topografix.com/GPX/1/1"/>', "x.gpx").text


def test_import_generic_gpx_route(auth_client, db):
    gpx = """<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1"><rte><type>bike</type>
      <rtept lat="52.3676" lon="4.9041"><name>Amsterdam</name><time>2024-05-04T08:00:00Z</time></rtept>
      <rtept lat="52.0907" lon="5.1214"><name>Utrecht</name></rtept></rte></gpx>"""
    assert _import(auth_client, gpx, "ride.gpx").status_code == 302
    trip = db.session.execute(db.select(Trip)).scalar_one()
    assert (trip.origin_name, trip.dest_name, trip.depart_date, trip.transport_mode) == (
        "Amsterdam", "Utrecht", date(2024, 5, 4), "bike")


def test_export_requires_login(client):
    assert client.get("/export.csv").status_code == 302


def test_geojson_export_is_valid(auth_client, db, user):
    _sample_data(db, user)
    doc = json.loads(auth_client.get("/export.geojson").data)
    feature = doc["features"][0]
    assert feature["geometry"]["type"] == "LineString"
    assert feature["geometry"]["coordinates"][0] == [139.6503, 35.6762] or feature["geometry"]["coordinates"][0][1] < 90


# --- Notes et photos ------------------------------------------------------------------------

def _image_bytes(fmt="JPEG", size=(1200, 800), gps=False):
    image = Image.new("RGB", size, (200, 40, 40))
    out = io.BytesIO()
    kwargs = {}
    if gps:
        exif = Image.Exif()
        exif[0x010F] = "PhoneMaker"  # Make
        exif[0x8825] = {1: "N", 2: (48.0, 51.0, 29.0)}  # GPSInfo
        kwargs["exif"] = exif.tobytes()
    image.save(out, fmt, **kwargs)
    return out.getvalue()


def _upload(client, url, *files):
    return client.post(url, data={"photos": [(io.BytesIO(data), name) for data, name in files]},
                       content_type="multipart/form-data")


def test_trip_notes_saved_from_form(auth_client, db):
    auth_client.post("/trips/new", data=_trip_form(notes="  Hôtel près de la gare  "))
    trip = db.session.execute(db.select(Trip)).scalar_one()
    assert trip.notes == "Hôtel près de la gare"
    assert "Hôtel près de la gare" in auth_client.get(f"/trips/{trip.id}").text


def test_photo_upload_strips_metadata_and_serves_thumbnail(app, auth_client, db, user):
    trip = make_trip(user)
    response = _upload(auth_client, f"/trips/{trip.id}/photos", (_image_bytes(gps=True), "vacances.jpg"))
    assert response.status_code == 302
    photo = db.session.execute(db.select(Photo)).scalar_one()
    assert (photo.trip_id, photo.width, photo.height, photo.original_name) == (trip.id, 1200, 800, "vacances.jpg")
    full = auth_client.get(f"/photos/{photo.id}")
    assert full.status_code == 200 and full.mimetype == "image/jpeg"
    assert "private" in full.headers["Cache-Control"]
    with Image.open(io.BytesIO(full.data)) as image:
        assert not image.getexif()  # plus de marque ni de position GPS
    with Image.open(io.BytesIO(auth_client.get(f"/photos/{photo.id}/thumb").data)) as thumb:
        assert thumb.size == (480, 480)


def test_png_with_transparency_and_large_images_are_resized(auth_client, db, user):
    trip = make_trip(user)
    image = Image.new("RGBA", (4000, 1000), (0, 0, 0, 0))
    out = io.BytesIO()
    image.save(out, "PNG")
    _upload(auth_client, f"/trips/{trip.id}/photos", (out.getvalue(), "a.png"))
    photo = db.session.execute(db.select(Photo)).scalar_one()
    assert (photo.width, photo.height) == (2560, 640)


def test_invalid_photo_rejected(auth_client, db, user):
    trip = make_trip(user)
    response = _upload(auth_client, f"/trips/{trip.id}/photos", (b"not an image at all", "fake.jpg"))
    assert response.status_code == 302
    assert db.session.execute(db.select(Photo)).first() is None
    assert "pas une image valide" in auth_client.get(f"/trips/{trip.id}").text


def test_photos_are_private(app, client, db, user, other_user):
    trip = make_trip(user)
    login(client)
    _upload(client, f"/trips/{trip.id}/photos", (_image_bytes(), "a.jpg"))
    photo = db.session.execute(db.select(Photo)).scalar_one()
    client.post("/auth/logout")
    assert client.get(f"/photos/{photo.id}").status_code == 302
    login(client, "bob@example.com")
    assert client.get(f"/photos/{photo.id}").status_code == 404
    assert client.post(f"/photos/{photo.id}/delete").status_code == 404
    assert _upload(client, f"/trips/{trip.id}/photos", (_image_bytes(), "b.jpg")).status_code == 404


def _files(app):
    folder = app.config["UPLOAD_FOLDER"]
    return sorted(os.listdir(folder)) if os.path.isdir(folder) else []


def test_photo_files_deleted_with_photo_trip_and_account(app, auth_client, db, user):
    trip = make_trip(user)
    other = make_trip(user, depart_date=date(2025, 6, 1))
    _upload(auth_client, f"/trips/{trip.id}/photos", (_image_bytes(), "a.jpg"), (_image_bytes(), "b.jpg"))
    _upload(auth_client, f"/trips/{other.id}/photos", (_image_bytes(), "c.jpg"))
    assert len(_files(app)) == 6  # photo + miniature
    first = db.session.execute(db.select(Photo).order_by(Photo.id)).scalars().first()
    auth_client.post(f"/photos/{first.id}/delete")
    assert len(_files(app)) == 4
    auth_client.post(f"/trips/{trip.id}/delete")
    assert len(_files(app)) == 2
    auth_client.post("/auth/delete", data={"del-delete_password": "password123"})
    assert _files(app) == []


def test_journey_notes_and_photos_survive_ungroup(app, auth_client, db, user):
    a = make_trip(user, depart_date=date(2025, 1, 1), notes="Aller")
    b = make_trip(user, depart_date=date(2025, 1, 5))
    auth_client.post("/journeys", data={"trip_ids": [a.id, b.id]})
    journey = db.session.execute(db.select(Journey)).scalar_one()
    auth_client.post(f"/journeys/{journey.id}/edit", data={"name": "Week-end", "notes": "Super séjour"})
    _upload(auth_client, f"/journeys/{journey.id}/photos", (_image_bytes(), "j.jpg"))
    page = auth_client.get(f"/journeys/{journey.id}").text
    assert "Super séjour" in page and "Week-end" in page
    auth_client.post(f"/journeys/{journey.id}/ungroup")
    db.session.expire_all()
    first = db.session.get(Trip, a.id)
    assert first.notes == "Aller\n\nSuper séjour"
    assert [p.original_name for p in first.photos] == ["j.jpg"]
    assert len(_files(app)) == 2


def test_merging_journeys_keeps_photos(auth_client, db, user):
    trips = [make_trip(user, depart_date=date(2025, 1, d)) for d in (1, 2, 3, 4)]
    auth_client.post("/journeys", data={"trip_ids": [trips[0].id, trips[1].id]})
    auth_client.post("/journeys", data={"trip_ids": [trips[2].id, trips[3].id]})
    first, second = db.session.execute(db.select(Journey).order_by(Journey.id)).scalars()
    _upload(auth_client, f"/journeys/{second.id}/photos", (_image_bytes(), "x.jpg"))
    auth_client.post("/journeys", data={"trip_ids": [trips[1].id, trips[2].id]})
    db.session.expire_all()
    (journey,) = db.session.execute(db.select(Journey)).scalars()
    assert [p.original_name for p in journey.photos] == ["x.jpg"]


def test_photo_limit_per_item(app, auth_client, db, user):
    app.config["MAX_PHOTOS_PER_ITEM"] = 1
    trip = make_trip(user)
    _upload(auth_client, f"/trips/{trip.id}/photos", (_image_bytes(), "a.jpg"), (_image_bytes(), "b.jpg"))
    assert db.session.scalar(db.select(db.func.count(Photo.id))) == 1


@pytest.mark.parametrize("locale,expected", [("fr", "0,7 %"), ("en", "0.7%"), ("de", "0,7 %")])
def test_land_share_formatting(app, locale, expected):
    from flask_babel import force_locale

    from app.i18n import format_share

    with app.test_request_context(), force_locale(locale):
        assert format_share(0.0069).replace("\xa0", " ").replace(" ", " ") == expected


def test_country_list_sorted_by_visits_then_name(app, db, user):
    from app.trips.stats import country_summary

    make_trip(user, origin_country="US", dest_country="TH")
    make_trip(user, origin_country="ES", dest_country="FR", depart_date=date(2025, 6, 1))
    make_trip(user, origin_country="FR", dest_country="FR", depart_date=date(2025, 7, 1))
    make_trip(user, origin_country="TH", dest_country="TH", depart_date=date(2025, 8, 1))
    with app.test_request_context():
        summary = country_summary(user.trips.all())
    # À nombre égal, ordre alphabétique sans tenir compte des accents (États-Unis avec les E).
    assert [(c["name"], c["trips"]) for c in summary] == [
        ("France", 2), ("Thaïlande", 2), ("Espagne", 1), ("États-Unis", 1)]
