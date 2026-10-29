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


def test_a_token_creates_a_demo_that_is_published_at_once(client, sp):
    """No review for anyone, tokens included (Liwei, 2026-10-28)."""
    secret = issue(client).json()["secret"]
    done = create_demo(client, sp, secret)
    assert done["status"] == "published" and done["uploaded_by"] == "token:AMP pipeline"
    log = client.get("/api/admin/admin-log?category=Uploads", headers=BOSS).json()["items"]
    assert {e["actor"] for e in log} == {"token:AMP pipeline"}


def test_an_old_skip_review_flag_is_simply_ignored(client, sp):
    r = issue(client, skip_review=True)
    assert r.status_code == 201 and "skip_review" not in r.json()["token"]
    assert create_demo(client, sp, r.json()["secret"])["status"] == "published"


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
    assert client.post(f"/api/uploads/{record['id']}/finish",
                       headers=maker).json()["status"] == "published"
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
                                  days=30, actor="test")
    _, no_hub = api_tokens.create(name="Downloads only", owner="seb@ptc.com",
                                  permissions=["download"], days=30, actor="test")
    c = TestClient(app, base_url="http://localhost", follow_redirects=False)
    assert c.get("/api/assets", headers=bearer(secret)).status_code == 200
    assert c.get("/", headers=bearer(secret)).status_code == 403, "pages are not for tokens"
    assert c.get("/api/assets", headers=bearer("tmh_bad_token")).status_code == 401
    assert c.get("/api/assets", headers=bearer(no_hub)).status_code == 403
    assert c.get("/api/assets").status_code == 401, "no token, no session: sign in"


def start_for(client, secret, submitted_by):
    return client.post("/api/uploads", json={"target": "demo_catalog", "kind": "ldk",
                                             "values": KIT, "files": FILES,
                                             "submitted_by": submitted_by},
                       headers=bearer(secret))


def test_any_token_may_name_who_an_upload_is_for(client, sp):
    """Seb, 2026-10-20/21: one token, several people using his tool -- always
    available, no special token needed."""
    secret = issue(client).json()["secret"]
    assert start_for(client, secret, "p@partner.it").status_code == 422, "a PTC person only"
    r = start_for(client, secret, "Ann@PTC.com")
    assert r.status_code == 201, r.text
    record = r.json()
    assert (record["uploaded_by"], record["submitted_by"], record["person"]) ==         ("token:AMP pipeline", "ann@ptc.com", "ann@ptc.com")
    assert record["warnings"] == []
    log = client.get("/api/admin/admin-log?category=Uploads", headers=BOSS).json()
    assert "ann@ptc.com" in json.dumps(log).lower(), "the Admin log keeps the request body"


def test_without_submitted_by_every_answer_warns(client, sp):
    secret = issue(client).json()["secret"]
    record = client.post("/api/uploads", json={"target": "demo_catalog", "kind": "ldk",
                                               "values": KIT, "files": FILES},
                         headers=bearer(secret)).json()
    assert record["submitted_by"] is None and record["person"] == "seb@ptc.com"
    assert "submitted_by is empty" in record["warnings"][0]
    assert "seb@ptc.com" in record["warnings"][0]
    mine = client.get("/api/uploads?mine=true", headers=bearer(secret)).json()
    assert mine[0]["warnings"], "in the list too"


def test_a_person_cannot_send_submitted_by(client, sp):
    access.create_group("Makers", "", ["view_hub", "upload_content"], ["maker@ptc.com"], "test")
    r = client.post("/api/uploads", json={"target": "demo_catalog", "kind": "ldk",
                                          "values": KIT, "files": FILES,
                                          "submitted_by": "ann@ptc.com"},
                    headers=easyauth_headers("maker@ptc.com"))
    assert r.status_code == 422
    r = client.post("/api/uploads", json={"target": "demo_catalog", "kind": "ldk",
                                          "values": KIT, "files": FILES},
                    headers=easyauth_headers("maker@ptc.com"))
    assert r.json()["warnings"] == [], "a person is the submitter; nothing to warn about"


def test_submitted_by_is_written_to_sharepoint_where_the_column_exists(client, sp, monkeypatch):
    from dataclasses import replace
    from backend.integrations.graph import upload_writer as uw
    from backend.services import upload_targets as ut
    real = uw.resolve
    secret = issue(client).json()["secret"]
    for has_column, who in ((False, "ann@ptc.com"), (True, "jane.doe@ptc.com")):
        monkeypatch.setattr(uw, "resolve", lambda c, spec, fresh=False:
                            replace(real(c, spec, fresh), has_submitted_by=has_column))
        values = {**KIT, "title": "Kit " + who}
        record = client.post("/api/uploads", json={"target": "demo_catalog", "kind": "ldk",
                                                   "values": values, "files": FILES,
                                                   "submitted_by": who},
                             headers=bearer(secret)).json()
        for i, f in enumerate(record["files"]):
            sp.items[f"i{i}"] = {"id": f"i{i}", "size": f["size"],
                                 "name": f["path"].rsplit("/", 1)[-1]}
            client.post(f"/api/uploads/{record['id']}/files/{i}/done",
                        json={"item_id": f"i{i}"}, headers=bearer(secret))
        assert client.post(f"/api/uploads/{record['id']}/finish",
                           headers=bearer(secret)).status_code == 200
        written = sp.written[-1][1]
        assert written.get(ut.SUBMITTED_COLUMN) == (who if has_column else None)


def test_a_demo_made_through_the_hub_is_credited_to_its_person(client, sp, tmp_path):
    """SharePoint names the Hub's app as the files' creator. submitted_by (read
    back by the sync) wins; else this slot's upload record knows the person."""
    secret = issue(client).json()["secret"]
    record = start_for(client, secret, "jane.doe@ptc.com").json()
    by_token = client.post("/api/uploads", json={"target": "demo_catalog", "kind": "ldk",
                                                 "values": {**KIT, "title": "Second Kit"},
                                                 "files": FILES}, headers=bearer(secret)).json()
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps([
        {"id": "kit-a", "type": "ldk", "title": "Creo Sheetmetal Kit", "products": ["Creo"],
         "source_item_id": record["folder_id"], "creator": None},
        {"id": "kit-b", "type": "ldk", "title": "Second Kit", "products": ["Creo"],
         "source_item_id": by_token["folder_id"], "creator": "SharePoint App"},
        {"id": "kit-c", "type": "ldk", "title": "From elsewhere", "products": ["Creo"],
         "source_item_id": "folder-elsewhere", "creator": None,
         "submitted_by": "max.mustermann@ptc.com"}]), encoding="utf-8")
    from backend.deps import build_repo
    from backend.repositories.base import AssetQuery
    creators = {a.id: a.creator for a in build_repo().list(
        AssetQuery(limit=10, include_pending=True)).items}
    assert creators == {"kit-a": "Jane Doe", "kit-b": "Seb",
                        "kit-c": "Max Mustermann"}, "submitted_by alone is enough"


def test_product_version_is_a_warning_through_the_api_and_required_on_the_page(client, sp):
    """A11 (Liwei, 2026-10-26): the page requires it; the API warns, so
    scripts keep working until their authors add it."""
    secret = issue(client).json()["secret"]
    values = {k: v for k, v in KIT.items() if k != "product_version"}
    r = client.post("/api/uploads", json={"target": "demo_catalog", "kind": "ldk",
                                          "values": values, "files": FILES,
                                          "submitted_by": "ann@ptc.com"}, headers=bearer(secret))
    assert r.status_code == 201, r.text
    assert any("product_version is empty" in w for w in r.json()["warnings"])
    access.create_group("Makers", "", ["view_hub", "upload_content"], ["maker@ptc.com"], "test")
    r = client.post("/api/uploads", json={"target": "demo_catalog", "kind": "ldk",
                                          "values": {**values, "title": "Page Kit"},
                                          "files": FILES},
                    headers=easyauth_headers("maker@ptc.com"))
    assert r.status_code == 422 and "Product version is required" in r.json()["detail"]
    ok = client.post("/api/uploads", json={"target": "demo_catalog", "kind": "ldk",
                                           "values": {**values, "title": "Page Kit",
                                                      "product_version": "N/A"},
                                           "files": FILES},
                     headers=easyauth_headers("maker@ptc.com"))
    assert ok.status_code == 201, "N/A is an answer"


def test_the_demo_owner_is_the_person_it_counts_as_made_by(client, sp, monkeypatch):
    """A4 (2026-10-26): DemoOwner gets submitted_by, else the token's owner."""
    from dataclasses import replace
    from backend.integrations.graph import upload_writer as uw
    from backend.services import upload_targets as ut
    real = uw.resolve
    monkeypatch.setattr(uw, "resolve", lambda c, spec, fresh=False:
                        replace(real(c, spec, fresh), has_demo_owner=True))
    secret = issue(client).json()["secret"]
    for title, who, owner in (("Kit A", "ann@ptc.com", "ann@ptc.com"),
                              ("Kit B", None, "seb@ptc.com")):
        record = client.post("/api/uploads", json={"target": "demo_catalog", "kind": "ldk",
                                                   "values": {**KIT, "title": title},
                                                   "files": FILES, "submitted_by": who},
                             headers=bearer(secret)).json()
        for i, f in enumerate(record["files"]):
            sp.items[f"i{i}"] = {"id": f"i{i}", "size": f["size"],
                                 "name": f["path"].rsplit("/", 1)[-1]}
            client.post(f"/api/uploads/{record['id']}/files/{i}/done",
                        json={"item_id": f"i{i}"}, headers=bearer(secret))
        client.post(f"/api/uploads/{record['id']}/finish", headers=bearer(secret))
        assert sp.written[-1][1].get(ut.OWNER_COLUMN) == owner
