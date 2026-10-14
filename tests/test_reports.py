"""Hub activity for every PTC employee (2026-10-14)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend import access, activity
from backend.auth import AuthMode
from backend.config import settings
from tests.test_auth import easyauth_headers

NOW = datetime.now(timezone.utc)


def ev(event, user=None, asset="bobcat", days=1, external=False):
    e = {"at": (NOW - timedelta(days=days)).isoformat(timespec="seconds"), "event": event}
    if asset and event != "search":
        e["asset_id"] = asset
    if user:
        e["user"] = user
    if external:
        e["external"] = True
    return e


EVENTS = ([ev("view", f"p{i}@ptc.com") for i in range(12) for _ in range(i + 1)]
          + [ev("download", "p11@ptc.com"), ev("search", "p0@ptc.com", asset=None)]
          + [ev("view", external=True), ev("download", external=True)]
          + [ev("view")]
          + [ev("view", "p0@ptc.com", days=400)])


def test_the_top_n_only_and_partners_only_as_a_count():
    out = activity.leaderboard(EVENTS, since=(NOW - timedelta(days=30)).isoformat(), top=10)
    ranked = [p["user"] for p in out["people"]]
    assert len(ranked) == 10 and ranked[0] == "p11@ptc.com", "most active first"
    assert "p0@ptc.com" not in ranked and "p1@ptc.com" not in ranked, "no bottom of the list"
    assert out["external_not_ranked"] == 2
    assert all("partner" not in json.dumps(p) for p in out["people"])
    assert out["totals"]["active_people"] == 12 and out["totals"]["anonymous"] == 1


def test_teams_are_hub_groups_with_their_totals():
    teams = [{"name": "CAD team", "members": ["p11@ptc.com", "p10@ptc.com", "x@ptc.com"]}]
    out = activity.leaderboard(EVENTS, top=3, teams=teams)
    [team] = out["teams"]
    assert (team["team"], team["members"], team["active"]) == ("CAD team", 3, 2)
    assert team["view"] == 12 + 11 and team["download"] == 1


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import app
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password", "")
    (tmp_path / "mirror").mkdir()
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps([
        {"id": "bobcat", "type": "vdk", "title": "Bobcat IPL", "products": ["Creo"]}]),
        encoding="utf-8")
    (tmp_path / "owned").mkdir()
    (tmp_path / "owned" / "usage_events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in EVENTS) + "\n", encoding="utf-8")
    return TestClient(app, base_url="http://localhost")


def test_every_ptc_employee_may_see_it_partners_may_not(client):
    body = client.get("/api/reports/activity", headers=easyauth_headers("someone@ptc.com"))
    assert body.status_code == 200 and body.json()["content"][0]["title"] == "Bobcat IPL"
    assert client.get("/api/reports/activity",
                      headers=easyauth_headers("p@partner.it")).status_code == 403
    access.update_group(access.EMPLOYEES, "a", permissions=["view_hub"])
    assert client.get("/api/reports/activity",
                      headers=easyauth_headers("someone@ptc.com")).status_code == 403


def test_the_old_address_leads_to_the_view_inside_the_hub(client):
    r = client.get("/reports", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/#/activity"


def test_the_daily_series_and_the_previous_period_come_with_it(client):
    from datetime import datetime, timedelta, timezone
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    body = client.get("/api/reports/activity", params={"since": since},
                      headers=easyauth_headers("someone@ptc.com")).json()
    assert len(body["series"]) in (30, 31) and body["previous"] is not None
    assert body["content"][0]["type"] == "vdk"
