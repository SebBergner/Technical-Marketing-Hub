"""A shared playlist and what each reader may see (Liwei, 2026-11-12).

The link carries no access of its own: each reader sees the playlist
through their own permissions. A GXC video stays invisible to anyone
without Access GXC videos -- counted, never named, never copied -- and a
PTC Only demo shows a partner its card but not its files.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend import access
from backend.auth import AuthMode
from backend.config import settings
from backend.repositories.json_repo import JsonAssetRepository
from tests.test_auth import easyauth_headers

OWNER, STAFF, PARTNER = "gxc@ptc.com", "someone@ptc.com", "p@partner.it"


def who(email, oid):
    """Each person their own Entra object id (the shared helper gives one to all)."""
    return {**easyauth_headers(email), "X-MS-CLIENT-PRINCIPAL-ID": oid}


OWNER_H, STAFF_H, PARTNER_H = who(OWNER, "oid-owner"), who(STAFF, "oid-staff"), \
    who(PARTNER, "oid-partner")


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import app
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password", "")
    (tmp_path / "mirror").mkdir()
    kits = [{"id": "bobcat", "type": "vdk", "title": "Bobcat IPL", "products": ["Creo"],
             "segment": "CAD", "source_item_id": "F-BOBCAT",
             "resources": [{"name": "Bobcat.mp4", "kind": "video", "item_id": "I-2"}]},
            {"id": "inside", "type": "ldk", "title": "Internal walkthrough", "products": ["Creo"],
             "segment": "CAD", "source_item_id": "F-IN",
             "resources": [{"name": "Inside.zip", "kind": "dataset", "item_id": "I-3"}]}]
    gxc = {"id": "gxc-lamborghini", "type": "video", "title": "Lamborghini walkthrough",
           "products": ["Creo"], "segment": "CAD", "source_item_id": "F-LAMBO",
           "resources": [{"name": "Lambo.mp4", "kind": "video", "item_id": "I-1"}]}
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps(kits), encoding="utf-8")
    (tmp_path / "mirror" / "gxc_video.json").write_text(json.dumps([gxc]), encoding="utf-8")
    access.create_group("GXC", "", ["view_gxc"], [OWNER, PARTNER], "test")
    JsonAssetRepository(str(tmp_path)).set_access("inside", "internal", "user:owner@ptc.com")
    return TestClient(app, base_url="http://localhost")


@pytest.fixture
def shared(client):
    r = client.post("/api/me/playlists", headers=OWNER_H, json={
        "name": "Customer pitch", "items": ["bobcat", "gxc-lamborghini", "inside"]})
    assert r.status_code == 201, r.text
    assert r.json()["items"] == ["bobcat", "gxc-lamborghini", "inside"], "the owner sees all"
    return r.json()["id"]


def test_a_gxc_video_is_counted_never_named_for_a_ptc_reader_without_gxc(client, shared):
    r = client.get(f"/api/me/playlists/{shared}", headers=STAFF_H)
    assert r.status_code == 200
    page = r.json()
    assert [a["id"] for a in page["items"]] == ["bobcat", "inside"]
    assert page["unavailable"] == 1
    assert "Lamborghini" not in r.text and "gxc-lamborghini" not in r.text
    copy = client.post(f"/api/me/playlists/{shared}/copy", headers=STAFF_H).json()
    assert copy["items"] == ["bobcat", "inside"], "a copy holds only what the reader sees"
    # The link grants nothing: the video itself is still not there for them.
    assert client.get("/api/assets/gxc-lamborghini", headers=STAFF_H).status_code == 404


def test_a_partner_sees_a_ptc_only_card_but_not_its_files_and_no_gxc(client, shared):
    r = client.get(f"/api/me/playlists/{shared}", headers=PARTNER_H)
    page = r.json()
    assert [a["id"] for a in page["items"]] == ["bobcat", "inside"], \
        "partners never see GXC, even in the GXC group"
    assert page["unavailable"] == 1 and "Lamborghini" not in r.text
    inside = client.get("/api/assets/inside", headers=PARTNER_H).json()
    assert inside["files_locked"] is True
    assert all(res.get("item_id") is None for res in inside.get("resources") or [])
    bobcat = client.get("/api/assets/bobcat", headers=PARTNER_H).json()
    assert bobcat["files_locked"] is False
    copy = client.post(f"/api/me/playlists/{shared}/copy", headers=PARTNER_H).json()
    assert copy["items"] == ["bobcat", "inside"]
