"""Who signed in when, and who has been active lately (2026-10-07).

The Admin page's Sign-ins tab. Two records, both in `owned/` beside the
groups (backend/access.py):

* `signin_events.jsonl` -- one line per SSO sign-in, appended at the
  callback: when, who, PTC or guest. Never rewritten.
* `activity.json` -- each signed-in person's last request, so the page can
  say who has been active in the last few minutes.

"Active", not "online": sign-in is a signed cookie and the server keeps no
session, so closing a tab tells nobody. Somebody who made a request in the
last ACTIVE_MINUTES is the honest version of "online now".

The last-request time is written at most once per WRITE_EVERY_SECONDS per
person and process, so browsing does not become a file write per click.
gunicorn runs several processes, each throttling on its own; two may write
the file close together and one update be lost, which costs at most one
interval of precision -- acceptable for a "who's around" figure.

What is deliberately NOT recorded here: what anyone viewed or downloaded.
The usage events (`usage_events.jsonl`) stay anonymous until management
decides on per-user tracking (asked 2026-10-05, Liwei 2026-10-07: possible
later). If it is approved, the place to add it is `_record()` in
routers/assets.py -- the same `user` key as here (the lower-cased email), so
the two can be joined on this tab.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone

from backend import access

log = logging.getLogger(__name__)

EVENTS_FILE = "signin_events.jsonl"
ACTIVITY_FILE = "activity.json"
ACTIVE_MINUTES = 15
WRITE_EVERY_SECONDS = 300

_lock = threading.RLock()
#: oid -> monotonic time this process last wrote that person's activity.
_written: dict[str, float] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(when: datetime) -> str:
    return when.isoformat(timespec="seconds")


def _parse(value: str | None) -> datetime | None:
    try:
        when = datetime.fromisoformat(value) if value else None
    except ValueError:
        return None
    if when is not None and when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when


# ───────────────────────────────────────────────────────────────── recording
def record_sign_in(*, oid: str, email: str | None, name: str | None,
                   external: bool, now: datetime | None = None) -> None:
    """Append one sign-in. Best effort: never stops a sign-in."""
    try:
        path = access._owned(EVENTS_FILE)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        entry = {"at": _iso(now or _now()), "event": "sign_in", "oid": oid,
                 "user": (email or "").strip().lower() or None, "name": name,
                 "external": bool(external)}
        with _lock, open(path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        _touch(oid, entry["user"], name, external, now=now, force=True)
    except Exception:                                      # noqa: BLE001
        log.exception("could not log the sign-in of %s", oid)


def note_request(user) -> None:
    """Called for every request with a session; writes only now and then."""
    if not user.is_authenticated or not user.object_id:
        return
    try:
        _touch(user.object_id, user.email, user.name, user.is_partner)
    except Exception:                                      # noqa: BLE001
        log.exception("could not note activity")


def _touch(oid: str, email: str | None, name: str | None, external: bool,
           now: datetime | None = None, force: bool = False) -> None:
    clock = time.monotonic()
    if not force and clock - _written.get(oid, -1e9) < WRITE_EVERY_SECONDS:
        return
    from backend.repositories.json_repo import _atomic_write
    with _lock:
        _written[oid] = clock
        state = _activity()
        state[oid] = {"user": (email or "").strip().lower() or None, "name": name,
                      "external": bool(external), "last_active": _iso(now or _now())}
        _atomic_write(access._owned(ACTIVITY_FILE), state)


def _activity() -> dict:
    try:
        with open(access._owned(ACTIVITY_FILE), encoding="utf-8") as fh:
            state = json.load(fh)
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def _events() -> list[dict]:
    try:
        with open(access._owned(EVENTS_FILE), encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


# ───────────────────────────────────────────────────────────────── reading
def report(*, since: str | None = None, until: str | None = None,
           today: str | None = None, q: str | None = None, user: str | None = None,
           offset: int = 0, limit: int = 50, now: datetime | None = None) -> dict:
    """Everything the Sign-ins tab shows.

    `since`/`until` bound the window and `today` is the start of the reader's
    day, all as ISO times from the browser -- "today" depends on where the
    reader sits, which the server does not know (the same reason the usage
    endpoints take bounds rather than named periods).
    """
    now = now or _now()
    lo, hi, day = _parse(since), _parse(until), _parse(today)
    known = {u.get("oid"): u for u in access.users_view()}
    activity = _activity()

    cutoff = now - timedelta(minutes=ACTIVE_MINUTES)
    active = []
    for oid, a in activity.items():
        when = _parse(a.get("last_active"))
        if when and when >= cutoff:
            k = known.get(oid) or {}
            active.append({"oid": oid, "user": a.get("user"),
                           "name": a.get("name") or k.get("name"),
                           "external": a.get("external"), "last_active": a["last_active"],
                           "groups": k.get("groups", [])})
    active.sort(key=lambda a: a["last_active"], reverse=True)

    events = _events()
    in_window = [e for e in events
                 if (lo is None or (_parse(e.get("at")) or now) >= lo)
                 and (hi is None or (_parse(e.get("at")) or now) < hi)]
    today_users = {e.get("oid") for e in events
                   if day is not None and (_parse(e.get("at")) or now) >= day}

    people: dict[str, dict] = {}
    for e in in_window:
        p = people.setdefault(e.get("oid"), {"oid": e.get("oid"), "user": e.get("user"),
                                             "name": e.get("name"),
                                             "external": e.get("external"),
                                             "sign_ins": 0, "last_sign_in": None})
        p["sign_ins"] += 1
        if (p["last_sign_in"] or "") < (e.get("at") or ""):
            p["last_sign_in"] = e.get("at")
            p["name"] = e.get("name") or p["name"]
    for oid, p in people.items():
        p["last_active"] = (activity.get(oid) or {}).get("last_active")
        p["groups"] = (known.get(oid) or {}).get("groups", [])
    people_list = sorted(people.values(), key=lambda p: p["last_sign_in"] or "",
                         reverse=True)

    log_rows = in_window
    if user:
        log_rows = [e for e in log_rows if e.get("oid") == user]
    if q:
        needle = q.strip().lower()
        log_rows = [e for e in log_rows
                    if needle in (e.get("user") or "") or needle in (e.get("name") or "").lower()]
    log_rows = sorted(log_rows, key=lambda e: e.get("at") or "", reverse=True)

    return {
        "active_minutes": ACTIVE_MINUTES,
        "active": active,
        "counts": {
            "active": len(active),
            "today_people": len(today_users),
            "window_people": len(people),
            "window_sign_ins": len(in_window),
            "guests": sum(1 for p in people.values() if p.get("external")),
        },
        "people": people_list,
        "log": {"total": len(log_rows), "offset": offset, "limit": limit,
                "items": log_rows[offset:offset + limit]},
        "recorded_since": events[0]["at"] if events else None,
    }
