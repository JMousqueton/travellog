"""Fichiers statiques versionnés : url_for('static') ajoute ?v=<empreinte du contenu>.

nginx met en cache un an les URL versionnées (deploy/nginx) : une modification du fichier change
l'empreinte, donc l'URL, et le navigateur télécharge la nouvelle version.
"""
import hashlib
import os

from flask import current_app, url_for

_versions = {}


def file_version(filename):
    """Empreinte courte du fichier, recalculée seulement s'il a changé (date ou taille)."""
    path = os.path.join(current_app.static_folder, filename)
    try:
        stat = os.stat(path)
    except OSError:
        return None
    key = (path, stat.st_mtime_ns, stat.st_size)
    if key not in _versions:
        with open(path, "rb") as fh:
            _versions[key] = hashlib.sha256(fh.read()).hexdigest()[:10]
    return _versions[key]


def js_import_map():
    """Import map des modules JS : les `import "./ui.js"` chargent aussi la version courante."""
    folder = os.path.join(current_app.static_folder, "js")
    imports = {}
    for name in sorted(os.listdir(folder)):
        if name.endswith(".js"):
            versioned = url_for("static", filename=f"js/{name}")
            imports[versioned.split("?")[0]] = versioned
    return {"imports": imports}


def init_app(app):
    app.jinja_env.globals["js_import_map"] = js_import_map

    @app.url_defaults
    def add_static_version(endpoint, values):
        if endpoint == "static" and "v" not in values:
            version = file_version(values.get("filename", ""))
            if version:
                values["v"] = version
