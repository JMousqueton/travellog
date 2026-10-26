import os

from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, ".env"))


# Valeurs de SECRET_KEY refusées en production (valeurs par défaut connues).
INSECURE_SECRET_KEYS = {"", "dev-insecure-change-me", "change-me"}


def _bool(name, default="0"):
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or "sqlite:///" + os.path.join(
        basedir, "instance", "travel.db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_HTTPONLY = True

    # Adresse publique de l'application (ex. https://voyages.example.org), utilisée pour les liens
    # envoyés par e-mail. Sans elle, l'URL est déduite de l'en-tête Host de la requête.
    APP_BASE_URL = os.environ.get("APP_BASE_URL", "").rstrip("/")
    # Nombre de proxys inverses de confiance devant l'application (X-Forwarded-For/Proto/Host).
    PROXY_FIX_COUNT = int(os.environ.get("PROXY_FIX_COUNT", "0"))

    # Limitation de débit (Flask-Limiter). memory:// est propre à chaque processus :
    # avec plusieurs workers, utilisez par exemple redis://localhost:6379.
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_HEADERS_ENABLED = True
    LOGIN_RATE_LIMIT = os.environ.get("LOGIN_RATE_LIMIT", "5 per minute;30 per hour")
    REGISTER_RATE_LIMIT = os.environ.get("REGISTER_RATE_LIMIT", "10 per hour")
    PASSWORD_RESET_RATE_LIMIT = os.environ.get("PASSWORD_RESET_RATE_LIMIT", "5 per hour")

    # En-têtes de sécurité. HSTS n'est envoyé que sur HTTPS ; 0 le désactive.
    HSTS_MAX_AGE = int(os.environ.get("HSTS_MAX_AGE", "0"))

    # Réinitialisation du mot de passe par e-mail (SMTP). Sans MAIL_SERVER, la fonction est
    # désactivée, sauf en développement où le lien est écrit dans les logs.
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_USE_TLS = _bool("MAIL_USE_TLS", "1")
    MAIL_USE_SSL = _bool("MAIL_USE_SSL")
    MAIL_FROM = os.environ.get("MAIL_FROM", "")
    MAIL_TIMEOUT = float(os.environ.get("MAIL_TIMEOUT", "10"))
    PASSWORD_RESET_MAX_AGE = int(os.environ.get("PASSWORD_RESET_MAX_AGE", "3600"))
    # Inscription par lien magique envoyé par e-mail (15 minutes par défaut).
    SIGNUP_LINK_MAX_AGE = int(os.environ.get("SIGNUP_LINK_MAX_AGE", "900"))

    # Journalisation et suivi des erreurs (Sentry, facultatif : pip install "sentry-sdk[flask]").
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
    SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
    SENTRY_TRACES_SAMPLE_RATE = float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0"))

    # Photos (dossier par défaut : instance/uploads) et taille maximale des requêtes.
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "")
    IMPORT_FOLDER = os.environ.get("IMPORT_FOLDER", "")  # aperçus d'import en attente (défaut : instance/imports)
    MAX_PHOTO_BYTES = int(os.environ.get("MAX_PHOTO_MB", "15")) * 1024 * 1024
    MAX_PHOTOS_PER_ITEM = int(os.environ.get("MAX_PHOTOS_PER_ITEM", "30"))
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_UPLOAD_MB", "64")) * 1024 * 1024
    MAX_IMPORT_BYTES = 5 * 1024 * 1024
    MAX_IMPORT_ROWS = 5000
    # Sauvegarde complète d'un compte (.zip avec photos) : limitée par MAX_UPLOAD_MB à l'envoi.
    MAX_ARCHIVE_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
    MAX_ARCHIVE_FILES = 20000

    # Sauvegardes (flask backup create) : dossier (vide : instance/backups) et nombre d'archives conservées.
    BACKUP_DIR = os.environ.get("BACKUP_DIR", "")
    BACKUP_KEEP = int(os.environ.get("BACKUP_KEEP", "14"))

    # Mentions légales et politique de confidentialité (valeurs propres à chaque installation, dans .env).
    LEGAL_PUBLISHER_NAME = os.environ.get("LEGAL_PUBLISHER_NAME", "")
    LEGAL_CONTACT_EMAIL = os.environ.get("LEGAL_CONTACT_EMAIL", "")
    LEGAL_HOST_NAME = os.environ.get("LEGAL_HOST_NAME", "")
    LEGAL_HOST_ADDRESS = os.environ.get("LEGAL_HOST_ADDRESS", "")
    LEGAL_HOST_PHONE = os.environ.get("LEGAL_HOST_PHONE", "")
    # Lieu de stockage des données : ville et code pays ISO (le nom du pays est traduit sur la page).
    LEGAL_DATA_CITY = os.environ.get("LEGAL_DATA_CITY", "")
    LEGAL_DATA_COUNTRY = os.environ.get("LEGAL_DATA_COUNTRY", "")
    LEGAL_LOG_RETENTION_DAYS = int(os.environ.get("LEGAL_LOG_RETENTION_DAYS", "52"))
    LEGAL_UPDATED = os.environ.get("LEGAL_UPDATED", "2026-10-25")
    SOURCE_URL = os.environ.get("SOURCE_URL", "https://github.com/JMousqueton/travellog")

    BABEL_DEFAULT_LOCALE = "fr"
    BABEL_DEFAULT_TIMEZONE = "UTC"
    LANG_COOKIE_NAME = "lang"
    LANG_COOKIE_MAX_AGE = 365 * 24 * 3600

    NOMINATIM_URL = os.environ.get("NOMINATIM_URL", "https://nominatim.openstreetmap.org/search")
    NOMINATIM_USER_AGENT = os.environ.get(
        "NOMINATIM_USER_AGENT", "TravelMap/1.0 (self-hosted; set NOMINATIM_USER_AGENT)"
    )
    NOMINATIM_EMAIL = os.environ.get("NOMINATIM_EMAIL") or None
    NOMINATIM_MIN_INTERVAL = float(os.environ.get("NOMINATIM_MIN_INTERVAL", "1.0"))
    NOMINATIM_TIMEOUT = float(os.environ.get("NOMINATIM_TIMEOUT", "8"))
    # Fichier verrou partagé par tous les workers d'une même machine pour respecter
    # NOMINATIM_MIN_INTERVAL. Vide : instance/nominatim.lock. "none" : verrou propre au processus.
    NOMINATIM_LOCK_FILE = os.environ.get("NOMINATIM_LOCK_FILE", "")
    # Calcul d'itinéraire OSRM (facultatif). Vide : distance estimée (vol d'oiseau × facteur par mode).
    # Le serveur de démonstration https://router.project-osrm.org ne calcule que les trajets en voiture,
    # et sa politique d'usage exclut un usage intensif : préférez une instance dédiée.
    ROUTING_URL = os.environ.get("ROUTING_URL", "").rstrip("/")
    # mode de transport -> profil OSRM
    ROUTING_PROFILES = os.environ.get("ROUTING_PROFILES", "car:driving,bus:driving")
    ROUTING_TIMEOUT = float(os.environ.get("ROUTING_TIMEOUT", "6"))
    GEOCODE_CACHE_DAYS = int(os.environ.get("GEOCODE_CACHE_DAYS", "30"))
    # Itinéraire d'un vol d'après son numéro (adsbdb) ; vide pour désactiver.
    FLIGHT_LOOKUP_URL = os.environ.get("FLIGHT_LOOKUP_URL", "https://api.adsbdb.com/v0/callsign/")
    FLIGHT_LOOKUP_TIMEOUT = float(os.environ.get("FLIGHT_LOOKUP_TIMEOUT", "8"))

    # Fond de carte. Sans URL sombre dédiée, le mode sombre applique un filtre CSS aux tuiles claires.
    MAP_TILE_URL = os.environ.get("MAP_TILE_URL", "https://tile.openstreetmap.org/{z}/{x}/{y}.png")
    MAP_TILE_URL_DARK = os.environ.get("MAP_TILE_URL_DARK", "")
    MAP_TILE_SUBDOMAINS = os.environ.get("MAP_TILE_SUBDOMAINS", "abc")
    MAP_TILE_ATTRIBUTION = os.environ.get("MAP_TILE_ATTRIBUTION", "")
    MAP_TILE_MAX_ZOOM = int(os.environ.get("MAP_TILE_MAX_ZOOM", "19"))

    # Logos des compagnies et opérateurs (logo.dev, clé publiable pk_…) ; sans clé, pas de logo.
    LOGO_DEV_TOKEN = os.environ.get("LOGO_DEV_TOKEN", "")


class DevelopmentConfig(Config):
    DEBUG = True


class TestingConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    LOGO_DEV_TOKEN = ""
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    WTF_CSRF_ENABLED = False
    NOMINATIM_MIN_INTERVAL = 0.0
    NOMINATIM_LOCK_FILE = "none"
    ROUTING_URL = ""
    FLIGHT_LOOKUP_URL = ""  # pas d'appel réseau en test
    # Limiteur actif mais avec des plafonds hors d'atteinte ; les tests de limitation les abaissent.
    RATELIMIT_STORAGE_URI = "memory://"
    LOGIN_RATE_LIMIT = REGISTER_RATE_LIMIT = PASSWORD_RESET_RATE_LIMIT = "10000 per minute"
    MAIL_SERVER = ""
    APP_BASE_URL = ""
    SENTRY_DSN = ""


class ProductionConfig(Config):
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True
    HSTS_MAX_AGE = int(os.environ.get("HSTS_MAX_AGE", "31536000"))


config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
