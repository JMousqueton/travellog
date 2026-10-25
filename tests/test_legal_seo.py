import json
import re

import pytest

from app.models import Setting

from .conftest import make_user


@pytest.fixture
def legal(app):
    app.config.update(LEGAL_PUBLISHER_NAME="Julien Mousqueton", LEGAL_HOST_NAME="OVH SAS (OVHcloud VPS)",
                      LEGAL_HOST_ADDRESS="2 rue Kellermann, 59100 Roubaix, France", LEGAL_HOST_PHONE="+33 9 72 10 10 07",
                      LEGAL_DATA_CITY="Gravelines", LEGAL_DATA_COUNTRY="FR", APP_BASE_URL="https://travellog.example")
    return app


# --- Pages légales --------------------------------------------------------------------------

def test_legal_notice(client, legal):
    html = client.get("/legal").text
    for text in ("Mentions légales", "Julien Mousqueton", "directeur de la publication", "OVH SAS (OVHcloud VPS)",
                 "2 rue Kellermann", "Gravelines, France", "licence MIT", "OpenStreetMap"):
        assert text in html, text
    assert "adresse de contact bientôt disponible" in html  # LEGAL_CONTACT_EMAIL vide


def test_contact_email_shown_when_configured(client, legal):
    legal.config["LEGAL_CONTACT_EMAIL"] = "privacy@example.org"
    assert 'href="mailto:privacy@example.org"' in client.get("/privacy").text


def test_missing_contact_flagged_to_admins_only(client, db, legal):
    assert "LEGAL_CONTACT_EMAIL" not in client.get("/legal").text
    admin = make_user("root@example.com")
    admin.is_admin = True
    db.session.commit()
    client.post("/auth/login", data={"email": "root@example.com", "password": "password123"})
    assert "LEGAL_CONTACT_EMAIL" in client.get("/legal").text


def test_privacy_policy_is_specific(client, legal):
    legal.config.update(BACKUP_KEEP=14, LEGAL_LOG_RETENTION_DAYS=52)
    html = client.get("/privacy").text
    for text in ("Politique de confidentialité", "tile.openstreetmap.org", "Google Fonts", "Nominatim",
                 "14 jours", "52 jours", "remember_token", "CNIL", "Supprimer mon compte", "Gravelines, France"):
        assert text in html, text
    assert "OSRM" not in html  # pas de calcul d'itinéraire configuré


@pytest.mark.parametrize("lang,title,country", [("en", "Legal notice", "Gravelines, France"),
                                               ("de", "Impressum", "Gravelines, Frankreich")])
def test_legal_pages_are_translated(client, legal, lang, title, country):
    html = client.get(f"/legal?lang={lang}").text
    assert title in html and country in html


def test_footer_links_to_legal_pages(client):
    html = client.get("/").text
    assert 'href="/legal"' in html and 'href="/privacy"' in html


# --- Référencement --------------------------------------------------------------------------

def test_landing_meta_tags(client, legal):
    html = client.get("/").text
    assert re.search(r'<meta name="description" content="[^"]{80,}">', html)
    assert '<link rel="canonical" href="https://travellog.example/">' in html
    for code in ("fr", "en", "es", "de", "it"):
        assert f'<link rel="alternate" hreflang="{code}" href="https://travellog.example/?lang={code}">' in html
    assert '<link rel="alternate" hreflang="x-default" href="https://travellog.example/">' in html
    assert '<meta property="og:image" content="https://travellog.example/static/img/og-image.png">' in html
    assert '<meta name="twitter:card" content="summary_large_image">' in html
    data = json.loads(re.search(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S).group(1))
    assert data["@type"] == "WebApplication" and data["isAccessibleForFree"] is True


def test_lang_parameter_gives_one_url_per_language(client, legal):
    html = client.get("/?lang=de").text
    assert '<html lang="de"' in html
    assert '<link rel="canonical" href="https://travellog.example/?lang=de">' in html
    assert '<meta property="og:locale" content="de_DE">' in html
    assert client.get("/?lang=xx").status_code == 200  # langue inconnue : ignorée


def test_private_pages_are_noindex(auth_client, client, user, db):
    from app.models import ShareLink

    link = ShareLink(user_id=user.id)
    db.session.add(link)
    db.session.commit()
    for path in ("/", "/trips", "/stats", "/api/trips"):
        response = auth_client.get(path)
        assert response.headers.get("X-Robots-Tag") == "noindex", path
        assert 'rel="canonical"' not in response.text, path
    assert client.get(f"/s/{link.token}").headers.get("X-Robots-Tag") == "noindex"


def test_public_pages_are_indexable(client):
    for path in ("/", "/legal", "/privacy", "/auth/register"):
        assert "X-Robots-Tag" not in client.get(path).headers, path
    assert client.get("/auth/login").headers.get("X-Robots-Tag") == "noindex"


def test_register_noindex_when_closed(client, db):
    Setting.set("registration_open", "0")
    db.session.commit()
    assert client.get("/auth/register", follow_redirects=True).headers.get("X-Robots-Tag") == "noindex"
    assert "/auth/register" not in client.get("/sitemap.xml").text


def test_robots_txt(client, legal):
    text = client.get("/robots.txt").text
    assert "Disallow: /\n" in text and "Allow: /$" in text and "Allow: /privacy" in text
    assert "Sitemap: https://travellog.example/sitemap.xml" in text


def test_sitemap(client, legal):
    response = client.get("/sitemap.xml")
    assert response.mimetype == "application/xml"
    xml = response.text
    assert "<loc>https://travellog.example/</loc>" in xml and "<loc>https://travellog.example/legal</loc>" in xml
    assert 'hreflang="it" href="https://travellog.example/privacy?lang=it"' in xml
    assert "/trips" not in xml and "/s/" not in xml


def test_webmanifest_and_images(client):
    manifest = client.get("/site.webmanifest")
    assert manifest.mimetype == "application/manifest+json"
    data = manifest.get_json()
    assert data["name"] == "Carnet de voyages" and {i["sizes"] for i in data["icons"]} >= {"192x192", "512x512"}
    for name in ("og-image.png", "icon-192.png", "icon-512.png", "apple-touch-icon.png"):
        assert client.get(f"/static/img/{name}").status_code == 200
