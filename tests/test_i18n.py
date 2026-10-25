import os
import re
from datetime import date

import pytest
from babel.messages.extract import DEFAULT_KEYWORDS, extract_from_dir
from babel.messages.frontend import parse_mapping_cfg
from babel.messages.pofile import read_po
from flask_babel import force_locale

from app.i18n import LANGUAGES, format_day, format_distance, js_strings

from .conftest import login, make_trip

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TRANSLATED = [code for code in LANGUAGES if code != "fr"]


def html_lang(response):
    return re.search(r'<html lang="([a-z]+)"', response.text).group(1)


def test_default_language_is_french(client):
    assert html_lang(client.get("/")) == "fr"


def test_accept_language_detection(client):
    response = client.get("/", headers={"Accept-Language": "de-DE,de;q=0.9,en;q=0.8"})
    assert html_lang(response) == "de"
    assert "Alle deine Reisen auf einer einzigen Karte." in response.text


def test_unsupported_accept_language_falls_back_to_french(client):
    assert html_lang(client.get("/", headers={"Accept-Language": "ja"})) == "fr"


def test_language_switch_sets_cookie_and_keeps_context(client):
    response = client.get("/lang/es?next=/auth/login%3Fnext%3D/trips")
    assert response.status_code == 302
    assert response.location == "/auth/login?next=/trips"
    assert "lang=es" in response.headers["Set-Cookie"]
    page = client.get("/auth/login")
    assert html_lang(page) == "es" and "Iniciar sesión" in page.text


def test_cookie_beats_accept_language(client):
    client.get("/lang/it")
    assert html_lang(client.get("/", headers={"Accept-Language": "en"})) == "it"


def test_unknown_language_404(client):
    assert client.get("/lang/xx").status_code == 404


def test_language_switch_rejects_open_redirect(client):
    assert client.get("/lang/en?next=https://evil.example").location == "/"


def test_profile_language_wins_and_is_saved(client, db, user):
    login(client)
    client.set_cookie("lang", "it")
    assert html_lang(client.get("/trips")) == "fr"  # profil (fr) prioritaire sur le cookie
    client.get("/lang/en")
    db.session.refresh(user)
    assert user.locale == "en"
    assert html_lang(client.get("/trips", headers={"Accept-Language": "de"})) == "en"


def test_profile_form_updates_locale_and_theme(client, db, user):
    login(client)
    response = client.post("/auth/profile", data={"locale": "de", "theme": "dark"})
    assert response.status_code == 302
    db.session.refresh(user)
    assert (user.locale, user.theme) == ("de", "dark")
    assert 'data-theme-pref="dark"' in client.get("/auth/profile").text


def test_theme_endpoint(client, db, user):
    login(client)
    assert client.post("/theme", json={"theme": "light"}).status_code == 200
    db.session.refresh(user)
    assert user.theme == "light"
    assert client.post("/theme", json={"theme": "purple"}).status_code == 400


@pytest.mark.parametrize("locale,expected", [
    ("fr", "14 juil. 2025"),
    ("en", "Jul 14, 2025"),
    ("es", "14 jul 2025"),
    ("de", "14.07.2025"),
    ("it", "14 lug 2025"),
])
def test_date_formatting(app, locale, expected):
    with app.test_request_context(), force_locale(locale):
        assert format_day(date(2025, 7, 14)) == expected


@pytest.mark.parametrize("locale,expected", [
    ("fr", "12 345,6 km"),
    ("en", "12,345.6 km"),
    ("de", "12.345,6 km"),
    ("it", "12.345,6 km"),
    ("es", "12.345,6 km"),
])
def test_distance_formatting(app, locale, expected):
    with app.test_request_context(), force_locale(locale):
        value = format_distance(12345.6)
    # Babel utilise des espaces insécables (U+00A0 / U+202F) : on les normalise.
    assert re.sub(r"[  ]", " ", value) == expected


def test_api_dates_follow_profile_language(client, db, user):
    make_trip(user, depart_date=date(2025, 7, 14))
    user.locale = "en"
    db.session.commit()
    login(client)
    trip = client.get("/api/trips").get_json()["trips"][0]
    assert trip["depart_date_fmt"] == "Jul 14, 2025"
    assert trip["mode_label"] == "Train"
    assert client.get("/api/trips").get_json()["count_label"] == "1 trip"


def test_js_strings_are_injected_and_translated(client):
    client.get("/lang/de")
    html = client.get("/").text
    assert 'id="i18n-data"' in html
    assert '"locale": "de"' in html
    assert "Legende" in html and "Flugzeug" in html


def test_js_files_contain_no_hardcoded_french():
    """Les fichiers JS ne doivent contenir que des clés, jamais de texte visible."""
    french = re.compile(r"[\"'`][^\"'`]*(?:voyage|Aucun|Chargement|Supprimer|Modifier|Retour|é|è|à)[^\"'`]*[\"'`]")
    js_dir = os.path.join(ROOT, "app", "static", "js")
    for name in os.listdir(js_dir):
        source = open(os.path.join(js_dir, name), encoding="utf-8").read()
        source = re.sub(r"//.*|/\*.*?\*/", "", source, flags=re.S)  # ignore les commentaires
        assert not french.search(source), f"Texte en dur dans {name}"


def _source_messages():
    """Extrait les chaînes à jour directement depuis le code (comme pybabel extract)."""
    with open(os.path.join(ROOT, "babel.cfg")) as fh:
        method_map, options_map = parse_mapping_cfg(fh)
    keywords = {**DEFAULT_KEYWORDS, "_l": None, "lazy_gettext": None}
    return {msg[2] for msg in extract_from_dir(ROOT, method_map, options_map, keywords=keywords)
            if not msg[0].startswith((".venv", "tests"))}


@pytest.fixture(scope="module")
def source_messages():
    messages = _source_messages()
    assert len(messages) > 100
    return messages


@pytest.mark.parametrize("lang", TRANSLATED)
def test_no_missing_translation(lang, source_messages):
    path = os.path.join(ROOT, "app", "translations", lang, "LC_MESSAGES", "messages.po")
    with open(path, "rb") as fh:
        catalog = read_po(fh, locale=lang)
    missing, untranslated, fuzzy = [], [], []
    for msgid in source_messages:
        key = msgid[0] if isinstance(msgid, tuple) else msgid
        message = catalog.get(key)
        if message is None:
            missing.append(key)
        elif message.fuzzy:
            fuzzy.append(key)
        elif not all(message.string) if isinstance(message.string, tuple) else not message.string:
            untranslated.append(key)
    assert not missing, f"[{lang}] clés absentes du .po (lancez `make translations`) : {missing}"
    assert not untranslated, f"[{lang}] chaînes non traduites : {untranslated}"
    assert not fuzzy, f"[{lang}] chaînes fuzzy à relire : {fuzzy}"


@pytest.mark.parametrize("lang", TRANSLATED)
def test_placeholders_preserved(lang):
    path = os.path.join(ROOT, "app", "translations", lang, "LC_MESSAGES", "messages.po")
    with open(path, "rb") as fh:
        catalog = read_po(fh, locale=lang)
    placeholder = re.compile(r"%\(\w+\)[sd]")
    for message in catalog:
        if not message.id:
            continue
        ids = message.id if isinstance(message.id, tuple) else (message.id,)
        strings = message.string if isinstance(message.string, tuple) else (message.string,)
        expected = set(placeholder.findall(ids[0]))
        for string in strings:
            assert set(placeholder.findall(string)) == expected, f"[{lang}] {ids[0]!r}"


@pytest.mark.parametrize("lang", list(LANGUAGES))
def test_every_js_string_translated(app, lang):
    with app.test_request_context(), force_locale(lang):
        strings = js_strings()
    with app.test_request_context(), force_locale("fr"):
        french = js_strings()
    assert set(strings) == set(french)
    if lang != "fr":
        # Mots identiques en français et dans d'autres langues (« Distance », « Pause »).
        unchanged = [k for k in strings if strings[k] == french[k] and k not in {"distance", "replay_pause"}]
        assert not unchanged, f"[{lang}] chaînes JS non traduites : {unchanged}"
