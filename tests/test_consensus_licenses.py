"""Consensus licence list: who sees Create DemoBoard (Elio, Seb, 2026-10-28)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend import admin_log, consensus_licenses
from backend.auth import AuthMode
from backend.config import settings
from tests.test_auth import easyauth_headers

ADMIN = "boss@ptc.com"
REPORT = ("﻿First Name,Last Name,Email,Role,Group,Date Added,Last Activity,Status\n"
          "Ann,Lee,Ann.Lee@ptc.com,Sender/Tracker,Sales,2024-01-01,2026-10-01,active\n"
          "Pat,Ner,pat@partner.it,Content Author,Partners,2024-01-01,,active\n"
          "No,Mail,,Admin,,,,active\n")


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import app
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password", "")
    monkeypatch.setattr(settings, "hub_admin_emails", ADMIN)
    return TestClient(app, base_url="http://localhost")


def upload(client, text=REPORT, who=ADMIN, name="Consensus - ManageUsersReport.csv"):
    return client.post("/api/admin/consensus-licenses", headers=easyauth_headers(who),
                       files={"file": (name, text.encode("utf-8"), "text/csv")})


def licensed(client, who):
    return client.get("/api/auth/me", headers=easyauth_headers(who)).json()["consensus_licensed"]


def test_the_report_as_consensus_exports_it_becomes_the_list(client):
    r = upload(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["count"], body["partners"], body["skipped"]) == (2, 1, 1)
    assert body["people"][0] == {"email": "ann.lee@ptc.com", "name": "Ann Lee",
                                 "role": "Sender/Tracker", "group": "Sales"}
    assert licensed(client, "ann.lee@ptc.com") and licensed(client, "pat@partner.it")
    assert not licensed(client, "someone@ptc.com")


def test_a_new_upload_replaces_the_whole_list(client):
    upload(client)
    upload(client, "Email\nnew@ptc.com\n")
    assert licensed(client, "new@ptc.com") and not licensed(client, "ann.lee@ptc.com")
    assert client.get("/api/admin/consensus-licenses",
                      headers=easyauth_headers(ADMIN)).json()["count"] == 1


def test_nobody_is_licensed_before_any_upload(client):
    assert not licensed(client, "ann.lee@ptc.com")


def test_a_file_that_is_not_the_report_is_refused_and_the_list_kept(client):
    upload(client)
    r = upload(client, "Name,Phone\nAnn,123\n")
    assert r.status_code == 422 and "Email" in r.json()["detail"]
    assert upload(client, "Email\nnot-an-address\n").status_code == 422
    assert licensed(client, "ann.lee@ptc.com")


def test_only_manage_users_may_upload(client):
    assert upload(client, who="someone@ptc.com").status_code == 403
    assert not licensed(client, "ann.lee@ptc.com")


def test_the_upload_is_in_the_admin_log(client):
    upload(client)
    entry = admin_log._entries()[-1]
    assert (entry["action"], entry["actor"]) == ("Uploaded the Consensus licence list",
                                                 f"user:{ADMIN}")
    assert admin_log.category_of("/api/admin/consensus-licenses") == "Users & groups"


def test_parse_keeps_one_row_per_address():
    people, skipped = consensus_licenses.parse(b"Email\nA@ptc.com\na@ptc.com\n")
    assert [p["email"] for p in people] == ["a@ptc.com"] and skipped == 0
