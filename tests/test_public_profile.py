from datetime import date, timedelta

from app.models import User

from .conftest import make_trip, make_user


def test_profile_disabled_by_default(client, user):
    assert user.public_name is None
    assert client.get("/u/alice").status_code == 404


def test_set_and_clear_public_name(auth_client, user, db):
    response = auth_client.post("/auth/public-profile", data={"pub-public_name": "  Alice_Travels "})
    assert response.status_code == 302 and response.location.endswith("#public-profile")
    assert db.session.get(User, user.id).public_name == "alice_travels"
    page = auth_client.get("/auth/profile").text
    assert "/u/alice_travels" in page
    auth_client.post("/auth/public-profile", data={"pub-public_name": ""})
    assert db.session.get(User, user.id).public_name is None


def test_public_name_validation(auth_client, other_user, db):
    other_user.public_name = "bob"
    db.session.commit()
    for name, message in (("bob", "déjà pris"), ("ab", "De 3 à 30"), ("é-té", "De 3 à 30"), ("-abc", "De 3 à 30")):
        response = auth_client.post("/auth/public-profile", data={"pub-public_name": name})
        assert response.status_code == 400 and message in response.text, name


def test_public_profile_shows_summary_without_private_details(client, user, db):
    user.public_name = "alice"
    user.home_name = "Maison secrète"
    db.session.commit()
    make_trip(user, notes="note privée")  # Paris → Lyon en train
    make_trip(user, origin_name="Paris, France", dest_name="Tokyo, Japon", dest_lat=35.68, dest_lon=139.69,
              transport_mode="plane", depart_date=date(2024, 4, 1), dest_country="JP", origin_country="FR")
    make_trip(user, dest_name="Rome, Italie", dest_lat=41.9, dest_lon=12.5, dest_country="IT",
              depart_date=date.today() + timedelta(days=30))  # à venir : jamais montré
    html = client.get("/u/Alice").text
    assert "alice" in html and "Voyage depuis 2024" in html
    assert "Japon" in html and "Italie" not in html
    assert "Avion" in html and "Train" in html
    assert "Badges" in html and "noindex" in html
    for secret in ("note privée", "Maison secrète", "alice@example.com", "Tokyo", "Lyon"):
        assert secret not in html, secret


def test_public_profile_without_trips(client, db):
    user = make_user("carol@example.com")
    user.public_name = "carol"
    db.session.commit()
    response = client.get("/u/carol")
    assert response.status_code == 200 and "Aucun voyage à afficher" in response.text


def test_public_profile_trips_per_year_chart(client, user, db):
    import json
    import re

    user.public_name = "alice"
    db.session.commit()
    make_trip(user, depart_date=date(2022, 5, 1))  # train par défaut
    make_trip(user, transport_mode="plane", depart_date=date(2024, 4, 1))
    make_trip(user, depart_date=date(2024, 9, 1))
    html = client.get("/u/alice").text
    assert "Trajets par année" in html and 'data-chart="chart-profile-years"' in html and "js/charts.js" in html
    spec = json.loads(re.search(r'<script type="application/json" id="chart-profile-years">(.*?)</script>', html).group(1))
    assert spec["labels"] == [2022, 2023, 2024]  # 2023 sans trajet : barre vide
    assert spec["series"] == {"train": [1, 0, 1], "plane": [0, 0, 1]}
