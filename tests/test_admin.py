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


def test_admin_blocks_user_and_ends_their_session(app, db, user):
    from app.models import ShareLink

    user.public_name = "alice"
    user.calendar_token = "cal-token"
    link = ShareLink(user_id=user.id)
    db.session.add(link)
    db.session.commit()
    user_client = app.test_client()
    login(user_client)
    assert user_client.get("/trips").status_code == 200

    admin = app.test_client()
    admin_client(admin, db)
    assert "Bloquer ce compte ?" in admin.get("/admin/").text
    assert admin.post(f"/admin/users/{user.id}/block").status_code == 302
    db.session.refresh(user)
    assert user.is_blocked
    page = admin.get("/admin/").text
    assert "Bloqué" in page
    assert 'href="/u/alice"' not in page and "Profil masqué : compte bloqué" in page

    assert user_client.get("/trips").status_code == 302  # session fermée
    response = login(app.test_client())
    assert "Ce compte est bloqué" in response.text
    anonymous = app.test_client()
    for url in ("/u/alice", f"/s/{link.token}", f"/api/shared/{link.token}/trips", "/calendar/cal-token.ics"):
        assert anonymous.get(url).status_code == 404, url

    admin.post(f"/admin/users/{user.id}/block")
    db.session.refresh(user)
    assert not user.is_blocked
    assert anonymous.get("/u/alice").status_code == 200
    assert login(app.test_client()).status_code == 302


def test_admin_cannot_block_self(client, db):
    admin = admin_client(client, db)
    client.post(f"/admin/users/{admin.id}/block")
    db.session.refresh(admin)
    assert not admin.is_blocked


def test_block_and_rename_require_admin(auth_client, db, other_user):
    assert auth_client.post(f"/admin/users/{other_user.id}/block").status_code == 403
    assert auth_client.post(f"/admin/users/{other_user.id}/name", data={"name-public_name": "x-bob"}).status_code == 403
    db.session.refresh(other_user)
    assert not other_user.is_blocked and other_user.public_name is None


def test_admin_sets_and_clears_public_name(client, db, user):
    admin_client(client, db)
    client.post(f"/admin/users/{user.id}/name", data={"name-public_name": "  Alice-Voyage "})
    db.session.refresh(user)
    assert user.public_name == "alice-voyage"
    assert "alice-voyage" in client.get("/admin/").text
    client.post(f"/admin/users/{user.id}/name", data={"name-public_name": ""})
    db.session.refresh(user)
    assert user.public_name is None


def test_admin_rename_rejects_invalid_or_taken_name(client, db, user, other_user):
    admin_client(client, db)
    other_user.public_name = "bob"
    db.session.commit()
    for name in ("bob", "a", "pas d'espace"):
        client.post(f"/admin/users/{user.id}/name", data={"name-public_name": name})
        db.session.refresh(user)
        assert user.public_name is None, name
    response = client.post(f"/admin/users/{user.id}/name", data={"name-public_name": "bob"}, follow_redirects=True)
    assert "Ce nom est déjà pris" in response.text


def test_admin_database_page(client, db, user, app, tmp_path):
    from app.backup import create_backup

    make_trip(user)
    admin_client(client, db)
    app.config["BACKUP_DIR"] = str(tmp_path / "backups")
    html = client.get("/admin/database").text
    assert "PostgreSQL" in html and "<code>trips</code>" in html and "Aucune sauvegarde" in html
    assert "Migrations en attente" in html  # base de test créée sans Alembic
    create_backup()
    html = client.get("/admin/database").text
    assert "Aucune sauvegarde" not in html and "1 archive conservée" in html


def test_admin_database_page_forbidden_for_regular_user(auth_client):
    assert auth_client.get("/admin/database").status_code == 403


def test_filesize_format(app):
    from flask_babel import force_locale

    from app.i18n import format_filesize

    with app.test_request_context(), force_locale("en"):
        assert [format_filesize(n) for n in (512, 2048, 5 * 1024 ** 2 + 1024 ** 2 // 2)] == ["512 byte", "2 kB", "5.5 MB"]


def _fake_stripe(monkeypatch, subs, invoices):
    from types import SimpleNamespace

    import stripe

    class Obj(SimpleNamespace):
        def to_dict(self):
            return dict(vars(self))

    def lister(items):
        return lambda **kw: SimpleNamespace(auto_paging_iter=lambda: iter([Obj(**i) for i in items]))
    monkeypatch.setattr(stripe.Subscription, "list", lister(subs))
    monkeypatch.setattr(stripe.Invoice, "list", lister(invoices))


def _sub(customer, interval, amount, start, status="active", cancel=False):
    return {"id": f"sub_{customer}", "customer": customer, "status": status, "start_date": start,
            "created": start, "cancel_at_period_end": cancel,
            "items": {"data": [{"current_period_end": start + 400 * 86400,
                                "price": {"unit_amount": amount, "currency": "eur",
                                          "recurring": {"interval": interval}}}]}}


def test_admin_subscriptions_hidden_without_billing(client, db):
    admin_client(client, db)
    assert client.get("/admin/subscriptions").status_code == 404
    assert "/admin/subscriptions" not in client.get("/admin/").text


def test_admin_subscriptions_lists_subscribers(app, client, db, user, other_user, monkeypatch):
    app.config.update(STRIPE_SECRET_KEY="sk_test_x")
    admin_client(client, db)
    user.stripe_customer_id, other_user.stripe_customer_id = "cus_a", "cus_b"
    db.session.commit()
    t0 = 1_760_000_000
    _fake_stripe(monkeypatch, [
        _sub("cus_a", "month", 200, t0),
        _sub("cus_b", "year", 1000, t0 + 1000, cancel=True),
        _sub("cus_old", "month", 200, t0, status="canceled"),  # terminé : absent
    ], [
        {"customer": "cus_a", "created": t0 + 10, "amount_paid": 200, "currency": "eur"},
        {"customer": "cus_a", "created": t0 + 30 * 86400, "amount_paid": 200, "currency": "eur"},
        {"customer": "cus_a", "created": t0 - 86400, "amount_paid": 999, "currency": "eur"},  # avant : exclu
        {"customer": "cus_b", "created": t0 + 1000, "amount_paid": 1000, "currency": "eur"},
    ])
    html = client.get("/admin/subscriptions").text
    assert "/admin/subscriptions" in html and "Abonnés mensuels" in html and "Abonnés annuels" in html
    assert "alice@example.com" in html and "bob@example.com" in html and "cus_old" not in html
    assert "4,00" in html and "10,00" in html and "14,00" in html  # encaissé par client, et total
    assert "Résilié" in html and "Mensuel" in html and "Annuel" in html


def test_admin_subscriptions_survives_stripe_error(app, client, db, monkeypatch):
    import stripe

    app.config.update(STRIPE_SECRET_KEY="sk_test_x")
    admin_client(client, db)

    def boom(**kw):
        raise stripe.APIConnectionError("down")
    monkeypatch.setattr(stripe.Subscription, "list", boom)
    response = client.get("/admin/subscriptions")
    assert response.status_code == 200 and "Stripe ne répond pas" in response.text
