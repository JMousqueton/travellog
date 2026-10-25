import json
import re

from app.assets import file_version


def test_static_urls_are_versioned(client):
    html = client.get("/").text
    version = file_version("css/app.css")
    assert f'href="/static/css/app.css?v={version}"' in html
    assert re.fullmatch(r"[0-9a-f]{10}", version)


def test_version_follows_file_content(app, tmp_path):
    app.static_folder = str(tmp_path)
    asset = tmp_path / "x.js"
    asset.write_text("a")
    first = file_version("x.js")
    asset.write_text("bb")
    assert file_version("x.js") != first
    assert file_version("absent.js") is None


def test_import_map_versions_js_modules(client):
    html = client.get("/").text
    imports = json.loads(re.search(r'<script type="importmap" nonce="[^"]+">(.*?)</script>', html).group(1))["imports"]
    assert imports["/static/js/ui.js"] == f"/static/js/ui.js?v={file_version('js/ui.js')}"
    assert html.index('type="importmap"') < html.index('type="module"')
