import csv
import io
import re
from datetime import date

import pytest

from app import utils
from app.models import Journey, Tag, Trip
from app.tags import parse_tags

from .conftest import make_trip


def _form(**overrides):
    data = dict(origin_name="Paris", origin_lat="48.8566", origin_lon="2.3522",
                dest_name="Lyon", dest_lat="45.764", dest_lon="4.8357", depart_date="2025-04-01", transport_mode="train")
    data.update(overrides)
    return data


def _tags(db):
    return sorted(t.name for t in db.session.execute(db.select(Tag)).scalars())


def test_parse_tags():
    assert parse_tags(" Vacances, famille,vacances ;  week-end  end ,, ") == ["Vacances", "famille", "week-end end"]


def test_tags_created_reused_and_pruned(auth_client, db):
    auth_client.post("/trips/new", data=_form(tags="Vacances, Famille"))
    auth_client.post("/trips/new", data=_form(depart_date="2025-05-01", tags="vacances"))
    assert _tags(db) == ["Famille", "Vacances"]  # « vacances » réutilise « Vacances »
    first, second = db.session.execute(db.select(Trip).order_by(Trip.id)).scalars()
    assert [t.name for t in second.tags] == ["Vacances"]
    assert 'value="Famille, Vacances"' in auth_client.get(f"/trips/{first.id}/edit").text
    auth_client.post(f"/trips/{first.id}/edit", data=_form(tags="Travail"))
    assert _tags(db) == ["Travail", "Vacances"]  # « Famille » n'est plus utilisée
    auth_client.post(f"/trips/{second.id}/delete")
    assert _tags(db) == ["Travail"]


def test_tag_limits(auth_client, db):
    response = auth_client.post("/trips/new", data=_form(tags=", ".join(f"t{i}" for i in range(11))))
    assert "10 étiquettes au maximum" in response.text
    response = auth_client.post("/trips/new", data=_form(tags="x" * 41))
    assert "40 caractères" in response.text
    assert db.session.execute(db.select(Trip)).first() is None


def test_tags_are_per_user(auth_client, client, db, user, other_user):
    auth_client.post("/trips/new", data=_form(tags="Secret"))
    other_trip = make_trip(other_user)
    other_trip.tags = [Tag(user_id=other_user.id, name="Secret")]
    db.session.commit()
    assert len(_tags(db)) == 2
    assert auth_client.get("/api/trips").get_json()["count"] == 1


def test_tag_filter(auth_client, db, user):
    auth_client.post("/trips/new", data=_form(tags="Travail"))
    auth_client.post("/trips/new", data=_form(depart_date="2025-05-01", tags="Vacances"))
    auth_client.post("/trips/new", data=_form(depart_date="2025-06-01"))
    ids = {t.name: t.id for t in db.session.execute(db.select(Tag)).scalars()}
    count = lambda q: auth_client.get(f"/api/trips?{q}").get_json()["count"]
    assert count(f"tags={ids['Travail']}") == 1
    assert count(f"tags={ids['Travail']},{ids['Vacances']}") == 2
    assert auth_client.get("/api/trips?tags=abc").status_code == 400
    assert auth_client.get("/api/trips").get_json()["trips"][0]["tags"] == []
    assert 'name="tags"' in auth_client.get("/").text  # filtre sur la carte


def test_journey_tags_apply_to_all_legs(auth_client, db, user):
    a, b = make_trip(user), make_trip(user, depart_date=date(2025, 5, 3))
    auth_client.post("/journeys", data={"trip_ids": [a.id, b.id]})
    journey = db.session.execute(db.select(Journey)).scalar_one()
    auth_client.post(f"/journeys/{journey.id}/edit", data={"name": "", "notes": "", "tags": "Famille"})
    db.session.expire_all()
    assert [t.name for t in db.session.get(Trip, a.id).tags] == ["Famille"]
    assert [t.name for t in db.session.get(Trip, b.id).tags] == ["Famille"]
    assert "Famille" in auth_client.get(f"/journeys/{journey.id}").text


def test_tag_stats(auth_client, db, user, monkeypatch):
    monkeypatch.setattr(utils, "today", lambda: date(2025, 12, 31))
    auth_client.post("/trips/new", data=_form(tags="Travail", origin_country="FR", dest_country="FR"))
    auth_client.post("/trips/new", data=_form(depart_date="2024-05-01", tags="Travail"))
    auth_client.post("/trips/new", data=_form(depart_date="2025-06-01"))
    html = auth_client.get("/stats").text
    section = html.split('id="tagsTitle"')[1].split("</table>")[0]
    assert "Travail" in section and "Sans étiquette" in section and "CO₂ en 2025" in section


def test_tags_survive_export_import(auth_client, db, user):
    auth_client.post("/trips/new", data=_form(tags="Vacances, Famille"))
    exported = auth_client.get("/export.csv").data
    row = next(csv.DictReader(io.StringIO(exported.decode("utf-8-sig"))))
    assert row["tags"] == "Famille, Vacances"
    db.session.delete(db.session.execute(db.select(Trip)).scalar_one())
    db.session.commit()
    auth_client.post("/import", data={"file": (io.BytesIO(exported), "t.csv")}, content_type="multipart/form-data")
    assert [t.name for t in db.session.execute(db.select(Trip)).scalar_one().tags] == ["Famille", "Vacances"]


# --- Recherche --------------------------------------------------------------------------------

@pytest.fixture
def searchable(auth_client, db, user):
    auth_client.post("/trips/new", data=_form(dest_name="Séville, Espagne", dest_lat="37.39", dest_lon="-5.98",
                                              notes="Tapas près de la cathédrale", tags="Gastronomie"))
    auth_client.post("/trips/new", data=_form(depart_date="2025-07-01", dest_name="Genève", dest_lat="46.2",
                                              dest_lon="6.14"))
    auth_client.post("/trips/new", data=_form(depart_date="2025-08-01"))
    return auth_client


def _destinations(client, query):
    html = client.get("/trips", query_string={"q": query}).text
    return html, sorted(re.findall(r'<span class="visually-hidden">→</span> ([^<,]+)', html))


@pytest.mark.parametrize("query,expected", [
    ("seville", ["Séville"]),            # sans accent
    ("CATHEDRALE", ["Séville"]),         # dans les notes, casse ignorée
    ("gastro", ["Séville"]),             # étiquette
    ("suisse", ["Genève"]),              # nom du pays dans la langue active
    ("paris lyon", ["Lyon"]),            # tous les mots doivent apparaître
    ("tokyo", []),
])
def test_search(searchable, query, expected):
    html, shown = _destinations(searchable, query)
    assert shown == expected
    if not expected:
        assert "Aucun résultat" in html


def test_search_count_and_clear_link(searchable):
    html = searchable.get("/trips?q=espagne").text
    assert "1 trajet trouvé pour « espagne »" in html and "Effacer la recherche" in html
