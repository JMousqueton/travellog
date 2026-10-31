import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from flask import current_app
from flask_login import UserMixin
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import CheckConstraint, Index, UniqueConstraint
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db, login_manager
from .geo import haversine_km
from .transport import TRANSPORT_MODES


def utcnow():
    return datetime.now(timezone.utc)


def as_utc(value):
    """Une date sans fuseau (anciennes données, saisie Python) est considérée en UTC."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    locale = db.Column(db.String(5), nullable=False, default="fr", server_default="fr")
    theme = db.Column(db.String(10), nullable=True)
    is_admin = db.Column(db.Boolean, nullable=False, default=False, server_default="0")
    # Compte bloqué par un administrateur : plus de connexion, ni de pages publiques, ni d'import par e-mail.
    is_blocked = db.Column(db.Boolean, nullable=False, default=False, server_default="0")
    # Domicile : point de départ et de retour pour le calcul des jours d'absence.
    home_name = db.Column(db.String(255), nullable=True)
    home_lat = db.Column(db.Float, nullable=True)
    home_lon = db.Column(db.Float, nullable=True)
    home_country = db.Column(db.String(2), nullable=True)
    # Jeton secret de l'abonnement agenda (.ics) ; NULL si l'abonnement est désactivé.
    calendar_token = db.Column(db.String(64), nullable=True, unique=True)
    # Nom du profil public (/u/<nom>), en minuscules ; NULL si le profil public est désactivé.
    public_name = db.Column(db.String(30), nullable=True)
    # Administrateurs : e-mail à chaque nouveau message d'utilisateur sur un ticket.
    ticket_emails = db.Column(db.Boolean, nullable=False, default=True, server_default="1")
    # Abonnement Premium (Stripe) : copie de l'abonnement, tenue à jour par le webhook (app/billing).
    stripe_customer_id = db.Column(db.String(64), nullable=True, unique=True)
    subscription_status = db.Column(db.String(20), nullable=True)  # active, trialing, past_due, canceled…
    subscription_interval = db.Column(db.String(10), nullable=True)  # month, year
    premium_until = db.Column(db.DateTime(timezone=True), nullable=True)  # fin de la période payée
    cancel_at_period_end = db.Column(db.Boolean, nullable=False, default=False, server_default="0")
    # Premium offert par un administrateur, sans abonnement.
    premium_granted = db.Column(db.Boolean, nullable=False, default=False, server_default="0")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    trips = db.relationship("Trip", back_populates="user", cascade="all, delete-orphan", lazy="dynamic")
    journeys = db.relationship("Journey", cascade="all, delete-orphan", lazy="dynamic")
    share_links = db.relationship("ShareLink", back_populates="user", cascade="all, delete-orphan",
                                  order_by="ShareLink.created_at.desc()")
    tags = db.relationship("Tag", cascade="all, delete-orphan", order_by="Tag.name")
    # Passe par l'ORM pour que les fichiers des photos soient supprimés avec le compte.
    photos = db.relationship("Photo", cascade="all", lazy="dynamic", overlaps="user")
    tickets = db.relationship("Ticket", back_populates="user", cascade="all, delete-orphan", lazy="dynamic")
    import_addresses = db.relationship("ImportAddress", back_populates="user", cascade="all, delete-orphan",
                                       order_by="ImportAddress.email")

    __table_args__ = (
        CheckConstraint("theme IS NULL OR theme IN ('light', 'dark')", name="theme_valid"),
        db.Index("ix_users_public_name", "public_name", unique=True),
    )

    # past_due : paiement refusé, Stripe réessaie pendant quelques jours ; l'accès est maintenu entre-temps.
    PREMIUM_STATUSES = ("active", "trialing", "past_due")

    @property
    def has_subscription(self):
        """Abonnement Stripe en cours (payé, ou en attente d'un nouvel essai de paiement)."""
        return (self.subscription_status in self.PREMIUM_STATUSES and self.premium_until is not None
                and as_utc(self.premium_until) > utcnow())

    @property
    def is_premium(self):
        return self.premium_granted or self.has_subscription

    @property
    def has_premium_access(self):
        """Fonctions Premium accessibles : toujours quand Stripe n'est pas configuré (rien n'est réservé)."""
        return not current_app.config.get("STRIPE_SECRET_KEY") or self.is_premium

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def password_fingerprint(self):
        """Empreinte du hash : change avec le mot de passe, ce qui invalide sessions et liens de réinitialisation."""
        return hashlib.sha256(self.password_hash.encode()).hexdigest()[:16]

    def get_id(self):
        return f"{self.id}.{self.password_fingerprint}"

    def password_reset_token(self):
        return _reset_serializer().dumps({"id": self.id, "fp": self.password_fingerprint})

    @staticmethod
    def from_password_reset_token(token):
        """Utilisateur du jeton, ou None s'il est invalide, expiré ou déjà utilisé."""
        try:
            data = _reset_serializer().loads(token, max_age=current_app.config["PASSWORD_RESET_MAX_AGE"])
        except BadSignature:
            return None
        user = db.session.get(User, data.get("id")) if isinstance(data, dict) else None
        if user is None or not hmac.compare_digest(str(data.get("fp")), user.password_fingerprint):
            return None
        return user

    @property
    def has_home(self):
        return self.home_lat is not None and self.home_lon is not None

    def __repr__(self):
        return f"<User {self.email}>"


def _reset_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="password-reset")


def _signup_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="signup")


def signup_token(email, locale):
    """Lien magique d'inscription : l'adresse (et la langue) signées, valables SIGNUP_LINK_MAX_AGE secondes."""
    return _signup_serializer().dumps({"email": email, "locale": locale})


def read_signup_token(token):
    """{"email", "locale"} si le jeton est valide et récent, sinon None. Il ne sert qu'une fois :
    une fois le compte créé, l'adresse existe et le lien est refusé."""
    try:
        data = _signup_serializer().loads(token, max_age=current_app.config["SIGNUP_LINK_MAX_AGE"])
    except BadSignature:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("email"), str):
        return None
    return data


@login_manager.user_loader
def load_user(session_id):
    """Les sessions ouvertes avant un changement de mot de passe, ou d'un compte bloqué, ne sont plus acceptées."""
    user_id, _, fingerprint = str(session_id).partition(".")
    if not user_id.isdigit():
        return None
    user = db.session.get(User, int(user_id))
    if user is None or user.is_blocked or not hmac.compare_digest(fingerprint, user.password_fingerprint):
        return None
    return user


_MODES_SQL = ", ".join(f"'{mode}'" for mode in TRANSPORT_MODES)


class Journey(db.Model):
    """Voyage composé de plusieurs trajets (par exemple Paris → Reykjavik → Amsterdam → Paris)."""

    __tablename__ = "journeys"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    legs = db.relationship("Trip", back_populates="journey", order_by=lambda: [Trip.depart_date, Trip.id])
    # Pas de delete-orphan : une photo change de parent (trajet ↔ voyage) lors des regroupements.
    photos = db.relationship("Photo", back_populates="journey", cascade="all", order_by="Photo.created_at")

    @property
    def route_label(self):
        """Étapes successives, sans répéter une ville d'arrivée qui sert de départ suivant."""
        stops = []
        for leg in self.legs:
            if not stops or stops[-1] != leg.origin_name:
                stops.append(leg.origin_name)
            stops.append(leg.dest_name)
        return " → ".join(stops)

    @property
    def display_name(self):
        return self.name or self.route_label

    @property
    def start_date(self):
        return self.legs[0].depart_date if self.legs else None

    @property
    def end_date(self):
        return max((leg.return_date or leg.depart_date for leg in self.legs), default=None)

    @property
    def total_distance_km(self):
        return sum(leg.total_distance_km for leg in self.legs)

    @property
    def co2_kg(self):
        return sum(leg.co2_kg for leg in self.legs)

    @property
    def status(self):
        from .utils import trip_status

        return trip_status(self.start_date, self.end_date) if self.legs else "past"

    @property
    def countries(self):
        """Pays traversés, dans l'ordre de l'itinéraire."""
        return list(dict.fromkeys(code for leg in self.legs for code in leg.countries))

    def __repr__(self):
        return f"<Journey {self.display_name}>"


trip_tags = db.Table(
    "trip_tags",
    db.Column("trip_id", db.Integer, db.ForeignKey("trips.id", ondelete="CASCADE"), primary_key=True),
    db.Column("tag_id", db.Integer, db.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True, index=True),
)


class Tag(db.Model):
    """Étiquette libre d'un utilisateur (vacances, travail, famille…)."""

    __tablename__ = "tags"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(40), nullable=False)

    trips = db.relationship("Trip", secondary=trip_tags, back_populates="tags")

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_tags_user_name"),)

    def __repr__(self):
        return f"<Tag {self.name}>"


class Trip(db.Model):
    __tablename__ = "trips"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    origin_name = db.Column(db.String(255), nullable=False)
    origin_lat = db.Column(db.Float, nullable=False)
    origin_lon = db.Column(db.Float, nullable=False)
    dest_name = db.Column(db.String(255), nullable=False)
    dest_lat = db.Column(db.Float, nullable=False)
    dest_lon = db.Column(db.Float, nullable=False)
    # Codes ISO 3166-1 alpha-2 (Nominatim, ou recherche hors ligne pour les imports et l'existant).
    origin_country = db.Column(db.String(2), nullable=True)
    dest_country = db.Column(db.String(2), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    # Vols : compagnie, numéro (« AF1148 ») et appareil ; trains : opérateur seulement (SERVICE_FIELDS).
    carrier = db.Column(db.String(80), nullable=True)
    service_number = db.Column(db.String(40), nullable=True)
    vehicle = db.Column(db.String(80), nullable=True)
    # Distance d'itinéraire (OSRM) d'un trajet simple, si un service de calcul est configuré.
    route_distance_km = db.Column(db.Float, nullable=True)
    depart_date = db.Column(db.Date, nullable=False)
    transport_mode = db.Column(db.String(10), nullable=False)
    is_round_trip = db.Column(db.Boolean, nullable=False, default=False, server_default="0")
    return_date = db.Column(db.Date, nullable=True)
    journey_id = db.Column(db.Integer, db.ForeignKey("journeys.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    user = db.relationship("User", back_populates="trips")
    journey = db.relationship("Journey", back_populates="legs")
    photos = db.relationship("Photo", back_populates="trip", cascade="all", order_by="Photo.created_at")
    tags = db.relationship("Tag", secondary=trip_tags, back_populates="trips", order_by="Tag.name")

    __table_args__ = (
        CheckConstraint(
            "(NOT is_round_trip AND return_date IS NULL) OR "
            "(is_round_trip AND return_date IS NOT NULL AND return_date >= depart_date)",
            name="return_date_consistency",
        ),
        CheckConstraint(f"transport_mode IN ({_MODES_SQL})", name="transport_mode_valid"),
        CheckConstraint(
            "origin_lat BETWEEN -90 AND 90 AND dest_lat BETWEEN -90 AND 90", name="lat_range"
        ),
        CheckConstraint(
            "origin_lon BETWEEN -180 AND 180 AND dest_lon BETWEEN -180 AND 180", name="lon_range"
        ),
        Index("ix_trips_user_depart", "user_id", "depart_date"),
        Index("ix_trips_user_mode", "user_id", "transport_mode"),
    )

    @property
    def straight_km(self):
        """Distance à vol d'oiseau d'un trajet simple."""
        return haversine_km(self.origin_lat, self.origin_lon, self.dest_lat, self.dest_lon)

    @property
    def distance_km(self):
        """Distance d'un trajet simple : itinéraire calculé si disponible, sinon estimation par mode."""
        if self.route_distance_km is not None:
            return self.route_distance_km
        from .transport import DETOUR_FACTORS

        return self.straight_km * DETOUR_FACTORS.get(self.transport_mode, 1.0)

    @property
    def distance_source(self):
        """« route » (itinéraire calculé), « estimate » (vol d'oiseau × facteur) ou « direct » (avion)."""
        from .transport import DETOUR_FACTORS

        if self.route_distance_km is not None:
            return "route"
        return "direct" if DETOUR_FACTORS.get(self.transport_mode, 1.0) == 1.0 else "estimate"

    @property
    def total_distance_km(self):
        return self.distance_km * (2 if self.is_round_trip else 1)

    @property
    def countries(self):
        return list(dict.fromkeys(c for c in (self.origin_country, self.dest_country) if c))

    @property
    def service_numbers(self):
        """(aller, retour) : un aller-retour enregistre « AF1148 / AF1549 » ; retour None sans second numéro."""
        number = self.service_number or ""
        outbound, sep, back = number.partition(" / ")
        if self.is_round_trip and sep and outbound.strip() and back.strip() and " / " not in back:
            return outbound.strip(), back.strip()
        return number or None, None

    @property
    def end_date(self):
        return self.return_date or self.depart_date

    @property
    def status(self):
        from .utils import trip_status

        return trip_status(self.depart_date, self.end_date)

    @property
    def co2_kg(self):
        from .transport import co2_kg

        return co2_kg(self.transport_mode, self.distance_km) * (2 if self.is_round_trip else 1)

    def fill_missing_countries(self):
        """Complète les pays absents par une recherche hors ligne sur les coordonnées."""
        from .countries import country_at

        if not self.origin_country:
            self.origin_country = country_at(self.origin_lat, self.origin_lon)
        if not self.dest_country:
            self.dest_country = country_at(self.dest_lat, self.dest_lon)

    def __repr__(self):
        return f"<Trip {self.origin_name} → {self.dest_name} ({self.transport_mode})>"


class GeocodeCache(db.Model):
    __tablename__ = "geocode_cache"

    id = db.Column(db.Integer, primary_key=True)
    query = db.Column(db.String(255), nullable=False)
    lang = db.Column(db.String(10), nullable=False)  # code de langue, ou "flight" (app/flights.py)
    # Meilleur résultat (NULL si aucun) ; la liste complète des suggestions est dans `results`.
    name = db.Column(db.String(255), nullable=True)
    lat = db.Column(db.Float, nullable=True)
    lon = db.Column(db.Float, nullable=True)
    results = db.Column(db.JSON, nullable=False, default=list)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (UniqueConstraint("query", "lang", name="uq_geocode_cache_query_lang"),)


class Setting(db.Model):
    """Réglages de l'application modifiables par les administrateurs (clé → valeur texte)."""

    __tablename__ = "settings"

    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.String(255), nullable=False)

    DEFAULTS = {"registration_open": "1"}

    @classmethod
    def get(cls, key):
        row = db.session.get(cls, key)
        return row.value if row is not None else cls.DEFAULTS[key]

    @classmethod
    def set(cls, key, value):
        row = db.session.get(cls, key)
        if row is None:
            db.session.add(cls(key=key, value=value))
        else:
            row.value = value


def registration_open():
    return Setting.get("registration_open") == "1"


def _new_token():
    return secrets.token_urlsafe(24)


class ShareLink(db.Model):
    """Lien secret donnant accès en lecture seule à tous les voyages d'un utilisateur."""

    __tablename__ = "share_links"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token = db.Column(db.String(64), nullable=False, unique=True, index=True, default=_new_token)
    label = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_used_at = db.Column(db.DateTime(timezone=True), nullable=True)
    # Les voyages à venir révèlent quand on est absent : masqués par défaut.
    include_upcoming = db.Column(db.Boolean, nullable=False, default=False, server_default="0")
    # Statistiques partagées : la liste des trajets n'est montrée que si le lien le prévoit.
    show_trips = db.Column(db.Boolean, nullable=False, default=False, server_default="0")

    user = db.relationship("User", back_populates="share_links")

    # Intervalle minimal entre deux mises à jour de last_used_at (évite une écriture par requête).
    USAGE_RESOLUTION = timedelta(minutes=5)

    @property
    def is_expired(self):
        return self.expires_at is not None and as_utc(self.expires_at) <= utcnow()

    def mark_used(self):
        now = utcnow()
        if self.last_used_at is None or now - as_utc(self.last_used_at) >= self.USAGE_RESOLUTION:
            self.last_used_at = now
            db.session.commit()

    @classmethod
    def active(cls, token):
        """Lien valide (existant, non expiré, compte non bloqué et Premium) correspondant au jeton, sinon None.

        Sans Premium, les liens restent enregistrés mais ne sont plus servis : ils reviennent avec l'abonnement."""
        link = db.session.execute(db.select(cls).filter_by(token=token)).scalar_one_or_none()
        if link is None or link.is_expired or link.user.is_blocked or not link.user.has_premium_access:
            return None
        return link


class Photo(db.Model):
    """Photo rattachée à un trajet ou à un voyage. Les fichiers sont dans UPLOAD_FOLDER (voir photos.py)."""

    __tablename__ = "photos"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    trip_id = db.Column(db.Integer, db.ForeignKey("trips.id", ondelete="CASCADE"), nullable=True, index=True)
    journey_id = db.Column(db.Integer, db.ForeignKey("journeys.id", ondelete="CASCADE"), nullable=True, index=True)
    # Nom de fichier aléatoire, sans extension : <stored_name>.jpg et <stored_name>.thumb.jpg
    stored_name = db.Column(db.String(64), nullable=False, unique=True)
    original_name = db.Column(db.String(255), nullable=True)
    width = db.Column(db.Integer, nullable=False)
    height = db.Column(db.Integer, nullable=False)
    size = db.Column(db.Integer, nullable=False)
    # Métadonnées relevées à l'envoi (appareil, réglages, date, GPS) : visibles du seul propriétaire,
    # jamais écrites dans le fichier servi. Voir photos.read_exif.
    exif = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    user = db.relationship("User", overlaps="photos")
    trip = db.relationship("Trip", back_populates="photos")
    journey = db.relationship("Journey", back_populates="photos")

    __table_args__ = (
        CheckConstraint("(trip_id IS NULL) <> (journey_id IS NULL)", name="single_owner"),
    )


class Ticket(db.Model):
    """Demande de support d'un utilisateur : un sujet et un échange de messages avec les administrateurs."""

    __tablename__ = "tickets"

    # open : en attente du support ; answered : le support a répondu ; closed : fermé.
    STATUSES = ("open", "answered", "closed")

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    subject = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(10), nullable=False, default="open", server_default="open", index=True)
    # L'utilisateur reçoit les réponses du support par e-mail (réglable pour chaque ticket).
    notify = db.Column(db.Boolean, nullable=False, default=True, server_default="1")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    user = db.relationship("User", back_populates="tickets")
    messages = db.relationship("TicketMessage", back_populates="ticket", cascade="all, delete-orphan",
                               order_by="TicketMessage.created_at, TicketMessage.id")

    __table_args__ = (
        CheckConstraint("status IN ('open', 'answered', 'closed')", name="ticket_status_valid"),
    )

    def add_message(self, author, body, from_staff):
        """Ajoute un message ; le statut suit le dernier à avoir écrit."""
        message = TicketMessage(author_id=author.id, body=body, from_staff=from_staff)
        self.messages.append(message)
        self.status = "answered" if from_staff else "open"
        self.updated_at = utcnow()
        return message


class TicketMessage(db.Model):
    __tablename__ = "ticket_messages"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    # NULL si l'auteur (un administrateur) a supprimé son compte : le message reste dans l'échange.
    author_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    from_staff = db.Column(db.Boolean, nullable=False, default=False, server_default="0")
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    ticket = db.relationship("Ticket", back_populates="messages")
    author = db.relationship("User")


class MailImport(db.Model):
    """E-mail déjà traité par l'import par e-mail (flask mail-import) : il n'est jamais traité deux fois.

    imported : trajets ajoutés, e-mail supprimé de la boîte ; failed : aucun trajet reconnu, ticket ouvert
    (une seule fois), e-mail laissé dans la boîte ; ignored : expéditeur inconnu ou non authentifié.
    """

    __tablename__ = "mail_imports"

    STATUSES = ("imported", "failed", "ignored")

    id = db.Column(db.Integer, primary_key=True)
    # Empreinte SHA-256 du Message-ID (ou de l'e-mail brut s'il n'en a pas).
    message_key = db.Column(db.String(64), nullable=False, unique=True)
    status = db.Column(db.String(10), nullable=False)
    sender = db.Column(db.String(255), nullable=True)
    subject = db.Column(db.String(200), nullable=True)
    reason = db.Column(db.String(255), nullable=True)
    trip_count = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id", ondelete="SET NULL"), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        CheckConstraint("status IN ('imported', 'failed', 'ignored')", name="mail_import_status_valid"),
    )


class ImportAddress(db.Model):
    """Adresse supplémentaire autorisée à envoyer des confirmations à l'import par e-mail. Elle n'est créée
    qu'après confirmation par lien magique, ne permet pas de se connecter, et ne peut être ni l'adresse d'un
    compte ni celle d'un autre utilisateur."""

    __tablename__ = "import_addresses"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    email = db.Column(db.String(255), nullable=False, unique=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    user = db.relationship("User", back_populates="import_addresses")

    @staticmethod
    def taken(email):
        """Vrai si l'adresse est déjà celle d'un compte ou une adresse d'import (de n'importe quel utilisateur)."""
        email = email.strip().lower()
        return (db.session.execute(db.select(User.id).filter(db.func.lower(User.email) == email)).first() is not None
                or is_import_address(email))


def is_import_address(email):
    return db.session.execute(
        db.select(ImportAddress.id).filter_by(email=email.strip().lower())).first() is not None


def _import_address_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="import-address")


def import_address_token(user, email):
    return _import_address_serializer().dumps({"id": user.id, "email": email})


def read_import_address_token(token):
    """{"id", "email"} si le jeton est valide et récent, sinon None."""
    try:
        data = _import_address_serializer().loads(token, max_age=current_app.config["IMPORT_ADDRESS_LINK_MAX_AGE"])
    except BadSignature:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("email"), str) or not isinstance(data.get("id"), int):
        return None
    return data


class JobRun(db.Model):
    """Exécution d'une tâche périodique (flask jobs run, lancée par un timer systemd) : suivie dans
    l'administration (onglet Tâches)."""

    __tablename__ = "job_runs"

    STATUSES = ("running", "ok", "failed", "skipped")

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(40), nullable=False)
    status = db.Column(db.String(10), nullable=False, default="running")
    summary = db.Column(db.String(255), nullable=True)
    error = db.Column(db.Text, nullable=True)
    started_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    finished_at = db.Column(db.DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('running', 'ok', 'failed', 'skipped')", name="job_run_status_valid"),
        db.Index("ix_job_runs_name_started_at", "name", "started_at"),
    )

    @property
    def duration(self):
        if self.finished_at is None:
            return None
        return (as_utc(self.finished_at) - as_utc(self.started_at)).total_seconds()
