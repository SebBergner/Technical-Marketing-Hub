"""View the Hub as a group (A9, 2026-11-16): docs/A9-view-as-plan.md."""
from __future__ import annotations

import hashlib
import json
import os
import re

import pytest
from fastapi.testclient import TestClient

from backend import access, activity
from backend.auth import AuthMode
from backend.config import settings
from tests.test_auth import easyauth_headers

BOSS, ANN = "boss@ptc.com", "ann@ptc.com"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import app
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    (tmp_path / "mirror").mkdir()
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps([
        {"id": "bobcat", "type": "vdk", "title": "Bobcat IPL", "products": ["Creo"],
         "resources": [{"name": "B.mp4", "kind": "video", "item_id": "I-2"}]}]),
        encoding="utf-8")
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password", "")
    monkeypatch.setattr(settings, "hub_admin_emails", BOSS)
    monkeypatch.setattr(activity, "_written", {})
    return TestClient(app, base_url="http://localhost")


def H(email=BOSS):
    return easyauth_headers(email)


def start(client, group, who=BOSS):
    return client.post("/api/admin/view-as", json={"group_id": group}, headers=H(who))


def me(client, who=BOSS):
    return client.get("/api/auth/me", headers=H(who)).json()


def exit_preview(client, who=BOSS):
    return client.post("/api/admin/view-as/exit", headers=H(who))


def _routes():
    """(method, path) for every API route, from the OpenAPI document: the
    router objects are nested in this FastAPI, so app.routes alone misses them."""
    from app import app
    out = []
    for path, ops in app.openapi()["paths"].items():
        for method in ops:
            if method.upper() in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                out.append((method.upper(), path))
    return out


def snapshot(root):
    out = {}
    for base, _, files in os.walk(root):
        for name in files:
            path = os.path.join(base, name)
            with open(path, "rb") as fh:
                out[os.path.relpath(path, root)] = hashlib.sha256(fh.read()).hexdigest()
    return out


# ───────────────────────────────────────────────────────── the permissions
def test_partners_are_previewed_as_partners_with_only_what_a_partner_may_hold(client):
    assert start(client, access.PARTNERS).status_code == 200
    user = me(client)["user"]
    assert user["is_partner"] is True
    assert set(user["permissions"]) <= access.PARTNER_ALLOWED
    assert user["view_as"]["label"] == "Partners"
    assert user["email"] is None and user["object_id"] is None


def test_ptc_employees_are_not_partners_and_lose_the_admins_own_rights(client):
    start(client, access.EMPLOYEES)
    user = me(client)["user"]
    assert user["is_partner"] is False
    assert "maintain_content" not in user["permissions"]
    assert "manage_users" not in user["permissions"]
    assert "view_hub" in user["permissions"] and "access_internal" in user["permissions"]


def test_a_hand_made_group_is_previewed_together_with_ptc_employees(client):
    group = access.create_group("Team Member", "", [access.Perm.MAINTAIN.value], [ANN], BOSS)
    assert start(client, group["id"]).json()["label"] == "Team Member (with PTC employees)"
    perms = set(me(client)["user"]["permissions"])
    assert {"maintain_content", "view_hub", "download"} <= perms
    assert "view_gxc" not in perms and "manage_users" not in perms


def test_a_preview_never_raises_what_the_person_may_do():
    """A group holding more than the real person gives them nothing extra."""
    access.create_group("Powerful", "", sorted(access.ALL), [], "x")
    real = {"view_hub", "manage_users"}
    assert set(access.preview_profile("powerful", real)["permissions"]) == real


def test_only_someone_who_manages_groups_may_start(client):
    assert start(client, access.PARTNERS, who=ANN).status_code == 403
    assert me(client, who=ANN)["user"]["view_as"] is None


def test_an_unknown_group_is_404_and_nothing_starts(client):
    assert start(client, "no-such-group").status_code == 404
    assert me(client)["user"]["view_as"] is None


def test_a_second_start_is_refused_until_exit(client):
    start(client, access.PARTNERS)
    assert start(client, access.EMPLOYEES).status_code == 403   # a write: refused by the guard
    assert me(client)["user"]["view_as"]["group_id"] == access.PARTNERS


def test_exit_gives_the_person_back_their_own_account(client):
    start(client, access.PARTNERS)
    assert exit_preview(client).json() == {"ok": True, "was_on": True}
    user = me(client)["user"]
    assert user["view_as"] is None and user["email"] == BOSS and "manage_users" in user["permissions"]
    assert exit_preview(client).json()["was_on"] is False        # leaving twice is harmless


# ───────────────────────────────────────────────────────── read-only
def test_a_preview_refuses_writes_with_one_message(client):
    start(client, access.EMPLOYEES)
    r = client.put("/api/me/favorites/bobcat", headers=H())
    assert r.status_code == 403
    assert r.headers["X-Hub-View-As"] == "read-only"
    assert "Read-only" in r.json()["detail"] and "PTC employees" in r.json()["detail"]
    assert client.get("/api/assets/bobcat", headers=H()).status_code == 200   # reading still works


def test_the_pages_own_telemetry_is_dropped_quietly(client, tmp_path):
    start(client, access.EMPLOYEES)
    for path, body in [("/api/assets/search-event", {"q": "creo", "results": 1}),
                       ("/api/assets/feature-event", {"feature": "my_hub"}),
                       ("/api/assets/bobcat/view", None),
                       ("/api/assets/bobcat/consensus-preview", None),
                       ("/api/welcome/seen", None), ("/api/welcome/shown", None)]:
        r = client.post(path, json=body, headers=H()) if body else client.post(path, headers=H())
        assert r.status_code == 204, path
    assert not (tmp_path / "owned" / "usage_events.jsonl").exists()


def test_every_write_route_is_refused_in_a_preview(client):
    """Enumerated, not hand-listed: a route added later is covered."""
    start(client, access.EMPLOYEES)
    wrong, checked = [], 0
    for method, path in _routes():
        if method == "GET" or path == "/api/admin/view-as/exit" or not path.startswith("/api/"):
            continue
        url = re.sub(r"\{[^}]+\}", "x", path.replace("{asset_id}", "bobcat"))
        r = client.request(method, url, json={}, headers=H())
        checked += 1
        if not (r.status_code == 204 or (r.status_code == 403
                                         and r.headers.get("X-Hub-View-As") == "read-only")):
            wrong.append((method, path, r.status_code))
    assert checked > 50, checked
    assert not wrong, wrong


def test_the_consensus_oauth_gets_are_refused_too(client):
    start(client, access.EMPLOYEES)
    assert client.get("/api/consensus/oauth/start", headers=H()).status_code == 403


def test_no_file_under_the_data_folder_changes_during_a_preview(client, tmp_path):
    start(client, access.PARTNERS)
    before = snapshot(tmp_path)
    for path in ["/api/auth/me", "/api/assets", "/api/assets/bobcat", "/api/me", "/api/me/favorites",
                 "/api/me/playlists", "/api/welcome", "/api/disclaimer", "/api/activity"]:
        client.get(path, headers=H())
    client.post("/api/assets/search-event", json={"q": "x", "results": 0}, headers=H())
    client.post("/api/assets/bobcat/view", headers=H())
    client.get("/api/assets/bobcat/files/I-2/preview", headers=H())
    assert snapshot(tmp_path) == before


# ───────────────────────────────────────────────────────── session and log
def test_a_preview_belongs_to_the_person_who_started_it(client):
    """Same cookie, another account: the preview is dropped, not inherited."""
    start(client, access.PARTNERS)
    other = easyauth_headers("other@ptc.com")
    other["X-MS-CLIENT-PRINCIPAL-ID"] = "oid-999"
    user = client.get("/api/auth/me", headers=other).json()["user"]
    assert user["view_as"] is None and user["email"] == "other@ptc.com"


def test_a_deleted_group_ends_the_preview_and_says_so_in_the_admin_log(client):
    group = access.create_group("Temp", "", [access.Perm.VIEW_HUB.value], [], BOSS)
    start(client, group["id"])
    access.delete_group(group["id"], BOSS)
    assert me(client)["user"]["view_as"] is None
    log = client.get("/api/admin/admin-log", headers=H()).json()
    assert any("Preview ended: the group was deleted" in e["action"] for e in log["items"])


def test_start_and_exit_are_logged_by_the_real_person(client):
    start(client, access.PARTNERS)
    exit_preview(client)
    entries = client.get("/api/admin/admin-log", headers=H()).json()["items"]
    mine = [e for e in entries if e["action"].endswith("viewing the Hub as a group")]
    assert {e["action"] for e in mine} == {"Started viewing the Hub as a group",
                                           "Stopped viewing the Hub as a group"}
    assert all(e["actor"] == f"user:{BOSS}" and e["target"] == "Partners" for e in mine)


def test_the_shared_admin_password_cannot_lift_a_preview(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "pw-for-tests")
    assert client.post("/api/admin/login", json={"username": "admin", "password": "pw-for-tests"}
                       ).status_code == 200
    start(client, access.PARTNERS)
    state = client.get("/api/admin/session", headers=H()).json()
    assert state["via"] is None and state["permissions"] == []


def test_an_api_token_is_never_previewed(client):
    from backend import api_tokens
    _, secret = api_tokens.create(name="t", owner=BOSS, permissions=["view_hub"], days=1,
                                  actor="x")
    start(client, access.PARTNERS)                  # the session now holds a preview
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {secret}"})
    assert r.status_code == 200 and r.json()["user"]["view_as"] is None
    assert r.json()["user"]["permissions"] == ["view_hub"]


def test_the_local_development_principal_may_start_one(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", AuthMode.DISABLED.value)
    assert client.post("/api/admin/view-as", json={"group_id": access.PARTNERS}).status_code == 200
    assert client.get("/api/auth/me").json()["user"]["view_as"]["label"] == "Partners"
    assert client.post("/api/admin/view-as/exit").json()["was_on"] is True


def test_my_hub_is_empty_in_a_preview_and_nothing_of_the_persons_own_shows(client, tmp_path):
    from backend.services import my_hub
    my_hub.set_favorite("oid:oid-123", "bobcat", True)
    start(client, access.PARTNERS)
    assert client.get("/api/me/favorites", headers=H()).json() == {"ids": []}


# ───────────────────────────────────────────────────────── the route sweep
def _get_urls():
    urls = []
    for method, path in _routes():
        if method != "GET" or not path.startswith("/api/"):
            continue
        if path.startswith("/api/consensus/oauth") or path.endswith(".csv") or path.endswith("/download"):
            continue
        urls.append(re.sub(r"\{[^}]+\}", "x", path.replace("{asset_id}", "bobcat")))
    return sorted(set(urls))


def _sweep(client, group, real_who, preview_who=BOSS):
    """Status of every GET route as a real member, and as the administrator
    previewing the same group. A difference is a bug or must be explained."""
    assert len(_get_urls()) > 50
    real = {u: client.get(u, headers=H(real_who)).status_code for u in _get_urls()}
    start(client, group, who=preview_who)
    seen = {u: client.get(u, headers=H(preview_who)).status_code for u in _get_urls()}
    exit_preview(client, who=preview_who)
    return {u: (real[u], seen[u]) for u in real if real[u] != seen[u]}


#: Routes whose answer is rightly different: they are about the signed-in
#: person themselves, which a preview deliberately is not.
PERSONAL = {"/api/auth/me", "/api/me", "/api/me/requests", "/api/me/feedback", "/api/me/demos",
            "/api/me/playlists", "/api/me/favorites", "/api/me/recent", "/api/disclaimer",
            "/api/welcome", "/api/consensus/users/me"}


def test_a_previewed_partner_gets_the_same_answers_as_a_real_partner(client):
    diff = _sweep(client, access.PARTNERS, "someone@outside-company.it")
    assert {u: d for u, d in diff.items() if u not in PERSONAL} == {}


def test_a_previewed_employee_gets_the_same_answers_as_a_real_employee(client):
    diff = _sweep(client, access.EMPLOYEES, ANN)
    assert {u: d for u, d in diff.items() if u not in PERSONAL} == {}


def test_no_get_route_fails_with_a_server_error_in_a_preview(client):
    start(client, access.PARTNERS)
    errors = {u: client.get(u, headers=H()).status_code for u in _get_urls()}
    assert {u: c for u, c in errors.items() if c in (401, 500)} == {}   # 503 = an integration that is off here
