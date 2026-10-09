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
    activity.record_sign_in(oid="b", email="bo@ptc.com", name="Bo", external=False,
                            now=NOW - timedelta(minutes=10))
    activity.record_sign_in(oid="p", email="p@partner.it", name="Pia", external=True,
                            now=NOW - timedelta(minutes=5))


def test_the_window_counts_ptc_people_and_all_sign_ins():
    sign_ins()
    r = activity.report(since=iso(NOW - timedelta(days=7)), today=iso(NOW - timedelta(hours=3)),
                        now=NOW)
    assert r["counts"] == {"active": 1, "today_people": 2, "today_external_sign_ins": 1,
                           "window_people": 2, "window_sign_ins": 3,
                           "window_external_sign_ins": 1}
    assert [p["user"] for p in r["people"]] == ["bo@ptc.com", "ann@ptc.com"]
    assert [e.get("user") for e in r["log"]["items"]] == [None, "bo@ptc.com", "ann@ptc.com"]
    assert r["recorded_since"] == iso(NOW - timedelta(days=10))


def test_a_partner_is_recorded_without_anything_that_names_them():
    """Meeting 2026-10-07: partners fully anonymous until compliance says otherwise."""
    sign_ins()
    raw = (open(activity.access._owned(activity.EVENTS_FILE), encoding="utf-8").read()
           + open(activity.access._owned(activity.ACTIVITY_FILE), encoding="utf-8").read())
    for trace in ("p@partner.it", "Pia", '"p"'):
        assert trace not in raw
    r = activity.report(now=NOW)
    assert r["log"]["items"][0] == {"at": iso(NOW - timedelta(minutes=5)), "event": "sign_in",
                                    "external": True}
    assert r["external_active"] is True and "p" not in {a["oid"] for a in r["active"]}


def test_a_guest_with_a_ptc_address_is_still_a_partner():
    activity.record_sign_in(oid="g", email="guest@ptc.com", name="G", external=True, now=NOW)
    assert activity.report(now=NOW)["log"]["items"][0].get("user") is None


def test_active_means_a_request_in_the_last_fifteen_minutes():
    sign_ins()
    r = activity.report(now=NOW)
    assert [a["user"] for a in r["active"]] == ["bo@ptc.com"], "Ann signed in 2 h ago"
    later = activity.report(now=NOW + timedelta(minutes=16))
    assert later["active"] == [] and later["external_active"] is False


def test_the_log_filters_by_person_and_by_text_and_pages():
    sign_ins()
    assert activity.report(user="a", now=NOW)["log"]["total"] == 2
    assert activity.report(q="BO", now=NOW)["log"]["total"] == 1
    assert activity.report(q="external", now=NOW)["log"]["total"] == 1
    assert activity.report(q="pia", now=NOW)["log"]["total"] == 0, "nothing to find a partner by"
    page = activity.report(limit=1, offset=2, now=NOW)["log"]
    assert (page["total"], [e["oid"] for e in page["items"]]) == (4, ["a"])


def test_identity_written_before_the_rule_is_scrubbed_and_counts_kept():
    import json
    from backend import access
    old = [{"at": iso(NOW), "event": "sign_in", "oid": "p", "user": "p@partner.it",
            "name": "Pia", "external": True},
           {"at": iso(NOW), "event": "sign_in", "oid": "x", "user": "x@other.com",
            "name": "Xu", "external": False},
           {"at": iso(NOW), "event": "sign_in", "oid": "a", "user": "ann@ptc.com",
            "name": "Ann", "external": False}]
    with open(access._owned(activity.EVENTS_FILE), "w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(e) + "\n" for e in old)
    with open(access._owned(activity.ACTIVITY_FILE), "w", encoding="utf-8") as fh:
        json.dump({"p": {"user": "p@partner.it", "name": "Pia", "external": True,
                         "last_active": iso(NOW)},
                   "a": {"user": "ann@ptc.com", "name": "Ann", "external": False,
                         "last_active": iso(NOW)}}, fh)
    with open(access._owned(access.USERS_FILE), "w", encoding="utf-8") as fh:
        json.dump([{"oid": "p", "email": "p@partner.it", "external": True},
                   {"oid": "a", "email": "ann@ptc.com", "external": False}], fh)

    assert activity.scrub_partners() == {"sign_ins": 2, "activity": 1, "users": 1}
    events = activity._events()
    assert [e.get("user") for e in events] == [None, None, "ann@ptc.com"]
    assert events[0] == {"at": iso(NOW), "event": "sign_in", "external": True}
    assert set(activity._activity()) == {"a", activity.EXTERNAL_KEY}
    assert [u["oid"] for u in access.known_users()] == ["a"]
    assert activity.scrub_partners() == {"sign_ins": 0, "activity": 0, "users": 0}


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
