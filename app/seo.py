"""Référencement : URL canonique et variantes de langue (hreflang), robots.txt, sitemap.xml, manifeste,
et en-tête X-Robots-Tag « noindex » sur tout ce qui n'est pas une page publique.

Chaque langue a sa propre adresse (?lang=en…), indexable séparément ; sans paramètre, la langue est
détectée (profil, cookie, navigateur) et l'adresse sert de « x-default ».
"""
from flask import Response, current_app, jsonify, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user

from .i18n import LANGUAGES, current_locale

# Pages publiques indexables. La page d'accueil ne l'est que pour les visiteurs non connectés
# (connecté, la même adresse affiche la carte personnelle).
INDEXABLE = {"trips.index", "auth.register", "main.legal", "main.privacy"}
SITEMAP = ["trips.index", "auth.register", "main.legal", "main.privacy"]
OG_LOCALES = {"fr": "fr_FR", "en": "en_GB", "es": "es_ES", "de": "de_DE", "it": "it_IT"}


def base_url():
    return current_app.config["APP_BASE_URL"] or request.url_root.rstrip("/")


def is_indexable():
    endpoint = request.endpoint
    if endpoint not in INDEXABLE:
        return False
    if endpoint == "trips.index" and current_user.is_authenticated:
        return False
    if endpoint == "auth.register":
        from .models import registration_open

        return registration_open()
    return True


def _page_url(path, lang=None):
    return f"{base_url()}{path}" + (f"?lang={lang}" if lang else "")


def seo_context():
    lang = request.args.get("lang")
    lang = lang if lang in LANGUAGES else None
    path = request.path
    return {
        "indexable": is_indexable(),
        "canonical": _page_url(path, lang),
        "alternates": [(code, _page_url(path, code)) for code in LANGUAGES] + [("x-default", _page_url(path))],
        "og_locale": OG_LOCALES.get(current_locale(), "fr_FR"),
        "og_locale_alternates": [OG_LOCALES[c] for c in LANGUAGES if c != current_locale() and c in OG_LOCALES],
        "image": base_url() + url_for("static", filename="img/og-image.png"),
        "base_url": base_url(),
    }


def init_app(app):
    @app.context_processor
    def inject_seo():
        return {"seo": seo_context()}

    @app.after_request
    def robots_header(response):
        # Cartes, liens de partage, fiches, API, photos, liens d'inscription… : jamais dans les moteurs.
        if request.endpoint not in (None, "static") and not is_indexable():
            response.headers.setdefault("X-Robots-Tag", "noindex")
        return response

    @app.route("/robots.txt")
    def robots_txt():
        lines = [
            "User-agent: *",
            "Allow: /$",
            "Allow: /auth/register",
            "Allow: /legal",
            "Allow: /privacy",
            "Allow: /static/",
            # Le reste est privé ou sans intérêt pour un moteur (liens de partage, API, photos…).
            "Disallow: /",
            "",
            f"Sitemap: {base_url()}{url_for('sitemap_xml')}",
        ]
        return Response("\n".join(lines) + "\n", mimetype="text/plain")

    @app.route("/sitemap.xml")
    def sitemap_xml():
        from .models import registration_open

        endpoints = [e for e in SITEMAP if e != "auth.register" or registration_open()]
        pages = []
        for endpoint in endpoints:
            path = url_for(endpoint)
            pages.append({
                "loc": _page_url(path),
                "alternates": [(code, _page_url(path, code)) for code in LANGUAGES] + [("x-default", _page_url(path))],
                "priority": "1.0" if endpoint == "trips.index" else "0.5",
            })
        return Response(render_template("seo/sitemap.xml", pages=pages, updated=current_app.config["LEGAL_UPDATED"]),
                        mimetype="application/xml")

    @app.route("/site.webmanifest")
    def webmanifest():
        response = jsonify({
            "name": _("Carnet de voyages"),
            "short_name": _("Carnet de voyages"),
            "description": _("Tous vos voyages, sur une seule carte."),
            "lang": current_locale(),
            "start_url": "/",
            "display": "standalone",
            "background_color": "#f6f7fb",
            "theme_color": "#4f46e5",
            "icons": [
                {"src": url_for("static", filename="img/icon-192.png"), "sizes": "192x192", "type": "image/png"},
                {"src": url_for("static", filename="img/icon-512.png"), "sizes": "512x512", "type": "image/png"},
                {"src": url_for("static", filename="img/favicon.svg"), "sizes": "any", "type": "image/svg+xml"},
            ],
        })
        response.mimetype = "application/manifest+json"
        return response
