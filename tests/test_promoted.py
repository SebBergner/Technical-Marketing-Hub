"""Promoted on Home: chosen on the Admin page, in order (Seb, via Liwei 2026-10-01)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import app
from backend.config import settings
from backend.repositories.json_repo import JsonAssetRepository


def seed(tmp_path, *ids, products=None):
    (tmp_path / "mirror").mkdir(exist_ok=True)
    rows = [{"id": i, "type": "ldk", "title": i.title(), "products": products or ["Creo"]}
            for i in ids]
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps(rows), encoding="utf-8")
    return JsonAssetRepository(str(tmp_path))


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "a-test-password")
    monkeypatch.setattr(settings, "auth_mode", "easyauth")
    return TestClient(app, base_url="http://localhost")


def sign_in(client):
    assert client.post("/api/admin/login",
                       json={"username": "admin", "password": "a-test-password"}).status_code == 200


def test_the_list_keeps_its_order_and_drops_repeats(tmp_path):
    repo = seed(tmp_path, "bobcat", "hill", "lambo")
    state = repo.set_promoted(["lambo", "bobcat", "lambo"], "admin-session")
    assert state["asset_ids"] == ["lambo", "bobcat"]
    assert state["changed_by"] == "admin-session" and state["changed_at"]
    assert (tmp_path / "owned" / "promoted.json").exists(), "Portal-owned, never mirror/"


def test_nobody_can_change_it_without_the_admin_key(client, tmp_path):
    seed(tmp_path, "bobcat")
    assert client.put("/api/admin/promoted", json={"asset_ids": ["bobcat"]}).status_code == 401
    assert client.get("/api/admin/promoted").status_code == 401


def test_an_admin_sets_it_and_home_reads_it_in_order(client, tmp_path):
    seed(tmp_path, "bobcat", "hill", "lambo")
    sign_in(client)
    body = client.put("/api/admin/promoted", json={"asset_ids": ["hill", "bobcat"]}).json()
    assert [a["id"] for a in body["assets"]] == ["hill", "bobcat"]
    assert body["max"] == 12
    assert [a["id"] for a in client.get("/api/assets/promoted").json()] == ["hill", "bobcat"]


def test_an_unknown_id_is_refused_and_a_dozen_is_the_limit(client, tmp_path):
    seed(tmp_path, *[f"demo{i}" for i in range(13)])
    sign_in(client)
    assert client.put("/api/admin/promoted", json={"asset_ids": ["nope"]}).status_code == 422
    too_many = [f"demo{i}" for i in range(13)]
    assert client.put("/api/admin/promoted", json={"asset_ids": too_many}).status_code == 422


def test_an_asset_that_leaves_the_catalogue_drops_off_home(client, tmp_path):
    repo = seed(tmp_path, "bobcat", "hill")
    repo.set_promoted(["bobcat", "hill"], "admin-session")
    seed(tmp_path, "hill")                     # bobcat no longer in the mirror
    assert [a["id"] for a in client.get("/api/assets/promoted").json()] == ["hill"]


def test_a_divested_product_is_never_promoted_onto_home(client, tmp_path):
    repo = seed(tmp_path, "twx", products=["ThingWorx"])
    repo.set_promoted(["twx"], "admin-session")
    assert client.get("/api/assets/promoted").json() == []
