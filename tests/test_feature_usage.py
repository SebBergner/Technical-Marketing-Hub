"""Feature usage (A16, Liwei 2026-11-16): which Hub features people opened."""
from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend import activity
from backend.auth import AuthMode
from backend.config import settings
from backend.services import feature_usage
from tests.test_auth import easyauth_headers

ADMIN, ANN, BOB, PARTNER = "boss@ptc.com", "ann@ptc.com", "bob@ptc.com", "p@partner.it"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import app
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    (tmp_path / "mirror").mkdir()
    (tmp_path / "mirror" / "sharepoint.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password", "")
    monkeypatch.setattr(settings, "hub_admin_emails", ADMIN)
    monkeypatch.setattr(activity, "_written", {})
    monkeypatch.setattr(feature_usage, "_seen", set())
    monkeypatch.setattr(feature_usage, "_seen_day", "")
    return TestClient(app, base_url="http://localhost")


def logged(tmp_path):
    path = tmp_path / "owned" / "usage_events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def post(client, who, feature):
    return client.post("/api/assets/feature-event", json={"feature": feature},
                       headers=easyauth_headers(who))


def test_a_known_feature_is_recorded_once_per_person_per_day(client, tmp_path):
    assert post(client, ANN, "my_hub").status_code == 204
    post(client, ANN, "my_hub")
    post(client, ANN, "my_hub")
    post(client, BOB, "my_hub")
    post(client, ANN, "user_guide")
    rows = logged(tmp_path)
    assert [(r["event"], r["feature"], r["user"]) for r in rows] == [
        ("feature", "my_hub", ANN), ("feature", "my_hub", BOB), ("feature", "user_guide", ANN)]


def test_a_name_outside_the_list_is_dropped_quietly(client, tmp_path):
    assert post(client, ANN, "something_new").status_code == 204
    assert post(client, ANN, "").status_code == 204
    assert logged(tmp_path) == []


def test_a_partner_is_recorded_as_external_never_by_name(client, tmp_path):
    post(client, PARTNER, "my_hub")
    (row,) = logged(tmp_path)
    assert row["external"] is True and "user" not in row
    assert PARTNER not in json.dumps(row)


def test_the_list_is_the_eleven_features_liwei_chose():
    assert [label for _, label in feature_usage.FEATURES] == [
        "My Hub", "Favorites", "Playlists", "Advanced Search", "Table view", "User guide",
        "Get help", "New Asset Inquiry", "Share Internally", "Create DemoBoard", "Report asset"]


def test_summary_counts_people_not_lines_and_keeps_partners_apart():
    ev = [
        {"at": "2026-11-16T09:00:00", "event": "feature", "feature": "my_hub", "user": ANN},
        {"at": "2026-11-16T10:00:00", "event": "feature", "feature": "my_hub", "user": ANN},
        {"at": "2026-11-17T10:00:00", "event": "feature", "feature": "my_hub", "user": "Ann@ptc.com"},
        {"at": "2026-11-17T11:00:00", "event": "feature", "feature": "my_hub", "user": BOB},
        {"at": "2026-11-17T11:00:00", "event": "feature", "feature": "my_hub", "external": True},
        {"at": "2026-11-24T11:00:00", "event": "feature", "feature": "my_hub", "user": BOB},
        {"at": "2026-11-17T11:00:00", "event": "feature", "feature": "not_listed", "user": BOB},
        {"at": "2026-11-17T11:00:00", "event": "view", "asset_id": "x", "user": BOB},
    ]
    out = feature_usage.summarise(ev, "2026-11-16T00:00:00", None, today=date(2026, 11, 25))
    rows = {r["id"]: r for r in out["rows"]}
    assert rows["my_hub"]["people"] == 2          # Ann (twice, any case) and Bob
    assert rows["my_hub"]["partner_visits"] == 1
    assert rows["my_hub"]["days"] == 3            # 11/16, 11/17, 11/24
    assert out["weeks"] == ["2026-11-16", "2026-11-23"]
    assert rows["my_hub"]["weekly"] == [2, 1]
    assert rows["user_guide"]["people"] == 0 and rows["user_guide"]["weekly"] == [0, 0]
    assert len(out["rows"]) == 11                 # every feature has a row, used or not


def test_summary_with_no_events_and_no_start_does_not_fail():
    out = feature_usage.summarise([], None, None, today=date(2026, 11, 16))
    assert len(out["rows"]) == 11 and out["weeks"] == ["2026-11-16"]


def test_stars_and_playlists_are_counted_from_their_files(tmp_path):
    me = tmp_path / "owned" / "me"
    me.mkdir(parents=True)
    (me / "a.json").write_text(json.dumps(
        {"favorites": [{"id": "x", "at": "2026-11-13T10:00:00+00:00"}]}), encoding="utf-8")
    (me / "b.json").write_text(json.dumps(
        {"favorites": [{"id": "x", "at": "2026-10-01T10:00:00+00:00"}]}), encoding="utf-8")
    (me / "c.json").write_text(json.dumps({"recent": []}), encoding="utf-8")
    (me / "broken.json").write_text("{", encoding="utf-8")
    pl = tmp_path / "owned" / "playlists"
    pl.mkdir()
    for i, (owner, at) in enumerate([("o1", "2026-11-14T00:00:00+00:00"),
                                      ("o1", "2026-11-15T00:00:00+00:00"),
                                      ("o2", "2026-09-01T00:00:00+00:00")]):
        (pl / f"p{i}.json").write_text(json.dumps({"id": f"p{i}", "owner": owner,
                                                   "created_at": at}), encoding="utf-8")
    out = feature_usage.starred_and_listed(str(tmp_path), "2026-11-01T00:00:00", None)
    assert out == {"starred_people": 1, "playlist_people": 1}
    out = feature_usage.starred_and_listed(str(tmp_path), None, None)
    assert out == {"starred_people": 2, "playlist_people": 2}


def test_the_admin_usage_page_carries_the_table(client, tmp_path):
    post(client, ANN, "my_hub")
    r = client.get("/api/admin/usage", headers=easyauth_headers(ADMIN))
    assert r.status_code == 200
    feats = r.json()["features"]
    my_hub = next(x for x in feats["rows"] if x["id"] == "my_hub")
    assert my_hub["people"] == 1
    assert "starred_people" in feats and "playlist_people" in feats
    # The old totals are untouched by a feature line.
    assert r.json()["totals"]["views"] == 0 and r.json()["totals"]["searches"] == 0
