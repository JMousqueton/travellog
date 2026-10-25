"""Chaque ressource chargée par les pages doit être autorisée par la Content-Security-Policy.

Une bibliothèque ou un service ajouté sans mettre à jour app/security.py serait bloqué par le
navigateur sans aucune erreur côté serveur : ce test le détecte avant la mise en production.
"""
from html.parser import HTMLParser
from urllib.parse import urlsplit

import pytest

from app.models import ShareLink

from .conftest import make_trip


class ResourceParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.resources = []        # (directive, url)
        self.inline_scripts = []   # attributs des <script> sans src

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script":
            if attrs.get("src"):
                self.resources.append(("script-src", attrs["src"]))
            elif attrs.get("type") != "application/json":  # bloc de données, jamais exécuté
                self.inline_scripts.append(attrs)
        elif tag == "link" and attrs.get("rel") == "stylesheet":
            self.resources.append(("style-src", attrs["href"]))
        elif tag == "img" and attrs.get("src"):
            self.resources.append(("img-src", attrs["src"]))


def parse_csp(header):
    directives = {}
    for part in header.split(";"):
        name, *values = part.split()
        directives[name] = values
    return directives


def allowed(url, sources):
    parts = urlsplit(url)
    if not parts.scheme:  # URL relative : même origine
        return "'self'" in sources
    if parts.scheme == "data":
        return "data:" in sources
    return f"{parts.scheme}:" in sources or f"{parts.scheme}://{parts.netloc}" in sources


def check_page(client, path, status=200):
    response = client.get(path)
    assert response.status_code == status, path
    csp = parse_csp(response.headers["Content-Security-Policy"])
    parser = ResourceParser()
    parser.feed(response.text)
    assert parser.resources, path
    for directive, url in parser.resources:
        sources = csp.get(directive, csp["default-src"])
        assert allowed(url, sources), f"{path} : {url} bloqué par {directive} {' '.join(sources)}"
    nonce = next(s for s in csp["script-src"] if s.startswith("'nonce-"))[7:-1]
    for attrs in parser.inline_scripts:
        assert attrs.get("nonce") == nonce, f"{path} : <script> en ligne sans nonce {attrs}"


@pytest.mark.parametrize("path", ["/", "/auth/login", "/auth/register", "/auth/forgot", "/legal", "/privacy"])
def test_public_pages_respect_csp(client, path):
    check_page(client, path)


def test_error_page_respects_csp(client):
    check_page(client, "/page-inexistante", status=404)


def test_private_pages_respect_csp(auth_client, user, db):
    trip = make_trip(user)
    link = ShareLink(user_id=user.id)
    db.session.add(link)
    db.session.commit()
    for path in ("/", "/trips", f"/trips/{trip.id}", "/trips/new", f"/trips/{trip.id}/edit", "/stats",
                 "/review/2025", "/auth/profile", "/share", "/import-export", f"/s/{link.token}",
                 f"/s/{link.token}/review/2025"):
        check_page(auth_client, path)
