"""Compression, versioned static URLs and modulepreload (WS-C, 2026-11-26).

backend/static_delivery.py says why. These pin what a browser relies on:
the build's own prefix is cacheable for a year, everything else is
revalidated, the pages name only the build's prefix, and gzip never touches
pictures or range answers.
"""
from __future__ import annotations

import gzip
import re

import pytest
from fastapi.testclient import TestClient

import app as app_module
from backend import static_delivery

GZ = {"Accept-Encoding": "gzip"}
PAGES = ("/", "/admin", "/content-health", "/migration")
THUMB = "img/thumbs/attract-loop-audio-introduction.jpg"


@pytest.fixture
def client():
    return TestClient(app_module.app)


@pytest.fixture
def build(monkeypatch):
    """A deployed build: BUILD_NUMBER 42."""
    monkeypatch.setattr(static_delivery, "current_token", lambda: "42")
    return "42"


@pytest.fixture
def local(monkeypatch):
    """A local checkout: no build number."""
    monkeypatch.setattr(static_delivery, "current_token", lambda: "")


# ------------------------------------------------------------- compression

def test_scripts_and_pages_are_gzipped_when_the_browser_accepts_it(client, local):
    for url in ("/static/js/hub/main.js", "/static/css/hub.css", "/"):
        r = client.get(url, headers=GZ)
        assert r.status_code == 200, url
        assert r.headers["content-encoding"] == "gzip", url
        assert "accept-encoding" in r.headers["vary"].lower(), url


def test_the_compressed_bytes_are_the_file(client, local):
    """TestClient decodes for us; check the raw stream too, so a body that
    claims gzip but is not is caught."""
    with client.stream("GET", "/static/js/hub/main.js", headers=GZ) as r:
        raw = b"".join(r.iter_raw())
    with open(f"{static_delivery.STATIC_DIR}/js/hub/main.js", "rb") as fh:
        assert gzip.decompress(raw) == fh.read()


def test_nothing_is_gzipped_for_a_client_that_did_not_ask(client, local):
    r = client.get("/static/js/hub/main.js", headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in r.headers


def test_small_answers_are_not_gzipped(client, local):
    """minimum_size is honoured: GZip sits inside the streaming middlewares,
    so it sees a whole body, not the first piece of one."""
    for url in ("/health", "/api/version", "/static/img/favicon.svg"):
        r = client.get(url, headers=GZ)
        assert "content-encoding" not in r.headers, url
        assert r.headers["content-length"] == str(len(r.content)), url


def test_pictures_are_not_gzipped(client, local):
    r = client.get(f"/static/{THUMB}", headers=GZ)
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert "content-encoding" not in r.headers


@pytest.mark.parametrize("path", [THUMB, "js/hub/main.js"])
def test_range_answers_are_untouched(client, build, path):
    """A 206 compressed would no longer match its Content-Range; a video or
    a seek in one would break. Same through the versioned prefix."""
    for prefix in ("/static/", "/static/v42/"):
        r = client.get(prefix + path, headers={**GZ, "Range": "bytes=0-99"})
        assert r.status_code == 206
        assert "content-encoding" not in r.headers
        assert r.headers["content-range"].startswith("bytes 0-99/")
        assert len(r.content) == 100


def test_an_unsatisfiable_range_is_a_plain_416(client, local):
    r = client.get("/static/js/hub/main.js", headers={**GZ, "Range": "bytes=99999999-"})
    assert r.status_code == 416
    assert "content-encoding" not in r.headers


def test_security_headers_survive_compression(client, local):
    r = client.get("/static/js/hub/main.js", headers=GZ)
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "SAMEORIGIN"


# ----------------------------------------------------------------- caching

def test_the_builds_prefix_is_immutable(client, build):
    r = client.get("/static/v42/js/hub/main.js", headers=GZ)
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
    with open(f"{static_delivery.STATIC_DIR}/js/hub/main.js", "rb") as fh:
        assert r.content == fh.read()


def test_the_plain_path_still_works_and_is_revalidated(client, build):
    r = client.get("/static/js/hub/main.js")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"
    again = client.get("/static/js/hub/main.js", headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304


def test_another_builds_prefix_is_served_but_never_immutable(client, build):
    """A page loaded before a deploy may still ask for its own build's files;
    it gets today's, and nothing caches them under the old name for a year."""
    r = client.get("/static/v41/js/hub/main.js")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"


def test_without_a_build_number_nothing_is_immutable(client, local):
    """A local checkout: an edit must show on the next reload."""
    for url in ("/static/js/hub/main.js", "/static/v42/js/hub/main.js"):
        assert client.get(url).headers["cache-control"] == "no-cache", url


def test_a_missing_file_under_the_prefix_is_a_404_not_cached(client, build):
    r = client.get("/static/v42/js/hub/no-such-module.js")
    assert r.status_code == 404
    assert "immutable" not in r.headers.get("cache-control", "")


def test_the_prefix_cannot_climb_out_of_static(client, build):
    for url in ("/static/v42/../app.py", "/static/v42/..%2Fapp.py", "/static/v42/%2e%2e/app.py"):
        assert client.get(url).status_code == 404, url


@pytest.mark.parametrize("page", PAGES)
def test_pages_are_revalidated_and_answer_304_when_unchanged(client, build, page):
    r = client.get(page, headers=GZ)
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["content-type"].startswith("text/html")
    again = client.get(page, headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304
    assert again.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize("page", PAGES)
def test_a_deployed_page_names_only_the_builds_prefix(client, build, page):
    html = client.get(page).text
    tags = re.findall(r"<(?:script|link)\b[^>]*?\s(?:src|href)=\"(/static/[^\"]+)\"", html)
    assert tags, page
    assert all(t.startswith("/static/v42/") for t in tags), [t for t in tags if "/v42/" not in t]


def test_a_local_page_is_unchanged_apart_from_preloads(client, local):
    html = client.get("/").text
    assert '<script src="/static/js/hub-ui.js" defer></script>' in html
    assert '<script type="module" src="/static/js/hub/main.js"></script>' in html
    assert "/static/v" not in html


def test_the_page_changes_with_the_build(client, monkeypatch):
    """Different build, different page, different ETag: a deploy can never
    be answered with the previous build's 304."""
    monkeypatch.setattr(static_delivery, "current_token", lambda: "41")
    old = client.get("/")
    monkeypatch.setattr(static_delivery, "current_token", lambda: "42")
    new = client.get("/")
    assert old.headers["etag"] != new.headers["etag"]
    assert client.get("/", headers={"If-None-Match": old.headers["etag"]}).status_code == 200


def test_a_plain_link_inside_a_page_is_left_alone(client, build):
    """Only script and link tags are versioned; the Admin page's link to the
    API guide is a page people open and bookmark."""
    html = client.get("/admin").text
    assert 'href="/static/docs/api-create-demo.html"' in html


def test_the_build_token_is_url_safe(monkeypatch, tmp_path):
    monkeypatch.setattr(static_delivery, "BASE_DIR", str(tmp_path))
    monkeypatch.setenv("BUILD_NUMBER", "17")
    assert static_delivery.asset_token() == "17"
    (tmp_path / "BUILD_NUMBER").write_text(' 123/"><x\n', encoding="utf-8")
    assert static_delivery.asset_token() == "123x"
    (tmp_path / "BUILD_NUMBER").unlink()
    monkeypatch.delenv("BUILD_NUMBER")
    assert static_delivery.asset_token() == ""


# ----------------------------------------------------------- modulepreload

def _preloads(html):
    return re.findall(r'<link rel="modulepreload" href="([^"]+)">', html)


def test_the_hub_preloads_its_whole_module_graph(client, build):
    import os
    preloads = _preloads(client.get("/").text)
    hub = sorted(f"/static/v42/js/hub/{f}" for f in os.listdir(f"{static_delivery.STATIC_DIR}/js/hub")
                 if f.endswith(".js"))
    # Every module under js/hub is reachable from main.js today; a new one
    # that is not would simply not be preloaded, which this would flag.
    assert sorted(preloads) == hub
    assert preloads[0] == "/static/v42/js/hub/main.js"
    assert len(preloads) == len(set(preloads))


def test_the_preloads_come_before_the_entry_script(client, build):
    html = client.get("/").text
    assert html.index('rel="modulepreload"') < html.index('<script type="module"')


@pytest.mark.parametrize("page,entry", [("/admin", "js/admin/main.js"),
                                        ("/content-health", "js/content-health/main.js")])
def test_admin_pages_preload_their_graph_including_shared_modules(client, build, page, entry):
    preloads = _preloads(client.get(page).text)
    assert preloads[0] == f"/static/v42/{entry}"
    assert "/static/v42/js/admin/util.js" in preloads
    assert "</head>" in client.get(page).text
    html = client.get(page).text
    assert html.index('rel="modulepreload"') < html.index("</head>")


def test_the_migration_page_has_no_modules_to_preload(client, build):
    assert _preloads(client.get("/migration").text) == []


def test_the_graph_follows_multiline_and_parent_imports(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "shared").mkdir()
    (tmp_path / "a" / "main.js").write_text(
        'import {\n  x,\n  y,\n} from "./b.js";\nimport "../shared/s.js";\n'
        'export { z } from "./c.js";\nimport lib from "https://cdn.example/lib.js";\n'
        '// import nope from "./commented.js" is not at line start, so ignored\n',
        encoding="utf-8")
    (tmp_path / "a" / "b.js").write_text('import { s } from "../shared/s.js";\n', encoding="utf-8")
    (tmp_path / "a" / "c.js").write_text("export const z = 1;\n", encoding="utf-8")
    (tmp_path / "shared" / "s.js").write_text('import { x } from "../a/main.js";\n', encoding="utf-8")
    graph = static_delivery.module_graph("a/main.js", str(tmp_path))
    assert graph == ["a/main.js", "a/b.js", "a/c.js", "shared/s.js"]
