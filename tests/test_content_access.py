"""Open / Internal, merged with the partner rule (2026-10-07)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend import access
from backend.access import EMPLOYEES
from backend.auth import AuthMode
from backend.config import settings
from backend.repositories.json_repo import JsonAssetRepository
from tests.test_auth import easyauth_headers

ADMIN, STAFF, PARTNER = "boss@ptc.com", "someone@ptc.com", "p@partner.it"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    (tmp_path / "mirror").mkdir()
    rows = [{"id": "lambo", "type": "vdk", "title": "Lamborghini IPL", "products": ["Creo"],
             "source_item_id": "F-LAMBO",
             "resources": [{"name": "Lambo.mp4", "kind": "video", "item_id": "I-1"}]},
            {"id": "bobcat", "type": "vdk", "title": "Bobcat IPL", "products": ["Creo"],
             "source_item_id": "F-BOBCAT",
             "resources": [{"name": "Bobcat.mp4", "kind": "video", "item_id": "I-2"}]}]
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps(rows), encoding="utf-8")
    r = JsonAssetRepository(str(tmp_path))
    r.replace_partner_access({"F-LAMBO": True, "F-BOBCAT": False})
    return r


@pytest.fixture
def client(repo, monkeypatch):
    from app import app
    from backend.routers.graph import require_client
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password", "")
    monkeypatch.setattr(settings, "hub_admin_emails", ADMIN)
    # Refused before Graph is reached; CI has no Graph credentials.
    app.dependency_overrides[require_client] = lambda: object()
    yield TestClient(app, base_url="http://localhost")
    app.dependency_overrides.clear()


def file_id(client, who, asset="bobcat"):
    return client.get(f"/api/assets/{asset}", headers=easyauth_headers(who)).json()[
        "resources"][0]["item_id"]


def test_a_folder_closed_to_partners_is_internal(repo):
    lambo, bobcat = repo.get("lambo"), repo.get("bobcat")
    assert (lambo.internal, lambo.internal_source) == (True, "sharepoint")
    assert bobcat.internal is False


def test_a_demo_marked_internal_on_the_hub_closes_to_partners_only(client, repo):
    assert file_id(client, PARTNER) == "I-2"
    repo.set_access("bobcat", "internal", "user:" + ADMIN)
    assert file_id(client, PARTNER) is None
    assert file_id(client, STAFF) == "I-2", "PTC employees have Access internal content"
    assert client.get("/api/assets/bobcat/files/I-2/download", follow_redirects=False,
                      headers=easyauth_headers(PARTNER)).status_code == 403
    asset = client.get("/api/assets/bobcat", headers=easyauth_headers(PARTNER)).json()
    assert asset["files_locked"] and asset["internal_source"] == "hub"


def test_the_permission_decides_not_the_account_type(client, repo):
    """One rule now: a group without Access internal content is shut out of
    Internal demos too, and a partner given it gets in."""
    access.update_group(EMPLOYEES, "a", permissions=["view_hub", "preview", "download"])
    assert file_id(client, STAFF, "lambo") is None
    access.create_group("Trusted partners", "", ["access_internal"], [PARTNER], "a")
    assert file_id(client, PARTNER, "lambo") == "I-1"


def test_opening_on_the_hub_cannot_open_a_folder_sharepoint_closed(repo):
    repo.set_access("lambo", "internal", "a")
    repo.set_access("lambo", "open", "a")
    assert repo.get("lambo").internal_source == "sharepoint"


def test_the_marks_are_hub_owned_and_listed_with_their_reason(repo, tmp_path):
    repo.set_access("bobcat", "internal", "user:" + ADMIN)
    assert (tmp_path / "owned" / "content_access.json").exists()
    listing = {i["asset_id"]: i for i in repo.content_access()}
    assert listing["bobcat"]["source"] == "hub" and listing["bobcat"]["marked_by"] == "user:" + ADMIN
    assert listing["lambo"]["source"] == "sharepoint"
    assert [i["asset_id"] for i in repo.content_access()] == ["bobcat", "lambo"], "Hub marks first"


def test_only_manage_content_access_may_change_it(client):
    put = lambda who, level="internal", asset="bobcat": client.put(   # noqa: E731
        f"/api/assets/{asset}/access", json={"level": level}, headers=easyauth_headers(who))
    assert put(STAFF).status_code == 403
    r = put(ADMIN)
    assert r.status_code == 200 and r.json() == {
        "asset_id": "bobcat", "internal": True, "internal_source": "hub"}
    assert put(ADMIN, "secret").status_code == 422
    assert put(ADMIN, asset="nope").status_code == 404
    assert client.get("/api/admin/content-access",
                      headers=easyauth_headers(ADMIN)).status_code == 200
    assert client.get("/api/admin/content-access",
                      headers=easyauth_headers(STAFF)).status_code == 403
