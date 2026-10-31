"""Bilan de l'année envoyé par e-mail fin décembre (tâche maintenance, chaque nuit).

À partir du REVIEW_EMAIL_DAY décembre, chaque compte qui a voyagé dans l'année et n'a pas désactivé l'envoi
reçoit une fois son bilan (chiffres clés, image jointe), dans sa langue. Un lien signé permet de se désabonner
sans se connecter (en-têtes List-Unsubscribe compris).
"""
from flask import current_app, render_template, url_for
from flask_babel import force_locale, format_decimal
from flask_babel import gettext as _
from itsdangerous import BadSignature, URLSafeSerializer

from . import review_image, utils
from .extensions import db
from .i18n import format_co2, format_distance
from .mail import mail_enabled, send_email
from .models import User

SALT = "review-emails-unsubscribe"
BATCH = 200  # envois au plus par nuit ; les suivants partent la nuit d'après


def unsubscribe_token(user):
    return URLSafeSerializer(current_app.config["SECRET_KEY"], salt=SALT).dumps(user.id)


def user_from_token(token):
    try:
        user_id = URLSafeSerializer(current_app.config["SECRET_KEY"], salt=SALT).loads(token)
    except BadSignature:
        return None
    return db.session.get(User, user_id) if isinstance(user_id, int) else None


def _external(endpoint, **values):
    base = current_app.config["APP_BASE_URL"]
    return base + url_for(endpoint, **values) if base else url_for(endpoint, _external=True, **values)


def in_season(today):
    return today.month == 12 and today.day >= current_app.config["REVIEW_EMAIL_DAY"]


def send_review(user, year):
    """Envoie le bilan de `year` à `user` : None s'il n'a pas voyagé cette année-là, sinon le succès de l'envoi."""
    # Tâche de nuit ou commande : pas de requête en cours, les adresses sont construites sur APP_BASE_URL.
    with current_app.test_request_context("/", base_url=current_app.config["APP_BASE_URL"] or "http://localhost"):
        return _send_review(user, year)


def _send_review(user, year):
    from .trips.queries import list_trips
    from .trips.routes import add_absences
    from .trips.stats import year_review

    trips = list_trips(user)
    with force_locale(user.locale):
        review = year_review(trips, year)
        if review is None:
            return None
        add_absences(review, user, trips)
        site = current_app.config["SITE_NAME"]
        image = review_image.render(review, site, current_app.config["APP_BASE_URL"])
        unsubscribe = _external("main.review_emails_unsubscribe", token=unsubscribe_token(user))
        subject = _("Votre année %(year)s en voyages", year=year)
        body = render_template("trips/email/review.txt", review=review, site=site,
                               laps=format_decimal(review["earth_laps"], format="#,##0.#"),
                               distance=format_distance(review["distance_km"]), co2=format_co2(review["co2_kg"]),
                               url=_external("trips.review", year=year), unsubscribe=unsubscribe,
                               settings=_external("auth.profile") + "#emails")
    return send_email(user.email, subject, body,
                      headers={"List-Unsubscribe": f"<{unsubscribe}>",
                               "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"},
                      attachments=[(f"voyage-voyage-{year}.png", image, "image/png")])


def send_year_reviews(today=None):
    """Envoie les bilans en attente ; renvoie le nombre d'e-mails envoyés (None hors période ou sans SMTP)."""
    today = today or utils.today()
    if not in_season(today) or not mail_enabled():
        return None
    year = today.year
    users = db.session.execute(db.select(User).filter(
        User.is_blocked.is_(False), User.review_emails.is_(True),
        db.or_(User.review_email_year.is_(None), User.review_email_year < year),
    ).order_by(User.id).limit(BATCH)).scalars().all()
    sent = 0
    for user in users:
        result = send_review(user, year)
        if result is False:
            continue  # échec SMTP : nouvel essai la nuit suivante
        sent += bool(result)
        # Noté aussi sans voyage cette année : le compte n'est plus relu les nuits suivantes.
        user.review_email_year = year
        db.session.commit()
    return sent
