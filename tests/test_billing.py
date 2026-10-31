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
                      PREMIUM_PRICE_MONTHLY="2", PREMIUM_PRICE_YEARLY="10", PREMIUM_CURRENCY="eur")
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
    assert "https://checkout.stripe.com" in form_action and "https://billing.stripe.com" in form_action
