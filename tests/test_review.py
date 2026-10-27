import io
from datetime import date

import pytest
from PIL import Image, ImageChops

from app import utils
from app.models import ShareLink
from app.trips.stats import year_review

from .conftest import make_trip

TOKYO = dict(dest_name="Tokyo, Japon", dest_lat=35.6762, dest_lon=139.6503, transport_mode="plane")


@pytest.fixture(autouse=True)
def frozen_today(monkeypatch):
    monkeypatch.setattr(utils, "today", lambda: date(2025, 12, 1))


@pytest.fixture
def history(user):
    make_trip(user, origin_country="FR", dest_country="FR", depart_date=date(2024, 3, 1))
    make_trip(user, origin_country="FR", dest_country="FR", depart_date=date(2025, 2, 1))
    make_trip(user, origin_country="FR", dest_country="JP", depart_date=date(2025, 7, 14), **TOKYO)
    make_trip(user, origin_country="FR", dest_country="JP", depart_date=date(2025, 12, 20), **TOKYO)  # à venir
    return user


def test_year_review_data(app, history):
    with app.test_request_context():
        review = year_review(history.trips.all(), 2025)
    assert review["count"] == 2  # le voyage de décembre n'a pas encore eu lieu
    assert [c["code"] for c in review["countries"]] == ["FR", "JP"]
    assert [c["code"] for c in review["new_countries"]] == ["JP"]  # la France était déjà visitée en 2024
    assert review["longest"].dest_name == "Tokyo, Japon"
    assert review["months"][1] == 1 and review["months"][6] == 1 and sum(review["months"]) == 2
    assert review["top_mode"] == "plane"
    assert review["earth_laps"] == pytest.approx(review["distance_km"] / 40075)


def test_review_page_and_latest_redirect(auth_client, history):
    assert auth_client.get("/review").location.endswith("/review/2025")
    html = auth_client.get("/review/2025").text
    assert "Bilan 2025" in html and "Japon" in html and "Tokyo, Japon" in html
    assert 'href="/review/2024"' in html  # navigation entre les années
    assert auth_client.get("/review/2019").status_code == 404


def test_review_without_trips(auth_client):
    response = auth_client.get("/review")
    assert response.status_code == 200 and "Pas encore de bilan" in response.text


@pytest.mark.parametrize("locale", ["fr", "de"])
def test_review_image(auth_client, db, history, locale):
    history.locale = locale
    db.session.commit()
    response = auth_client.get("/review/2025.png")
    assert response.status_code == 200 and response.mimetype == "image/png"
    with Image.open(io.BytesIO(response.data)) as image:
        assert image.size == (1080, 1350)
    assert auth_client.get("/review/2023.png").status_code == 404


def test_review_requires_login(client):
    assert client.get("/review/2025").status_code == 302
    assert client.get("/review/2025.png").status_code == 302


def test_shared_review(app, db, history):
    link = ShareLink(user_id=history.id)
    db.session.add(link)
    db.session.commit()
    anonymous = app.test_client()
    assert anonymous.get(f"/s/{link.token}/review").location.endswith(f"/s/{link.token}/review/2025")
    html = anonymous.get(f"/s/{link.token}/review/2025").text
    assert "Bilan 2025" in html and "/trips/" not in html.split("<main")[1]  # pas de lien vers les fiches privées
    assert anonymous.get(f"/s/{link.token}/review/2025.png").mimetype == "image/png"
    assert anonymous.get("/s/nope/review/2025").status_code == 404


def test_long_names_are_truncated_in_image(app, user):
    from app.review_image import render

    make_trip(user, depart_date=date(2025, 1, 1), origin_name="A" * 200, dest_name="B" * 200)
    with app.test_request_context():
        data = render(year_review(user.trips.all(), 2025), "Voyage Voyage")
    assert data.startswith(b"\x89PNG")


def test_image_content_stays_inside_canvas(app, user):
    """Le bas de l'image (sous les libellés des mois) reste dans le dégradé, sans débordement."""
    from app.review_image import HEIGHT, render

    for month in (1, 6, 12):
        make_trip(user, depart_date=date(2025, month, 2), origin_country="FR", dest_country="IT")
    with app.test_request_context():
        image = Image.open(io.BytesIO(render(year_review(user.trips.all(), 2025), "Voyage Voyage")))
    bottom = image.crop((0, HEIGHT - 40, image.width, HEIGHT)).convert("RGB")
    assert len(bottom.getcolors(maxcolors=100_000)) < 40  # uniquement le fond : aucun texte ne déborde


def test_image_shows_site_address(app, user):
    """L'adresse APP_BASE_URL est écrite, centrée, sous le graphique des mois."""
    from app.review_image import HEIGHT, WIDTH, render

    make_trip(user, depart_date=date(2025, 3, 2), origin_country="FR", dest_country="IT")
    with app.test_request_context():
        review = year_review(user.trips.all(), 2025)
        plain = Image.open(io.BytesIO(render(review, "Voyage Voyage"))).convert("RGB")
        signed = Image.open(io.BytesIO(render(review, "Voyage Voyage", "https://travellog.example.org/")))
    box = (0, HEIGHT - 90, WIDTH, HEIGHT - 40)
    diff = ImageChops.difference(plain.crop(box), signed.convert("RGB").crop(box)).getbbox()
    assert diff and abs((diff[0] + diff[2]) / 2 - WIDTH / 2) < 4  # texte centré
