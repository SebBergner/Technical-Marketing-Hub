"""Searches worked out at 04:00 in Boston (services/search_insights_store.py)."""
from __future__ import annotations

from datetime import datetime, timezone

from backend.services import search_insights_store as store


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


def test_four_in_the_morning_in_boston_through_daylight_saving():
    # 12 Nov: EST (UTC-5), 04:00 Boston is 09:00 UTC.
    assert store.last_slot(utc(2026, 11, 12, 10, 0)) == utc(2026, 11, 12, 9, 0)
    assert store.last_slot(utc(2026, 11, 12, 8, 59)) == utc(2026, 11, 11, 9, 0)
    # 1 July: EDT (UTC-4), 04:00 Boston is 08:00 UTC.
    assert store.last_slot(utc(2026, 7, 1, 8, 30)) == utc(2026, 7, 1, 8, 0)
    assert store.next_slot(utc(2026, 11, 12, 10, 0)) == utc(2026, 11, 13, 9, 0)


def test_due_once_the_morning_run_is_older_than_the_latest_four_oclock():
    now = utc(2026, 11, 12, 10, 0)
    assert store.is_due({}, now)
    assert not store.is_due({"computed_at": "2026-11-12T09:05:00+00:00"}, now)
    assert store.is_due({"computed_at": "2026-11-12T08:55:00+00:00"}, now)


def test_refresh_waits_an_hour_and_never_while_running():
    now = utc(2026, 11, 12, 10, 0)
    assert store.refresh_view({}, now)["available"] is True
    v = store.refresh_view({"refresh_at": "2026-11-12T09:30:00+00:00"}, now)
    assert (v["available"], v["available_at"]) == (False, "2026-11-12T10:30:00+00:00")
    assert store.refresh_view({"refresh_at": "2026-11-12T08:59:00+00:00"}, now)["available"]
    assert store.refresh_view({"running_since": "2026-11-12T09:59:00+00:00"}, now)["available"] is False


def test_the_scheduled_run_happens_once(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(store, "compute_all",
                        lambda data_dir=None, now=None: calls.append(1) or store._update(
                            data_dir, computed_at=store._now().isoformat(), running_since=None))
    assert store.tick(str(tmp_path)) is True
    assert store.tick(str(tmp_path)) is False, "not due again until tomorrow's 04:00"
    assert calls == [1]


def test_a_failed_refresh_does_not_hold_the_button(tmp_path, monkeypatch):
    def boom(data_dir=None, now=None):
        raise RuntimeError("catalogue unreadable")
    monkeypatch.setattr(store, "compute_all", boom)
    store._update(str(tmp_path), refresh_at=store._now().isoformat())
    store.run(str(tmp_path), "refresh")
    state = store.load(str(tmp_path))
    assert state["refresh_at"] is None and state["running_since"] is None
    assert store.refresh_view(state)["available"] is True
