"""/health checks the data it runs on (backend/health.py, 2026-11-26)."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from backend import health
from backend.auth import AuthMode
from backend.config import BASE_DIR, settings


@pytest.fixture
def client():
    from app import app
    return TestClient(app, base_url="http://localhost", follow_redirects=False)


def answer(client):
    r = client.get("/health")
    return r.status_code, r.json()


def test_a_mounted_data_dir_with_owned_is_healthy(client, tmp_path, monkeypatch):
    (tmp_path / "owned").mkdir()
    (tmp_path / "owned" / "access.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    status, body = answer(client)
    assert status == 200
    assert body == {"status": "ok", "storage_durable": True,
                    "checks": {"data_dir": True, "owned_readable": True}}


def test_a_missing_data_dir_is_a_503(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "not-mounted"))
    status, body = answer(client)
    assert status == 503 and body["status"] == "fail"
    assert body["checks"]["data_dir"] is False


def test_an_empty_mount_point_is_a_503(client, tmp_path, monkeypatch):
    """What a failed mount usually leaves: the directory, and nothing in it."""
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    status, body = answer(client)
    assert status == 503
    assert body["checks"] == {"data_dir": True, "owned_readable": None}


def test_an_unreadable_owned_folder_is_a_503(client, tmp_path, monkeypatch):
    (tmp_path / "owned").mkdir()
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    real = os.scandir

    def refuse(path):
        if str(path).endswith("owned"):
            raise PermissionError(13, "denied", str(path))
        return real(path)
    monkeypatch.setattr(health.os, "scandir", refuse)
    status, body = answer(client)
    assert status == 503 and body["checks"]["owned_readable"] is False


def test_a_fresh_checkout_is_healthy_but_not_durable(client, monkeypatch):
    """Inside the code folder neither folder exists before the first write."""
    monkeypatch.setattr(settings, "data_dir",
                        os.path.join(BASE_DIR, "data", "no-such-runtime-dir"))
    status, body = answer(client)
    assert status == 200
    assert body["storage_durable"] is False and body["checks"]["data_dir"] is False


def test_the_answer_names_no_path_and_is_not_cached(client, tmp_path, monkeypatch):
    (tmp_path / "owned").mkdir()
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    r = client.get("/health")
    assert str(tmp_path) not in r.text and "owned/" not in r.text
    assert r.headers["cache-control"] == "no-store"


def test_it_stays_open_without_a_sign_in(client, tmp_path, monkeypatch):
    (tmp_path / "owned").mkdir()
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "auth_mode", AuthMode.OIDC.value)
    assert client.get("/health").status_code == 200
