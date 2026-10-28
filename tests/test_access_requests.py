"""Requests to make a demo Internal or Open, and the Admin log's filters and
export (2026-10-15)."""
from __future__ import annotations

import csv
import io
import json

import pytest
from fastapi.testclient import TestClient

from backend import access
from backend.auth import AuthMode
from backend.config import settings
from tests.test_auth import easyauth_headers

BOSS = easyauth_headers("boss@ptc.com")
ANN = easyauth_headers("ann@ptc.com")
BO = easyauth_headers("bo@ptc.com")
PARTNER = easyauth_headers("p@partner.it")


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import app
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password", "")
    monkeypatch.setattr(settings, "hub_admin_emails", "boss@ptc.com")
    (tmp_path / "mirror").mkdir()
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps([
        {"id": "bobcat", "type": "ldk", "title": "Bobcat", "products": ["Creo"]},
        {"id": "lambo", "type": "vdk", "title": "Lambo", "products": ["Creo"],
         "internal": True, "internal_source": "sharepoint"}]), encoding="utf-8")
    return TestClient(app, base_url="http://localhost")


class _Answer:
    def __init__(self, status_code, body):
        self.status_code, self._body = status_code, body

    def json(self):
        return self._body


def ask(client, who=ANN, level="internal", reason="Customer data in the recording"):
    """A request made before 2026-10-28, when people still asked on the Hub;
    now only one left from then exists (Report an issue instead)."""
    from backend.deps import get_repo
    from backend.services import access_requests
    repo = get_repo()
    email = who["X-MS-CLIENT-PRINCIPAL-NAME"]
    try:
        made = access_requests.create(repo, repo.get("bobcat"), level, reason, f"user:{email}")
    except access_requests.RequestError as exc:
        return _Answer(422, {"detail": str(exc)})
    return _Answer(201, {"pending": made})


def test_nobody_asks_on_the_hub_any_more(client):
    """Liwei, 2026-10-28: Report an issue (Other) instead."""
    r = client.post("/api/assets/bobcat/access-requests",
                    json={"level": "internal", "reason": "x"}, headers=ANN)
    assert r.status_code == 405
    assert "request_content_access" not in access.ALL
    assert client.get("/api/assets/bobcat/access-requests", headers=ANN).status_code == 403, \
        "only Manage content access sees the ones left"


def test_one_left_from_before_is_approved_and_applied(client):
    pending = ask(client).json()["pending"]
    assert client.get("/api/assets/bobcat", headers=ANN).json()["internal"] is False, \
        "nothing changes until someone decides"
    decided = client.post(f"/api/admin/access-requests/{pending['id']}/decision",
                          json={"approve": True, "note": "Agreed"}, headers=BOSS).json()
    assert (decided["status"], decided["decided_by"]) == ("approved", "user:boss@ptc.com")
    assert client.get("/api/assets/bobcat", headers=ANN).json()["internal"] is True
    mark = next(i for i in client.get("/api/admin/content-access", headers=BOSS).json()
                if i["asset_id"] == "bobcat")
    assert mark["reason"] == "Requested by ann@ptc.com: Customer data in the recording"


def test_a_rejection_changes_nothing_and_says_why(client):
    rid = ask(client).json()["pending"]["id"]
    client.post(f"/api/admin/access-requests/{rid}/decision",
                json={"approve": False, "note": "Public material"}, headers=BOSS)
    view = client.get("/api/assets/bobcat/access-requests", headers=BOSS).json()
    assert view["pending"] is None
    assert (view["history"][0]["status"], view["history"][0]["note"]) == ("rejected", "Public material")
    assert client.get("/api/assets/bobcat", headers=ANN).json()["internal"] is False


def test_only_a_manager_decides(client):
    rid = ask(client).json()["pending"]["id"]
    assert client.post(f"/api/admin/access-requests/{rid}/decision",
                       json={"approve": True}, headers=BO).status_code == 403
    assert client.post(f"/api/admin/access-requests/{rid}/decision",
                       json={"approve": True}, headers=BOSS).status_code == 200
    assert client.post(f"/api/admin/access-requests/{rid}/decision",
                       json={"approve": True}, headers=BOSS).status_code == 422, "already settled"


def test_every_step_is_in_the_admin_log_under_content_access(client):
    rid = ask(client).json()["pending"]["id"]
    client.post(f"/api/admin/access-requests/{rid}/decision", json={"approve": True},
                headers=BOSS)
    client.put("/api/assets/bobcat/still-current", json={"still_current": True}, headers=BOSS)
    log = client.get("/api/admin/admin-log?category=Content access", headers=BOSS).json()
    assert [e["action"] for e in log["items"]] == ["Decided an access request"]
    assert log["items"][0]["target"] == "bobcat", "the demo, not the request's id"
    review = client.get("/api/admin/admin-log?category=Content review", headers=BOSS).json()
    assert [e["action"] for e in review["items"]] == ["Set Still current"]


def test_the_admin_log_filters_by_result_and_exports_csv(client):
    client.put("/api/assets/bobcat/access", json={"level": "internal"}, headers=PARTNER)  # refused
    client.put("/api/assets/bobcat/access", json={"level": "internal"}, headers=BOSS)     # done
    refused = client.get("/api/admin/admin-log?result=refused", headers=BOSS).json()
    assert [e["actor"] for e in refused["items"]] == ["user:p@partner.it"]
    r = client.get("/api/admin/admin-log.csv?category=Content access", headers=BOSS)
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    assert r.text.startswith("\ufeff"), "so Excel reads it as UTF-8"
    rows = list(csv.DictReader(io.StringIO(r.text.lstrip("\ufeff"))))
    assert {row["action"] for row in rows} == {"Set a demo Open or Internal"}
    assert {row["result"] for row in rows} == {"done", "refused"}
    exported = client.get("/api/admin/admin-log?category=Usage data", headers=BOSS).json()
    assert exported["items"][0]["action"] == "Exported the Admin log", "an export is logged"
