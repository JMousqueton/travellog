import io
import re

from app.models import Trip

from .conftest import import_file, login, make_user
from .test_flight_import import FLIGHTY, FLIGHTY_HEADER, _flighty_line


def _preview(client, content, filename="flights.csv"):
    return client.post("/import", data={"file": (io.BytesIO(content.encode()), filename)},
                       content_type="multipart/form-data")


def _token(html):
    return re.search(r'name="token" type="hidden" value="([^"]+)"', html).group(1)


def test_preview_lists_trips_without_creating_them(auth_client, db):
    response = _preview(auth_client, FLIGHTY)
    assert response.status_code == 200
    assert "3 trajets trouvés dans « flights.csv »" in response.text
    assert "1 vol annulé ignoré" in response.text and "LHR → CDG" in response.text
    assert "AF1148 · Air France · Airbus A321" in response.text
    assert db.session.execute(db.select(Trip)).first() is None


def test_confirm_imports_only_selected_rows(auth_client, db):
    lines = [("10/12/15", 1, "CDG", "BCN"), ("3/2/20", 2, "CDG", "PRG"), ("5/3/22", 3, "CDG", "LHR")]
    content = FLIGHTY_HEADER + "\n" + "\n".join(_flighty_line(*line) for line in lines) + "\n"
    import_file(auth_client, content, "flights.csv", rows=[2])
    trips = db.session.execute(db.select(Trip)).scalars().all()
    assert [t.service_number for t in trips] == ["AF3"]


def test_preview_token_is_single_use_and_private(client, db):
    make_user()
    bob = make_user("bob@example.com")
    login(client)
    token = _token(_preview(client, FLIGHTY).text)
    client.post("/auth/logout")
    login(client, "bob@example.com")
    response = client.post("/import/confirm", data={"token": token, "rows": ["0"]}, follow_redirects=True)
    assert "Cet aperçu a expiré" in response.text  # l'aperçu d'un autre utilisateur est introuvable
    assert db.session.execute(db.select(Trip).filter_by(user_id=bob.id)).first() is None
    client.post("/auth/logout")
    login(client)
    assert client.post("/import/confirm", data={"token": token, "rows": ["0"]}).status_code == 302
    response = client.post("/import/confirm", data={"token": token, "rows": ["0"]}, follow_redirects=True)
    assert "Cet aperçu a expiré" in response.text
    assert len(db.session.execute(db.select(Trip)).all()) == 1


def test_nothing_selected(auth_client, db):
    response = import_file(auth_client, FLIGHTY, "flights.csv", rows=[])
    assert response.status_code == 302
    assert db.session.execute(db.select(Trip)).first() is None
