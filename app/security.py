"""En-têtes de sécurité HTTP (CSP avec nonce, anti-clickjacking, HSTS…)."""
import secrets

from flask import g, request

# Origines externes autorisées : CDN des bibliothèques, Google Fonts et mesure d'audience (Matomo).
ANALYTICS_ORIGIN = "https://stats.mousqueton.io"
SCRIPT_SOURCES = ("https://cdn.jsdelivr.net", ANALYTICS_ORIGIN)
STYLE_SOURCES = ("https://cdn.jsdelivr.net", "https://cdnjs.cloudflare.com",
                 "https://fonts.googleapis.com")
FONT_SOURCES = ("https://cdnjs.cloudflare.com", "https://fonts.gstatic.com")


def csp_nonce():
    """Nonce de la requête, à placer sur chaque <script> en ligne."""
    if "csp_nonce" not in g:
        g.csp_nonce = secrets.token_urlsafe(16)
    return g.csp_nonce


def content_security_policy(nonce):
    # Les attributs style="" (couleurs des modes) et Leaflet imposent 'unsafe-inline' pour les styles.
    # Les tuiles de carte viennent d'un fournisseur configurable : img-src accepte tout HTTPS.
    directives = {
        "default-src": ["'self'"],
        "script-src": ["'self'", f"'nonce-{nonce}'", *SCRIPT_SOURCES],
        "style-src": ["'self'", "'unsafe-inline'", *STYLE_SOURCES],
        "font-src": ["'self'", *FONT_SOURCES],
        "img-src": ["'self'", "data:", "https:"],
        "connect-src": ["'self'", ANALYTICS_ORIGIN],
        "object-src": ["'none'"],
        "base-uri": ["'self'"],
        "form-action": ["'self'"],
        "frame-ancestors": ["'none'"],
    }
    return "; ".join(f"{name} {' '.join(values)}" for name, values in directives.items())


def init_app(app):
    app.jinja_env.globals["csp_nonce"] = csp_nonce

    @app.before_request
    def new_nonce():
        # g peut survivre à la requête si un contexte d'application englobant est actif.
        g.pop("csp_nonce", None)

    @app.after_request
    def set_security_headers(response):
        headers = response.headers
        headers.setdefault("Content-Security-Policy", content_security_policy(csp_nonce()))
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        # N'envoie que l'origine aux sites tiers (tuiles, CDN) : le jeton des liens de partage ne fuit pas.
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        max_age = app.config.get("HSTS_MAX_AGE", 0)
        if max_age and request.is_secure:
            headers.setdefault("Strict-Transport-Security", f"max-age={max_age}")
        return response
