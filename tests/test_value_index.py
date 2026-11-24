"""The Value Roadmap index read from `<video>.index.json` files (2026-11-24).

AMP-shaped JSON saved next to a video in its demo folder becomes that demo's
Value Roadmap: parsed by services/value_index.py, set aside from the files by
the sync, read only when its eTag changes, merged into the catalogue by the
repository, and shown -- page, filters, facets -- only to "Preview the Value
Roadmap" (access.Perm.VIEW_ROADMAP), being unreviewed AI output.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import access
from backend.auth import AuthMode
from backend.config import settings
from backend.integrations.graph import value_index_sync
from backend.integrations.graph.sync import build_assets
from backend.models import Asset
from backend.repositories.base import AssetQuery
from backend.repositories.json_repo import JsonAssetRepository
from backend.services import value_index as vi
from tests.test_auth import easyauth_headers
from tests.test_graph import DRIVE_ID, client_for, file_item, folder

FIXTURE = Path(__file__).parent / "fixtures" / "value_index" / "bobcat_engineering.index.json"
ADMIN, TESTER, STAFF, PARTNER = "boss@ptc.com", "tester@ptc.com", "someone@ptc.com", "p@partner.it"


def bobcat() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# ──────────────────────────────────────────────────────────────── parsing
def test_parses_amps_own_format():
    index = vi.parse(FIXTURE.read_bytes())
    assert [p["name"] for p in index["processes"]][:2] == [
        "Requirements Management & Review", "Model-Based Design & Engineering"]
    assert len(index["processes"]) == 6 and len(index["capabilities"]) == 12
    first = index["capabilities"][0]
    assert first["id"] == "requirements-management-review--intelligent-requirements-assistance"
    assert first["process_id"] == "requirements-management-review"
    assert index["value_drivers"] == ["Efficiency", "Innovation", "Quality & Regulatory"]
    assert len(index["initiatives"]) == 6 and index["initiatives"][0]["evidence"]
    assert len(index["metrics"]) == 5 and index["challenges"] == []
    assert [s["start_s"] for s in index["scenes"]] == [1.5, 67.9, 134.3, 200.8]
    assert index["scenes"][1]["tags"][2]["name"] == "Asset Health"
    assert index["used_audio"] is True and index["source"] == "claude"


def test_scene_tags_may_be_ids_or_names():
    data = bobcat()
    data["analysis"]["scenes"] = [
        {"start_s": 5, "end_s": 9, "description": "x",
         "tags": ["verification-validation--test-management", "Asset Health", "Unknown thing"]}]
    tags = vi.parse(data)["scenes"][0]["tags"]
    assert [t["name"] for t in tags] == ["Test Management", "Asset Health", "Unknown thing"]
    assert tags[0]["type"] == "capability"


def test_the_two_parts_may_sit_at_the_top_level():
    data = bobcat()
    flat = {**data["analysis"], **data["value_roadmap"]}
    index = vi.parse(flat)
    assert len(index["capabilities"]) == 12 and index["summary"]


@pytest.mark.parametrize("raw, why", [
    (b"{not json", "not valid JSON"),
    (b"[1, 2]", "not a JSON object"),
    (b'{"hello": 1}', "no `analysis` or `value_roadmap`"),
    (b'{"analysis": {"tags": []}}', "holds no tags"),
])
def test_what_is_not_an_index_says_why(raw, why):
    with pytest.raises(vi.NotAnIndex, match=why):
        vi.parse(raw)


def test_index_files_and_their_videos():
    assert vi.is_index_file("Demo.index.json") and vi.is_index_file("A.MP4.INDEX.JSON")
    assert not vi.is_index_file(".index.json") and not vi.is_index_file("notes.json")
    videos = [{"name": "Demo.mp4", "kind": "video", "subfolder": "Videos"},
              {"name": "Demo.pptx", "kind": "document", "subfolder": "Videos"}]
    assert vi.match_video("Demo.index.json", "Videos", videos)["name"] == "Demo.mp4"
    assert vi.match_video("Demo.mp4.index.json", "Videos", videos)["name"] == "Demo.mp4"
    assert vi.match_video("Demo.index.json", None, videos) is None     # other folder
    assert vi.match_video("Other.index.json", "Videos", videos) is None


# ─────────────────────────────────────────────────────────────────── sync
def test_the_sync_sets_index_files_aside():
    items = [folder("Bobcat Kit", item_id="F-BOBCAT"),
             file_item("Bobcat_03_Engineering.mp4", "/Bobcat Kit/Videos"),
             {**file_item("Bobcat_03_Engineering.index.json", "/Bobcat Kit/Videos"),
              "file": {"mimeType": "application/json"}, "eTag": "e1"}]
    assets, result = build_assets(items)
    assert [r.name for r in assets[0].resources] == ["Bobcat_03_Engineering.mp4"]
    assert result.resources == 1
    assert result.index_files == [{
        "folder": "Bobcat Kit", "folder_id": "F-BOBCAT", "subfolder": "Videos",
        "name": "Bobcat_03_Engineering.index.json",
        "item_id": "file-Bobcat_03_Engineering.index.json", "etag": "e1",
        "modified_at": None}]


def _graph(files: dict[str, bytes], calls: list[str]):
    """A Graph that serves each item's content through a download URL."""
    def handler(request):
        path = request.url.path
        if path.startswith(f"/v1.0/drives/{DRIVE_ID}/items/"):
            item = path.rsplit("/", 1)[-1]
            return httpx.Response(200, json={
                "id": item, "@microsoft.graph.downloadUrl": f"https://dl.example/{item}"})
        if request.url.host == "dl.example":
            item = path.strip("/")
            calls.append(item)
            return httpx.Response(200, content=files[item])
        return httpx.Response(404)
    return client_for(handler)


def test_refresh_reads_only_changed_files():
    items = [folder("Bobcat Kit", item_id="F-BOBCAT"),
             {**file_item("Bobcat_03_Engineering.mp4", "/Bobcat Kit/Videos"), "id": "V1"},
             {**file_item("Bobcat_03_Engineering.index.json", "/Bobcat Kit/Videos"),
              "id": "J1", "eTag": "e1"},
             {**file_item("Broken.index.json", "/Bobcat Kit"), "id": "J2", "eTag": "e9"}]
    assets, result = build_assets(items)
    calls: list[str] = []
    client = _graph({"J1": FIXTURE.read_bytes(), "J2": b"{oops"}, calls)

    store, stats = value_index_sync.refresh(client, DRIVE_ID, result.index_files, assets, None)
    assert calls == ["J1", "J2"]
    entry = store["files"]["J1"]
    assert entry["video"] == "Bobcat_03_Engineering.mp4" and entry["video_item_id"] == "V1"
    assert entry["index"]["value_drivers"] and entry["error"] is None
    assert store["files"]["J2"]["index"] is None
    assert stats["indexed_demos"] == 1 and stats["downloaded"] == 1
    assert stats["errors"][0]["name"] == "Broken.index.json"

    calls.clear()
    store2, stats2 = value_index_sync.refresh(client, DRIVE_ID, result.index_files, assets, store)
    assert calls == [] and stats2["unchanged"] == 2
    assert store2["files"]["J1"]["index"] == entry["index"]


# ───────────────────────────────────────────────────────────── repository
@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    (tmp_path / "mirror").mkdir()
    kit = {"id": "bobcat", "type": "vdk", "title": "Bobcat IPL", "products": ["Creo"],
           "segment": "CAD", "source_item_id": "F-BOBCAT",
           "resources": [{"name": "Bobcat_03_Engineering.mp4", "kind": "video",
                          "subfolder": "Videos", "item_id": "V1"}]}
    other = {"id": "other", "type": "video", "title": "Something else", "products": ["Creo"],
             "segment": "CAD", "source_item_id": "F-OTHER"}
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps([kit, other]),
                                                         encoding="utf-8")
    r = JsonAssetRepository(str(tmp_path))
    r.replace_value_index({"files": {"J1": {
        "folder_id": "F-BOBCAT", "subfolder": "Videos",
        "name": "Bobcat_03_Engineering.index.json", "item_id": "J1", "etag": "e1",
        "video": "Bobcat_03_Engineering.mp4", "video_item_id": "V1",
        "index": vi.parse(FIXTURE.read_bytes()), "error": None}}})
    return r


def test_a_demo_carries_its_index(repo):
    asset = repo.get("bobcat")
    assert asset.has_roadmap and asset.value_index is not None
    video = asset.value_index.videos[0]
    assert video.video == "Bobcat_03_Engineering.mp4" and video.video_item_id == "V1"
    assert "Multi-Physics Simulation" in asset.value_index.capabilities
    # Kept out of the record's own value drivers: never in text search or cards.
    assert asset.value_drivers == []
    assert repo.get("other").value_index is None


def test_filters_and_facets_read_the_index(repo):
    def ids(**kw):
        return {a.id for a in repo.list(AssetQuery(**kw)).items}
    assert ids(processes=["Verification & Validation"]) == {"bobcat"}
    assert ids(capabilities=["Asset Health"]) == {"bobcat"}
    assert ids(value_drivers=["Innovation"]) == {"bobcat"}
    assert ids(capabilities=["Nothing like it"]) == set()
    assert ids(text="Innovation") == set()          # AI words are not searchable
    facets = repo.facets()
    assert {f.value: f.count for f in facets.processes}["Analytics & Reporting"] == 1
    assert {f.value: f.count for f in facets.value_drivers} == {
        "Efficiency": 1, "Innovation": 1, "Quality & Regulatory": 1}


def test_a_broken_file_adds_nothing(repo):
    store = repo.value_index_store()
    store["files"]["J1"]["index"], store["files"]["J1"]["error"] = None, "not valid JSON"
    repo.replace_value_index(store)
    assert repo.get("bobcat").value_index is None and not repo.get("bobcat").has_roadmap


# ─────────────────────────────────────────────────────────────── the API
@pytest.fixture
def client(repo, monkeypatch):
    from app import app
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password", "")
    monkeypatch.setattr(settings, "hub_admin_emails", ADMIN)
    access.create_group("Value Roadmap testers", "", ["view_value_roadmap"],
                        [TESTER, PARTNER], "test")
    yield TestClient(app, base_url="http://localhost")
    app.dependency_overrides.clear()


def test_only_preview_the_value_roadmap_sees_it(client):
    def page(who):
        r = client.get("/api/assets/bobcat", headers=easyauth_headers(who))
        assert r.status_code == 200, r.text
        return r.json()
    assert page(TESTER)["value_index"]["videos"][0]["summary"]
    assert page(ADMIN)["value_index"] is not None
    assert page(STAFF)["value_index"] is None
    assert page(PARTNER)["value_index"] is None     # never a partner's


def test_the_filters_and_counts_are_theirs_too(client):
    def ids(who, **params):
        r = client.get("/api/assets", params=params, headers=easyauth_headers(who))
        return {a["id"] for a in r.json()["items"]}
    assert ids(TESTER, capability="Asset Health") == {"bobcat"}
    assert ids(STAFF, capability="Asset Health") == {"bobcat", "other"}     # ignored
    facets = lambda who: client.get("/api/taxonomy", headers=easyauth_headers(who)).json()
    assert facets(TESTER)["processes"] and facets(TESTER)["value_drivers"]
    assert facets(STAFF)["processes"] == [] and facets(STAFF)["value_drivers"] == []
