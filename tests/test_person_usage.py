"""What PTC people use, by person; partners anonymous (meeting 2026-10-07, built 2026-10-09)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend import activity
from backend.auth import AuthMode
from backend.config import settings
from tests.test_auth import easyauth_headers

ADMIN, ANN, PARTNER = "boss@ptc.com", "ann@ptc.com", "p@partner.it"
NOW = datetime(2026, 10, 9, 15, 0, tzinfo=timezone.utc)


def iso(dt):
    return dt.isoformat(timespec="seconds")


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import app
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    (tmp_path / "mirror").mkdir()
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps([
        {"id": "bobcat", "type": "vdk", "title": "Bobcat IPL", "products": ["Creo"],
         "resources": [{"name": "B.mp4", "kind": "video", "item_id": "I-2"}]}]),
        encoding="utf-8")
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password", "")
    monkeypatch.setattr(settings, "hub_admin_emails", ADMIN)
    monkeypatch.setattr(activity, "_written", {})
    return TestClient(app, base_url="http://localhost")


def logged(tmp_path):
    path = tmp_path / "owned" / "usage_events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_ptc_people_are_named_partners_are_not_anyone_else_is_anonymous(client, tmp_path):
    client.post("/api/assets/bobcat/view", headers=easyauth_headers("Ann@PTC.com"))
    client.post("/api/assets/bobcat/view", headers=easyauth_headers(PARTNER))
    client.post("/api/assets/search-event", json={"q": "bobcat", "results": 1},
                headers=easyauth_headers(ANN))
    client.post("/api/assets/search-event", json={"q": "lambo", "results": 0},
                headers=easyauth_headers(PARTNER))
    view_ann, view_partner, search_ann, search_partner = logged(tmp_path)
    assert view_ann["user"] == ANN and "external" not in view_ann
    assert view_partner == {"at": view_partner["at"], "event": "view", "asset_id": "bobcat",
                            "external": True}
    assert search_ann["user"] == ANN
    assert "user" not in search_partner and search_partner["external"] is True


def events():
    return [
        {"at": iso(NOW - timedelta(days=1)), "event": "view", "asset_id": "bobcat", "user": ANN},
        {"at": iso(NOW - timedelta(hours=5)), "event": "download", "asset_id": "bobcat",
         "user": ANN, "file": "B.mp4"},
        {"at": iso(NOW - timedelta(hours=4)), "event": "search", "user": ANN, "q": "creo",
         "results": 3},
        {"at": iso(NOW - timedelta(hours=3)), "event": "view", "asset_id": "bobcat",
         "user": "bo@ptc.com"},
        {"at": iso(NOW - timedelta(hours=2)), "event": "view", "asset_id": "bobcat",
         "external": True},
        {"at": iso(NOW - timedelta(days=30)), "event": "view", "asset_id": "bobcat", "user": ANN},
        {"at": iso(NOW - timedelta(hours=1)), "event": "view", "asset_id": "bobcat"},
    ]


def test_people_get_their_counts_and_people_without_a_sign_in_in_the_period_appear():
    activity.record_sign_in(oid="a", email=ANN, name="Ann", external=False,
                            now=NOW - timedelta(days=2))
    since = iso(NOW - timedelta(days=7))
    rep = activity.attach_usage(activity.report(since=since, now=NOW), events(), since=since)
    people = {p["user"]: p for p in rep["people"]}
    assert set(people) == {ANN, "bo@ptc.com"}, "Bo used it without signing in this week"
    assert {k: people[ANN]["usage"][k] for k in activity.USAGE_KINDS} == {
        "view": 1, "preview": 0, "download": 1, "search": 1}
    assert rep["counts"]["window_external_usage"] == 1
    assert rep["counts"]["window_usage"]["view"] == 4, "Ann, Bo, the partner, the anonymous one"


def test_one_persons_activity_newest_first_with_titles():
    out = activity.person_usage(events(), "ANN@ptc.com", {"bobcat": "Bobcat IPL"},
                                since=iso(NOW - timedelta(days=7)))
    assert out["counts"] == {"view": 1, "preview": 0, "download": 1, "search": 1}
    assert [(i["event"], i["title"], i["q"]) for i in out["items"]] == [
        ("search", None, "creo"), ("download", "Bobcat IPL", None), ("view", "Bobcat IPL", None)]
    assert activity.person_usage(events(), PARTNER, {})["total"] == 0


def test_only_view_admin_reads_a_persons_activity(client):
    client.post("/api/assets/bobcat/view", headers=easyauth_headers(ANN))
    url = "/api/admin/activity/person?email=" + ANN
    assert client.get(url, headers=easyauth_headers(ANN)).status_code == 403
    body = client.get(url, headers=easyauth_headers(ADMIN)).json()
    assert body["total"] == 1 and body["items"][0]["title"] == "Bobcat IPL"
    people = client.get("/api/admin/activity", headers=easyauth_headers(ADMIN)).json()["people"]
    assert [p["user"] for p in people] == [ANN]
