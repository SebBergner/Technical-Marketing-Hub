"""How fresh the catalogue is (Summit, 2026-10): the sidebar's "Catalogue updated"."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.config import settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import app
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    (tmp_path / "mirror").mkdir()
    (tmp_path / "owned").mkdir()
    return TestClient(app, base_url="http://localhost"), tmp_path


def test_nothing_synced_yet_says_nothing(client):
    c, _ = client
    assert c.get("/api/assets/freshness").json() == {"updated_at": None, "hours_utc": []}


def test_the_newest_sync_of_any_source_and_the_schedule_when_on(client):
    c, root = client
    (root / "owned" / "sync_state.json").write_text(json.dumps({
        "sharepoint": {"last_success_at": "2026-10-26T06:00:05"},
        "consensus": {"last_success_at": "2026-10-26T06:03:40"},
        "nobody": {"last_success_at": "2030-01-01T00:00:00"}}), encoding="utf-8")
    (root / "owned" / "auto_sync.json").write_text(
        json.dumps({"enabled": True, "hours_utc": [6, 18]}), encoding="utf-8")
    assert c.get("/api/assets/freshness").json() == {
        "updated_at": "2026-10-26T06:03:40", "hours_utc": [6, 18]}
