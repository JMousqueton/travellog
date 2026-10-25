import re

from app.assets import file_version


def test_service_worker_precaches_versioned_static_files(client):
    response = client.get("/sw.js")
    assert response.status_code == 200 and response.mimetype == "application/javascript"
    assert response.headers["Cache-Control"] == "no-cache"
    assert "connect-src 'self' https://cdn.jsdelivr.net" in response.headers["Content-Security-Policy"]
    body = response.text
    assert f'"/static/css/app.css?v={file_version("css/app.css")}"' in body
    assert '"/static/vendor/leaflet-1.9.4/leaflet.js?v=' in body and "LICENSE" not in body
    assert 'const OFFLINE_URL = "/offline"' in body and '"/auth/"' in body


def test_service_worker_version_follows_static_files(app, client, tmp_path):
    first = re.search(r'const VERSION = "(\w+)"', client.get("/sw.js").text).group(1)
    (tmp_path / "x.js").write_text("a")
    app.static_folder = str(tmp_path)
    second = re.search(r'const VERSION = "(\w+)"', client.get("/sw.js").text).group(1)
    assert first != second


def test_offline_page_has_no_account_details(auth_client):
    response = auth_client.get("/offline")
    assert response.status_code == 200
    assert "Vous êtes hors ligne" in response.text and "alice@example.com" not in response.text


def test_pages_register_service_worker(client):
    main_js = client.get(f"/static/js/main.js?v={file_version('js/main.js')}").text
    assert 'navigator.serviceWorker.register("/sw.js")' in main_js and 'caches.delete("pages")' in main_js
