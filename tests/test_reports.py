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
    # The tiles count everyone, like the daily line: named, anonymous and
    # partners alike (2026-10-16) -- 78 named views + 1 anonymous + 1 partner.
    assert (out["totals"]["view"], out["totals"]["download"], out["totals"]["search"]) == (80, 2, 1)
    assert sum(d["view"] for d in out["series"]) == out["totals"]["view"]


def test_the_page_says_from_when_people_are_counted_by_name(tmp_path, monkeypatch):
    """Production's log before 2026-10-16 names nobody: a period reaching
    back past the first named event says so; one inside it does not."""
    from backend.routers import reports
    events = [ev("view", days=20), ev("view", "p0@ptc.com", days=3),
              ev("view", "p1@ptc.com", days=1)]
    repo = type("R", (), {"usage_events": lambda self: events,
                          "list": lambda self, q: type("L", (), {"items": []})()})()
    monkeypatch.setattr(reports.access, "load_state", lambda: {"groups": []})
    month = reports.hub_activity(since=(NOW - timedelta(days=30)).isoformat(), until=None,
                                 top=10, repo=repo)
    assert month["named_since"] == events[1]["at"][:10]
    two_days = reports.hub_activity(since=(NOW - timedelta(days=2)).isoformat(), until=None,
                                    top=10, repo=repo)
    assert two_days["named_since"] is None


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


def test_creators_are_ranked_by_how_much_their_demos_were_used_in_the_window():
    events = [ev("view", "a@ptc.com", asset="kit1"), ev("download", "b@ptc.com", asset="kit1"),
              ev("view", "a@ptc.com", asset="kit2"), ev("view", "a@ptc.com", asset="video"),
              ev("view", "a@ptc.com", asset="old", days=400)]
    out = activity.leaderboard(events, since=(NOW - timedelta(days=30)).isoformat(),
                               creators={"kit1": "Hughes, Paul", "kit2": "Wall, Eric",
                                         "old": "Aulenbach, Jason"})
    assert [(c["creator"], c["demos"], c["views"], c["downloads"], c["people"])
            for c in out["creators"]] == [("Hughes, Paul", 1, 1, 1, 2), ("Wall, Eric", 1, 1, 0, 1)]
    assert out["unattributed_uses"] == 1, "the Demo Video one has no creator"
    assert "Aulenbach, Jason" not in {c["creator"] for c in out["creators"]}, \
        "unused in the window: not ranked at all"


def test_the_hub_page_is_revalidated_and_carries_no_inline_handlers(client):
    """2026-10-14: index.html is markup only; behaviour lives in
    static/js/hub-ui.js, and the page must not be served stale after a deploy."""
    r = client.get("/")
    assert r.headers["cache-control"] == "no-cache"
    assert "onclick=" not in r.text and "onchange=" not in r.text
    assert '<script src="/static/js/hub-ui.js" defer></script>' in r.text


def test_the_usage_breakdown_reads_the_catalogue_once_and_names_types(client, monkeypatch):
    """2026-10-14: a get() per demo used rebuilt the catalogue each time and
    took the Hub usage tab to 15 s; and a type read "AssetType.VDK"."""
    from backend.repositories.json_repo import JsonAssetRepository
    calls = []
    real_get = JsonAssetRepository.get
    monkeypatch.setattr(JsonAssetRepository, "get",
                        lambda self, aid: calls.append(aid) or real_get(self, aid))
    boss = easyauth_headers("boss@ptc.com")
    monkeypatch.setattr(settings, "hub_admin_emails", "boss@ptc.com")
    demo = client.get("/api/admin/usage/breakdown?dimension=demo", headers=boss).json()
    assert demo["rows"][0]["label"] == "Bobcat IPL" and calls == []
    by_type = client.get("/api/admin/usage/breakdown?dimension=type", headers=boss).json()
    assert [r["label"] for r in by_type["rows"]] == ["VDKs"]
    scoped = client.get("/api/admin/usage/breakdown?dimension=demo&scope_dim=type&scope_key=vdk",
                        headers=boss).json()
    assert scoped["total_rows"] == 1, "drilling into a type still matches its demos"


# ── the Dashboard (Serge, 2026-10-23) ─────────────────────────────────────
def test_usage_comes_by_asset_type_too(client):
    """PTC people only, like the content list: partners' uses are not in it."""
    body = client.get("/api/reports/activity",
                      headers=easyauth_headers("someone@ptc.com")).json()
    # 78 named views, one recorded without a name, one 400 days back (no
    # period asked for); the partner's view and download are not counted.
    assert body["by_type"] == [{"type": "vdk", "views": 80, "downloads": 1, "demos": 1}]
    assert "used" not in body, "the per-demo map stays on the server"


def test_the_library_is_for_ptc_people_and_counts_by_type_and_month(client):
    from datetime import date
    body = client.get("/api/reports/library", headers=easyauth_headers("someone@ptc.com"))
    assert body.status_code == 200
    d = body.json()
    assert d["total"] == 1
    assert {t["type"]: t["count"] for t in d["types"]}["vdk"] == 1
    assert [x["key"] for x in d["dimensions"]] == ["type", "product", "segment", "language", "age"]
    assert len(d["by_month"]) == 24 and d["by_month"][-1]["month"] == date.today().strftime("%Y-%m")
    assert client.get("/api/reports/library",
                      headers=easyauth_headers("p@partner.it")).status_code == 403
