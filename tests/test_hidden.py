"""Hidden from the Hub, chosen on the Admin page (Liwei, 2026-10-06)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import app
from backend.config import settings
from backend.repositories.base import AssetQuery
from backend.repositories.json_repo import JsonAssetRepository


def seed(tmp_path, *ids):
    (tmp_path / "mirror").mkdir(exist_ok=True)
    rows = [{"id": i, "type": "ldk", "title": i.title(), "products": ["Creo"]} for i in ids]
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps(rows), encoding="utf-8")
    return JsonAssetRepository(str(tmp_path))


def test_a_hidden_demo_leaves_every_read_and_comes_back_on_unhide(tmp_path):
    repo = seed(tmp_path, "bobcat", "hill")
    repo.set_promoted(["bobcat"], "admin-session")
    items = repo.hide("bobcat", "admin-session")
    assert [i["asset_id"] for i in items] == ["bobcat"] and items[0]["title"] == "Bobcat"
    assert [a.id for a in repo.list(AssetQuery(limit=10)).items] == ["hill"]
    assert repo.list(AssetQuery(text="bobcat", limit=10)).total == 0
    assert repo.get("bobcat") is None and repo.is_hidden("bobcat")
    repo.unhide("bobcat")
    assert repo.get("bobcat") is not None and not repo.is_hidden("bobcat")


def test_a_sync_does_not_bring_a_hidden_demo_back(tmp_path):
    repo = seed(tmp_path, "bobcat")
    repo.hide("bobcat", "admin-session")
    seed(tmp_path, "bobcat")                       # the mirror is rewritten
    assert repo.get("bobcat") is None
    assert (tmp_path / "owned" / "hidden.json").exists(), "Portal-owned, never mirror/"


def test_only_a_listed_demo_can_be_hidden(tmp_path):
    repo = seed(tmp_path, "bobcat")
    with pytest.raises(KeyError):
        repo.hide("nope", "admin-session")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "a-test-password")
    monkeypatch.setattr(settings, "auth_mode", "disabled")   # everyone a curator...
    return TestClient(app, base_url="http://localhost")


def test_only_an_admin_session_hides_not_a_curator(client, tmp_path):
    seed(tmp_path, "bobcat")
    # ...and still refused: hiding needs the admin sign-in itself.
    assert client.post("/api/admin/hidden", json={"asset_id": "bobcat"}).status_code == 401
    assert client.post("/api/admin/login",
                       json={"username": "admin", "password": "a-test-password"}).status_code == 200
    assert [i["asset_id"] for i in client.post("/api/admin/hidden", json={"asset_id": "bobcat"}).json()] == ["bobcat"]
    gone = client.get("/api/assets/bobcat")
    assert gone.status_code == 404 and "hidden" in gone.json()["detail"]
    assert client.post("/api/admin/hidden", json={"asset_id": "nope"}).status_code == 422
    assert client.delete("/api/admin/hidden/bobcat").json() == []
    assert client.get("/api/assets/bobcat").status_code == 200
