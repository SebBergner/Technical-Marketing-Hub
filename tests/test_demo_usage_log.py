"""The demonstration usage log, and the promise that removing it is safe.

Synthetic events exist so the Admin page can be shown to people before the
Hub has accumulated real traffic. The whole arrangement is only defensible if
two things hold: every made-up figure is labelled as one, and taking the
made-up figures away cannot damage the real record. Both are asserted here,
because both are the kind of property that survives review and then quietly
breaks a release later.
"""
import json
import os

import pytest

from backend.repositories.json_repo import DEMO_USAGE_EVENTS, JsonAssetRepository


@pytest.fixture()
def repo(tmp_path):
    return JsonAssetRepository(str(tmp_path))


def demo_file(repo):
    return os.path.join(repo.owned_dir, DEMO_USAGE_EVENTS)


def write_demo(repo, *events):
    os.makedirs(repo.owned_dir, exist_ok=True)
    with open(demo_file(repo), "w", encoding="utf-8", newline="\n") as fh:
        for event in events:
            fh.write(json.dumps(event) + "\n")


def test_demo_events_are_read_alongside_the_real_ones(repo):
    """Merged on read, so the page needs no notion of a demo mode."""
    repo.record_usage_event("view", asset_id="real-one")
    write_demo(repo, {"event": "view", "asset_id": "made-up",
                      "at": "2026-01-01T09:00:00", "synthetic": True})

    events = repo.usage_events()

    assert {e["asset_id"] for e in events} == {"real-one", "made-up"}


def test_the_merged_log_is_in_time_order(repo):
    """Two files read one after another arrive in file order, not time order,
    and the chart draws whatever sequence it is handed."""
    write_demo(repo, {"event": "view", "at": "2026-01-01T09:00:00",
                      "synthetic": True},
               {"event": "view", "at": "2026-06-01T09:00:00",
                "synthetic": True})
    repo.record_usage_event("view", asset_id="real-one")   # now, so: last

    stamps = [e["at"] for e in repo.usage_events()]

    assert stamps == sorted(stamps)


def test_a_demo_event_raises_the_synthetic_banner(repo):
    """What the Admin page actually checks.

    The banner is driven by the per-event flag, not by the filename, so this
    is the assertion that stops a made-up figure being read as a measurement.
    A real log alone must not raise it, or the warning becomes background
    noise that people learn to ignore.
    """
    repo.record_usage_event("view", asset_id="real-one")
    assert not any(e.get("synthetic") for e in repo.usage_events())

    write_demo(repo, {"event": "view", "asset_id": "made-up",
                      "at": "2026-01-01T09:00:00", "synthetic": True})

    assert any(e.get("synthetic") for e in repo.usage_events())


def test_removing_the_demo_file_leaves_real_events_untouched(repo):
    """The reason the demo data lives in its own file at all.

    With one combined log, "delete the made-up figures" is a download, a
    filter and an upload -- and the obvious shortcut deletes however much
    genuine usage has built up beside them.
    """
    repo.record_usage_event("view", asset_id="real-one")
    repo.record_usage_event("download", asset_id="real-one", file="Kit.zip")
    write_demo(repo, {"event": "view", "asset_id": "made-up",
                      "at": "2026-01-01T09:00:00", "synthetic": True})
    assert len(repo.usage_events()) == 3

    os.remove(demo_file(repo))

    remaining = repo.usage_events()
    assert len(remaining) == 2
    assert {e["asset_id"] for e in remaining} == {"real-one"}
    assert not any(e.get("synthetic") for e in remaining)


def test_recording_never_writes_to_the_demo_file(repo):
    """Nothing in the app appends here. If a real event could land in the demo
    file, deleting that file would start destroying real data -- which is the
    one thing this split exists to prevent."""
    write_demo(repo, {"event": "view", "asset_id": "made-up",
                      "at": "2026-01-01T09:00:00", "synthetic": True})
    before = open(demo_file(repo), encoding="utf-8").read()

    repo.record_usage_event("view", asset_id="real-one")
    repo.record_usage_event("search", q="windchill", results=3)

    assert open(demo_file(repo), encoding="utf-8").read() == before
    real = os.path.join(repo.owned_dir, "usage_events.jsonl")
    assert os.path.exists(real)


def test_a_window_filters_both_files(repo):
    """The demo log is not exempt from the time range, or "this week" would
    quietly include four months of invented history."""
    write_demo(repo, {"event": "view", "at": "2026-01-01T09:00:00",
                      "synthetic": True},
               {"event": "view", "at": "2026-06-01T09:00:00",
                "synthetic": True})

    assert len(repo.usage_events(since="2026-03-01T00:00:00")) == 1
    assert len(repo.usage_events(until="2026-03-01T00:00:00")) == 1
