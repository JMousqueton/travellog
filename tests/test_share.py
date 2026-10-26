from datetime import date

from app.models import ShareLink

from .conftest import login, make_trip


def create_link(client, db, label="Famille"):
    client.post("/share", data={"label": label})
    return db.session.execute(db.select(ShareLink).order_by(ShareLink.id.desc())).scalars().first()


def test_share_page_requires_login(client):
    assert client.get("/share").status_code == 302


def test_create_link_and_view_anonymously(client, db, user):
    make_trip(user)
    login(client)
    link = create_link(client, db)
    assert link.user_id == user.id and len(link.token) >= 32
    assert link.token in client.get("/share").text
    client.post("/auth/logout")
    page = client.get(f"/s/{link.token}")
    assert page.status_code == 200
    assert "noindex" in page.text and "Famille" in page.text
    assert user.email not in page.text
    data = client.get(f"/api/shared/{link.token}/trips").get_json()
    assert data["count"] == 1
    assert data["trips"][0]["edit_url"] is None and data["trips"][0]["delete_url"] is None
    assert client.get(f"/api/shared/{link.token}/stats").get_json()["count"] == 1


def test_shared_map_has_year_filter(client, db, user):
    make_trip(user, depart_date=date(2023, 3, 1))
    make_trip(user, depart_date=date(2025, 5, 1))
    make_trip(user, depart_date=date(2099, 1, 1))
    login(client)
    link = create_link(client, db)
    html = client.get(f"/s/{link.token}").text
    assert 'data-year=""' in html and 'data-year="2025"' in html and 'data-year="2023"' in html
    assert 'data-year="2099"' not in html
    link.include_upcoming = True
    db.session.commit()
    assert 'data-year="2099"' in client.get(f"/s/{link.token}").text


def test_shared_view_respects_filters(client, db, user):
    make_trip(user, transport_mode="train")
    make_trip(user, transport_mode="plane")
    login(client)
    link = create_link(client, db)
    assert client.get(f"/api/shared/{link.token}/trips?modes=plane").get_json()["count"] == 1


def test_shared_view_only_shows_owner_trips(client, db, user, other_user):
    make_trip(user)
    make_trip(other_user)
    make_trip(other_user)
    login(client)
    link = create_link(client, db)
    assert client.get(f"/api/shared/{link.token}/trips").get_json()["count"] == 1


def test_unknown_token_404(client):
    assert client.get("/s/nope").status_code == 404
    assert client.get("/api/shared/nope/trips").status_code == 404
    assert client.get("/api/shared/nope/stats").status_code == 404


def test_revoke_link(client, db, user):
    login(client)
    link = create_link(client, db)
    token = link.token
    client.post(f"/share/{link.id}/revoke")
    assert client.get(f"/s/{token}").status_code == 404


def test_cannot_revoke_someone_elses_link(client, db, user, other_user):
    login(client)
    link = create_link(client, db)
    client.post("/auth/logout")
    login(client, "bob@example.com")
    assert client.post(f"/share/{link.id}/revoke").status_code == 404
    assert db.session.get(ShareLink, link.id) is not None
