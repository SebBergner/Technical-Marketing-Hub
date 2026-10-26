"""The table view's column sorts (Serge, 2026-10-23): either way, empty last."""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.config import settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import app
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    (tmp_path / "mirror").mkdir()
    today = date.today()
    rows = [{"id": i, "type": kind, "title": title, "products": ["Creo"], "segment": seg,
             "uploaded_at": (today - timedelta(days=n)).isoformat(),
             "date_stated": i == "a"}
            for n, (i, kind, title, seg) in enumerate([
                ("a", "video", "Beta", "PLM"), ("b", "ldk", "alpha", "CAD"),
                ("c", "vdk", "Gamma", None)])]
    rows[0]["uploaded_at"] = (today - timedelta(days=10)).isoformat()
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps(rows), encoding="utf-8")
    return TestClient(app, base_url="http://localhost")


def ids(response):
    assert response.status_code == 200, response.text
    return [a["id"] for a in response.json()["items"]]


def test_title_sorts_both_ways_ignoring_case(client):
    assert ids(client.get("/api/assets?sort=title")) == ["b", "a", "c"]
    assert ids(client.get("/api/assets?sort=title&order=desc")) == ["c", "a", "b"]


def test_a_column_with_nothing_in_it_stays_last_either_way(client):
    assert ids(client.get("/api/assets?sort=segment")) == ["b", "a", "c"]
    assert ids(client.get("/api/assets?sort=segment&order=desc")) == ["a", "b", "c"]


def test_type_sorts_and_unknown_sorts_are_refused(client):
    assert ids(client.get("/api/assets?sort=type")) == ["b", "c", "a"]
    assert client.get("/api/assets?sort=colour").status_code == 422
    assert client.get("/api/assets?sort=title&order=up").status_code == 422


def test_a_stated_date_is_on_the_response(client):
    items = {a["id"]: a for a in client.get("/api/assets").json()["items"]}
    assert items["a"]["date_stated"] is True and items["b"]["date_stated"] is False
