"""The welcome pop-up: once per person, again after a big update (Liwei, 2026-11-08)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend import welcome
from backend.auth import AuthMode
from backend.config import settings
from tests.test_auth import easyauth_headers


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import app
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password", "")
    return TestClient(app, base_url="http://localhost")


def status(client, who):
    return client.get("/api/welcome", headers=easyauth_headers(who)).json()


def test_shown_once_per_person(client):
    assert status(client, "ann@ptc.com") == {"required": True, "version": welcome.VERSION,
                                             "kind": "welcome", "whats_new": []}
    assert client.post("/api/welcome/seen", headers=easyauth_headers("ann@ptc.com")).status_code == 200
    assert not status(client, "ann@ptc.com")["required"], "not again, in any browser"
    assert status(client, "bob@ptc.com")["required"], "per person"


def test_a_big_update_shows_what_is_new_to_those_who_saw_the_welcome(client, monkeypatch):
    client.post("/api/welcome/seen", headers=easyauth_headers("ann@ptc.com"))
    monkeypatch.setattr(welcome, "VERSION", "2027-01-15")
    monkeypatch.setattr(welcome, "WHATS_NEW", ("Playlists",))
    again = status(client, "ann@ptc.com")
    assert again["required"] and again["kind"] == "whats_new" and again["whats_new"] == ["Playlists"]
    assert status(client, "new@ptc.com")["kind"] == "welcome", "someone new is welcomed"
    client.post("/api/welcome/seen", headers=easyauth_headers("ann@ptc.com"))
    assert not status(client, "ann@ptc.com")["required"]
