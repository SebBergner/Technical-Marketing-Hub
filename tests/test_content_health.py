"""Content health (/content-health; Liwei, 2026-11-11)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend import access
from backend.auth import AuthMode
from backend.config import settings
from backend.repositories.json_repo import JsonAssetRepository
from tests.test_auth import easyauth_headers

KEEPER = easyauth_headers("keeper@ptc.com")        # Maintain content, no View Admin
VIEWER = easyauth_headers("viewer@ptc.com")        # View Admin, no Maintain content


def _res(name, sub=None):
    ext = name.rsplit(".", 1)[-1]
    return {"name": name, "kind": "dataset", "extension": ext, "subfolder": sub}


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import app
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password", "")
    (tmp_path / "mirror").mkdir()
    rows = [
        {"id": "full", "type": "ldk", "title": "Full Kit", "products": ["Creo Parametric"],
         "segment": "CAD", "resource_count": 2, "demo_owner_name": "Ann Lee",
         "resources": [_res("Foot Bath.zip"), _res("Foot Bath.rar")]},
        {"id": "page-only", "type": "vdk", "title": "Page Only", "products": ["Creo Parametric"],
         "segment": "CAD", "resource_count": 0, "resources": []},
        {"id": "empty", "type": "vdk", "title": "Empty Kit", "products": [], "segment": None,
         "resource_count": 0, "resources": []},
        {"id": "cad", "type": "cad_model", "title": "Bracket", "products": ["Creo Parametric"],
         "segment": None, "resource_count": 1,
         "resources": [_res("a.zip", "One"), _res("a.rar", "Two")]},
    ]
    for r in rows:
        r["source"] = "sharepoint"
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps(rows), encoding="utf-8")
    repo = JsonAssetRepository(str(tmp_path))
    repo.set_sync_field("sharepoint", "health", {
        "read_at": "2026-11-11T06:00:00",
        "skipped_folders": [{"name": "Few", "files": 1}, {"name": "Many", "files": 9}],
        "loose_files": [{"name": "stray.rar"}]})
    for q, n in (("ignition", 0), ("Ignition ", 0), ("ignition", 1), ("creo", 40), ("mbd", 2)):
        repo.record_usage_event("search", q=q, results=n, user="p@ptc.com")
    # Under a filter: counted, never as finding little (Bobcat, 2026-11-12).
    repo.record_usage_event("search", q="Full Kit", results=0, filters={"type": ["vm"]},
                            user="p@ptc.com")
    access.create_group("Keepers", "", ["view_hub", "maintain_content"], ["keeper@ptc.com"], "t")
    access.create_group("Viewers", "", ["view_hub", "view_admin"], ["viewer@ptc.com"], "t")
    return TestClient(app, base_url="http://localhost")


def test_it_needs_maintain_content_not_view_admin(client):
    assert client.get("/api/content-health/checks", headers=KEEPER).status_code == 200
    assert client.get("/api/content-health/checks", headers=VIEWER).status_code == 403
    assert client.get("/api/content-health/checks").status_code == 401


def test_the_checks(client):
    d = client.get("/api/content-health/checks", headers=KEEPER).json()
    assert [f["name"] for f in d["skipped_folders"]] == ["Many", "Few"], "most files first"
    assert [f["name"] for f in d["loose_files"]] == ["stray.rar"]
    assert [r["asset_id"] for r in d["empty"]] == ["empty"], "a page-only demo has no folder"
    assert d["empty"][0]["library"] == "Demo Catalog"
    assert [r["asset_id"] for r in d["no_product"]] == ["empty"]
    assert [r["asset_id"] for r in d["no_segment"]] == ["empty"], "a CAD dataset has no Segment"
    archives = d["same_name_archives"]
    assert [(r["asset_id"], r["files"]) for r in archives] == [("full", ["foot bath.rar/.zip"])]
    assert archives[0]["owner"] == "Ann Lee"


def test_searches_that_found_little(client):
    from backend.services import search_insights_store as store
    assert client.get("/api/content-health/searches", headers=KEEPER).json()["pending"] is True
    store.compute_all()
    d = client.get("/api/content-health/searches", headers=KEEPER).json()
    assert d["totals"]["recorded"] == 6 and d["totals"]["typing"] == 0
    rows = {(r["q"].lower(), r["filters"]): r for r in d["rows"]}
    assert set(rows) == {("ignition", None), ("mbd", None), ("creo", None),
                         ("full kit", "Type: Virtual Machine")}
    assert (rows[("ignition", None)]["times"], rows[("ignition", None)]["no_results"],
            rows[("ignition", None)]["few_results"], rows[("ignition", None)]["people"])         == (3, 2, 1, 1)
    # Nothing in the catalogue is called anything like "ignition": a gap.
    gaps = {(g["q"].lower(), g["filters"]) for g in d["gaps"]}
    assert gaps == {("ignition", None), ("mbd", None), ("full kit", "Type: Virtual Machine")}
    assert "p@ptc.com" not in json.dumps(d)


def test_recent_changes_only_in_this_pages_areas(client):
    assert client.get("/api/content-health/changes?category=Content access",
                      headers=KEEPER).status_code == 200
    assert client.get("/api/content-health/changes?category=Users %26 groups",
                      headers=KEEPER).status_code == 422


def test_the_admin_page_no_longer_serves_them(client):
    boss = easyauth_headers("viewer@ptc.com")
    for path in ("/api/admin/content-review", "/api/admin/content-access",
                 "/api/admin/hidden", "/api/admin/content"):
        assert client.get(path, headers=boss).status_code == 404, path


def test_the_page_is_served(client):
    r = client.get("/content-health", headers=KEEPER)
    assert r.status_code == 200 and "Content health" in r.text


def test_the_hub_says_when_a_search_was_filtered(client, tmp_path):
    for body in ({"q": "Bobcat", "results": 0,
                  "filters": {"type": ["vm"], "sort": ["title"], "family": ["x" * 99]}},
                 {"q": "Bobcat", "results": 11}):
        assert client.post("/api/assets/search-event", json=body,
                           headers=KEEPER).status_code == 204
    events = [e for e in JsonAssetRepository(str(tmp_path)).usage_events()
              if e.get("q") == "Bobcat"]
    assert [e.get("filters") for e in events] == [{"type": ["vm"], "family": ["x" * 60]}, None]


def test_searches_are_worked_out_ahead_and_refreshed_at_most_hourly(client, monkeypatch):
    from backend.services import search_insights_store as store
    ran = []
    monkeypatch.setattr(store.threading, "Thread",
                        lambda target, args, **kw: type("T", (), {"start": lambda self: (
                            ran.append(args), target(*args))})())
    store.compute_all()
    first = client.get("/api/content-health/searches?days=30", headers=KEEPER).json()
    JsonAssetRepository(str(store.settings.data_dir)).record_usage_event(
        "search", q="new word", results=0, user="q@ptc.com")
    again = client.get("/api/content-health/searches?days=30", headers=KEEPER).json()
    assert again["totals"] == first["totals"], "a page load never works it out"
    assert again["refresh"]["available"] is True
    r = client.post("/api/content-health/searches/refresh", headers=KEEPER)
    assert r.status_code == 202 and ran, r.text
    after = client.get("/api/content-health/searches?days=30", headers=KEEPER).json()
    assert after["totals"]["recorded"] == first["totals"]["recorded"] + 1
    assert after["refresh"]["available"] is False and after["refresh"]["available_at"]
    again = client.post("/api/content-health/searches/refresh", headers=KEEPER)
    assert again.status_code == 429 and "available again at" in again.json()["detail"]
    assert client.post("/api/content-health/searches/refresh", headers=VIEWER).status_code == 403
