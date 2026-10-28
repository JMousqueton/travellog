"""Application installable et consultable hors ligne : service worker (/sw.js) et page hors ligne.

Le service worker est généré ici pour connaître les URL versionnées des fichiers statiques (app/assets.py) :
leur liste change avec leur contenu, donc la version du cache aussi.
"""
import hashlib
import os

from flask import current_app, render_template, url_for

# Jamais mis en cache : authentification, fichiers téléchargés, import, agenda, photos, support.
NETWORK_ONLY = ("/auth/", "/export", "/import", "/calendar/", "/photos/", "/support", "/admin/", "/sw.js")


def static_urls():
    """URL versionnées de tous les fichiers statiques (précachés à l'installation)."""
    root = current_app.static_folder
    urls = []
    for folder, _dirs, files in os.walk(root):
        for name in sorted(files):
            if name.startswith(".") or name in ("LICENSE",) or name.endswith(".map"):
                continue
            relative = os.path.relpath(os.path.join(folder, name), root).replace(os.sep, "/")
            if relative.startswith("vendor/") and not name.endswith((".js", ".css")):
                # Polices et images des bibliothèques : demandées par leur CSS sans ?v= (le dossier porte
                # déjà la version de la bibliothèque).
                urls.append(f"{current_app.static_url_path}/{relative}")
            else:
                urls.append(url_for("static", filename=relative))
    return sorted(urls)


def init_app(app):
    @app.route("/sw.js")
    def service_worker():
        precache = static_urls()
        version = hashlib.sha256("\n".join(precache).encode()).hexdigest()[:12]
        body = render_template("pwa/sw.js", version=version, precache=precache, offline_url=url_for("offline"),
                               network_only=NETWORK_ONLY)
        response = current_app.response_class(body, mimetype="application/javascript")
        response.headers["Cache-Control"] = "no-cache"
        # La CSP d'un service worker régit ses propres fetch() : l'origine seulement.
        response.headers["Content-Security-Policy"] = "default-src 'none'; connect-src 'self'"
        return response

    @app.route("/offline")
    def offline():
        # Page autonome, sans en-tête de compte : elle est gardée en cache pour tous.
        return render_template("pwa/offline.html")
