"""Abonnement Premium (Stripe) : aucun appel réseau, Stripe est simulé."""
import hashlib
import hmac
import json
import time
from datetime import timedelta
from types import SimpleNamespace

import pytest
import stripe

from app.billing import premium_required, stripe_sync
from app.models import User, utcnow

from .conftest import login, make_user

WEBHOOK_SECRET = "whsec_test"


@pytest.fixture
def billing(app):
    app.config.update(STRIPE_SECRET_KEY="sk_test_x", STRIPE_WEBHOOK_SECRET=WEBHOOK_SECRET,
                      PREMIUM_PRICE_MONTHLY="2", PREMIUM_PRICE_YEARLY="10", PREMIUM_CURRENCY="eur")  # 10 : teste l'économie
    stripe_sync._price_ids.clear()
    return app


def subscription(status="active", days=30, interval="month", cancel=False):
    end = int((utcnow() + timedelta(days=days)).timestamp())
    return {"id": "sub_1", "status": status, "cancel_at_period_end": cancel,
            "items": {"data": [{"current_period_end": end, "price": {"recurring": {"interval": interval}}}]}}


def signed_post(client, event, secret=WEBHOOK_SECRET):
    payload = json.dumps(event)
    ts = int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()
    return client.post("/billing/webhook", data=payload, content_type="application/json",
                       headers={"Stripe-Signature": f"t={ts},v1={sig}"})


def event(type_, customer="cus_1"):
    return {"id": "evt_1", "object": "event", "type": type_,
            "data": {"object": {"id": "obj_1", "object": "subscription", "customer": customer}}}


def test_disabled_without_stripe_key(auth_client, app):
    assert auth_client.get("/billing/").status_code == 404
    assert "/billing/" not in auth_client.get("/auth/profile").text


def test_pricing_page_uses_env_prices(auth_client, billing):
    page = auth_client.get("/billing/").text
    assert "2,00" in page and "10,00" in page and "58" in page  # économie : 1 - 10 / 24
    assert 'href="/billing/"' in auth_client.get("/auth/profile").text  # lien du menu


def test_plan_amount_parsing(billing):
    billing.config["PREMIUM_PRICE_MONTHLY"] = "2.50"
    assert stripe_sync.plan_amount("monthly") == 250
    billing.config["PREMIUM_PRICE_MONTHLY"] = "2,5"
    assert stripe_sync.plan_amount("monthly") == 250
    for bad in ("abc", "0", "-1", "2.555"):
        billing.config["PREMIUM_PRICE_MONTHLY"] = bad
        with pytest.raises(ValueError):
            stripe_sync.plan_amount("monthly")


def test_price_created_once_from_env(billing, monkeypatch):
    created = []
    monkeypatch.setattr(stripe.Price, "list", lambda **kw: SimpleNamespace(data=[]))
    modified = []
    monkeypatch.setattr(stripe.Product, "retrieve", lambda pid: SimpleNamespace(id=pid, tax_code=None))
    monkeypatch.setattr(stripe.Product, "modify", lambda pid, **kw: modified.append(kw))
    monkeypatch.setattr(stripe.Price, "create", lambda **kw: created.append(kw) or SimpleNamespace(id="price_new"))
    assert stripe_sync.price_id("yearly") == "price_new"
    assert stripe_sync.price_id("yearly") == "price_new"  # en cache
    assert len(created) == 1 and modified == [{"tax_code": "txcd_10103000"}]
    assert created[0]["unit_amount"] == 1000 and created[0]["currency"] == "eur"
    assert created[0]["recurring"] == {"interval": "year"} and created[0]["lookup_key"] == "premium_year_1000_eur"


def test_existing_price_reused(billing, monkeypatch):
    monkeypatch.setattr(stripe.Product, "retrieve", lambda pid: SimpleNamespace(id=pid, tax_code="txcd_10103000"))
    monkeypatch.setattr(stripe.Product, "modify", lambda *a, **kw: pytest.fail("code fiscal déjà à jour"))
    monkeypatch.setattr(stripe.Price, "list", lambda **kw: SimpleNamespace(data=[SimpleNamespace(id="price_old")]))
    monkeypatch.setattr(stripe.Price, "create", lambda **kw: pytest.fail("ne doit pas créer de tarif"))
    assert stripe_sync.price_id("monthly") == "price_old"


def test_checkout_redirects_to_stripe(auth_client, billing, monkeypatch):
    calls = []
    monkeypatch.setattr(stripe_sync, "create_checkout_session",
                        lambda user, plan, **kw: calls.append((user.email, plan, kw)) or "https://checkout.stripe.com/c/pay/x")
    resp = auth_client.post("/billing/checkout", data={"plan": "monthly"})
    assert resp.status_code == 303 and resp.location == "https://checkout.stripe.com/c/pay/x"
    assert calls[0][:2] == ("alice@example.com", "monthly")
    assert "{CHECKOUT_SESSION_ID}" in calls[0][2]["success_url"]
    assert auth_client.post("/billing/checkout", data={"plan": "lifetime"}).status_code == 400


def test_checkout_refused_when_already_subscribed(auth_client, billing, user, db, monkeypatch):
    stripe_sync.apply_subscription(user, subscription())
    db.session.commit()
    monkeypatch.setattr(stripe_sync, "create_checkout_session", lambda *a, **kw: pytest.fail("déjà abonné"))
    resp = auth_client.post("/billing/checkout", data={"plan": "yearly"})
    assert resp.status_code == 302 and resp.location.endswith("/billing/")


def test_checkout_stripe_error(auth_client, billing, monkeypatch):
    def boom(*a, **kw):
        raise stripe.APIConnectionError("réseau")
    monkeypatch.setattr(stripe_sync, "create_checkout_session", boom)
    resp = auth_client.post("/billing/checkout", data={"plan": "monthly"}, follow_redirects=True)
    assert "momentanément indisponible" in resp.text


@pytest.mark.parametrize("status,days,premium", [
    ("active", 30, True), ("trialing", 30, True), ("past_due", 3, True),
    ("canceled", 30, False), ("unpaid", 30, False), ("incomplete", 30, False), ("active", -1, False),
])
def test_premium_status(app, user, status, days, premium):
    stripe_sync.apply_subscription(user, subscription(status, days))
    assert user.is_premium is premium


def test_apply_subscription_fields_and_reset(app, user):
    stripe_sync.apply_subscription(user, subscription(interval="year", cancel=True))
    assert user.subscription_interval == "year" and user.cancel_at_period_end is True
    stripe_sync.apply_subscription(user, None)
    assert user.subscription_status is None and user.premium_until is None and not user.is_premium


def test_period_end_on_subscription_for_older_api(app, user):
    end = int((utcnow() + timedelta(days=5)).timestamp())
    stripe_sync.apply_subscription(user, {"status": "active", "current_period_end": end, "items": {"data": []}})
    assert user.is_premium


def test_webhook_rejects_bad_signature(client, billing):
    assert signed_post(client, event("customer.subscription.updated"), secret="whsec_other").status_code == 400
    assert client.post("/billing/webhook", data="{}", content_type="application/json").status_code == 400


def test_webhook_resyncs_from_stripe(client, billing, user, db, monkeypatch):
    user.stripe_customer_id = "cus_1"
    db.session.commit()
    state = {"sub": subscription()}
    monkeypatch.setattr(stripe_sync, "fetch_subscription", lambda customer: state["sub"])

    assert signed_post(client, event("customer.subscription.created")).status_code == 200
    assert db.session.get(User, user.id).is_premium

    # Événements en désordre : un « updated » tardif après la résiliation ne réactive rien,
    # car l'état est toujours relu chez Stripe.
    state["sub"] = subscription("canceled")
    signed_post(client, event("customer.subscription.deleted"))
    signed_post(client, event("customer.subscription.updated"))
    db.session.expire_all()
    assert not db.session.get(User, user.id).is_premium


def test_webhook_ignores_unknown_customer_and_events(client, billing, monkeypatch):
    monkeypatch.setattr(stripe_sync, "fetch_subscription", lambda customer: pytest.fail("client inconnu"))
    assert signed_post(client, event("customer.subscription.updated", customer="cus_unknown")).status_code == 200
    assert signed_post(client, event("charge.refunded")).status_code == 200


def test_fetch_prefers_running_subscription(billing, monkeypatch):
    subs = [stripe.StripeObject.construct_from(s, "k") for s in (subscription("canceled"), subscription("active"))]
    monkeypatch.setattr(stripe.Subscription, "list", lambda **kw: SimpleNamespace(data=subs))
    assert stripe_sync.fetch_subscription("cus_1")["status"] == "active"


def test_premium_required(app, client, user, db, billing):
    app.add_url_rule("/premium-test", "premium_test", premium_required(lambda: "ok"))
    app.add_url_rule("/api/premium-test", "api_premium_test", premium_required(lambda: "ok"))
    login(client)
    resp = client.get("/premium-test")
    assert resp.status_code == 302 and resp.location.endswith("/billing/")
    assert client.get("/api/premium-test").status_code == 402
    user.premium_granted = True
    db.session.commit()
    assert client.get("/premium-test").text == "ok"


def test_premium_required_open_without_billing(app, client, user):
    app.add_url_rule("/premium-test", "premium_test", premium_required(lambda: "ok"))
    login(client)
    assert client.get("/premium-test").text == "ok"


def test_account_deletion_deletes_stripe_customer(auth_client, billing, user, db, monkeypatch):
    user.stripe_customer_id = "cus_1"
    db.session.commit()
    deleted = []
    monkeypatch.setattr(stripe.Customer, "delete", lambda cid: deleted.append(cid))
    resp = auth_client.post("/auth/delete", data={"del-delete_password": "password123", "del-confirm": "y"})
    assert resp.status_code == 302 and deleted == ["cus_1"]
    assert db.session.get(User, user.id) is None


def test_account_kept_when_stripe_unreachable(auth_client, billing, user, db, monkeypatch):
    user.stripe_customer_id = "cus_1"
    db.session.commit()

    def boom(cid):
        raise stripe.APIConnectionError("réseau")
    monkeypatch.setattr(stripe.Customer, "delete", boom)
    resp = auth_client.post("/auth/delete", data={"del-delete_password": "password123", "del-confirm": "y"},
                            follow_redirects=True)
    assert "pas pu être résilié" in resp.text
    assert db.session.get(User, user.id) is not None


def test_admin_grants_premium(client, db, user):
    admin = make_user("root@example.com")
    admin.is_admin = True
    db.session.commit()
    login(client, "root@example.com")
    client.post(f"/admin/users/{user.id}/premium")
    assert db.session.get(User, user.id).premium_granted is True
    assert "Premium offert" in client.get("/admin/").text
    client.post(f"/admin/users/{user.id}/premium")
    assert db.session.get(User, user.id).premium_granted is False


def test_maintenance_resyncs_expired_subscriptions(billing, db, user, monkeypatch):
    from app import jobs

    user.stripe_customer_id = "cus_1"
    stripe_sync.apply_subscription(user, subscription(days=-1))  # renouvellement non reçu
    db.session.commit()
    monkeypatch.setattr(stripe_sync, "fetch_subscription", lambda customer: subscription(days=30))
    record = jobs.run_job("maintenance")
    assert record.status == "ok" and "1 abonnement(s) relu(s)" in record.summary
    assert db.session.get(User, user.id).is_premium


def test_csp_allows_stripe_redirects(client):
    csp = client.get("/").headers["Content-Security-Policy"]
    form_action = next(p for p in csp.split(";") if p.strip().startswith("form-action"))
    assert "https://checkout.stripe.com" in form_action


def subscribe(user, db, **kw):
    user.stripe_customer_id = "cus_1"
    stripe_sync.apply_subscription(user, subscription(**kw))
    db.session.commit()


def test_subscriber_sees_invoices_and_stop_not_plans(auth_client, billing, user, db):
    subscribe(user, db)
    page = auth_client.get("/billing/").text
    assert 'name="plan"' not in page and "S&#39;abonner" not in page
    assert "Mes factures" in page and "Arrêter mon abonnement" in page and 'action="/billing/cancel"' in page
    assert "Reprendre mon abonnement" not in page


def test_cancelled_subscriber_can_resume(auth_client, billing, user, db):
    subscribe(user, db, cancel=True)
    page = auth_client.get("/billing/").text
    assert 'action="/billing/resume"' in page and 'action="/billing/cancel"' not in page
    assert 'name="plan"' not in page


def test_granted_premium_sees_no_plans(auth_client, billing, user, db):
    user.premium_granted = True
    db.session.commit()
    page = auth_client.get("/billing/").text
    assert 'name="plan"' not in page and "offert" in page


def test_non_subscriber_sees_plans(auth_client, billing):
    page = auth_client.get("/billing/").text
    assert page.count('name="plan"') == 2 and "Arrêter mon abonnement" not in page


@pytest.mark.parametrize("route,cancel", [("cancel", True), ("resume", False)])
def test_cancel_and_resume(auth_client, billing, user, db, monkeypatch, route, cancel):
    subscribe(user, db, cancel=not cancel)
    calls = []

    def modify(sub_id, **kw):
        calls.append((sub_id, kw))
        return stripe.StripeObject.construct_from(subscription(cancel=kw["cancel_at_period_end"]), "k")
    monkeypatch.setattr(stripe_sync, "fetch_subscription", lambda customer: subscription(cancel=not cancel))
    monkeypatch.setattr(stripe.Subscription, "modify", modify)
    resp = auth_client.post(f"/billing/{route}", follow_redirects=True)
    assert calls == [("sub_1", {"cancel_at_period_end": cancel})]
    refreshed = db.session.get(User, user.id)
    assert refreshed.cancel_at_period_end is cancel and refreshed.is_premium  # accès gardé jusqu'à la fin
    assert ("est arrêté" if cancel else "reprend") in resp.text


def test_cancel_without_subscription(auth_client, billing, user, db, monkeypatch):
    user.stripe_customer_id = "cus_1"
    db.session.commit()
    monkeypatch.setattr(stripe_sync, "fetch_subscription", lambda customer: None)
    monkeypatch.setattr(stripe.Subscription, "modify", lambda *a, **kw: pytest.fail("rien à arrêter"))
    assert "Aucun abonnement en cours" in auth_client.post("/billing/cancel", follow_redirects=True).text


def test_cancel_stripe_error(auth_client, billing, user, db, monkeypatch):
    subscribe(user, db)

    def boom(customer):
        raise stripe.APIConnectionError("réseau")
    monkeypatch.setattr(stripe_sync, "fetch_subscription", boom)
    assert "pas pu être modifié" in auth_client.post("/billing/cancel", follow_redirects=True).text


def test_invoices_page(auth_client, billing, user, db, monkeypatch):
    subscribe(user, db)
    invs = [stripe.StripeObject.construct_from(i, "k") for i in (
        {"number": "A-0002", "created": 1793000000, "total": 200, "currency": "eur", "status": "open",
         "hosted_invoice_url": "https://invoice.stripe.com/i/2", "invoice_pdf": "https://pay.stripe.com/2.pdf"},
        {"number": "A-0001", "created": 1790000000, "total": 200, "currency": "eur", "status": "paid",
         "hosted_invoice_url": "https://invoice.stripe.com/i/1", "invoice_pdf": "https://pay.stripe.com/1.pdf"},
        {"number": None, "created": 1793100000, "total": 200, "currency": "eur", "status": "draft"},
    )]
    seen = []
    monkeypatch.setattr(stripe.Invoice, "list", lambda **kw: seen.append(kw) or SimpleNamespace(data=invs))
    page = auth_client.get("/billing/invoices").text
    assert seen[0]["customer"] == "cus_1"
    assert "A-0002" in page and "A-0001" in page and page.count("2,00") == 2  # brouillon exclu
    assert "https://pay.stripe.com/1.pdf" in page and "Payer" in page and "Payée" in page


def test_invoices_without_customer(auth_client, billing):
    assert "Aucune facture" in auth_client.get("/billing/invoices").text


# --- Photos : fonction Premium -----------------------------------------------------------------

def _jpeg():
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 40, 40)).save(out, "JPEG")
    return out.getvalue()


def _upload_photo(client, url):
    import io
    return client.post(url, data={"photos": [(io.BytesIO(_jpeg()), "a.jpg")]}, content_type="multipart/form-data")


def test_photo_upload_requires_premium(auth_client, billing, user, db):
    from app.models import Photo

    from .conftest import make_trip

    trip = make_trip(user)
    page = auth_client.get(f"/trips/{trip.id}").text
    assert "réservé aux abonnés Premium" in page and 'enctype="multipart/form-data"' not in page
    resp = _upload_photo(auth_client, f"/trips/{trip.id}/photos")
    assert resp.status_code == 302 and resp.location.endswith("/billing/")
    assert db.session.execute(db.select(Photo)).first() is None

    user.premium_granted = True
    db.session.commit()
    assert 'enctype="multipart/form-data"' in auth_client.get(f"/trips/{trip.id}").text
    _upload_photo(auth_client, f"/trips/{trip.id}/photos")
    assert db.session.execute(db.select(db.func.count(Photo.id))).scalar() == 1


def test_journey_photo_upload_requires_premium(auth_client, billing, user, db):
    from .conftest import make_trip

    a, b = make_trip(user), make_trip(user)
    auth_client.post("/journeys", data={"trip_ids": [a.id, b.id]})
    from app.models import Journey
    journey = db.session.execute(db.select(Journey)).scalar_one()
    resp = _upload_photo(auth_client, f"/journeys/{journey.id}/photos")
    assert resp.status_code == 302 and resp.location.endswith("/billing/")


def test_existing_photos_stay_visible_and_deletable(app, client, user, db):
    from app.models import Photo

    from .conftest import make_trip

    trip = make_trip(user)
    login(client)
    _upload_photo(client, f"/trips/{trip.id}/photos")  # sans Stripe : pas de restriction
    photo = db.session.execute(db.select(Photo)).scalar_one()
    app.config.update(STRIPE_SECRET_KEY="sk_test_x")  # puis l'abonnement devient nécessaire
    assert client.get(f"/photos/{photo.id}/thumb").status_code == 200
    assert f"/photos/{photo.id}/thumb" in client.get(f"/trips/{trip.id}").text
    client.post(f"/photos/{photo.id}/delete")
    assert db.session.execute(db.select(Photo)).first() is None


def test_archive_restore_skips_photos_without_premium(app, client, user, db):
    import io

    from .conftest import make_trip

    trip = make_trip(user)
    login(client)
    _upload_photo(client, f"/trips/{trip.id}/photos")
    archive = client.get("/export.zip").data
    client.post("/auth/logout")

    app.config.update(STRIPE_SECRET_KEY="sk_test_x")
    make_user("carol@example.com")
    login(client, "carol@example.com")
    result = client.post("/import", data={"file": (io.BytesIO(archive), "backup.zip")},
                         content_type="multipart/form-data", follow_redirects=True)
    assert "1 photo non restaurée" in result.text
    carol = db.session.execute(db.select(User).filter_by(email="carol@example.com")).scalar_one()
    assert carol.trips.count() == 1 and carol.photos.count() == 0


# --- Support : fonction Premium ----------------------------------------------------------------

def test_support_requires_premium(auth_client, billing, user, db):
    from app.models import Ticket

    for method, url in (("get", "/support"), ("post", "/support")):
        resp = getattr(auth_client, method)(url, data={"subject": "Aide", "body": "Bonjour"})
        assert resp.status_code == 302 and resp.location.endswith("/billing/")
    assert db.session.execute(db.select(Ticket)).first() is None
    assert "Accès au support" in auth_client.get("/billing/").text

    subscribe(user, db)
    assert auth_client.get("/support").status_code == 200
    auth_client.post("/support", data={"subject": "Aide", "body": "Bonjour"})
    ticket = db.session.execute(db.select(Ticket)).scalar_one()

    stripe_sync.apply_subscription(user, subscription("canceled"))  # abonnement terminé
    db.session.commit()
    for url in (f"/support/{ticket.id}", f"/support/{ticket.id}/close", f"/support/{ticket.id}/notify"):
        method = auth_client.get if url.endswith(str(ticket.id)) else auth_client.post
        assert method(url).location.endswith("/billing/")


# --- Partage et profil public : fonctions Premium ----------------------------------------------

def test_share_link_creation_requires_premium(auth_client, billing, user, db):
    from app.models import ShareLink

    page = auth_client.get("/share").text
    assert "réservés aux abonnés Premium" in page and 'name="label"' not in page
    resp = auth_client.post("/share", data={"label": "Famille"})
    assert resp.status_code == 302 and resp.location.endswith("/billing/")
    assert db.session.execute(db.select(ShareLink)).first() is None

    subscribe(user, db)
    assert 'name="label"' in auth_client.get("/share").text
    auth_client.post("/share", data={"label": "Famille"})
    assert db.session.execute(db.select(ShareLink)).scalar_one().label == "Famille"


def test_share_links_suspended_without_premium(app, client, user, db):
    from app.models import ShareLink

    from .conftest import make_trip

    make_trip(user)
    link = ShareLink(user_id=user.id)
    db.session.add(link)
    db.session.commit()
    urls = (f"/s/{link.token}", f"/s/{link.token}/stats", f"/api/shared/{link.token}/trips")
    assert all(client.get(u).status_code == 200 for u in urls)  # sans Stripe : rien n'est réservé

    app.config.update(STRIPE_SECRET_KEY="sk_test_x")
    assert all(client.get(u).status_code == 404 for u in urls)  # Premium absent : lien suspendu
    user.premium_granted = True
    db.session.commit()
    assert all(client.get(u).status_code == 200 for u in urls)  # de retour avec le Premium

    user.premium_granted = False
    db.session.commit()
    login(client)
    assert "ne sont plus accessibles" in client.get("/share").text
    client.post(f"/share/{link.id}/revoke")  # révoquer reste possible
    assert db.session.execute(db.select(ShareLink)).first() is None


def test_public_profile_requires_premium(auth_client, billing, user, db):
    resp = auth_client.post("/auth/public-profile", data={"pub-public_name": "alice"})
    assert resp.status_code == 302 and resp.location.endswith("/billing/")
    assert db.session.get(User, user.id).public_name is None

    subscribe(user, db)
    auth_client.post("/auth/public-profile", data={"pub-public_name": "alice"})
    assert auth_client.get("/u/alice").status_code == 200

    stripe_sync.apply_subscription(user, subscription("canceled"))
    db.session.commit()
    assert auth_client.get("/u/alice").status_code == 404  # suspendu
    page = auth_client.get("/auth/profile").text
    assert "/u/alice n&#39;est plus accessible" in page or "/u/alice n'est plus accessible" in page
    auth_client.post("/auth/public-profile", data={"pub-public_name": ""})  # le retirer reste possible
    assert db.session.get(User, user.id).public_name is None


def test_diamond_marks_premium_features(app, client, user, db):
    login(client)
    assert "fa-gem" not in client.get("/share").text  # sans Stripe : pas de diamant
    app.config.update(STRIPE_SECRET_KEY="sk_test_x")
    menu = client.get("/auth/profile").text
    assert menu.count("Fonction Premium") >= 3  # partage, support, profil public
    about = client.get("/about").text
    assert "fa-gem" in about and "12,00" in about and "Gratuit, sans publicité, et open source" not in about


def test_landing_marks_photos_with_diamond(app, client):
    app.config.update(STRIPE_SECRET_KEY="sk_test_x")
    page = client.get("/").text
    assert page.count("fa-gem") == 1 and "essentiel est gratuit" in page


# --- Import par e-mail : fonction Premium ------------------------------------------------------

def test_mail_import_requires_premium(app, db, user):
    from app import mail_import
    from app.models import MailImport

    from .test_mail_import import AIR_FRANCE_TEXT, make_mail

    app.config.update(STRIPE_SECRET_KEY="sk_test_x", MAIL_IMPORT_REQUIRE_DKIM=False)
    outcome = mail_import.process(make_mail(text=AIR_FRANCE_TEXT, subject="Résa").as_bytes())
    assert outcome.status == "ignored" and not outcome.delete and user.trips.count() == 0
    assert db.session.execute(db.select(MailImport)).scalar_one().reason == "Premium requis"
    [reply] = [m for m in app.extensions.get("mail_outbox", []) if m["To"] == "alice@example.com"]
    assert reply["Subject"] == "Import non effectué : Résa"
    assert "réservé aux abonnés Premium" in reply.get_content() and "/billing/" in reply.get_content()

    user.premium_granted = True
    db.session.commit()
    outcome = mail_import.process(make_mail(text=AIR_FRANCE_TEXT, message_id="<again@x>").as_bytes())
    assert outcome.status == "imported" and user.trips.count() == 1


def test_unknown_sender_gets_no_premium_reply(app, db, user):
    from app import mail_import

    from .test_mail_import import AIR_FRANCE_TEXT, make_mail

    app.config.update(STRIPE_SECRET_KEY="sk_test_x", MAIL_IMPORT_REQUIRE_DKIM=False)
    mail_import.process(make_mail(text=AIR_FRANCE_TEXT, sender="stranger@example.org").as_bytes())
    assert app.extensions.get("mail_outbox", []) == []


def test_import_addresses_require_premium(auth_client, billing, user, db):
    from app.models import ImportAddress

    billing.config.update(IMPORT_ADDRESS="addto@voyage-voyage.app")
    page = auth_client.get("/auth/profile").text
    assert "import par e-mail est réservé" in page and 'name="imp-email"' not in page
    resp = auth_client.post("/auth/import-addresses", data={"imp-email": "work@example.org"})
    assert resp.status_code == 302 and resp.location.endswith("/billing/")
    assert db.session.execute(db.select(ImportAddress)).first() is None
    subscribe(user, db)
    assert 'name="imp-email"' in auth_client.get("/auth/profile").text


def test_transfer_page_marks_mail_import_premium(auth_client, billing, user, db):
    billing.config.update(IMPORT_ADDRESS="addto@voyage-voyage.app")
    page = auth_client.get("/import-export").text
    assert "fa-gem" in page and "import par e-mail est réservé" in page and "#mail-import" not in page
    subscribe(user, db)
    page = auth_client.get("/import-export").text
    assert "fa-gem" in page and "#mail-import" in page and "import par e-mail est réservé" not in page


def test_pricing_page_links_to_plan_comparison_unless_premium(auth_client, billing, user, db):
    assert 'href="/plans"' in auth_client.get("/billing/").text
    user.premium_granted = True
    db.session.commit()
    assert 'href="/plans"' not in auth_client.get("/billing/").text
