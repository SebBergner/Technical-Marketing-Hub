"""Sign-in log and recent activity (backend/activity.py, 2026-10-07)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend import activity
from backend.auth import AuthMode, CurrentUser
from backend.config import settings
from tests.test_auth import easyauth_headers

NOW = datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)


def iso(dt):
    return dt.isoformat(timespec="seconds")


@pytest.fixture(autouse=True)
def fresh_throttle(monkeypatch):
    monkeypatch.setattr(activity, "_written", {})
    monkeypatch.setattr(settings, "hub_admin_emails", "")


def sign_ins():
    activity.record_sign_in(oid="a", email="Ann@PTC.com", name="Ann", external=False,
                            now=NOW - timedelta(days=10))
    activity.record_sign_in(oid="a", email="ann@ptc.com", name="Ann", external=False,
                            now=NOW - timedelta(hours=2))
    activity.record_sign_in(oid="p", email="p@partner.it", name="Pia", external=True,
                            now=NOW - timedelta(minutes=5))


def test_the_window_counts_people_and_sign_ins():
    sign_ins()
    r = activity.report(since=iso(NOW - timedelta(days=7)), today=iso(NOW - timedelta(hours=3)),
                        now=NOW)
    assert r["counts"] == {"active": 1, "today_people": 2, "window_people": 2,
                           "window_sign_ins": 2, "guests": 1}
    assert [p["user"] for p in r["people"]] == ["p@partner.it", "ann@ptc.com"]
    assert [e["user"] for e in r["log"]["items"]] == ["p@partner.it", "ann@ptc.com"]
    assert r["recorded_since"] == iso(NOW - timedelta(days=10))


def test_active_means_a_request_in_the_last_fifteen_minutes():
    sign_ins()
    r = activity.report(now=NOW)
    assert [a["user"] for a in r["active"]] == ["p@partner.it"], "Ann signed in 2 h ago"
    assert activity.report(now=NOW + timedelta(minutes=16))["active"] == []


def test_the_log_filters_by_person_and_by_text_and_pages():
    sign_ins()
    assert activity.report(user="a", now=NOW)["log"]["total"] == 2
    assert activity.report(q="PIA", now=NOW)["log"]["total"] == 1
    page = activity.report(limit=1, offset=1, now=NOW)["log"]
    assert (page["total"], [e["oid"] for e in page["items"]]) == (3, ["a"])


def test_browsing_is_noted_at_most_every_few_minutes(monkeypatch):
    writes = []
    monkeypatch.setattr("backend.repositories.json_repo._atomic_write",
                        lambda path, payload: writes.append(payload))
    ann = CurrentUser(email="ann@ptc.com", object_id="a", is_authenticated=True)
    for _ in range(5):
        activity.note_request(ann)
    assert len(writes) == 1
    activity.note_request(CurrentUser(email="x@ptc.com"))   # not signed in: nothing
    assert len(writes) == 1


def test_only_view_admin_reads_it(monkeypatch):
    from app import app
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password", "")
    monkeypatch.setattr(settings, "hub_admin_emails", "boss@ptc.com")
    client = TestClient(app, base_url="http://localhost")
    assert client.get("/api/admin/activity").status_code == 401
    assert client.get("/api/admin/activity",
                      headers=easyauth_headers("someone@ptc.com")).status_code == 403
    body = client.get("/api/admin/activity", headers=easyauth_headers("boss@ptc.com")).json()
    assert body["active_minutes"] == 15 and body["log"]["items"] == []
