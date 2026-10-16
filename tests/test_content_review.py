"""Archive and the content-review lists (2026-10-14)."""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.access import EMPLOYEES
from backend import access
from backend.auth import AuthMode
from backend.config import settings
from tests.test_auth import easyauth_headers

BOSS, STAFF = easyauth_headers("boss@ptc.com"), easyauth_headers("someone@ptc.com")


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import app
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password", "")
    monkeypatch.setattr(settings, "hub_admin_emails", "boss@ptc.com")
    (tmp_path / "mirror").mkdir()
    today = date.today()
    rows = [{"id": i, "type": "video", "title": f"Clip {i}", "products": ["Creo"],
             "uploaded_at": (today - timedelta(days=days)).isoformat()}
            for i, days in (("fresh", 30), ("idle", 500), ("used", 600), ("dusty", 3000))]
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps(rows), encoding="utf-8")
    (tmp_path / "owned").mkdir()
    recent = (today - timedelta(days=10)).isoformat() + "T10:00:00+00:00"
    (tmp_path / "owned" / "usage_events.jsonl").write_text("\n".join(json.dumps(e) for e in [
        {"at": recent, "event": "view", "asset_id": "used", "user": "ann@ptc.com"},
        {"at": recent, "event": "download", "asset_id": "used", "user": "bo@ptc.com"},
    ]) + "\n", encoding="utf-8")
    return TestClient(app, base_url="http://localhost")


def ids(response):
    return sorted(a["id"] for a in response.json()["items"])


# ─────────────────────────────────────────────────────────── archive
def test_an_archived_demo_leaves_every_list_but_stays_in_sharepoint(client, tmp_path):
    r = client.put("/api/assets/dusty/archive", json={"archived": True, "reason": "UI from 2018"},
                   headers=BOSS)
    assert r.status_code == 200
    assert "dusty" not in ids(client.get("/api/assets", headers=STAFF))
    assert client.get("/api/taxonomy", headers=STAFF).json()["total"] == 3
    assert client.get("/api/assets/dusty", headers=STAFF).status_code == 404
    mirror = json.loads((tmp_path / "mirror" / "sharepoint.json").read_text(encoding="utf-8"))
    assert "dusty" in {r["id"] for r in mirror}, "the source is never touched"


def test_see_archived_content_opens_it_and_lists_it_on_request(client):
    client.put("/api/assets/dusty/archive", json={"archived": True}, headers=BOSS)
    assert client.get("/api/assets/dusty", headers=BOSS).json()["archived"] is True
    assert "dusty" in ids(client.get("/api/assets?archived=true", headers=BOSS))
    assert "dusty" not in ids(client.get("/api/assets?archived=true", headers=STAFF)), \
        "asking is not enough without the permission"


def test_archiving_needs_review_content_and_restores(client):
    assert client.put("/api/assets/dusty/archive", json={"archived": True},
                      headers=STAFF).status_code == 403
    access.update_group(EMPLOYEES, "a", permissions=["view_hub", "review_content"])
    assert client.put("/api/assets/dusty/archive", json={"archived": True},
                      headers=STAFF).status_code == 200
    client.put("/api/assets/dusty/archive", json={"archived": False}, headers=STAFF)
    assert "dusty" in ids(client.get("/api/assets", headers=STAFF))


# ─────────────────────────────────────────────────────── review lists
def test_the_review_lists_dust_idle_and_expiring(client):
    review = client.get("/api/admin/content-review", headers=BOSS).json()
    assert [r["asset_id"] for r in review["dust"]] == ["dusty"]
    assert [r["asset_id"] for r in review["idle"]] == ["idle"], \
        "over a year old and not used; 'used' was opened last week; 'fresh' is too new"
    assert review["usage_since"] and review["idle_days"] == 180


def test_still_current_takes_a_demo_off_the_lists_and_shows_when_it_runs_out(client):
    client.put("/api/assets/dusty/still-current", json={"still_current": True}, headers=BOSS)
    review = client.get("/api/admin/content-review", headers=BOSS).json()
    assert review["dust"] == [] and review["expiring"] == [], "a year away"


def test_usage_and_people_are_counted_for_the_reviewer(client):
    review = client.get("/api/admin/content-review?min_age_days=0&idle_days=5",
                        headers=BOSS).json()
    used = next(r for r in review["idle"] if r["asset_id"] == "used")
    assert (used["views_12m"], used["downloads_12m"], used["people_12m"]) == (1, 1, 2)


def test_archived_demos_are_listed_with_who_and_why(client):
    client.put("/api/assets/dusty/archive", json={"archived": True, "reason": "UI from 2018"},
               headers=BOSS)
    review = client.get("/api/admin/content-review", headers=BOSS).json()
    assert review["dust"] == []
    [entry] = review["archived"]
    assert (entry["asset_id"], entry["by"], entry["reason"]) == (
        "dusty", "user:boss@ptc.com", "UI from 2018")


def test_a_leftover_sample_file_never_counts_as_use(client, tmp_path):
    """The sample activity was removed (2026-10-16); a file it left on a share
    is never read, so it cannot make an unused demo look used."""
    long_ago = (date.today() - timedelta(days=80)).isoformat() + "T10:00:00+00:00"
    (tmp_path / "owned" / "usage_events.demo.jsonl").write_text(json.dumps(
        {"at": long_ago, "event": "view", "asset_id": "idle", "synthetic": True,
         "user": "sample.user.01@sample.invalid"}) + "\n", encoding="utf-8")
    review = client.get("/api/admin/content-review", headers=BOSS).json()
    assert "idle" in [r["asset_id"] for r in review["idle"]]
    assert review["usage_since"] > long_ago
