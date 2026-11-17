"""The search API for other programs (Seb, 2026-11-17): GET /api/v1/search."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend import access
from backend.auth import AuthMode
from backend.config import settings
from backend.services import search_terms as st
from tests.test_auth import easyauth_headers

BOSS = easyauth_headers("boss@ptc.com")
URL = "/api/v1/search"


def file(name, item_id, kind="video"):
    return {"name": name, "kind": kind, "item_id": item_id, "size_bytes": 1234}


ROWS = [
    {"id": "a", "type": "video", "title": "PTC Modeler - MBSE in Windchill",
     "description": "x" * 600, "segment": "PLM", "products": ["Windchill"], "language": "en",
     "uploaded_at": "2026-09-14", "resources": [file("a_main.mp4", "item-a1")]},
    {"id": "b", "type": "video", "title": "Model-Based Systems Engineering Overview",
     "segment": "PLM", "language": "de"},
    {"id": "c", "type": "vdk", "title": "Creo Parametric Overview", "segment": "CAD",
     "products": ["Creo Parametric"], "language": "en",
     "resources": [file("c_kit.zip", "item-c1", "dataset")]},
    {"id": "d", "type": "vdk", "title": "Internal Creo Roadmap", "segment": "CAD",
     "language": "en",
     "resources": [file("d_secret.pptx", "item-d1", "document")]},
] + [{"id": f"p{i}", "type": "video", "title": f"Paging demo {i}", "language": "en"}
     for i in range(5)]


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import app
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(st, "_seen", {"path": None, "at": 0.0, "stamp": None, "table": ()})
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password", "")
    monkeypatch.setattr(settings, "hub_admin_emails", "boss@ptc.com")
    monkeypatch.setattr(settings, "custom_domain", "hub.example.com")
    (tmp_path / "mirror").mkdir()
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps(ROWS), encoding="utf-8")
    # "d" is PTC Only: marked on the Hub (owned/content_access.json).
    (tmp_path / "owned").mkdir()
    (tmp_path / "owned" / "content_access.json").write_text(
        json.dumps({"d": {"by": "user:boss@ptc.com", "at": "2026-11-17T00:00:00", "reason": None}}),
        encoding="utf-8")
    return TestClient(app, base_url="http://localhost")


def token(client, perms, name="Growth OS"):
    r = client.post("/api/admin/api-tokens", headers=BOSS,
                    json={"name": name, "owner": "seb@ptc.com", "permissions": perms})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['secret']}"}


def ids(r):
    assert r.status_code == 200, r.text
    return [i["id"] for i in r.json()["items"]]


def test_nobody_is_refused_and_a_token_needs_view_the_hub(client):
    assert client.get(URL, params={"q": "creo"}).status_code == 401
    assert client.get(URL, params={"q": "creo"},
                      headers=token(client, ["preview"])).status_code == 403


def test_a_token_gets_the_documented_shape(client):
    h = token(client, ["view_hub", "preview", "download"])
    r = client.get(URL, params={"q": "windchill"}, headers=h)
    body = r.json()
    assert r.status_code == 200
    assert (body["query"], body["total"], body["limit"], body["offset"]) == ("windchill", 1, 20, 0)
    hit = body["items"][0]
    assert hit["id"] == "a" and hit["type"] == "video" and hit["segment"] == "PLM"
    assert hit["hub_url"] == "https://hub.example.com/#/asset/a"
    assert hit["published"] == "2026-09-14"
    assert len(hit["summary"]) <= 501 and hit["summary"].endswith("…")
    assert hit["files_available"] is True
    assert hit["files"] == [{
        "name": "a_main.mp4", "kind": "video", "size_bytes": 1234,
        "preview_url": "https://hub.example.com/api/assets/a/files/item-a1/preview",
        "download_url": "https://hub.example.com/api/assets/a/files/item-a1/download"}]


def test_filters_narrow_the_search(client):
    h = token(client, ["view_hub", "preview", "download"])
    assert ids(client.get(URL, params={"segment": "CAD"}, headers=h)) == ["c", "d"]
    assert ids(client.get(URL, params={"segment": "CAD", "type": "vdk", "q": "roadmap"},
                          headers=h)) == ["d"]
    assert ids(client.get(URL, params={"language": "de"}, headers=h)) == ["b"]
    assert ids(client.get(URL, params={"product": "Creo Parametric"}, headers=h)) == ["c"]


def test_search_term_groups_expand_like_the_page(client):
    h = token(client, ["view_hub", "preview", "download"])
    assert ids(client.get(URL, params={"q": "MBSE"}, headers=h)) == ["a", "b"]


def test_without_preview_and_download_files_are_named_but_not_linked(client):
    h = token(client, ["view_hub"])
    hit = client.get(URL, params={"q": "windchill"}, headers=h).json()["items"][0]
    assert hit["files_available"] is False
    assert hit["files"][0]["name"] == "a_main.mp4"
    assert hit["files"][0]["preview_url"] is None and hit["files"][0]["download_url"] is None


def test_a_closed_demo_has_no_file_links_for_a_caller_without_internal_access(client):
    open_h = token(client, ["view_hub", "preview", "download"])
    shut_h = token(client, ["view_hub", "preview", "download", "access_internal"], "Internal")
    hit = client.get(URL, params={"q": "roadmap"}, headers=open_h).json()["items"][0]
    assert hit["internal"] is True and hit["files_available"] is False
    assert [f["download_url"] for f in hit["files"]] == [None]
    hit = client.get(URL, params={"q": "roadmap"}, headers=shut_h).json()["items"][0]
    assert hit["files_available"] is True and hit["files"][0]["download_url"]


def test_paging(client):
    h = token(client, ["view_hub"])
    first = client.get(URL, params={"q": "paging", "limit": 2}, headers=h).json()
    assert first["total"] == 5 and len(first["items"]) == 2 and first["limit"] == 2
    second = client.get(URL, params={"q": "paging", "limit": 2, "offset": 2}, headers=h).json()
    assert second["offset"] == 2 and len(second["items"]) == 2
    assert not {i["id"] for i in first["items"]} & {i["id"] for i in second["items"]}
    assert client.get(URL, params={"limit": 101}, headers=h).status_code == 422


def test_a_call_is_not_recorded_as_a_search(client, tmp_path):
    h = token(client, ["view_hub"])
    client.get(URL, params={"q": "windchill"}, headers=h)
    leftover = [p for p in tmp_path.rglob("*") if p.is_file() and "search" in p.name.lower()
                and "terms" not in p.name.lower()]
    assert leftover == []
