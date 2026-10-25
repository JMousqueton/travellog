from datetime import date

import pytest

from app import utils


@pytest.mark.parametrize("today,expected", [(date(2026, 3, 1), "© 2026 Julien Mousqueton"),
                                            (date(2028, 1, 1), "© 2026–2028 Julien Mousqueton")])
def test_footer_years(client, monkeypatch, today, expected):
    monkeypatch.setattr(utils, "today", lambda: today)
    html = client.get("/").text.replace("&copy;", "©")
    assert expected in html
    assert 'href="https://github.com/JMousqueton/travellog"' in html


def test_footer_on_map_page_is_in_sidebar(auth_client):
    html = auth_client.get("/").text
    assert html.count('class="site-footer') == 1 and "site-footer sidebar-footer" in html
