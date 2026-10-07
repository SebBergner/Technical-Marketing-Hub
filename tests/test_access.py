"""Users, groups and permissions (backend/access.py, 2026-10-06)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend import access
from backend.access import ADMINS, EMPLOYEES, PARTNERS, Perm
from backend.auth import ANONYMOUS, DEV_PRINCIPAL, AuthMode, CurrentUser
from backend.config import settings
from tests.test_auth import easyauth_headers

ME = "liwchen@ptc.com"


def person(email, **kw):
    return CurrentUser(email=email, is_authenticated=True, **kw)


@pytest.fixture(autouse=True)
def no_named_admins_or_curators(monkeypatch):
    """A developer's .env may name either; the rules are tested from zero."""
    for name in ("hub_admin_emails", "auth_curator_groups", "auth_curator_emails",
                 "auth_curator_oids"):
        monkeypatch.setattr(settings, name, "")


# ─────────────────────────────────────────────── who gets what by default
def test_staff_partners_and_nobody_by_default():
    staff = person("someone@ptc.com").permissions
    assert {Perm(p) for p in staff} == {Perm.VIEW_HUB, Perm.PREVIEW, Perm.DOWNLOAD,
                                        Perm.INTERNAL, Perm.CREATE_DEMO}
    partner = person("p@partner.it").permissions
    assert {Perm(p) for p in partner} == {Perm.VIEW_HUB, Perm.PREVIEW, Perm.DOWNLOAD}
    assert ANONYMOUS.permissions == frozenset()


def test_a_guest_token_is_a_partner_whatever_the_address():
    groups = [g["id"] for g in access.groups_of(person("x@ptc.com", external=True))]
    assert groups == [PARTNERS]


def test_the_bootstrap_admin_has_everything(monkeypatch):
    monkeypatch.setattr(settings, "hub_admin_emails", f" {ME.upper()} , other@ptc.com")
    assert person(ME).permissions == access.ALL
    assert [g["id"] for g in access.groups_of(person(ME))] == [ADMINS, EMPLOYEES]


def test_admins_are_matched_on_the_upn_as_well_as_the_email(monkeypatch):
    monkeypatch.setattr(settings, "hub_admin_emails", ME)
    assert person("liwei.alias@ptc.com", username=ME).can(Perm.MANAGE_USERS)


def test_local_development_has_everything_but_the_admin_page():
    """So the Admin page still needs a real sign-in on a laptop, as before."""
    assert not DEV_PRINCIPAL.can(Perm.VIEW_ADMIN)
    assert not DEV_PRINCIPAL.can(Perm.MANAGE_USERS)
    assert DEV_PRINCIPAL.can(Perm.RUN_SYNC) and DEV_PRINCIPAL.can(Perm.EDIT_METADATA)


def test_the_curator_settings_still_grant_edit_metadata_only():
    seb = person("seb@ptc.com", roles={"viewer", "curator"})
    assert seb.can(Perm.EDIT_METADATA) and not seb.can(Perm.RUN_MIGRATION)


# ─────────────────────────────────────────────── groups
def test_a_group_grants_its_members_its_permissions_and_is_audited():
    access.create_group("Marketing ops", "", [Perm.MANAGE_HOME.value, "not-a-perm"],
                        ["Elio@PTC.com"], "user:" + ME)
    elio = person("elio@ptc.com")
    assert elio.can(Perm.MANAGE_HOME) and elio.can(Perm.INTERNAL), "union with PTC employees"
    assert not person("other@ptc.com").can(Perm.MANAGE_HOME)
    group = access.load_state()["groups"][-1]
    assert (group["id"], group["permissions"], group["members"]) == (
        "marketing-ops", ["manage_home"], ["elio@ptc.com"])
    [entry] = access.audit_log()
    assert (entry["actor"], entry["action"], entry["group"]) == (
        "user:" + ME, "create", "marketing-ops")


def test_changes_are_audited_with_what_changed():
    access.create_group("Reviewers", "", [], [], "a")
    access.update_group("reviewers", "b", permissions=["edit_metadata"], members=["x@ptc.com"])
    access.update_group("reviewers", "c", members=[])
    latest, middle = access.audit_log()[:2]
    assert middle["permissions"] == {"added": ["edit_metadata"], "removed": []}
    assert middle["members"] == {"added": ["x@ptc.com"], "removed": []}
    assert latest["members"] == {"added": [], "removed": ["x@ptc.com"]}
    access.update_group("reviewers", "d", members=[])
    assert len(access.audit_log()) == 3, "no change, no entry"


def test_partners_permissions_can_be_changed():
    access.update_group(PARTNERS, "a", permissions=["view_hub"])
    assert person("p@partner.it").permissions == frozenset({"view_hub"})


@pytest.mark.parametrize("change, message", [
    (lambda: access.delete_group(ADMINS, "a"), "built in"),
    (lambda: access.delete_group(PARTNERS, "a"), "built in"),
    (lambda: access.update_group(ADMINS, "a", permissions=[]), "every permission"),
    (lambda: access.update_group(EMPLOYEES, "a", members=["x@ptc.com"]), "automatically"),
    (lambda: access.update_group(ADMINS, "a", members=[]), "cannot be left empty"),
    (lambda: access.create_group("Administrators", "", [], [], "a"), "already a group"),
    (lambda: access.create_group("New", "", [], ["not an email"], "a"), "Not an email"),
    (lambda: access.create_group("  ", "", [], [], "a"), "needs a name"),
])
def test_what_the_rules_refuse(change, message):
    with pytest.raises(access.AccessError, match=message):
        change()


def test_a_damaged_file_falls_back_to_the_built_in_groups(tmp_path, monkeypatch):
    (tmp_path / "access.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(access, "_owned", lambda name: str(tmp_path / name))
    assert [g["id"] for g in access.load_state()["groups"]] == [ADMINS, EMPLOYEES, PARTNERS]


def test_known_users_are_shown_with_their_groups(monkeypatch):
    monkeypatch.setattr(settings, "hub_admin_emails", ME)
    access.record_sign_in(oid="1", email=ME, username=ME, name="Liwei", external=False)
    access.record_sign_in(oid="2", email=None, username="p@partner.it", name="P", external=True)
    access.record_sign_in(oid="1", email=ME, username=ME, name="Liwei Chen", external=False)
    users = {u["oid"]: u for u in access.users_view()}
    assert len(users) == 2 and users["1"]["name"] == "Liwei Chen"
    assert users["1"]["groups"] == [ADMINS, EMPLOYEES] and users["2"]["groups"] == [PARTNERS]


# ─────────────────────────────────────────────── the endpoints
@pytest.fixture
def client(monkeypatch):
    from app import app
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password", "")
    monkeypatch.setattr(settings, "hub_admin_emails", ME)
    return TestClient(app, base_url="http://localhost")


def test_an_sso_admin_opens_the_admin_page_without_the_password(client):
    session = client.get("/api/admin/session", headers=easyauth_headers(ME)).json()
    assert (session["signed_in"], session["via"]) == (True, "sso")
    assert client.get("/api/admin/overview", headers=easyauth_headers(ME)).status_code == 200


def test_staff_without_view_admin_are_refused_with_403(client):
    staff = easyauth_headers("someone@ptc.com")
    assert client.get("/api/admin/session", headers=staff).json()["signed_in"] is False
    assert client.get("/api/admin/overview", headers=staff).status_code == 403
    assert client.get("/api/admin/access").status_code == 401


def test_view_admin_alone_reads_groups_but_cannot_change_anything(client):
    access.create_group("Viewers", "", ["view_admin"], ["v@ptc.com"], "a")
    viewer = easyauth_headers("v@ptc.com")
    assert client.get("/api/admin/access", headers=viewer).status_code == 200
    assert client.post("/api/admin/access/groups", headers=viewer,
                       json={"name": "X"}).status_code == 403
    assert client.put("/api/admin/promoted", headers=viewer,
                      json={"asset_ids": []}).status_code == 403


def test_an_admin_manages_groups_through_the_api(client):
    me = easyauth_headers(ME)
    r = client.post("/api/admin/access/groups", headers=me,
                    json={"name": "Sales engineers", "permissions": ["view_hub"],
                          "members": ["se@ptc.com"]})
    assert r.status_code == 201, r.text
    assert r.json()["groups"][-1]["id"] == "sales-engineers"
    assert r.json()["audit"][0]["actor"] == f"user:{ME}"
    r = client.put("/api/admin/access/groups/sales-engineers", headers=me,
                   json={"members": ["se@ptc.com", "se2@ptc.com"]})
    assert r.json()["groups"][-1]["members"] == ["se2@ptc.com", "se@ptc.com"]
    assert client.put("/api/admin/access/groups/administrators", headers=me,
                      json={"permissions": []}).status_code == 422
    assert client.delete("/api/admin/access/groups/nope", headers=me).status_code == 404
    assert client.delete("/api/admin/access/groups/sales-engineers",
                         headers=me).status_code == 200


def test_auth_me_lists_the_permissions_the_pages_use(client):
    body = client.get("/api/auth/me", headers=easyauth_headers("p@partner.it")).json()
    assert body["user"]["permissions"] == ["download", "preview", "view_hub"]


def test_a_group_without_create_demo_cannot_submit_a_request(client):
    access.update_group(EMPLOYEES, "a", permissions=["view_hub"])
    r = client.post("/api/requests", headers=easyauth_headers("someone@ptc.com"), json={})
    assert r.status_code == 403


def test_without_download_the_file_is_refused(client, tmp_path, monkeypatch):
    from app import app
    from backend.routers.graph import require_client
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    (tmp_path / "mirror").mkdir()
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps([
        {"id": "bobcat", "type": "vdk", "title": "Bobcat", "products": ["Creo"],
         "resources": [{"name": "B.mp4", "kind": "video", "item_id": "I-2"}]}]),
        encoding="utf-8")
    # Refused before Graph is reached; CI has no Graph credentials.
    app.dependency_overrides[require_client] = lambda: object()
    try:
        access.update_group(EMPLOYEES, "a", permissions=["view_hub", "preview"])
        r = client.get("/api/assets/bobcat/files/I-2/download",
                       headers=easyauth_headers("someone@ptc.com"), follow_redirects=False)
        assert r.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_with_neither_preview_nor_download_the_file_ids_are_withheld(client, tmp_path, monkeypatch):
    """Like a partner on a closed folder: the names, not the ids that open them."""
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    (tmp_path / "mirror").mkdir()
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps([
        {"id": "bobcat", "type": "vdk", "title": "Bobcat", "products": ["Creo"],
         "resources": [{"name": "B.mp4", "kind": "video", "item_id": "I-2"}]}]),
        encoding="utf-8")
    staff = easyauth_headers("someone@ptc.com")
    assert client.get("/api/assets/bobcat", headers=staff).json()["resources"][0]["item_id"] == "I-2"
    access.update_group(EMPLOYEES, "a", permissions=["view_hub"])
    body = client.get("/api/assets/bobcat", headers=staff).json()
    assert body["files_locked"] is True and body["resources"][0]["item_id"] is None

