"""API tokens: a program creating demos through the API (Seb, 2026-10-15)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend import access, api_tokens
from backend.auth import AuthMode
from backend.config import settings
from tests.test_auth import easyauth_headers
from tests.test_uploads import FILES, KIT, FakeSharePoint

BOSS = easyauth_headers("boss@ptc.com")
ANN = easyauth_headers("ann@ptc.com")


@pytest.fixture
def sp(monkeypatch):
    fake = FakeSharePoint()
    fake.install(monkeypatch)
    return fake


@pytest.fixture
def client(tmp_path, monkeypatch, sp):
    from app import app
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password", "")
    monkeypatch.setattr(settings, "hub_admin_emails", "boss@ptc.com")
    (tmp_path / "mirror").mkdir()
    (tmp_path / "mirror" / "sharepoint.json").write_text("[]", encoding="utf-8")
    return TestClient(app, base_url="http://localhost")


def issue(client, **kw):
    body = {"name": "AMP pipeline", "owner": "seb@ptc.com",
            "permissions": ["view_hub", "upload_content"], **kw}
    return client.post("/api/admin/api-tokens", json=body, headers=BOSS)


def bearer(secret):
    return {"Authorization": f"Bearer {secret}"}


def create_demo(client, sp, secret):
    r = client.post("/api/uploads", json={"target": "demo_catalog", "kind": "ldk",
                                          "values": KIT, "files": FILES}, headers=bearer(secret))
    assert r.status_code == 201, r.text
    record = r.json()
    for i, f in enumerate(record["files"]):
        client.post(f"/api/uploads/{record['id']}/files/{i}/session", headers=bearer(secret))
        sp.items[f"item-{i}"] = {"id": f"item-{i}", "size": f["size"],
                                 "name": f["path"].rsplit("/", 1)[-1]}
        assert client.post(f"/api/uploads/{record['id']}/files/{i}/done",
                           json={"item_id": f"item-{i}"}, headers=bearer(secret)).status_code == 200
    return client.post(f"/api/uploads/{record['id']}/finish", headers=bearer(secret)).json()


def test_issuing_needs_manage_users_and_the_secret_is_shown_once(client, tmp_path):
    assert client.post("/api/admin/api-tokens", json={"name": "x", "owner": "a@ptc.com",
                                                      "permissions": ["view_hub"]},
                       headers=ANN).status_code == 403
    r = issue(client)
    assert r.status_code == 201
    secret = r.json()["secret"]
    assert secret.startswith("tmh_")
    listed = client.get("/api/admin/api-tokens", headers=BOSS).json()["tokens"]
    assert listed[0]["status"] == "active" and "hash" not in listed[0]
    assert secret not in json.dumps(listed), "never shown again"
    raw = open(access._owned(api_tokens.FILE), encoding="utf-8").read()
    assert secret not in raw, "only its hash is kept"


def test_a_token_never_carries_an_administrative_permission(client):
    for perm in ("view_admin", "manage_users", "review_content", "manage_content_access"):
        assert issue(client, name=perm, permissions=["view_hub", perm]).status_code == 422


def test_a_token_creates_a_demo_that_waits_for_review(client, sp):
    secret = issue(client).json()["secret"]
    done = create_demo(client, sp, secret)
    assert done["status"] == "pending" and done["uploaded_by"] == "token:AMP pipeline"
    log = client.get("/api/admin/admin-log?category=Uploads", headers=BOSS).json()["items"]
    assert {e["actor"] for e in log} == {"token:AMP pipeline"}


def test_a_token_without_review_publishes_on_submission(client, sp):
    secret = issue(client, skip_review=True).json()["secret"]
    assert create_demo(client, sp, secret)["status"] == "published"


def test_what_a_token_cannot_do(client, sp):
    reader = issue(client, name="Reader", permissions=["view_hub"]).json()["secret"]
    r = client.post("/api/uploads", json={"target": "demo_catalog", "kind": "ldk",
                                          "values": KIT, "files": FILES}, headers=bearer(reader))
    assert r.status_code == 403
    assert client.get("/api/admin/api-tokens", headers=bearer(reader)).status_code == 403
    # An unknown token is nobody (easyauth here; the OIDC gate refuses it, below).
    assert client.post("/api/uploads", json={}, headers=bearer("tmh_nope_nope")).status_code == 401


def test_revoked_and_expired_tokens_stop_working(client, sp):
    created = issue(client).json()
    secret, token_id = created["secret"], created["token"]["id"]
    start = {"target": "demo_catalog", "kind": "ldk", "values": KIT, "files": FILES}
    client.post(f"/api/admin/api-tokens/{token_id}/revoke", headers=BOSS)
    assert client.post("/api/uploads", json=start, headers=bearer(secret)).status_code == 401
    secret = issue(client, name="Short").json()["secret"]
    items = json.load(open(access._owned(api_tokens.FILE), encoding="utf-8"))
    for t in items:
        t["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    json.dump(items, open(access._owned(api_tokens.FILE), "w", encoding="utf-8"))
    assert client.post("/api/uploads", json=start, headers=bearer(secret)).status_code == 401


def test_internal_asked_for_at_creation_holds_before_and_after_indexing(client, sp, tmp_path):
    access.create_group("Makers", "", ["view_hub", "upload_content"], ["maker@ptc.com"], "t")
    maker = easyauth_headers("maker@ptc.com")
    r = client.post("/api/uploads", json={"target": "demo_catalog", "kind": "ldk", "values": KIT,
                                          "files": FILES, "internal": True}, headers=maker)
    record = r.json()
    for i, f in enumerate(record["files"]):
        sp.items[f"item-{i}"] = {"id": f"item-{i}", "size": f["size"],
                                 "name": f["path"].rsplit("/", 1)[-1]}
        client.post(f"/api/uploads/{record['id']}/files/{i}/done", json={"item_id": f"item-{i}"},
                    headers=maker)
    client.post(f"/api/uploads/{record['id']}/finish", headers=maker)
    client.post(f"/api/uploads/{record['id']}/publish", json={}, headers=BOSS)
    # Indexed only now, after publishing: still Internal.
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps([
        {"id": "creo-sheetmetal-kit", "type": "ldk", "title": "Creo Sheetmetal Kit",
         "products": ["Creo"], "source_item_id": record["folder_id"]}]), encoding="utf-8")
    assert client.get("/api/assets/creo-sheetmetal-kit", headers=ANN).json()["internal"] is True
    client.put("/api/assets/creo-sheetmetal-kit/access", json={"level": "open"}, headers=BOSS)
    assert client.get("/api/assets/creo-sheetmetal-kit", headers=ANN).json()["internal"] is False


def test_under_sign_in_a_token_reaches_the_api_and_nothing_else(tmp_path, monkeypatch):
    from app import app
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "auth_mode", AuthMode.OIDC.value)
    (tmp_path / "mirror").mkdir()
    (tmp_path / "mirror" / "sharepoint.json").write_text("[]", encoding="utf-8")
    _, secret = api_tokens.create(name="Reader", owner="seb@ptc.com", permissions=["view_hub"],
                                  days=30, skip_review=False, actor="test")
    _, no_hub = api_tokens.create(name="Downloads only", owner="seb@ptc.com",
                                  permissions=["download"], days=30, skip_review=False,
                                  actor="test")
    c = TestClient(app, base_url="http://localhost", follow_redirects=False)
    assert c.get("/api/assets", headers=bearer(secret)).status_code == 200
    assert c.get("/", headers=bearer(secret)).status_code == 403, "pages are not for tokens"
    assert c.get("/api/assets", headers=bearer("tmh_bad_token")).status_code == 401
    assert c.get("/api/assets", headers=bearer(no_hub)).status_code == 403
    assert c.get("/api/assets").status_code == 401, "no token, no session: sign in"
