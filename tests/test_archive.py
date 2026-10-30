"""Archiving moves a SharePoint demo's folder into _Archive (A8, 2026-10-28)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend import access
from backend.auth import AuthMode
from backend.config import settings
from backend.integrations.graph.sync import lift_archive
from backend.services import archive as ar
from tests.test_auth import easyauth_headers

TEAM = [{"roles": ["owner"], "grantedToV2": {"siteGroup": {"id": "3"}}},
        {"roles": ["write"], "grantedToV2": {"siteGroup": {"id": "5"}}}]
OPEN = TEAM + [{"roles": ["read"], "grantedToV2": {"siteGroup": {"id": "4"}}}]   # + Visitors


class FakeDrive:
    """root (OPEN) / _Archive (TEAM) / Kit (inherits) / Kit/Videos/a.mp4."""

    def __init__(self):
        self.parent = {"kit": "root", "videos": "kit", "a": "videos", "_arch": "root"}
        self.names = {"kit": "Kit", "videos": "Videos", "a": "a.mp4", "_arch": "_Archive"}
        self.own = {"_arch": TEAM}       # items with permissions of their own
        self.moves = []

    def perms(self, item):
        while item not in self.own and item != "root":
            item = self.parent[item]
        return self.own.get(item, OPEN)

    def _request(self, method, url, params=None, json=None, **kw):
        if url.endswith("/root") and method == "GET":
            return {"id": "root"}
        if url.endswith("/root:/_Archive"):
            return {"id": "_arch", "folder": {}}
        if "/root:/" in url:
            name = url.rsplit("/root:/", 1)[1]
            hit = [i for i, n in self.names.items() if n == name and self.parent[i] == "root"]
            return {"id": hit[0]} if hit else None
        if url.endswith("/permissions"):
            return {"value": self.perms(url.split("/items/")[1].split("/")[0])}
        if method == "PATCH":
            item = url.rsplit("/", 1)[1]
            self.moves.append((item, json["parentReference"]["id"]))
            self.parent[item] = json["parentReference"]["id"]
            return {"id": item}
        if method == "GET" and "/items/" in url:
            item = url.rsplit("/", 1)[1]
            return {"id": item, "name": self.names[item]}
        raise AssertionError(url)

    def _paged(self, url, params=None):
        parent = url.split("/items/")[1].split("/")[0]
        return [{"id": i, "name": self.names[i], **({"folder": {}} if i != "a" else {})}
                for i, p in self.parent.items() if p == parent]


def test_an_inheriting_demo_moves_into_archive_and_back():
    d = FakeDrive()
    ar.archive(d, "drive", "kit")
    assert d.parent["kit"] == "_arch"
    ar.restore(d, "drive", "kit")
    assert d.parent["kit"] == "root"


def test_a_file_with_its_own_permissions_refuses_the_archive_and_nothing_moves():
    d = FakeDrive()
    d.own["a"] = OPEN + [{"roles": ["read"], "link": {"scope": "anonymous"}}]
    with pytest.raises(ar.ArchiveRefused, match="a.mp4"):
        ar.archive(d, "drive", "kit")
    assert d.moves == []


def test_own_permissions_equal_to_the_parents_are_caught_after_the_move():
    """Equal before (passes the first check), still Visitors-open after."""
    d = FakeDrive()
    d.own["kit"] = OPEN
    with pytest.raises(ar.ArchiveRefused, match="Moved back"):
        ar.archive(d, "drive", "kit")
    assert d.moves == [("kit", "_arch"), ("kit", "root")] and d.parent["kit"] == "root"


def test_restore_refuses_when_the_name_is_taken():
    d = FakeDrive()
    ar.archive(d, "drive", "kit")
    d.names["new"], d.parent["new"] = "Kit", "root"
    with pytest.raises(ar.ArchiveRefused, match="already has a folder"):
        ar.restore(d, "drive", "kit")


def test_the_sync_reads_archived_demos_as_themselves():
    items = [{"id": "arch", "name": "_Archive", "folder": {},
              "parentReference": {"path": "/drives/d/root:"}},
             {"id": "kit", "name": "Kit", "folder": {},
              "parentReference": {"path": "/drives/d/root:/_Archive"}},
             {"id": "f", "name": "a.mp4", "file": {},
              "parentReference": {"path": "/drives/d/root:/_Archive/Kit/Videos"}}]
    out, archive_id = lift_archive(items)
    assert archive_id == "arch" and [i["id"] for i in out] == ["kit", "f"]
    assert out[0]["parentReference"]["path"] == "/drives/d/root:" and out[0]["hub_archived"]
    assert out[1]["parentReference"]["path"] == "/drives/d/root:/Kit/Videos"


# ── through the API ───────────────────────────────────────────────────────
@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import app
    import backend.routers.uploads as up
    from backend.integrations.graph import upload_writer as uw
    from backend.services import upload_targets as ut
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password", "")
    (tmp_path / "mirror").mkdir()
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps([
        {"id": "kit", "type": "ldk", "title": "Kit", "source": "sharepoint",
         "source_item_id": "kit", "products": ["Creo"]}]), encoding="utf-8")
    (tmp_path / "mirror" / "consensus.json").write_text(json.dumps([
        {"id": "tour", "type": "video", "title": "Tour", "source": "consensus",
         "source_item_id": "u1"}]), encoding="utf-8")
    drive = FakeDrive()
    monkeypatch.setattr(up, "_client", lambda: drive)
    monkeypatch.setattr(up, "_target", lambda c, key, fresh=False: uw.Target(
        spec=ut.TARGETS[key], site_id="s", drive_id="drive", list_id="l",
        demo_content_type_id="x", product_note_field=None, choices={}, terms=None))
    monkeypatch.setattr(up, "_sync_soon", lambda repo, actor: None)
    access.create_group("Team Member", "", ["view_hub", "maintain_content", "view_admin"],
                        ["team@ptc.com"], "test")
    access.create_group("Viewers", "", ["view_hub", "view_admin"], ["rev@ptc.com"], "test")
    c = TestClient(app, base_url="http://localhost")
    c.drive = drive
    return c


TEAM_USER = easyauth_headers("team@ptc.com")


def test_archiving_needs_maintain_content_and_moves_the_folder(client):
    url = "/api/assets/kit/archive"
    assert client.put(url, json={"archived": True},
                      headers=easyauth_headers("rev@ptc.com")).status_code == 403
    r = client.put(url, json={"archived": True, "reason": "old UI"}, headers=TEAM_USER)
    assert r.status_code == 200, r.text
    assert client.drive.parent["kit"] == "_arch"
    shown = client.get("/api/assets/kit", headers=TEAM_USER).json()
    assert shown["archived"] and shown["sharepoint_archived"]
    listed = client.get("/api/admin/content-review", headers=TEAM_USER).json()["archived"]
    assert listed[0]["where"] == "sharepoint" and listed[0]["in_sharepoint"] is True
    assert client.put(url, json={"archived": False}, headers=TEAM_USER).status_code == 200
    assert client.drive.parent["kit"] == "root"


def test_a_consensus_demo_is_archived_in_the_hub_only(client):
    r = client.put("/api/assets/tour/archive", json={"archived": True}, headers=TEAM_USER)
    assert r.status_code == 200 and client.drive.moves == []
    listed = client.get("/api/admin/content-review", headers=TEAM_USER).json()["archived"]
    assert listed[0]["where"] == "hub"


def test_a_refusal_says_why_and_archives_nothing(client):
    client.drive.own["a"] = OPEN + [{"roles": ["read"], "link": {"scope": "anonymous"}}]
    r = client.put("/api/assets/kit/archive", json={"archived": True}, headers=TEAM_USER)
    assert r.status_code == 422 and "a.mp4" in r.json()["detail"]
    assert not client.get("/api/assets/kit", headers=TEAM_USER).json()["archived"]
