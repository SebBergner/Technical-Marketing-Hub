"""One SharePoint sync at a time, and a requested sync is never dropped
(routers/graph.sync_soon, 2026-10-15)."""
from __future__ import annotations

import threading
import time

import backend.routers.graph as graph


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
