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


def ask(client, who=ANN, level="internal", reason="Customer data in the recording"):
    return client.post("/api/assets/bobcat/access-requests",
                       json={"level": level, "reason": reason}, headers=who)


def test_a_ptc_employee_asks_with_a_reason_and_an_approval_applies_it(client):
    r = ask(client)
    assert r.status_code == 201
    pending = r.json()["pending"]
    assert (pending["level"], pending["requested_by"]) == ("internal", "user:ann@ptc.com")
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
    view = client.get("/api/assets/bobcat/access-requests", headers=ANN).json()
    assert view["pending"] is None
    assert (view["history"][0]["status"], view["history"][0]["note"]) == ("rejected", "Public material")
    assert client.get("/api/assets/bobcat", headers=ANN).json()["internal"] is False


def test_the_rules(client):
    assert ask(client, reason="  ").status_code == 422, "a reason is required"
    assert ask(client, level="open").status_code == 422, "already Open"
    assert client.post("/api/assets/lambo/access-requests", json={
        "level": "open", "reason": "x"}, headers=ANN).status_code == 422, \
        "closed in SharePoint: only SharePoint can open it"
    assert ask(client).status_code == 201
    assert ask(client, who=BO).status_code == 422, "one pending request per demo"
    assert ask(client, who=PARTNER).status_code == 403, "partners do not ask"


def test_only_the_requester_withdraws_and_only_a_manager_decides(client):
    first = ask(client).json()
    rid = first["pending"]["id"]
    assert first["may_withdraw"] is True
    assert client.get("/api/assets/bobcat/access-requests", headers=BO).json()["may_withdraw"] is False
    assert client.post(f"/api/assets/bobcat/access-requests/{rid}/withdraw",
                       headers=BO).status_code == 422
    assert client.post(f"/api/admin/access-requests/{rid}/decision",
                       json={"approve": True}, headers=BO).status_code == 403
    r = client.post(f"/api/assets/bobcat/access-requests/{rid}/withdraw", headers=ANN)
    assert r.json()["history"][0]["status"] == "withdrawn"
    assert client.post(f"/api/admin/access-requests/{rid}/decision",
                       json={"approve": True}, headers=BOSS).status_code == 422, "already settled"


def test_every_step_is_in_the_admin_log_under_content_access(client):
    rid = ask(client).json()["pending"]["id"]
    client.post(f"/api/admin/access-requests/{rid}/decision", json={"approve": True},
                headers=BOSS)
    client.put("/api/assets/bobcat/still-current", json={"still_current": True}, headers=BOSS)
    log = client.get("/api/admin/admin-log?category=Content access", headers=BOSS).json()
    assert [e["action"] for e in log["items"]] == ["Decided an access request",
                                                    "Requested an access change"]
    assert log["items"][0]["target"] == "bobcat", "the demo, not the request's id"
    review = client.get("/api/admin/admin-log?category=Content review", headers=BOSS).json()
    assert [e["action"] for e in review["items"]] == ["Set Still current"]


def test_the_admin_log_filters_by_result_and_exports_csv(client):
    ask(client, who=PARTNER)                                   # refused
    ask(client)                                                # done
    refused = client.get("/api/admin/admin-log?result=refused", headers=BOSS).json()
    assert [e["actor"] for e in refused["items"]] == ["user:p@partner.it"]
    r = client.get("/api/admin/admin-log.csv?category=Content access", headers=BOSS)
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    assert r.text.startswith("﻿"), "so Excel reads it as UTF-8"
    rows = list(csv.DictReader(io.StringIO(r.text.lstrip("﻿"))))
    assert {row["action"] for row in rows} == {"Requested an access change"}
    assert {row["result"] for row in rows} == {"done", "refused"}
    exported = client.get("/api/admin/admin-log?category=Usage data", headers=BOSS).json()
    assert exported["items"][0]["action"] == "Exported the Admin log", "an export is logged"
