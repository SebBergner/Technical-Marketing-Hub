"""Content health -> Searches, worked out ahead of time (Liwei, 2026-11-12).

Not on the first page load of a day, which made somebody wait (24 s on
production): every day at REFRESH_HOUR in Boston, for every period the
page offers, kept in `owned/search_insights.json` so every worker serves
the same answer at once.

* **The schedule** runs in the app, like the daily sync (backend/
  auto_sync.py): a loop wakes every ten minutes and works the figures out
  if the last time is older than the latest 04:00 in Boston -- so a run
  missed while the app slept or swapped happens on the next wake, and a new
  deployment works them out without anyone opening the page.
* **Refresh** on the page works them out again now, in the background. One
  person's refresh hides the button from everyone for COOLDOWN_SECONDS, so
  several people cannot keep the server busy; it is in the Admin log.
* **Two versions** of each period: for people who may see GXC videos and
  for people who may not, since "finds today" counts the demos the reader
  can find.
* **One process at a time**: a lock file on the shared data directory, as
  the daily sync has; one older than STALE_LOCK_SECONDS is taken over.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone

from backend.config import settings

log = logging.getLogger(__name__)

STATE_FILE = "search_insights.json"
LOCK_FILE = "search_insights.lock"
#: 04:00 in Boston (Liwei, 2026-11-12), before the US team's day and after
#: Europe's and Asia's searches of the day before.
REFRESH_HOUR = 4
TIME_ZONE = "America/New_York"
COOLDOWN_SECONDS = 3600
#: The page's periods, in days; None is all time.
PERIODS = (7, 30, 90, None)
TICK_SECONDS = 600
FIRST_TICK_SECONDS = 90
STALE_LOCK_SECONDS = 1800


def _zone():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(TIME_ZONE)
    except Exception:                                      # noqa: BLE001
        return timezone(timedelta(hours=-5))               # Eastern standard time


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _path(name: str, data_dir: str | None = None) -> str:
    return os.path.join(data_dir or settings.data_dir, "owned", name)


def period_key(days: int | None, gxc: bool) -> str:
    return f"{days or 'all'}|{'gxc' if gxc else 'no-gxc'}"


# ─────────────────────────────────────────────────────────────── state
def load(data_dir: str | None = None) -> dict:
    try:
        with open(_path(STATE_FILE, data_dir), encoding="utf-8") as fh:
            state = json.load(fh)
        return state if isinstance(state, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}


def _save(state: dict, data_dir: str | None = None) -> None:
    from backend.repositories.json_repo import _atomic_write
    os.makedirs(os.path.dirname(_path(STATE_FILE, data_dir)), exist_ok=True)
    _atomic_write(_path(STATE_FILE, data_dir), state)


def _update(data_dir: str | None = None, **fields) -> dict:
    state = load(data_dir)
    state.update(fields)
    _save(state, data_dir)
    return state


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        d = datetime.fromisoformat(value)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def last_slot(now: datetime | None = None) -> datetime:
    """The latest REFRESH_HOUR in Boston at or before `now`, in UTC."""
    local = (now or _now()).astimezone(_zone())
    slot = local.replace(hour=REFRESH_HOUR, minute=0, second=0, microsecond=0)
    if local < slot:
        slot = (slot - timedelta(days=1)).replace(hour=REFRESH_HOUR)
    return slot.astimezone(timezone.utc)


def next_slot(now: datetime | None = None) -> datetime:
    local = last_slot(now).astimezone(_zone())
    return (local + timedelta(days=1)).replace(hour=REFRESH_HOUR).astimezone(timezone.utc)


def is_due(state: dict, now: datetime | None = None) -> bool:
    done = _parse(state.get("computed_at"))
    return done is None or done < last_slot(now)


def refresh_view(state: dict, now: datetime | None = None) -> dict:
    """What the page needs to show the Refresh button, or why it is not."""
    now = now or _now()
    asked = _parse(state.get("refresh_at"))
    available_at = asked + timedelta(seconds=COOLDOWN_SECONDS) if asked else None
    running = bool(state.get("running_since"))
    return {"running": running, "running_since": state.get("running_since"),
            "last_at": state.get("refresh_at"),
            "available": not running and (available_at is None or now >= available_at),
            "available_at": available_at.isoformat(timespec="seconds")
            if available_at and now < available_at else None,
            "next_scheduled_at": next_slot(now).isoformat(timespec="seconds")}


# ────────────────────────────────────────────────────────── one at a time
def _claim(data_dir: str | None = None) -> bool:
    path = _path(LOCK_FILE, data_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                age = time.time() - os.path.getmtime(path)
            except OSError:
                continue
            if age < STALE_LOCK_SECONDS:
                return False
            try:
                os.remove(path)
            except OSError:
                return False
            continue
        with os.fdopen(fd, "w") as fh:
            fh.write(f"{os.getpid()} {_now().isoformat(timespec='seconds')}")
        return True
    return False


def _release(data_dir: str | None = None) -> None:
    try:
        os.remove(_path(LOCK_FILE, data_dir))
    except OSError:
        pass


# ──────────────────────────────────────────────────────────────── work
def compute_all(data_dir: str | None = None, now: datetime | None = None) -> dict:
    """Every period, both versions, into the state file. The caller holds
    the lock."""
    from backend.deps import build_repo
    from backend.services import search_insights as si
    from backend.services.usage import events as _events

    now = now or _now()
    started = time.monotonic()
    results: dict[str, dict] = {}
    for gxc in (True, False):
        repo = build_repo(gxc=gxc)
        records = repo.listed_records().values() if hasattr(repo, "listed_records") else []
        vocab = si.vocabulary(records)
        events = _events(repo)
        for days in PERIODS:
            results[period_key(days, gxc)] = si.insights(
                events, now - timedelta(days=days) if days else None, now,
                finds_now=lambda q, key, repo=repo: si.finds_now(repo, q, key),
                vocab=vocab, filters_words=si.filters_words)
    stamp = now.isoformat(timespec="seconds")
    state = load(data_dir)
    state.update(computed_at=stamp, seconds=round(time.monotonic() - started, 1),
                 results=results, running_since=None)
    _save(state, data_dir)
    log.info("search insights worked out in %.1f s", state["seconds"])
    return state


def run(data_dir: str | None = None, reason: str = "schedule") -> bool:
    """Work everything out now if no other process is. False when another
    one already is."""
    if not _claim(data_dir):
        return False
    try:
        _update(data_dir, running_since=_now().isoformat(timespec="seconds"),
                running_reason=reason)
        compute_all(data_dir)
        return True
    except Exception:                                      # noqa: BLE001
        log.exception("search insights failed")
        # A refresh that failed does not hold the button back for an hour.
        fields = {"running_since": None, "last_error_at": _now().isoformat(timespec="seconds")}
        if reason == "refresh":
            fields["refresh_at"] = None
        _update(data_dir, **fields)
        return True
    finally:
        _release(data_dir)


class Cooldown(Exception):
    """Refresh is not available yet; the message says until when."""


def request_refresh(actor: str, data_dir: str | None = None) -> dict:
    """Start working everything out again, in the background, unless it is
    running or somebody refreshed within the hour."""
    state = load(data_dir)
    view = refresh_view(state)
    if view["running"]:
        raise Cooldown("already being worked out")
    if not view["available"]:
        raise Cooldown(f"available again at {view['available_at']}")
    state = _update(data_dir, refresh_at=_now().isoformat(timespec="seconds"),
                    refresh_by=actor)
    threading.Thread(target=run, args=(data_dir, "refresh"), daemon=True,
                     name="search-insights-refresh").start()
    return refresh_view(state)


def tick(data_dir: str | None = None, now: datetime | None = None) -> bool:
    """Work everything out if the 04:00 run is due. True if it ran here."""
    if not is_due(load(data_dir), now):
        return False
    return run(data_dir, "schedule")


async def scheduler() -> None:
    """The loop the app starts. Never raises."""
    await asyncio.sleep(FIRST_TICK_SECONDS)
    while True:
        try:
            await asyncio.to_thread(tick)
        except Exception:                                  # noqa: BLE001
            log.exception("search insights tick failed")
        await asyncio.sleep(TICK_SECONDS)
