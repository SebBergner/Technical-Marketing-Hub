"""My Hub (A3; 2026-11-12): favourites, recently viewed, my requests."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend import access
from backend.auth import AuthMode
from backend.config import settings
from backend.routers import me as me_router
from backend.services import my_hub
from tests.test_auth import easyauth_headers

# Each person their own Entra object id (the shared helper gives everyone one).
ANN = {**easyauth_headers("ann@ptc.com"), "X-MS-CLIENT-PRINCIPAL-ID": "oid-ann"}
BOB = {**easyauth_headers("bob@ptc.com"), "X-MS-CLIENT-PRINCIPAL-ID": "oid-bob"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import app
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password", "")
    (tmp_path / "mirror").mkdir()
    rows = [{"id": f"d{i}", "type": "video", "title": f"Demo {i}", "products": ["Creo Parametric"],
             "segment": "CAD", "uploaded_at": "2026-01-0%d" % (i + 1)} for i in range(4)]
    rows[3]["archived"] = True
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps(rows), encoding="utf-8")
    access.create_group("Makers", "", ["view_hub", "upload_content"], ["bob@ptc.com"], "t")
    me_router._requests_cache.clear()
    return TestClient(app, base_url="http://localhost")


def test_favorites_are_each_persons_own(client):
    assert client.put("/api/me/favorites/d1", headers=ANN).json()["ids"] == ["d1"]
    assert client.put("/api/me/favorites/d0", headers=ANN).json()["ids"] == ["d0", "d1"]
    assert client.get("/api/me/favorites", headers=BOB).json()["ids"] == []
    assert client.delete("/api/me/favorites/d1", headers=ANN).json()["ids"] == ["d0"]
    assert client.put("/api/me/favorites/nope", headers=ANN).status_code == 404
    assert client.get("/api/me/favorites").status_code == 401


def test_recently_viewed_newest_first_once_each_and_only_what_is_visible(client, tmp_path):
    for aid in ("d0", "d1", "d0", "d2"):
        assert client.post(f"/api/assets/{aid}/view", headers=ANN).status_code == 204
    key = "oid:oid-ann"
    my_hub.note_view(key, "d3")                    # archived since: not shown
    page = client.get("/api/me", headers=ANN).json()
    assert [r["id"] for r in page["recent"]] == ["d2", "d0", "d1"]
    assert page["recent"][0]["viewed_at"]
    assert client.get("/api/me", headers=BOB).json()["recent"] == []


def test_the_files_name_nobody(client, tmp_path):
    client.put("/api/me/favorites/d1", headers=ANN)
    names = [p.name for p in (tmp_path / "owned" / "me").iterdir()]
    assert names and not any("ann" in n for n in names)


def test_sections_follow_permissions(client):
    assert client.get("/api/me", headers=ANN).json()["sections"] == {"requests": True,
                                                                      "demos": False}
    assert client.get("/api/me", headers=BOB).json()["sections"]["demos"] is True


def test_my_requests_are_matched_by_requester_and_read_back(client, monkeypatch):
    rows = [
        {"item_id": "1", "request_id": "REQ-1", "title": "A", "status": "Delivered",
         "requester": "ann@ptc.com", "asset_type": "Video", "products": "Creo",
         "brief": "x", "delivered": "https://tmh.ptcxc.com/#/asset/d1",
         "created_at": "2026-11-01T10:00:00Z", "modified_at": None},
        {"item_id": "2", "request_id": "REQ-2", "title": "B", "status": "Triaged",
         "requester": "bob@ptc.com", "asset_type": "VDK", "products": "Windchill",
         "brief": "y", "delivered": None, "created_at": "2026-11-02T10:00:00Z",
         "modified_at": None},
    ]
    monkeypatch.setattr(me_router, "_all_requests", lambda: [dict(r) for r in rows])
    mine = client.get("/api/me/requests", headers=ANN).json()
    assert mine["readable"] is True
    assert [(r["request_id"], r["status"], r["delivered"]) for r in mine["items"]] == \
        [("REQ-1", "Delivered", "https://tmh.ptcxc.com/#/asset/d1")]
    assert "requester" not in mine["items"][0]


def test_a_request_still_waiting_for_sharepoint_shows_too(client, monkeypatch):
    monkeypatch.setattr(me_router, "_all_requests", lambda: None)
    r = client.post("/api/requests", headers=ANN, json={
        "asset_type": "video", "products": ["Creo"], "brief": "A short brief"})
    assert r.status_code == 201
    mine = client.get("/api/me/requests", headers=ANN).json()
    assert mine["readable"] is False
    assert [i["status"] for i in mine["items"]] == ["Not sent yet"]


# ─────────────────────────────────────────────── playlists (phase 2)
def make(client, who, name="Customer pitch", items=()):
    r = client.post("/api/me/playlists", headers=who, json={"name": name, "items": list(items)})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_a_playlist_is_its_owners_to_change(client):
    pid = make(client, ANN, items=["d0", "d1"])
    assert client.put(f"/api/me/playlists/{pid}/items/d2", headers=ANN).json()["items"] == \
        ["d0", "d1", "d2"]
    r = client.patch(f"/api/me/playlists/{pid}", headers=ANN,
                     json={"name": "  Renamed  ", "items": ["d2", "d0", "d1"]})
    assert (r.json()["name"], r.json()["items"]) == ("Renamed", ["d2", "d0", "d1"])
    assert client.delete(f"/api/me/playlists/{pid}/items/d0", headers=ANN).json()["items"] == \
        ["d2", "d1"]
    for call in (lambda: client.put(f"/api/me/playlists/{pid}/items/d0", headers=BOB),
                 lambda: client.patch(f"/api/me/playlists/{pid}", headers=BOB, json={"name": "x"}),
                 lambda: client.delete(f"/api/me/playlists/{pid}", headers=BOB)):
        assert call().status_code == 403
    assert [p["name"] for p in client.get("/api/me/playlists", headers=ANN).json()["items"]] == \
        ["Renamed"]
    assert client.get("/api/me/playlists", headers=BOB).json()["items"] == []
    assert client.delete(f"/api/me/playlists/{pid}", headers=ANN).status_code == 204
    assert client.get(f"/api/me/playlists/{pid}", headers=ANN).status_code == 404


def test_a_shared_link_shows_what_the_reader_may_open_and_copies_only_that(client):
    pid = make(client, ANN, items=["d0", "d3", "d1"])        # d3 archived: nobody sees it
    page = client.get(f"/api/me/playlists/{pid}", headers=BOB).json()
    assert ([a["id"] for a in page["items"]], page["unavailable"], page["mine"]) == \
        (["d0", "d1"], 1, False)
    copy = client.post(f"/api/me/playlists/{pid}/copy", headers=BOB).json()
    assert (copy["name"], copy["items"]) == ("Customer pitch", ["d0", "d1"])
    assert client.get(f"/api/me/playlists/{copy['id']}", headers=BOB).json()["mine"] is True


def test_names_are_required_and_bounded(client):
    assert client.post("/api/me/playlists", headers=ANN, json={"name": "   "}).status_code == 422
    pid = make(client, ANN, name="x" * 150)
    assert len(client.get(f"/api/me/playlists/{pid}", headers=ANN).json()["name"]) == 80
    assert client.get("/api/me/playlists/../../etc", headers=ANN).status_code == 404


def test_a_playlist_file_holds_no_address_or_object_id(client, tmp_path):
    """The sign-in here gives the address as the name: it is not kept."""
    make(client, ANN)
    text = next((tmp_path / "owned" / "playlists").iterdir()).read_text(encoding="utf-8")
    assert "ann@ptc.com" not in text and "oid-ann" not in text
