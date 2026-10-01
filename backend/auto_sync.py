"""The daily sync, switched on and off from the Admin page (Liwei, 2026-09-28).

Twice a day since 2026-09-30 (Seb: one run early morning, one late at night).
Both hours are chosen on the Admin page, and one switch turns both on or off
(Liwei). A setting saved before then held a single `hour_utc`; it is read as
that hour plus the one twelve hours later.

What it does: at each hour chosen on the Admin page, run the same
two syncs the Admin buttons run -- SharePoint (with the VM pages) and then
Consensus -- and record how it went. The buttons and the schedule call the
same functions (`run_sync` in routers/graph.py and routers/consensus.py), so
a scheduled sync is exactly a button press nobody had to make.

Where the setting lives: `owned/auto_sync.json` under DATA_DIR. It is
Portal-authored, so it belongs with the other owned files and not with the
rebuildable mirror. Each slot has its own share, so each slot has its own
switch -- turning it on for staging does not turn it on for production.

How it runs, and the three things that shaped it:

* **In the app, not beside it.** A loop started with the app wakes every
  ten minutes and asks "is a run due?". No second Azure resource to create,
  secure and keep in step with the code. The cost: App Service unloads an
  idle app after about twenty minutes unless *Always On* is enabled, and an
  unloaded app has no loop. So "due" is defined to catch up -- a run missed
  while asleep happens on the next wake after the hour -- and the Admin page
  says when the last one actually ran.

* **Several processes may run this loop.** gunicorn starts more than one
  worker, each with its own copy. A lock file created with O_EXCL on the
  shared data directory lets exactly one of them run; the others see it and
  skip. A lock older than three hours belonged to a process that died
  mid-sync and is taken over.

* **Switching it on does not start a sync.** The first run is the next time
  the chosen hour comes round, so turning the switch on in the middle of a
  working day does not quietly rewrite the catalogue under whoever is using
  it. The buttons are still there for a sync now.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

from backend.config import settings

log = logging.getLogger(__name__)

STATE_FILE = "auto_sync.json"
LOCK_FILE = "auto_sync.lock"
#: 06:00 UTC: 02:00 in New York, 14:00 in Shanghai -- the quiet end of the day
#: for most of the team, and after overnight edits in SharePoint.
DEFAULT_HOUR_UTC = 6
#: The two daily runs. The second default is twelve hours on: 14:00 in New
#: York, 02:00 in Shanghai.
RUNS_PER_DAY = 2
DEFAULT_HOURS_UTC = (DEFAULT_HOUR_UTC, (DEFAULT_HOUR_UTC + 12) % 24)
TICK_SECONDS = 600
FIRST_TICK_SECONDS = 60
STALE_LOCK_SECONDS = 3 * 3600


def _owned(name: str, data_dir: str | None = None) -> str:
    return os.path.join(data_dir or settings.data_dir, "owned", name)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def load_state(data_dir: str | None = None) -> dict:
    path = _owned(STATE_FILE, data_dir)
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f) or {}
    except (OSError, ValueError):
        state = {}
    state.setdefault("enabled", False)
    state.setdefault("hour_utc", DEFAULT_HOUR_UTC)
    if not state.get("hours_utc"):
        # Saved before there were two runs: keep its hour, add the one twelve
        # hours later.
        first = int(state["hour_utc"]) % 24
        state["hours_utc"] = [first, (first + 12) % 24]
    state["hours_utc"] = _hours(state["hours_utc"])
    return state


def _hours(hours) -> list[int]:
    """Exactly RUNS_PER_DAY hours, each 0-23, in the order given."""
    hours = [int(h) % 24 for h in ([hours] if isinstance(hours, int) else list(hours))]
    defaults = list(DEFAULT_HOURS_UTC)
    while len(hours) < RUNS_PER_DAY:
        hours.append(defaults[len(hours)])
    return hours[:RUNS_PER_DAY]


def save_state(state: dict, data_dir: str | None = None) -> None:
    from backend.repositories.json_repo import _atomic_write   # the one safe writer
    path = _owned(STATE_FILE, data_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _atomic_write(path, state)


def configure(enabled: bool, hours_utc, actor: str,
              data_dir: str | None = None, now: datetime | None = None) -> dict:
    """`hours_utc`: the two run hours (an int alone sets the first, as before)."""
    now = now or _now()
    state = load_state(data_dir)
    if enabled and not state.get("enabled"):
        # The schedule starts counting from here -- see the module docstring.
        state["enabled_at"] = now.isoformat(timespec="seconds")
    if isinstance(hours_utc, int):
        hours_utc = [hours_utc] + state["hours_utc"][1:]
    hours = _hours(hours_utc)
    state.update(enabled=bool(enabled), hours_utc=hours,
                 # Kept for anything that still reads one hour.
                 hour_utc=hours[0],
                 changed_by=actor, changed_at=now.isoformat(timespec="seconds"))
    save_state(state, data_dir)
    log.info("auto sync %s at %s UTC by %s", "enabled" if enabled else "disabled",
             " and ".join(f"{h:02d}:00" for h in hours), actor)
    return state


def last_slot(hour_utc: int, now: datetime) -> datetime:
    """The most recent moment one daily hour said "sync now"."""
    slot = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    return slot if slot <= now else slot - timedelta(days=1)


def _latest_slot(state: dict, now: datetime) -> datetime:
    """The most recent moment any of the daily hours said "sync now"."""
    return max(last_slot(h, now) for h in state["hours_utc"])


def next_slot(state: dict, now: datetime | None = None) -> datetime | None:
    if not state.get("enabled"):
        return None
    now = now or _now()
    if is_due(state, now):
        return now
    return min(last_slot(h, now) + timedelta(days=1) for h in state["hours_utc"])


def is_due(state: dict, now: datetime | None = None) -> bool:
    """On, and the latest scheduled moment has not been run since.

    "Since" counts from the later of the last run and the moment the switch
    was turned on, so switching on never triggers a run by itself, and a run
    missed while the app was asleep still happens once it wakes.
    """
    if not state.get("enabled"):
        return False
    now = now or _now()
    slot = _latest_slot(state, now)
    covered = [t for t in (_parse((state.get("last_run") or {}).get("started_at")),
                           _parse(state.get("enabled_at"))) if t]
    return not covered or slot > max(covered)


# ─────────────────────────────────────────────────────────── one process only
def _claim(data_dir: str | None = None) -> bool:
    path = _owned(LOCK_FILE, data_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                age = time.time() - os.path.getmtime(path)
            except OSError:
                continue                  # released between the two calls
            if age < STALE_LOCK_SECONDS:
                return False
            log.warning("auto sync: taking over a lock %.0f min old", age / 60)
            try:
                os.remove(path)
            except OSError:
                return False
            continue
        with os.fdopen(fd, "w") as f:
            f.write(f"{os.getpid()} {_now().isoformat(timespec='seconds')}")
        return True
    return False


def _release(data_dir: str | None = None) -> None:
    try:
        os.remove(_owned(LOCK_FILE, data_dir))
    except OSError:
        pass


# ───────────────────────────────────────────────────────────────── the run
def _run_sources(repo) -> dict:
    """Both syncs, each isolated: Consensus failing does not undo SharePoint,
    and a source this deployment has no credentials for is skipped, not
    failed."""
    from backend.integrations.graph.client import get_graph_client
    from backend.routers import consensus, graph

    results: dict[str, dict] = {}
    client = get_graph_client()
    if client is None:
        results["sharepoint"] = {"ok": None, "skipped": "not configured"}
    else:
        try:
            summary = graph.run_sync(client, repo, "schedule")
            results["sharepoint"] = {"ok": True,
                                     "vm_pages_ok": (summary.get("vm_pages") or {}).get("ok"),
                                     "demo_video_ok": (summary.get("demo_video") or {}).get("ok")}
        except Exception as exc:                          # noqa: BLE001
            log.exception("auto sync: sharepoint failed")
            results["sharepoint"] = {"ok": False, "error": str(exc)[:300]}
    try:
        summary = consensus.run_sync(consensus.get_client(), repo, "schedule")
        results["consensus"] = {"ok": True, "api": summary.get("api")}
    except consensus.ConsensusNotConfigured:
        results["consensus"] = {"ok": None, "skipped": "not configured"}
    except Exception as exc:                              # noqa: BLE001
        log.exception("auto sync: consensus failed")
        results["consensus"] = {"ok": False, "error": str(exc)[:300]}
    return results


def tick(repo=None, data_dir: str | None = None, now: datetime | None = None,
         run=_run_sources) -> dict | None:
    """Run the daily sync if it is due and no other process is running it.

    Returns the run's record, or None when nothing was due (or another
    process had it). Safe to call as often as you like.
    """
    if not is_due(load_state(data_dir), now):
        return None
    if not _claim(data_dir):
        return None
    try:
        # Another process may have finished a run between the first look
        # and taking the lock.
        state = load_state(data_dir)
        if not is_due(state, now):
            return None
        started = now or _now()
        state["last_run"] = {"started_at": started.isoformat(timespec="seconds")}
        save_state(state, data_dir)
        if repo is None:
            from backend.deps import build_repo
            repo = build_repo()
        results = run(repo)
        record = {
            "started_at": started.isoformat(timespec="seconds"),
            "finished_at": _now().isoformat(timespec="seconds"),
            "ok": all(r.get("ok") is not False for r in results.values()),
            "results": results,
        }
        state = load_state(data_dir)          # keep a switch flipped meanwhile
        state["last_run"] = record
        save_state(state, data_dir)
        log.info("auto sync ran: %s", record)
        return record
    finally:
        _release(data_dir)


async def scheduler() -> None:
    """The loop the app starts. Never raises: a bad tick is logged and the
    next one tries again."""
    await asyncio.sleep(FIRST_TICK_SECONDS)
    while True:
        try:
            await asyncio.to_thread(tick)
        except Exception:                                  # noqa: BLE001
            log.exception("auto sync tick failed")
        await asyncio.sleep(TICK_SECONDS)
