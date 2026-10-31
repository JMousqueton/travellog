"""Appels à Stripe. L'état local (colonnes de User) n'est jamais déduit du contenu d'un événement : à chaque
signal (webhook, retour de paiement, tâche maintenance), l'abonnement est relu chez Stripe. L'ordre des
événements et leurs doublons n'ont donc aucune importance."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import stripe
from flask import current_app

from ..extensions import db
from ..models import User

PRODUCT_ID = "travellog_premium"
PLANS = {"monthly": ("month", "PREMIUM_PRICE_MONTHLY"), "yearly": ("year", "PREMIUM_PRICE_YEARLY")}

_price_ids = {}  # lookup_key -> price_…, par processus


def _client():
    stripe.api_key = current_app.config["STRIPE_SECRET_KEY"]
    stripe.max_network_retries = 2
    return stripe


def plan_amount(plan):
    """Montant du plan en centimes, d'après .env (« 2 » ou « 2.50 »)."""
    raw = current_app.config[PLANS[plan][1]]
    try:
        cents = Decimal(str(raw).replace(",", ".")) * 100
    except InvalidOperation:
        raise ValueError(f"{PLANS[plan][1]} invalide : {raw!r}") from None
    if cents <= 0 or cents != cents.to_integral_value():
        raise ValueError(f"{PLANS[plan][1]} invalide : {raw!r}")
    return int(cents)


def plan_price(plan):
    """Montant du plan en unités de la devise, pour l'affichage."""
    return Decimal(plan_amount(plan)) / 100


def _ensure_product(client):
    """Produit Premium, avec le code fiscal de .env (exigé par Stripe Managed Payments pour la TVA)."""
    tax_code = current_app.config["STRIPE_TAX_CODE"] or None
    try:
        product = client.Product.retrieve(PRODUCT_ID)
    except client.InvalidRequestError:
        name = f"{current_app.config['SITE_NAME']} Premium"
        try:
            client.Product.create(id=PRODUCT_ID, name=name, tax_code=tax_code)
        except client.InvalidRequestError:
            pass  # créé entre-temps par un autre worker
        return
    if tax_code and getattr(product, "tax_code", None) != tax_code:
        client.Product.modify(PRODUCT_ID, tax_code=tax_code)


def price_id(plan):
    """Tarif Stripe du plan au prix de .env : retrouvé par sa lookup_key, ou créé."""
    interval = PLANS[plan][0]
    currency = current_app.config["PREMIUM_CURRENCY"]
    amount = plan_amount(plan)
    key = f"premium_{interval}_{amount}_{currency}"
    if key in _price_ids:
        return _price_ids[key]
    client = _client()
    _ensure_product(client)
    found = client.Price.list(lookup_keys=[key], active=True, limit=1).data
    if found:
        _price_ids[key] = found[0].id
        return found[0].id
    price = client.Price.create(product=PRODUCT_ID, unit_amount=amount, currency=currency,
                                recurring={"interval": interval}, lookup_key=key,
                                metadata={"plan": plan})
    _price_ids[key] = price.id
    return price.id


def ensure_customer(user):
    if not user.stripe_customer_id:
        customer = _client().Customer.create(email=user.email, preferred_locales=[user.locale],
                                             metadata={"user_id": str(user.id)})
        user.stripe_customer_id = customer.id
        db.session.commit()
    return user.stripe_customer_id


def create_checkout_session(user, plan, success_url, cancel_url):
    session = _client().checkout.Session.create(
        mode="subscription",
        customer=ensure_customer(user),
        client_reference_id=str(user.id),
        line_items=[{"price": price_id(plan), "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        locale=user.locale,
    )
    return session.url


def list_invoices(user, limit=36):
    """Factures du client, de la plus récente à la plus ancienne (brouillons exclus)."""
    if not user.stripe_customer_id:
        return []
    invoices = _client().Invoice.list(customer=user.stripe_customer_id, limit=limit).data
    rows = []
    for inv in invoices:
        inv = inv.to_dict()
        if inv.get("status") == "draft":
            continue
        rows.append({
            "number": inv.get("number"),
            "date": datetime.fromtimestamp(inv["created"], timezone.utc),
            "amount": Decimal(inv.get("total") or 0) / 100,
            "currency": (inv.get("currency") or "eur").upper(),
            "status": inv.get("status"),  # paid, open, void, uncollectible
            "url": inv.get("hosted_invoice_url"),
            "pdf": inv.get("invoice_pdf"),
        })
    return rows


def set_cancel_at_period_end(user, cancel):
    """Arrête (à la fin de la période payée) ou reprend l'abonnement en cours ; False s'il n'y en a pas."""
    sub = fetch_subscription(user.stripe_customer_id) if user.stripe_customer_id else None
    if sub is None or sub["status"] not in User.PREMIUM_STATUSES:
        apply_subscription(user, sub)
        return False
    updated = _client().Subscription.modify(sub["id"], cancel_at_period_end=cancel)
    apply_subscription(user, updated.to_dict())
    return True


def fetch_subscription(customer_id):
    """Abonnement à retenir pour le client : un abonnement en cours de préférence, sinon le plus récent."""
    subs = [s.to_dict() for s in _client().Subscription.list(customer=customer_id, status="all", limit=10).data]
    for sub in subs:  # du plus récent au plus ancien
        if sub["status"] in User.PREMIUM_STATUSES:
            return sub
    return subs[0] if subs else None


def apply_subscription(user, sub):
    """Recopie l'abonnement Stripe (dict, ou None) dans les colonnes du compte."""
    if sub is None:
        user.subscription_status = user.subscription_interval = user.premium_until = None
        user.cancel_at_period_end = False
        return
    item = sub["items"]["data"][0] if sub.get("items", {}).get("data") else {}
    # Selon la version de l'API, la fin de période est portée par l'élément ou par l'abonnement.
    end = item.get("current_period_end") or sub.get("current_period_end")
    user.subscription_status = sub["status"]
    user.subscription_interval = ((item.get("price") or {}).get("recurring") or {}).get("interval")
    user.premium_until = datetime.fromtimestamp(end, timezone.utc) if end else None
    user.cancel_at_period_end = bool(sub.get("cancel_at_period_end"))


def sync_customer(customer_id):
    """Relit l'abonnement du client chez Stripe ; renvoie le compte mis à jour (None si inconnu)."""
    user = db.session.execute(db.select(User).filter_by(stripe_customer_id=customer_id)).scalar_one_or_none()
    if user is None:
        return None
    apply_subscription(user, fetch_subscription(customer_id))
    return user


def sync_checkout_session(user, session_id):
    """Retour de Stripe Checkout : met l'abonnement à jour sans attendre le webhook."""
    session = _client().checkout.Session.retrieve(session_id)
    if session.customer != user.stripe_customer_id:
        return None
    return sync_customer(user.stripe_customer_id)


def delete_customer(user):
    """Suppression du compte : le client Stripe est supprimé, ce qui résilie aussitôt ses abonnements
    (plus aucun prélèvement). Les factures restent chez Stripe pour la comptabilité."""
    if not user.stripe_customer_id or not current_app.config.get("STRIPE_SECRET_KEY"):
        return
    try:
        _client().Customer.delete(user.stripe_customer_id)
    except stripe.InvalidRequestError as exc:
        if exc.http_status != 404:  # déjà supprimé chez Stripe
            raise
    user.stripe_customer_id = None


def construct_event(payload, signature):
    return stripe.Webhook.construct_event(payload, signature, current_app.config["STRIPE_WEBHOOK_SECRET"])
