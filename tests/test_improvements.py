"""Lien Premium, capture d'accueil, premiers pas, badge du profil public, revenus des abonnements, bilan de
l'année par e-mail et page « Mes photos »."""
import csv
import io
from datetime import date

import pytest

from .conftest import make_trip
from .test_admin import _fake_stripe, _sub, admin_client
from .test_features import _image_bytes, _upload


@pytest.fixture
def billing(app):
    app.config.update(STRIPE_SECRET_KEY="sk_test_x", PREMIUM_PRICE_MONTHLY="2", PREMIUM_PRICE_YEARLY="12")
    return app


# 6 et 8 : lien Premium et capture de la carte sur l'accueil

def test_footer_and_landing_link_to_plans_with_billing(client, billing):
    html = client.get("/").text
    assert html.count('href="/plans"') >= 2  # accroche et pied de page
    assert "img/hero-map-light.webp" in html and "img/hero-map-dark.webp" in html


def test_no_premium_link_without_billing(client):
    assert 'href="/plans"' not in client.get("/").text


# 9 : premiers pas sur une carte vide

def test_empty_map_shows_welcome_card(auth_client, user):
    html = auth_client.get("/").text
    assert "welcome-card" in html and 'href="/trips/new"' in html and 'href="/import-export"' in html


def test_welcome_card_hidden_once_trips_exist(auth_client, user):
    make_trip(user)
    assert "welcome-card" not in auth_client.get("/").text


# 13 : badge SVG du profil public (Premium)

def test_public_badge_svg(client, user, db):
    user.public_name = "alice"
    db.session.commit()
    make_trip(user)
    make_trip(user, dest_name="Rome", dest_lat=41.9, dest_lon=12.5, transport_mode="plane")
    response = client.get("/u/alice/badge.svg")
    assert response.status_code == 200 and response.mimetype == "image/svg+xml"
    assert response.headers["Cross-Origin-Resource-Policy"] == "cross-origin"
    assert "/u/alice" in response.text and "<title>" in response.text and ">2<" in response.text


def test_public_badge_needs_premium(client, user, db, billing):
    user.public_name = "alice"
    db.session.commit()
    assert client.get("/u/alice/badge.svg").status_code == 404
    user.premium_granted = True
    db.session.commit()
    assert client.get("/u/alice/badge.svg").status_code == 200


def test_profile_shows_badge_code(auth_client, user, db):
    user.public_name = "alice"
    db.session.commit()
    html = auth_client.get("/auth/profile").text
    assert "/u/alice/badge.svg" in html and "[![" in html


# 14 : revenus par mois, résiliations et export CSV

def _stripe_with_history(monkeypatch, user, db):
    import stripe

    user.stripe_customer_id = "cus_a"
    db.session.commit()
    t0 = 1_760_000_000  # 9 oct. 2025
    _fake_stripe(monkeypatch, [_sub("cus_a", "month", 200, t0),
                               dict(_sub("cus_z", "month", 200, t0), status="canceled", ended_at=t0 + 40 * 86400)],
                 [{"customer": "cus_a", "created": t0 + 10, "amount_paid": 200, "currency": "eur"}])
    return stripe


def test_admin_subscriptions_shows_monthly_revenue(client, db, user, billing, monkeypatch):
    from app.billing.stripe_sync import monthly_history

    _stripe_with_history(monkeypatch, user, db)
    admin_client(client, db)
    html = client.get("/admin/subscriptions").text
    assert "rev-chart" in html and "Exporter en CSV" in html
    report = {"payments": [(date(2026, 10, 3), 200, "EUR")], "ended": [date(2026, 9, 2)]}
    history = monthly_history(report, date(2026, 10, 31))
    assert len(history) == 12 and history[-1]["revenue"] == {"EUR": 2} and history[-2]["ended"] == 1


def test_admin_subscriptions_csv(client, db, user, billing, monkeypatch):
    _stripe_with_history(monkeypatch, user, db)
    admin_client(client, db)
    response = client.get("/admin/subscriptions.csv")
    assert response.mimetype == "text/csv" and "attachment" in response.headers["Content-Disposition"]
    rows = list(csv.reader(io.StringIO(response.text.lstrip("﻿"))))
    assert rows[0][0] == "email" and rows[1][0] == "alice@example.com" and rows[1][-1] == "2"
    assert len(rows) == 2  # l'abonnement terminé n'est pas listé


# 15 : bilan de l'année par e-mail fin décembre

def test_year_review_email_sent_once_in_december(app, user, db, monkeypatch):
    from app import review_email

    make_trip(user, depart_date=date(2026, 6, 1))
    outbox = app.extensions.setdefault("mail_outbox", [])
    outbox.clear()
    assert review_email.send_year_reviews(date(2026, 12, 20)) is None  # trop tôt
    assert review_email.send_year_reviews(date(2026, 12, 28)) == 1
    message = outbox[-1]
    assert message["To"] == "alice@example.com" and "2026" in message["Subject"]
    assert message["List-Unsubscribe"].startswith("<") and "/emails/review/unsubscribe/" in message["List-Unsubscribe"]
    attachments = list(message.iter_attachments())
    assert attachments[0].get_content_type() == "image/png"
    assert review_email.send_year_reviews(date(2026, 12, 29)) == 0  # une seule fois par an
    db.session.refresh(user)
    assert user.review_email_year == 2026


def test_year_review_email_respects_opt_out_and_no_trips(app, user, other_user, db):
    from app import review_email

    make_trip(user, depart_date=date(2026, 6, 1))
    user.review_emails = False
    db.session.commit()
    assert review_email.send_year_reviews(date(2026, 12, 28)) == 0  # désabonnée, et bob n'a pas voyagé
    db.session.refresh(other_user)
    assert other_user.review_email_year == 2026  # n'est plus relu les nuits suivantes


def test_unsubscribe_link(client, user, db):
    from app.review_email import unsubscribe_token

    url = f"/emails/review/unsubscribe/{unsubscribe_token(user)}"
    assert "Me désabonner" in client.get(url).text and user.review_emails
    assert client.post(url).status_code == 200  # un clic, sans jeton CSRF
    db.session.refresh(user)
    assert user.review_emails is False
    assert client.get("/emails/review/unsubscribe/forged").status_code == 404


def test_review_emails_preference(auth_client, user, db):
    assert 'id="emails"' in auth_client.get("/auth/profile").text
    auth_client.post("/auth/profile/review-emails", data={"enabled": "0"})
    db.session.refresh(user)
    assert user.review_emails is False


def test_review_email_cli_sends_now(app, user, db):
    make_trip(user, depart_date=date(2025, 6, 1))
    result = app.test_cli_runner().invoke(args=["review-email", "send", "alice@example.com", "--year", "2025"])
    assert result.exit_code == 0 and "envoyé" in result.output
    assert user.review_email_year is None  # un test ne compte pas comme l'envoi de décembre
    result = app.test_cli_runner().invoke(args=["review-email", "send", "alice@example.com", "--year", "2019"])
    assert result.exit_code != 0


# Mes photos : carte des photos localisées (Premium)

def test_photos_map_lists_geotagged_photos(auth_client, user, db):
    from app.models import Photo

    trip = make_trip(user)
    _upload(auth_client, f"/trips/{trip.id}/photos", (_image_bytes(), "a.jpg"), (_image_bytes(), "b.jpg"))
    first = db.session.execute(db.select(Photo).order_by(Photo.id)).scalars().first()
    first.exif = dict(first.exif or {}, lat=45.76, lon=4.84, taken_at="2025-05-01T10:00:00")
    db.session.commit()
    html = auth_client.get("/photos").text
    assert 'id="photosMap"' in html and html.count("\"thumb\":") == 1 and "Paris, France" in html and "Lyon, France" in html
    assert 'href="/photos"' in html  # menu
    assert "d3-geo" in html and 'data-world-url="/static/data/world.json' in html  # vue globe


def test_photos_map_empty_state(auth_client, user):
    html = auth_client.get("/photos").text
    assert 'id="photosMap"' not in html and 'href="/trips"' in html


def test_photos_menu_with_diamond_and_premium_redirect(auth_client, user, billing):
    html = auth_client.get("/trips").text
    assert 'href="/photos"' in html and "fa-gem" in html  # menu visible, avec le diamant
    response = auth_client.get("/photos")
    assert response.status_code == 302 and response.location.endswith("/billing/")
