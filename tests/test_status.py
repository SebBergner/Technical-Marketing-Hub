"""Release status for the post-swap smoke test (Liwei, 2026-11-11)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend import api_tokens, auto_sync
from backend.auth import AuthMode
from backend.config import settings
from backend.version import app_version


def bearer(secret):
    return {"Authorization": f"Bearer {secret}"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import app
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "auth_mode", AuthMode.OIDC.value)
    (tmp_path / "mirror").mkdir()
    (tmp_path / "mirror" / "sharepoint.json").write_text("[]", encoding="utf-8")
    return TestClient(app, base_url="http://localhost", follow_redirects=False)


@pytest.fixture
def token():
    _, secret = api_tokens.create(name="Smoke test", owner="liwei@ptc.com",
                                  permissions=["view_hub"], days=30, actor="test")
    return secret


def test_a_reader_token_sees_the_release_status(client, token):
    r = client.get("/api/status", headers=bearer(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"] == app_version()
    assert set(body["sync"]) >= {"sharepoint", "demo_video", "consensus"}
    assert set(body["hub_settings"]) == {"show_page_only_demos", "show_demo_page_links",
                                         "gxc_downloads"}
    assert body["hub_settings"]["show_page_only_demos"] is True
    assert body["auto_sync"]["last_run"] is None


def test_nobody_signed_out_sees_it(client):
    assert client.get("/api/status").status_code == 401
    assert client.get("/api/status", headers=bearer("tmh_bad_token")).status_code == 401


def test_the_last_daily_run_says_only_whether_each_source_worked(client, token, tmp_path):
    state = auto_sync.load_state()
    state["last_run"] = {"started_at": "2026-11-11T06:00:00+00:00",
                         "finished_at": "2026-11-11T06:09:00+00:00", "ok": False,
                         "results": {"sharepoint": {"ok": True, "vm_pages_ok": True},
                                     "consensus": {"ok": False, "error": "secret detail"}}}
    auto_sync.save_state(state)
    run = client.get("/api/status", headers=bearer(token)).json()["auto_sync"]["last_run"]
    assert run["ok"] is False
    assert run["sources"] == {"sharepoint": True, "consensus": False}
    assert "secret detail" not in json.dumps(run)
