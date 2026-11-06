"""The Customer Data Disclaimer pop-up and its record (Elio, 2026-11-05)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend import disclaimer
from backend.auth import AuthMode
from backend.config import settings
from tests.test_auth import easyauth_headers

ADMIN = "boss@ptc.com"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import app
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password", "")
    monkeypatch.setattr(settings, "hub_admin_emails", ADMIN)
    return TestClient(app, base_url="http://localhost")


def status(client, who):
    return client.get("/api/disclaimer", headers=easyauth_headers(who)).json()


def test_asked_once_then_not_again(client):
    first = status(client, "ann@ptc.com")
    assert first["required"] and first["title"] == "Customer Data Disclaimer"
    assert len(first["terms"]) == 4
    r = client.post("/api/disclaimer/accept", headers=easyauth_headers("ann@ptc.com"))
    assert r.status_code == 200, r.text
    assert not status(client, "ann@ptc.com")["required"]
    assert status(client, "bob@ptc.com")["required"], "per person, not per browser"


def test_asked_again_after_twelve_months_or_a_new_text(tmp_path, monkeypatch):
    class Ann:
        email, name, token_name = "ann@ptc.com", "Lee, Ann", None
    d = str(tmp_path)
    then = datetime.now(timezone.utc) - timedelta(days=disclaimer.ASK_AGAIN_DAYS + 1)
    disclaimer.accept(Ann(), d, now=then)
    assert disclaimer.status(Ann(), d)["required"]
    disclaimer.accept(Ann(), d)
    assert not disclaimer.status(Ann(), d)["required"]
    row = disclaimer.load(d)["ann@ptc.com"]
    assert row["times"] == 2 and row["first_accepted_at"] == then.isoformat(timespec="seconds")
    monkeypatch.setattr(disclaimer, "VERSION", "2027-01-01")
    assert disclaimer.status(Ann(), d)["required"], "an acceptance is of the words shown"


def test_a_program_with_an_api_token_is_never_asked(tmp_path):
    class Program:
        email, token_name = None, "uploader"
    assert disclaimer.status(Program(), str(tmp_path))["required"] is False
    with pytest.raises(ValueError):
        disclaimer.accept(Program(), str(tmp_path))


def test_admin_lists_who_accepted_with_a_csv(client):
    client.post("/api/disclaimer/accept", headers=easyauth_headers("ann@ptc.com"))
    r = client.get("/api/admin/disclaimer", headers=easyauth_headers(ADMIN))
    assert r.status_code == 200, r.text
    (person,) = r.json()["people"]
    assert person["email"] == "ann@ptc.com" and person["current"] and person["due_again_at"]
    csv = client.get("/api/admin/disclaimer.csv", headers=easyauth_headers(ADMIN))
    assert csv.status_code == 200 and "ann@ptc.com" in csv.text
    assert client.get("/api/admin/disclaimer",
                      headers=easyauth_headers("ann@ptc.com")).status_code == 403
