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
    return [a["id"] for a in response.json()["items"]]


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


# ── picked by hand (Liwei, 2026-10-28) ─────────────────────────────────────
from backend import access                                    # noqa: E402
from backend import admin_log                                 # noqa: E402
from backend.auth import AuthMode                             # noqa: E402
from tests.test_auth import easyauth_headers                  # noqa: E402

EDITOR = easyauth_headers("editor@ptc.com")
ANN = easyauth_headers("ann@ptc.com")


@pytest.fixture
def signed_in(data, monkeypatch):
    from app import app
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password", "")
    access.create_group("Editors", "", ["view_hub", "edit_metadata"], ["editor@ptc.com"], "test")
    JsonAssetRepository(str(data)).set_archived("archived", True, "user:test@ptc.com")
    return TestClient(app, base_url="http://localhost")


def picked(response):
    assert response.status_code == 200, response.text
    return [a["id"] for a in response.json()["items"] if a["picked"]]


def test_a_pick_comes_first_on_both_pages_and_the_rest_fill_up(signed_in):
    c = signed_in
    assert c.put("/api/assets/base/related/nothing", headers=EDITOR).status_code == 200
    page = c.get("/api/assets/base/related", headers=ANN)
    assert ids(page) == ["nothing", "family-segment-type", "family-only", "segment-type"]
    assert picked(page) == ["nothing"]
    assert picked(c.get("/api/assets/nothing/related", headers=ANN)) == ["base"]


def test_only_editors_pick_and_only_they_see_what_was_marked(signed_in):
    c = signed_in
    assert c.put("/api/assets/base/related/nothing", headers=ANN).status_code == 403
    assert c.put("/api/assets/base/not-related/family-only", headers=ANN,
                 json={"not_related": True}).status_code == 403
    assert c.put("/api/assets/base/not-related/family-only", headers=EDITOR,
                 json={"not_related": True}).status_code == 200
    assert c.get("/api/assets/base/related", headers=ANN).json()["not_related"] == []
    marked = c.get("/api/assets/base/related", headers=EDITOR).json()["not_related"]
    assert [(m["id"], m["by"]) for m in marked] == [("family-only", "user:editor@ptc.com")]


def test_not_related_holds_on_its_own_page_only_and_can_be_undone(signed_in):
    c = signed_in
    c.put("/api/assets/base/not-related/family-only", headers=EDITOR, json={"not_related": True})
    assert "family-only" not in ids(c.get("/api/assets/base/related", headers=ANN))
    assert "base" in ids(c.get("/api/assets/family-only/related", headers=ANN))
    c.put("/api/assets/base/not-related/family-only", headers=EDITOR, json={"not_related": False})
    assert "family-only" in ids(c.get("/api/assets/base/related", headers=ANN))


def test_picking_a_demo_marked_not_related_lets_it_back(signed_in):
    c = signed_in
    c.put("/api/assets/base/not-related/family-only", headers=EDITOR, json={"not_related": True})
    c.put("/api/assets/base/related/family-only", headers=EDITOR)
    assert picked(c.get("/api/assets/base/related", headers=ANN)) == ["family-only"]
    assert c.get("/api/assets/base/related", headers=EDITOR).json()["not_related"] == []


def test_removing_a_pick_takes_it_off_both_pages(signed_in):
    c = signed_in
    c.put("/api/assets/base/related/nothing", headers=EDITOR)
    assert c.delete("/api/assets/nothing/related/base", headers=EDITOR).status_code == 200
    assert picked(c.get("/api/assets/base/related", headers=ANN)) == []
    assert c.delete("/api/assets/nothing/related/base", headers=EDITOR).status_code == 404


def test_refused_picks(signed_in):
    c = signed_in
    assert c.put("/api/assets/base/related/base", headers=EDITOR).status_code == 422
    assert c.put("/api/assets/base/related/no-such", headers=EDITOR).status_code == 404
    c.put("/api/assets/base/related/nothing", headers=EDITOR)
    r = c.put("/api/assets/nothing/related/base", headers=EDITOR)
    assert r.status_code == 422 and "already" in r.json()["detail"]


def test_six_picks_at_most_on_one_page(data, signed_in):
    rows = json.loads((data / "mirror" / "sharepoint.json").read_text(encoding="utf-8"))
    rows += [_row(f"x{n}", ["Codebeamer"], "ALM", days=n + 10) for n in range(6)]
    (data / "mirror" / "sharepoint.json").write_text(json.dumps(rows), encoding="utf-8")
    c = signed_in
    for n in range(6):
        assert c.put(f"/api/assets/base/related/x{n}", headers=EDITOR).status_code == 200
    r = c.put("/api/assets/base/related/nothing", headers=EDITOR)
    assert r.status_code == 422 and "6" in r.json()["detail"]
    assert ids(c.get("/api/assets/base/related", headers=ANN)) == [f"x{n}" for n in range(6)]


def test_an_archived_pick_is_not_shown(data, signed_in):
    c = signed_in
    c.put("/api/assets/base/related/nothing", headers=EDITOR)
    JsonAssetRepository(str(data)).set_archived("nothing", True, "user:test@ptc.com")
    assert "nothing" not in ids(c.get("/api/assets/base/related", headers=ANN))


def test_every_change_is_in_the_admin_log(signed_in):
    c = signed_in
    c.put("/api/assets/base/related/nothing", headers=EDITOR)
    c.put("/api/assets/base/not-related/family-only", headers=EDITOR, json={"not_related": True})
    c.delete("/api/assets/base/related/nothing", headers=EDITOR)
    actions = [(e["action"], e["actor"]) for e in admin_log._entries()]
    assert actions[-3:] == [("Picked a related demo", "user:editor@ptc.com"),
                            ("Marked or unmarked a demo Not related", "user:editor@ptc.com"),
                            ("Removed a picked related demo", "user:editor@ptc.com")]
    assert admin_log.category_of("/api/assets/base/related/nothing") == "Metadata"
