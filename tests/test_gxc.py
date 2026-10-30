"""GXC videos: a library only "View GXC videos" sees (Liwei, 2026-10-29).

Without the permission a GXC video does not exist on the Hub -- not listed,
not found, and its link opens nothing; with it, it is PTC Only and never
customer facing. Admin switches its downloads, off by default. The
migration sends the sheet's GXC Gallery rows to the GXC library.
"""
from __future__ import annotations

import csv
import json

import pytest
from fastapi.testclient import TestClient

from backend import access, admin_log
from backend.auth import AuthMode
from backend.config import settings
from backend.integrations.graph import video_sync as vs
from backend.repositories.json_repo import GXC_SOURCES, JsonAssetRepository
from backend.services import brightcove_runner as run
from tests.test_auth import easyauth_headers
from tests.test_video_sync import doc_set, mp4

ADMIN, STAFF, MEMBER, PARTNER = "boss@ptc.com", "someone@ptc.com", "gxc@ptc.com", "p@partner.it"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    (tmp_path / "mirror").mkdir()
    kit = {"id": "bobcat", "type": "vdk", "title": "Bobcat IPL", "products": ["Creo"],
           "segment": "CAD", "source_item_id": "F-BOBCAT"}
    gxc = {"id": "gxc-lamborghini", "type": "video", "title": "Lamborghini walkthrough",
           "products": ["Creo"], "segment": "CAD", "source_item_id": "F-LAMBO",
           "customer_facing": True,
           "resources": [{"name": "Lambo.mp4", "kind": "video", "item_id": "I-1"}]}
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps([kit]), encoding="utf-8")
    (tmp_path / "mirror" / "gxc_video.json").write_text(json.dumps([gxc]), encoding="utf-8")
    access.create_group("GXC", "", ["view_gxc"], [MEMBER, PARTNER], "test")
    return JsonAssetRepository(str(tmp_path))


@pytest.fixture
def client(repo, monkeypatch):
    from app import app
    from backend.routers.graph import require_client
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password", "")
    monkeypatch.setattr(settings, "hub_admin_emails", ADMIN)
    app.dependency_overrides[require_client] = lambda: object()
    yield TestClient(app, base_url="http://localhost")
    app.dependency_overrides.clear()


def ids(client, who, **params):
    r = client.get("/api/assets", params=params, headers=easyauth_headers(who))
    assert r.status_code == 200, r.text
    return {a["id"] for a in r.json()["items"]}


def test_without_view_gxc_a_gxc_video_does_not_exist(client):
    assert ids(client, STAFF) == {"bobcat"}
    assert ids(client, STAFF, q="Lamborghini") == set()
    assert client.get("/api/assets/gxc-lamborghini",
                      headers=easyauth_headers(STAFF)).status_code == 404
    related = client.get("/api/assets/bobcat/related", headers=easyauth_headers(STAFF)).json()
    assert "gxc-lamborghini" not in json.dumps(related)


def test_the_gxc_group_and_administrators_see_it_as_ptc_only(client):
    for who in (MEMBER, ADMIN):
        assert ids(client, who) == {"bobcat", "gxc-lamborghini"}, who
        a = client.get("/api/assets/gxc-lamborghini", headers=easyauth_headers(who)).json()
        assert a["gxc"] and a["internal"] and a["customer_facing"] is False, who


def test_a_partner_never_sees_gxc_even_in_the_group(client):
    assert ids(client, PARTNER) == {"bobcat"}


def test_the_hubs_own_jobs_see_everything(repo, tmp_path):
    assert repo.get("gxc-lamborghini") is not None
    assert JsonAssetRepository(str(tmp_path), gxc=False).get("gxc-lamborghini") is None


def test_downloads_are_off_until_admin_switches_them_on(client, repo):
    from backend.routers import assets as assets_router
    get = lambda: client.get("/api/assets/gxc-lamborghini",       # noqa: E731
                             headers=easyauth_headers(MEMBER)).json()
    assert get()["downloads_off"] is True
    r = client.get("/api/assets/gxc-lamborghini/files/I-1/download", follow_redirects=False,
                   headers=easyauth_headers(MEMBER))
    assert r.status_code == 403 and "switched off" in r.json()["detail"]
    assert client.get("/api/assets/bobcat", headers=easyauth_headers(MEMBER)).json()[
        "downloads_off"] is False, "only GXC videos"

    put = lambda who, on: client.put("/api/admin/gxc", json={"downloads": on},  # noqa: E731
                                     headers=easyauth_headers(who))
    assert put(STAFF, True).status_code == 403
    r = put(ADMIN, True)
    assert r.status_code == 200 and r.json()["downloads"] is True
    assert get()["downloads_off"] is False
    assert assets_router._require_gxc_download("gxc-lamborghini", repo) is None
    entry = admin_log._entries()[-1]
    assert entry["action"] == "Switched GXC video downloads"
    assert admin_log.category_of("/api/admin/gxc") == "Content access"


def test_admin_says_which_groups_see_gxc(client):
    s = client.get("/api/admin/gxc", headers=easyauth_headers(ADMIN)).json()
    assert s["library"] == "GXC Video" and s["videos"] == 1 and s["downloads"] is False
    assert {g["name"] for g in s["groups"]} >= {"Administrators", "GXC"}


def test_team_member_is_given_view_gxc_once():
    saved_before = {
        "catalogue": sorted(access.ALL - {"view_gxc"}),
        "groups": [{"id": "tdd-team", "name": "Team Member", "members": ["a@ptc.com"],
                    "permissions": ["view_hub"]},
                   {"id": "tdd", "name": "TDD Team", "members": [], "permissions": ["view_hub"]},
                   {"id": "sales", "name": "Sales", "members": [], "permissions": ["view_hub"]}]}
    with open(access._owned(access.STATE_FILE), "w", encoding="utf-8") as fh:
        json.dump(saved_before, fh)
    groups = {g["id"]: g for g in access.load_state()["groups"]}
    assert "view_gxc" in groups["tdd-team"]["permissions"]
    assert "view_gxc" not in groups["sales"]["permissions"]
    assert "view_gxc" not in groups["tdd"]["permissions"], "only the name production uses"
    assert "view_gxc" not in groups[access.EMPLOYEES]["permissions"]


def test_the_gxc_library_syncs_into_its_own_mirror_with_its_own_ids():
    (a,), result = vs.build_assets([doc_set("Lamborghini walkthrough"),
                                    mp4("Lamborghini walkthrough")], vs.GXC_VIDEO)
    assert a.id == "gxc-lamborghini-walkthrough"
    assert result.as_dict()["source"] == "gxc_video"
    assert vs.library_of(a.id) is vs.GXC_VIDEO
    assert vs.library_of("video-x") is vs.DEMO_VIDEO and vs.library_of("bobcat") is None
    assert {lib.source for lib in vs.LIBRARIES if lib.gxc} == GXC_SOURCES


# ─────────────────────────────────────────────────────────────── migration
def manifest(tmp_path, *rows):
    path = tmp_path / "manifest.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=run.COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return str(path)


def test_a_gxc_row_needs_no_customer_facing_and_is_never_customer_facing(tmp_path):
    gxc, ptc = run.load_manifest(manifest(
        tmp_path,
        {"brightcove_id": "1", "title": "Lambo", "gallery": "GXC Gallery", "customer_facing": "yes"},
        {"brightcove_id": "2", "title": "Change", "gallery": "PTC Gallery"}))
    assert gxc.is_gxc and gxc.customer_facing is False and gxc.problems == []
    assert not ptc.is_gxc and "customer_facing is empty" in ptc.problems
    assert run.fields_for(gxc)["Customer_x0020_Facing"] is False


def test_hub_activity_leaves_out_a_gxc_video_for_whoever_cannot_see_it(client, repo):
    repo.record_usage_event("view", "gxc-lamborghini", actor="user:" + MEMBER)
    url = "/api/reports/activity"
    seen = lambda who: [c["asset_id"] for c in client.get(          # noqa: E731
        url, headers=easyauth_headers(who)).json()["content"]]
    assert seen(STAFF) == [], "not even its id, which spells its title"
    assert seen(MEMBER) == ["gxc-lamborghini"]
