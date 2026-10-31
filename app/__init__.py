import logging
import os

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_babel import lazy_gettext as _l

from config import INSECURE_SECRET_KEYS, config_by_name

from . import assets, i18n, pwa, security, seo
from .extensions import babel, csrf, db, limiter, login_manager, migrate
from .mail import mail_enabled


def create_app(config_name=None):
    app = Flask(__name__, instance_relative_config=True)
    config_name = config_name or os.environ.get("FLASK_CONFIG", "development")
    app.config.from_object(config_by_name[config_name])
    app.config["CONFIG_NAME"] = config_name
    if config_name == "production" and (app.config.get("SECRET_KEY") or "") in INSECURE_SECRET_KEYS:
        raise RuntimeError("SECRET_KEY doit être définie avec une valeur secrète en production (voir .env.example).")
    if not app.config["SQLALCHEMY_DATABASE_URI"].startswith("postgresql+psycopg://"):
        name = "TEST_DATABASE_URL" if config_name == "testing" else "DATABASE_URL"
        raise RuntimeError(f"{name} doit pointer vers une base PostgreSQL (voir .env.example).")
    os.makedirs(app.instance_path, exist_ok=True)
    if not app.config["UPLOAD_FOLDER"]:
        app.config["UPLOAD_FOLDER"] = os.path.join(app.instance_path, "uploads")
    if not app.config["IMPORT_FOLDER"]:
        app.config["IMPORT_FOLDER"] = os.path.join(app.instance_path, "imports")
    if not app.config["NOMINATIM_LOCK_FILE"]:
        app.config["NOMINATIM_LOCK_FILE"] = os.path.join(app.instance_path, "nominatim.lock")

    _configure_logging(app)
    if app.config["PROXY_FIX_COUNT"]:
        from werkzeug.middleware.proxy_fix import ProxyFix

        n = app.config["PROXY_FIX_COUNT"]
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=n, x_proto=n, x_host=n)

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    limiter.init_app(app)
    security.init_app(app)
    assets.init_app(app)
    pwa.init_app(app)
    seo.init_app(app)
    babel.init_app(app, locale_selector=i18n.select_locale)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = _l("Connectez-vous pour accéder à cette page.")
    login_manager.login_message_category = "info"

    @login_manager.unauthorized_handler
    def unauthorized():
        if request.path.startswith("/api/"):
            return jsonify(error=_("Authentification requise.")), 401
        flash(_("Connectez-vous pour accéder à cette page."), "info")
        return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))

    app.jinja_env.add_extension("jinja2.ext.do")
    i18n.init_app(app)

    from . import models  # noqa: F401  (enregistre les modèles pour les migrations)
    from . import photos  # noqa: F401  (suppression des fichiers à la validation)
    from .admin import bp as admin_bp
    from .api import bp as api_bp
    from .auth import bp as auth_bp
    from .billing import bp as billing_bp
    from .main import bp as main_bp
    from .share import bp as share_bp
    from .transfer import bp as transfer_bp
    from .support import bp as support_bp
    from .trips import bp as trips_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(trips_bp)
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(share_bp)
    app.register_blueprint(transfer_bp)
    app.register_blueprint(support_bp)
    app.register_blueprint(billing_bp)

    _register_error_handlers(app)

    from .carriers import logo_url

    app.jinja_env.globals["carrier_logo"] = logo_url

    from .billing import billing_enabled, premium_access

    @app.context_processor
    def inject_settings():
        return {"registration_open": models.registration_open, "password_reset_enabled": mail_enabled,
                "billing_enabled": billing_enabled, "premium_access": premium_access,
                "copyright_years": copyright_years()}

    from .cli import register_cli

    register_cli(app)
    return app


COPYRIGHT_START = 2026


def copyright_years():
    """« 2026 », puis « 2026–2027 » à partir de 2027."""
    from .utils import today

    year = today().year
    return f"{COPYRIGHT_START}–{year}" if year > COPYRIGHT_START else str(COPYRIGHT_START)


def _register_error_handlers(app):
    messages = {
        400: (_l("Requête invalide"), _l("La requête envoyée n'a pas pu être traitée.")),
        403: (_l("Accès refusé"), _l("Vous n'avez pas l'autorisation d'accéder à cette page.")),
        404: (_l("Page introuvable"), _l("La page demandée n'existe pas ou a été déplacée.")),
        413: (_l("Fichier trop volumineux"), _l("Le fichier envoyé dépasse la taille autorisée.")),
        429: (_l("Trop de tentatives"), _l("Vous avez effectué trop de demandes. Patientez quelques minutes puis réessayez.")),
        500: (_l("Erreur interne"), _l("Une erreur inattendue s'est produite. Réessayez plus tard.")),
    }

    def handler(error):
        code = getattr(error, "code", 500) or 500
        title, text = messages.get(code, messages[500])
        if request.path.startswith("/api/"):
            return jsonify(error=str(title)), code
        template = "errors/404.html" if code == 404 else "errors/error.html"
        return render_template(template, code=code, title=title, text=text), code

    for code in messages:
        app.register_error_handler(code, handler)


def _configure_logging(app):
    """Format horodaté et niveau LOG_LEVEL ; Sentry si SENTRY_DSN est défini."""
    from flask.logging import default_handler

    default_handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s"))
    app.logger.setLevel(app.config["LOG_LEVEL"])

    if app.config["SENTRY_DSN"]:
        try:
            import sentry_sdk
        except ImportError:
            app.logger.warning("SENTRY_DSN est défini mais sentry-sdk n'est pas installé.")
            return
        sentry_sdk.init(
            dsn=app.config["SENTRY_DSN"],
            environment=app.config["CONFIG_NAME"],
            traces_sample_rate=app.config["SENTRY_TRACES_SAMPLE_RATE"],
            send_default_pii=False,
        )
