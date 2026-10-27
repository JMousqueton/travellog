import pytest


def test_about_explains_the_name(client):
    html = client.get("/about").text
    assert "Pourquoi « Voyage Voyage » ?" in html
    assert "Desireless" in html and "Merci à Mallorie pour l'idée !" in html
    assert "Toutes les fonctionnalités" in html and "Flighty" in html
    assert 'href="/auth/register"' in html  # visiteur : invitation à s'inscrire


@pytest.mark.parametrize("lang,title,thanks", [("en", "Why “Voyage Voyage”?", "Thanks to Mallorie for the idea!"),
                                               ("de", "Warum „Voyage Voyage“?", "Danke an Mallorie für die Idee!"),
                                               ("es", "¿Por qué «Voyage Voyage»?", "¡Gracias a Mallorie por la idea!"),
                                               ("it", "Perché «Voyage Voyage»?", "Grazie a Mallorie per l'idea!")])
def test_about_is_translated(client, lang, title, thanks):
    html = client.get(f"/about?lang={lang}").text.replace("&#39;", "'")
    assert title in html and thanks in html


def test_landing_links_to_about(client):
    html = client.get("/").text
    assert html.count('href="/about"') >= 3  # accroche, bouton sous les fonctionnalités, pied de page


def test_about_for_signed_in_user_has_no_signup_button(auth_client):
    html = auth_client.get("/about").text
    assert "Pourquoi « Voyage Voyage » ?" in html and 'href="/auth/register"' not in html


def test_site_name_and_tagline(client):
    html = client.get("/?lang=en").text
    assert "<title>" in html and "· Voyage Voyage</title>" in html
    assert '<span class="brand-tagline">the travel log</span>' in html
