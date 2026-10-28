"""Related demos under a demo's page (A13, Summit; six, Liwei 2026-10-28)."""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.config import settings
from backend.repositories.json_repo import JsonAssetRepository


def _row(i, products, segment, kind="video", days=0):
    return {"id": i, "type": kind, "title": i.upper(), "products": products,
            "segment": segment,
            "uploaded_at": (date.today() - timedelta(days=days)).isoformat()}


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    (tmp_path / "mirror").mkdir()
    rows = [
        _row("base", ["Creo Parametric"], "CAD"),
        _row("family-segment-type", ["Creo Simulate"], "CAD", days=30),
        _row("family-only", ["Creo Parametric"], "PLM", kind="ldk", days=1),
        _row("segment-type", ["Windchill PDMLink"], "CAD", days=2),
        _row("type-only", ["Windchill PDMLink"], "PLM", days=3),
        _row("nothing", ["Codebeamer"], "ALM", kind="vdk", days=4),
        _row("archived", ["Creo Parametric"], "CAD", days=5),
    ]
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps(rows), encoding="utf-8")
    return tmp_path


@pytest.fixture
def client(data):
    from app import app
    JsonAssetRepository(str(data)).set_archived("archived", True, "user:test@ptc.com")
    return TestClient(app, base_url="http://localhost")


def ids(response):
    assert response.status_code == 200, response.text
    return [a["id"] for a in response.json()]


def test_family_counts_most_then_segment_then_type(client):
    assert ids(client.get("/api/assets/base/related")) == [
        "family-segment-type", "family-only", "segment-type"]


def test_type_alone_is_not_related_and_the_demo_itself_is_never_offered(client):
    got = ids(client.get("/api/assets/base/related"))
    assert "type-only" not in got and "nothing" not in got and "base" not in got


def test_nothing_archived_is_offered(client):
    assert "archived" not in ids(client.get("/api/assets/base/related"))


def test_a_tie_goes_to_views_then_the_newest(data):
    from app import app
    (data / "mirror" / "sharepoint.json").write_text(json.dumps([
        _row("base", ["Creo Parametric"], "CAD"),
        _row("old", ["Creo Parametric"], "CAD", days=400),
        _row("new", ["Creo Parametric"], "CAD", days=1),
    ]), encoding="utf-8")
    client = TestClient(app, base_url="http://localhost")
    assert ids(client.get("/api/assets/base/related")) == ["new", "old"]
    JsonAssetRepository(str(data)).increment_stat("old", "views", 3)
    assert ids(client.get("/api/assets/base/related")) == ["old", "new"]


def test_more_families_shared_ranks_higher(data):
    from app import app
    (data / "mirror" / "sharepoint.json").write_text(json.dumps([
        _row("base", ["Creo Parametric", "Windchill PDMLink", "Codebeamer"], "PLM"),
        _row("one", ["Windchill PDMLink"], "PLM", days=1),
        _row("three", ["Creo Parametric", "Windchill PDMLink", "Codebeamer"], "PLM", days=9),
    ]), encoding="utf-8")
    client = TestClient(app, base_url="http://localhost")
    assert ids(client.get("/api/assets/base/related")) == ["three", "one"]


def test_the_same_language_goes_first_among_equals(data):
    from app import app
    rows = [_row("base", ["Creo Parametric"], "CAD"),
            _row("japanese", ["Creo Parametric"], "CAD", days=1),
            _row("english", ["Creo Parametric"], "CAD", days=9)]
    rows[1]["language"] = "ja"
    (data / "mirror" / "sharepoint.json").write_text(json.dumps(rows), encoding="utf-8")
    client = TestClient(app, base_url="http://localhost")
    assert ids(client.get("/api/assets/base/related")) == ["english", "japanese"]


def test_six_by_default_and_a_limit_is_kept(data):
    from app import app
    (data / "mirror" / "sharepoint.json").write_text(json.dumps(
        [_row("base", ["Creo Parametric"], "CAD")]
        + [_row(f"c{n}", ["Creo Parametric"], "CAD", days=n + 1) for n in range(9)]),
        encoding="utf-8")
    client = TestClient(app, base_url="http://localhost")
    assert len(ids(client.get("/api/assets/base/related"))) == 6
    assert len(ids(client.get("/api/assets/base/related?limit=2"))) == 2
    assert client.get("/api/assets/base/related?limit=0").status_code == 422


def test_an_unknown_demo_is_a_404(client):
    assert client.get("/api/assets/no-such-demo/related").status_code == 404
