from app.models import User

from .conftest import login, make_trip, make_user


def test_admin_page_requires_login(client):
    response = client.get("/admin/")
    assert response.status_code == 302
    assert "/auth/login" in response.location


def test_admin_page_forbidden_for_regular_user(auth_client):
    assert auth_client.get("/admin/").status_code == 403


def test_admin_page_lists_users(client, db, user, other_user):
    admin = make_user("root@example.com")
    admin.is_admin = True
    db.session.commit()
    make_trip(user)
    make_trip(user)
    login(client, "root@example.com")
    response = client.get("/admin/")
    assert response.status_code == 200
    assert "alice@example.com" in response.text and "bob@example.com" in response.text


def test_admin_link_only_for_admins(client, db, user):
    login(client)
    assert "/admin/" not in client.get("/trips").text
    user.is_admin = True
    db.session.commit()
    assert "/admin/" in client.get("/trips").text


def test_create_admin_command_creates_user(app, db):
    result = app.test_cli_runner().invoke(args=["create-admin", "Root@Example.com", "--password", "secret123"])
    assert result.exit_code == 0, result.output
    user = db.session.execute(db.select(User).filter_by(email="root@example.com")).scalar_one()
    assert user.is_admin and user.check_password("secret123")


def test_create_admin_command_promotes_existing_user(app, db, user):
    result = app.test_cli_runner().invoke(args=["create-admin", "alice@example.com"])
    assert result.exit_code == 0, result.output
    db.session.refresh(user)
    assert user.is_admin and user.check_password("password123")


def test_create_admin_command_rejects_short_password(app, db):
    result = app.test_cli_runner().invoke(args=["create-admin", "root@example.com", "--password", "short"])
    assert result.exit_code != 0
    assert db.session.execute(db.select(User).filter_by(email="root@example.com")).first() is None


def admin_client(client, db):
    admin = make_user("root@example.com")
    admin.is_admin = True
    db.session.commit()
    login(client, "root@example.com")
    return admin


def test_admin_deletes_user_and_their_data(client, db, user, other_user):
    from app.models import Journey, Trip

    admin_client(client, db)
    a, b = make_trip(user), make_trip(user)
    journey = Journey(user_id=user.id)
    a.journey = b.journey = journey
    db.session.add(journey)
    db.session.commit()
    make_trip(other_user)
    response = client.post(f"/admin/users/{user.id}/delete")
    assert response.status_code == 302
    assert db.session.get(User, user.id) is None
    assert db.session.execute(db.select(Journey)).first() is None
    assert [t.user_id for t in db.session.execute(db.select(Trip)).scalars()] == [other_user.id]


def test_admin_cannot_delete_self(client, db):
    admin = admin_client(client, db)
    client.post(f"/admin/users/{admin.id}/delete")
    assert db.session.get(User, admin.id) is not None


def test_delete_user_requires_admin(auth_client, db, other_user):
    assert auth_client.post(f"/admin/users/{other_user.id}/delete").status_code == 403
    assert db.session.get(User, other_user.id) is not None


def test_delete_unknown_user_404(client, db):
    admin_client(client, db)
    assert client.post("/admin/users/999/delete").status_code == 404


def test_registration_open_by_default(client):
    assert client.get("/auth/register").status_code == 200
    assert "/auth/register" in client.get("/auth/login").text


def test_admin_can_close_registration(client, db):
    admin_client(client, db)
    assert client.get("/admin/settings").status_code == 200
    client.post("/admin/settings", data={})
    client.post("/auth/logout")
    response = client.get("/auth/register")
    assert response.status_code == 302 and "/auth/login" in response.location
    response = client.post("/auth/register", data={
        "email": "new@example.com", "password": "password123", "confirm": "password123"})
    assert response.status_code == 302
    assert db.session.execute(db.select(User).filter_by(email="new@example.com")).first() is None
    assert "/auth/register" not in client.get("/auth/login").text
    assert "/auth/register" not in client.get("/").text


def test_admin_can_reopen_registration(client, db):
    admin_client(client, db)
    client.post("/admin/settings", data={})
    client.post("/admin/settings", data={"registration_open": "y"})
    client.post("/auth/logout")
    assert client.get("/auth/register").status_code == 200


def test_settings_requires_admin(auth_client):
    assert auth_client.get("/admin/settings").status_code == 403
    assert auth_client.post("/admin/settings", data={}).status_code == 403
