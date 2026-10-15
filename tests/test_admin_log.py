"""The Admin log: append-only, every Admin change, tamper-evident
(backend/admin_log.py, 2026-10-14)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend import admin_log
from backend.auth import AuthMode
from backend.config import settings
from tests.test_auth import easyauth_headers


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import app
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "a-test-password-long-enough")
    monkeypatch.setattr(settings, "hub_admin_emails", "boss@ptc.com")
    (tmp_path / "mirror").mkdir()
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps([
        {"id": "bobcat", "type": "ldk", "title": "Bobcat", "products": ["Creo"]}]),
        encoding="utf-8")
    return TestClient(app, base_url="http://localhost")


def entries():
    return admin_log.read(limit=500)["items"]


def test_a_change_is_recorded_with_who_what_and_the_answer(client):
    boss = easyauth_headers("boss@ptc.com")
    assert client.post("/api/admin/hidden", json={"asset_id": "bobcat"},
                       headers=boss).status_code == 200
    e = entries()[0]
    assert (e["actor"], e["action"], e["status"]) == ("user:boss@ptc.com", "Hid a demo", 200)
    assert e["detail"]["body"] == {"asset_id": "bobcat"}
    assert e["target"] == "bobcat", "from the body when the path does not name it"
    assert client.delete("/api/admin/hidden/bobcat", headers=boss).status_code == 200
    e = entries()[0]
    assert (e["action"], e["target"]) == ("Unhid a demo", "bobcat")


def test_a_refused_attempt_is_recorded_too(client):
    someone = easyauth_headers("someone@ptc.com")
    assert client.post("/api/admin/hidden", json={"asset_id": "bobcat"},
                       headers=someone).status_code == 403
    e = entries()[0]
    assert (e["actor"], e["status"]) == ("user:someone@ptc.com", 403)


def test_the_admin_password_is_never_written(client):
    assert client.post("/api/admin/login", json={"username": "admin",
                                                 "password": "wrong"}).status_code == 401
    assert client.post("/api/admin/login", json={
        "username": "admin", "password": "a-test-password-long-enough"}).status_code == 200
    failed, ok = entries()[1], entries()[0]
    assert (failed["actor"], failed["status"]) == ("anonymous", 401)
    assert (ok["actor"], ok["status"]) == ("admin-session", 200)
    assert ok["detail"]["body"] == {"username": "admin", "password": "•••"}
    raw = open(admin_log._path(), encoding="utf-8").read()
    assert "a-test-password" not in raw and "wrong" not in raw


def test_reads_are_not_logged_but_looking_up_a_person_is(client):
    boss = easyauth_headers("boss@ptc.com")
    client.get("/api/admin/hidden", headers=boss)
    client.get("/api/assets", headers=boss)
    assert entries() == []
    client.get("/api/admin/activity/person?email=p1@ptc.com", headers=boss)
    e = entries()[0]
    assert e["action"] == "Looked up a person's activity"
    assert e["detail"]["query"] == {"email": "p1@ptc.com"}


def test_nothing_can_change_or_delete_an_entry(client):
    boss = easyauth_headers("boss@ptc.com")
    client.post("/api/admin/hidden", json={"asset_id": "bobcat"}, headers=boss)
    for method in ("delete", "put", "patch", "post"):
        assert getattr(client, method)("/api/admin/admin-log", headers=boss).status_code == 405
    body = client.get("/api/admin/admin-log", headers=boss).json()
    assert body["integrity"]["intact"] is True
    assert body["total"] >= 1


def test_an_edit_to_the_file_breaks_the_chain_where_it_was_made(client):
    boss = easyauth_headers("boss@ptc.com")
    client.post("/api/admin/hidden", json={"asset_id": "bobcat"}, headers=boss)
    client.delete("/api/admin/hidden/bobcat", headers=boss)
    client.post("/api/admin/hidden", json={"asset_id": "bobcat"}, headers=boss)
    assert admin_log.verify()["intact"]
    path = admin_log._path()
    lines = open(path, encoding="utf-8").read().splitlines()
    doctored = json.loads(lines[1])
    doctored["actor"] = "user:someone-else@ptc.com"
    lines[1] = json.dumps(doctored)
    open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    assert admin_log.verify() == {"intact": False, "entries": 3, "broken_at": 2}
    # Removing a line is caught the same way.
    del lines[1]
    open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    assert admin_log.verify()["broken_at"] == 2


def test_hiding_a_demo_is_content_access_not_the_home_page(client):
    from backend import access
    access.create_group("Home editors", "", ["view_admin", "manage_home"],
                        ["curator@ptc.com"], "test")
    access.create_group("Access editors", "", ["view_admin", "manage_content_access"],
                        ["keeper@ptc.com"], "test")
    hide = {"asset_id": "bobcat"}
    assert client.post("/api/admin/hidden", json=hide,
                       headers=easyauth_headers("curator@ptc.com")).status_code == 403
    assert client.post("/api/admin/hidden", json=hide,
                       headers=easyauth_headers("keeper@ptc.com")).status_code == 200
