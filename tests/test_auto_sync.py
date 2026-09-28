"""The daily sync: when it runs, that only one process runs it, and the switch.

Every test runs against a temporary data directory and a fake `run`, so
nothing here can reach SharePoint or Consensus -- the real sources are only
ever touched through `_run_sources`, whose isolation is tested with the two
routers' `run_sync` replaced.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import app
from backend import auto_sync
from backend.config import settings

UTC = timezone.utc


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=UTC)


@pytest.fixture
def data(tmp_path):
    return str(tmp_path)


def turned_on(data, hour=6, when=at(28, 10)):
    return auto_sync.configure(True, hour, "test", data_dir=data, now=when)


class Recorder:
    def __init__(self, results=None):
        self.calls = 0
        self.results = results or {"sharepoint": {"ok": True}, "consensus": {"ok": True}}

    def __call__(self, repo):
        self.calls += 1
        return self.results


# ──────────────────────────────────────────────────────────────── when
def test_off_by_default_and_off_means_never(data):
    run = Recorder()
    assert auto_sync.load_state(data)["enabled"] is False
    assert auto_sync.tick(repo=object(), data_dir=data, now=at(29, 12), run=run) is None
    assert run.calls == 0


def test_switching_it_on_does_not_start_a_sync(data):
    # On at 10:00 with the hour at 06:00: the next run is tomorrow at 06:00,
    # not now -- nobody's afternoon catalogue changes under them.
    turned_on(data, hour=6, when=at(28, 10))
    run = Recorder()
    assert auto_sync.tick(repo=object(), data_dir=data, now=at(28, 10, 30), run=run) is None
    assert auto_sync.tick(repo=object(), data_dir=data, now=at(29, 5, 59), run=run) is None
    assert run.calls == 0
    assert auto_sync.next_slot(auto_sync.load_state(data), at(28, 10, 30)) == at(29, 6)


def test_it_runs_once_per_day_at_the_hour(data):
    turned_on(data, hour=6, when=at(28, 10))
    run = Recorder()
    assert auto_sync.tick(repo=object(), data_dir=data, now=at(29, 6, 5), run=run)["ok"] is True
    assert auto_sync.tick(repo=object(), data_dir=data, now=at(29, 6, 15), run=run) is None
    assert auto_sync.tick(repo=object(), data_dir=data, now=at(29, 23), run=run) is None
    assert auto_sync.tick(repo=object(), data_dir=data, now=at(30, 6, 1), run=run) is not None
    assert run.calls == 2


def test_a_run_missed_while_the_app_slept_happens_when_it_wakes(data):
    # Without Always On the app unloads when idle; the loop stops with it.
    turned_on(data, hour=6, when=at(28, 10))
    run = Recorder()
    assert auto_sync.tick(repo=object(), data_dir=data, now=at(29, 14), run=run) is not None
    assert run.calls == 1


def test_the_hour_is_utc_and_changing_it_moves_the_next_run(data):
    turned_on(data, hour=6, when=at(28, 10))
    auto_sync.configure(True, 22, "test", data_dir=data, now=at(28, 11))
    state = auto_sync.load_state(data)
    assert state["hour_utc"] == 22
    assert auto_sync.next_slot(state, at(28, 11)) == at(28, 22)


# ─────────────────────────────────────────────────────── one process only
def test_a_second_process_skips_while_the_first_holds_the_lock(data):
    turned_on(data, hour=6, when=at(28, 10))
    assert auto_sync._claim(data)                 # the other worker, mid-run
    run = Recorder()
    assert auto_sync.tick(repo=object(), data_dir=data, now=at(29, 6, 5), run=run) is None
    assert run.calls == 0
    auto_sync._release(data)
    assert auto_sync.tick(repo=object(), data_dir=data, now=at(29, 6, 15), run=run) is not None


def test_a_lock_left_by_a_dead_process_is_taken_over(data):
    turned_on(data, hour=6, when=at(28, 10))
    assert auto_sync._claim(data)
    lock = os.path.join(data, "owned", auto_sync.LOCK_FILE)
    old = time.time() - auto_sync.STALE_LOCK_SECONDS - 60
    os.utime(lock, (old, old))
    run = Recorder()
    assert auto_sync.tick(repo=object(), data_dir=data, now=at(29, 6, 5), run=run) is not None


def test_the_lock_is_released_even_when_the_run_raises(data):
    turned_on(data, hour=6, when=at(28, 10))

    def boom(repo):
        raise RuntimeError("disk full")

    with pytest.raises(RuntimeError):
        auto_sync.tick(repo=object(), data_dir=data, now=at(29, 6, 5), run=boom)
    assert not os.path.exists(os.path.join(data, "owned", auto_sync.LOCK_FILE))
    # And it counts as tried: the loop does not hammer a failing source
    # every ten minutes for the rest of the day.
    assert auto_sync.tick(repo=object(), data_dir=data, now=at(29, 6, 15),
                          run=Recorder()) is None


# ──────────────────────────────────────────────────────────── the record
def test_a_failure_is_recorded_not_hidden(data):
    turned_on(data, hour=6, when=at(28, 10))
    run = Recorder({"sharepoint": {"ok": True},
                    "consensus": {"ok": False, "error": "token expired"}})
    record = auto_sync.tick(repo=object(), data_dir=data, now=at(29, 6, 5), run=run)
    assert record["ok"] is False
    assert auto_sync.load_state(data)["last_run"]["results"]["consensus"]["error"] == "token expired"


def test_a_source_without_credentials_is_skipped_not_failed(data):
    turned_on(data, hour=6, when=at(28, 10))
    run = Recorder({"sharepoint": {"ok": True},
                    "consensus": {"ok": None, "skipped": "not configured"}})
    assert auto_sync.tick(repo=object(), data_dir=data, now=at(29, 6, 5), run=run)["ok"] is True


def test_consensus_failing_does_not_stop_sharepoint(monkeypatch):
    from backend.integrations.graph import client as graph_client
    from backend.routers import consensus, graph

    calls = []
    monkeypatch.setattr(graph_client, "get_graph_client", lambda: object())
    monkeypatch.setattr(graph, "run_sync", lambda c, r, a: calls.append("sp") or {"vm_pages": {"ok": True}})

    def consensus_fails(c, r, a):
        calls.append("cs")
        raise RuntimeError("502 from Consensus")

    monkeypatch.setattr(consensus, "run_sync", consensus_fails)
    results = auto_sync._run_sources(repo=object())
    assert calls == ["sp", "cs"]
    assert results["sharepoint"]["ok"] is True
    assert results["consensus"] == {"ok": False, "error": "502 from Consensus"}


# ────────────────────────────────────────────────────────────── the switch
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "a-test-password")
    # Sign-in enforced, so the laptop's development principal (a curator by
    # design) is not in play and the admin key is the only way in.
    monkeypatch.setattr(settings, "auth_mode", "easyauth")
    # Loopback, or the admin cookie is marked Secure and dropped over http
    # (the reason test_auth.py gives for the same line).
    return TestClient(app, base_url="http://localhost")


def test_nobody_can_flip_it_without_the_admin_key(client):
    assert client.put("/api/admin/auto-sync", json={"enabled": True}).status_code == 401


def test_an_admin_flips_it_and_the_page_sees_it(client):
    assert client.post("/api/admin/login",
                       json={"username": "admin", "password": "a-test-password"}).status_code == 200
    body = client.put("/api/admin/auto-sync", json={"enabled": True, "hour_utc": 5}).json()
    assert (body["enabled"], body["hour_utc"], body["changed_by"]) == (True, 5, "admin-session")
    assert body["next_run_at"]
    overview = client.get("/api/admin/overview").json()["auto_sync"]
    assert overview["enabled"] is True
    assert client.put("/api/admin/auto-sync", json={"enabled": True, "hour_utc": 24}).status_code == 422


def test_the_suite_never_starts_the_loop():
    assert settings.auto_sync_scheduler is False
