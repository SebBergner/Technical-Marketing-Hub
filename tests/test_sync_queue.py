"""One SharePoint sync at a time, and a requested sync is never dropped
(routers/graph.sync_soon, 2026-10-15)."""
from __future__ import annotations

import os
import threading
import time

import pytest

import backend.routers.graph as graph


@pytest.fixture(autouse=True)
def lock_in_tmp(tmp_path, monkeypatch):
    """The cross-worker lock file lives in a scratch folder, not DATA_DIR."""
    path = str(tmp_path / "sharepoint_sync")
    monkeypatch.setattr(graph, "_lock_path", lambda repo: path)
    return path


def test_a_request_during_a_sync_runs_once_after_it(monkeypatch):
    started, release, calls = threading.Event(), threading.Event(), []

    def fake(client, repo, actor, full=False):
        calls.append(actor)
        if len(calls) == 1:
            started.set()
            release.wait(5)
        return {}
    monkeypatch.setattr(graph, "_run_sync", fake)
    monkeypatch.setattr(graph, "get_graph_client", lambda: object())

    running = threading.Thread(target=graph.run_sync, args=(object(), None, "button"))
    running.start()
    assert started.wait(5)
    graph.sync_soon(None, "upload A")          # both made while "button" runs,
    graph.sync_soon(None, "upload B")          # which cannot see their folders
    assert graph.sync_running()
    release.set()
    running.join(5)
    for _ in range(50):
        if not graph.sync_running():
            break
        time.sleep(0.1)
    assert calls == ["button", "queued for upload B"], "exactly one more, after it"


def test_two_syncs_never_overlap(monkeypatch):
    inside, overlap = [0], []

    def fake(client, repo, actor, full=False):
        inside[0] += 1
        overlap.append(inside[0])
        time.sleep(0.05)
        inside[0] -= 1
        return {}
    monkeypatch.setattr(graph, "_run_sync", fake)
    threads = [threading.Thread(target=graph.run_sync, args=(object(), None, f"t{i}"))
               for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert max(overlap) == 1


def test_a_sync_in_another_worker_is_seen_and_waited_for(lock_in_tmp, monkeypatch):
    """2026-11-05: the threading lock covered one gunicorn worker only."""
    calls = []
    monkeypatch.setattr(graph, "_run_sync",
                        lambda client, repo, actor, full=False: calls.append(actor) or {})
    with open(lock_in_tmp + ".lock", "w") as fh:      # another worker's sync
        fh.write("12345")
    assert graph.sync_running()
    t = threading.Thread(target=graph.run_sync, args=(object(), None, "button"))
    t.start()
    time.sleep(0.3)
    assert calls == [], "waits while the other worker syncs"
    os.remove(lock_in_tmp + ".lock")
    t.join(10)
    assert calls == ["button"]
    assert not graph.sync_running()


def test_a_lock_left_by_a_dead_worker_is_taken_over(lock_in_tmp, monkeypatch):
    calls = []
    monkeypatch.setattr(graph, "_run_sync",
                        lambda client, repo, actor, full=False: calls.append(actor) or {})
    with open(lock_in_tmp + ".lock", "w") as fh:
        fh.write("12345")
    old = time.time() - graph.SYNC_STALE_SECONDS - 60
    os.utime(lock_in_tmp + ".lock", (old, old))
    assert not graph.sync_running()
    graph.run_sync(object(), None, "button")
    assert calls == ["button"]


def test_the_button_returns_at_once_and_a_full_request_is_kept(monkeypatch):
    """D17: the button queues the sync instead of holding the request open
    past Azure's front end (HTTP 499 on staging, 2026-11-03)."""
    started, release, runs = threading.Event(), threading.Event(), []

    def fake(client, repo, actor, full=False):
        runs.append((actor, full))
        if len(runs) == 1:
            started.set()
            release.wait(5)
        return {}
    monkeypatch.setattr(graph, "_run_sync", fake)
    monkeypatch.setattr(graph, "get_graph_client", lambda: object())
    graph.sync_soon(None, "upload")
    assert started.wait(5)
    result = graph.sync(full=True, repo=None, actor="liwei", client=object())
    assert result == {"queued": True, "was_running": True}
    release.set()
    for _ in range(50):
        if not graph.sync_running():
            break
        time.sleep(0.1)
    assert runs == [("queued for upload", False), ("queued for liwei", True)]
