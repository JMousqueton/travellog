import stripe
from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_babel import format_currency, format_percent
from flask_babel import gettext as _
from flask_login import current_user, login_required

from ..extensions import csrf, db, limiter
from ..i18n import format_day
from . import billing_enabled, bp
from . import stripe_sync

# Événements qui déclenchent une relecture de l'abonnement du client.
SYNC_EVENTS = {
    "checkout.session.completed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.paid",
    "invoice.payment_failed",
}


@bp.before_request
def require_billing():
    if not billing_enabled():
        abort(404)


@bp.route("/")
@login_required
def index():
    currency = current_app.config["PREMIUM_CURRENCY"].upper()
    monthly, yearly = stripe_sync.plan_price("monthly"), stripe_sync.plan_price("yearly")
    saving = 1 - yearly / (12 * monthly)
    return render_template(
        "billing/index.html",
        monthly=format_currency(monthly, currency), yearly=format_currency(yearly, currency),
        saving=format_percent(saving) if saving >= 0.01 else None)


@bp.route("/checkout", methods=["POST"])
@login_required
@limiter.limit("10 per hour")
def checkout():
    plan = request.form.get("plan")
    if plan not in stripe_sync.PLANS:
        abort(400)
    if current_user.has_subscription:
        flash(_("Vous êtes déjà abonné."), "info")
        return redirect(url_for(".index"))
    try:
        url = stripe_sync.create_checkout_session(
            current_user, plan,
            success_url=url_for(".success", _external=True) + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=url_for(".index", _external=True))
    except stripe.StripeError:
        current_app.logger.exception("Stripe : création de la session de paiement")
        flash(_("Le paiement est momentanément indisponible. Réessayez dans quelques minutes."), "danger")
        return redirect(url_for(".index"))
    return redirect(url, code=303)


@bp.route("/success")
@login_required
def success():
    session_id = request.args.get("session_id", "")
    if session_id.startswith("cs_") and current_user.stripe_customer_id:
        try:
            stripe_sync.sync_checkout_session(current_user, session_id)
            db.session.commit()
        except stripe.StripeError:
            current_app.logger.exception("Stripe : lecture de la session de paiement")
    if current_user.has_subscription:
        flash(_("Merci ! Votre abonnement Premium est actif."), "success")
    else:
        # Paiement encore en cours de confirmation : le webhook mettra le compte à jour.
        flash(_("Merci ! Votre paiement est en cours de confirmation."), "info")
    return redirect(url_for(".index"))


@bp.route("/invoices")
@login_required
def invoices():
    try:
        rows = stripe_sync.list_invoices(current_user)
    except stripe.StripeError:
        current_app.logger.exception("Stripe : liste des factures")
        flash(_("Les factures sont momentanément indisponibles. Réessayez dans quelques minutes."), "danger")
        return redirect(url_for(".index"))
    for row in rows:
        row["amount"] = format_currency(row["amount"], row["currency"])
    return render_template("billing/invoices.html", invoices=rows)


def _set_cancel(cancel):
    try:
        changed = stripe_sync.set_cancel_at_period_end(current_user, cancel)
        db.session.commit()
    except stripe.StripeError:
        current_app.logger.exception("Stripe : modification de l'abonnement")
        flash(_("Votre abonnement n'a pas pu être modifié. Réessayez dans quelques minutes."), "danger")
        return redirect(url_for(".index"))
    if not changed:
        flash(_("Aucun abonnement en cours."), "info")
    elif cancel:
        flash(_("Votre abonnement est arrêté : l'accès Premium reste actif jusqu'au %(date)s, sans nouveau prélèvement.",
                date=format_day(current_user.premium_until)), "success")
    else:
        flash(_("Votre abonnement reprend : prochain renouvellement le %(date)s.",
                date=format_day(current_user.premium_until)), "success")
    return redirect(url_for(".index"))


@bp.route("/cancel", methods=["POST"])
@login_required
def cancel():
    return _set_cancel(True)


@bp.route("/resume", methods=["POST"])
@login_required
def resume():
    return _set_cancel(False)


@bp.route("/webhook", methods=["POST"])
@csrf.exempt
@limiter.exempt
def webhook():
    """Appelé par Stripe ; authentifié par la signature Stripe-Signature (secret STRIPE_WEBHOOK_SECRET)."""
    if not current_app.config["STRIPE_WEBHOOK_SECRET"]:
        abort(404)
    try:
        event = stripe_sync.construct_event(request.get_data(), request.headers.get("Stripe-Signature"))
    except (ValueError, stripe.SignatureVerificationError):
        abort(400)
    if event.type in SYNC_EVENTS:
        customer = getattr(event.data.object, "customer", None)
        if isinstance(customer, str):
            # Une erreur Stripe donne une réponse 500 : Stripe renverra l'événement plus tard.
            stripe_sync.sync_customer(customer)
            db.session.commit()
    return "", 200
