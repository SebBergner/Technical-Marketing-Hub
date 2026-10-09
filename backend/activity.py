"""Who signed in when, and who has been active lately (2026-10-07).

The Admin page's Sign-ins tab. Two records, both in `owned/` beside the
groups (backend/access.py):

* `signin_events.jsonl` -- one line per SSO sign-in, appended at the
  callback: when, who, PTC or guest. Never rewritten, except once by
  `scrub_partners()` below.
* `activity.json` -- each signed-in PTC person's last request, so the page
  can say who has been active in the last few minutes.

"Active", not "online": sign-in is a signed cookie and the server keeps no
session, so closing a tab tells nobody. Somebody who made a request in the
last ACTIVE_MINUTES is the honest version of "online now".

The last-request time is written at most once per WRITE_EVERY_SECONDS per
person and process, so browsing does not become a file write per click.
gunicorn runs several processes, each throttling on its own; two may write
the file close together and one update be lost, which costs at most one
interval of precision -- acceptable for a "who's around" figure.

**Partners are anonymous** (meeting 2026-10-07). PTC employees agree to
activity tracking in their employment agreement; partners must for now be
fully anonymized -- Elio is confirming with legal compliance whether more is
allowed. So a partner's sign-in is logged as "an external user signed in at
T", with no oid, address or name, and partners have no per-person "last
active" at all: only the time of the latest request by any external user, so
the page can say external users are around without saying who.
`scrub_partners()` removes identity written before this rule; the app runs
it at startup and it does nothing once the files are clean.

What is deliberately NOT recorded here: what anyone viewed or downloaded.
The usage events (`usage_events.jsonl`) stay anonymous until per-user
tracking for PTC people is added (agreed 2026-10-07). The place to add it is
`_record()` in routers/assets.py -- the same `user` key as here (the
lower-cased email), so the two can be joined on this tab; partners stay
anonymous there too.
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
#: activity.json key for the latest request by any external user. Not an oid,
#: so it can never collide with a person.
EXTERNAL_KEY = "_external"
EXTERNAL_WRITE_EVERY_SECONDS = 60

_lock = threading.RLock()
#: oid (or EXTERNAL_KEY) -> monotonic time this process last wrote it.
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


def is_partner(email: str | None, external: bool) -> bool:
    """The test CurrentUser.is_partner uses: a guest token, or an address
    outside PTC's domains."""
    from backend.auth import CurrentUser
    return CurrentUser(email=email, external=bool(external)).is_partner


# ───────────────────────────────────────────────────────────────── recording
def record_sign_in(*, oid: str, email: str | None, name: str | None,
                   external: bool, now: datetime | None = None) -> None:
    """Append one sign-in. Best effort: never stops a sign-in. A partner's is
    anonymous: when, and that it was an external user -- nothing else."""
    try:
        path = access._owned(EVENTS_FILE)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        partner = is_partner(email, external)
        entry = {"at": _iso(now or _now()), "event": "sign_in", "external": partner}
        if not partner:
            entry.update(oid=oid, user=(email or "").strip().lower() or None, name=name)
        with _lock, open(path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        if partner:
            _touch_external(now=now, force=True)
        else:
            _touch(oid, entry["user"], name, now=now, force=True)
    except Exception:                                      # noqa: BLE001
        log.exception("could not log a sign-in")


def note_request(user) -> None:
    """Called for every request with a session; writes only now and then."""
    if not user.is_authenticated or not user.object_id:
        return
    try:
        if user.is_partner:
            _touch_external()
        else:
            _touch(user.object_id, user.email, user.name)
    except Exception:                                      # noqa: BLE001
        log.exception("could not note activity")


def _touch(oid: str, email: str | None, name: str | None,
           now: datetime | None = None, force: bool = False) -> None:
    """A PTC person's latest request."""
    clock = time.monotonic()
    if not force and clock - _written.get(oid, -1e9) < WRITE_EVERY_SECONDS:
        return
    from backend.repositories.json_repo import _atomic_write
    with _lock:
        _written[oid] = clock
        state = _activity()
        state[oid] = {"user": (email or "").strip().lower() or None, "name": name,
                      "external": False, "last_active": _iso(now or _now())}
        _atomic_write(access._owned(ACTIVITY_FILE), state)


def _touch_external(now: datetime | None = None, force: bool = False) -> None:
    """The latest request by any external user: one time, nobody's."""
    clock = time.monotonic()
    if not force and clock - _written.get(EXTERNAL_KEY, -1e9) < EXTERNAL_WRITE_EVERY_SECONDS:
        return
    from backend.repositories.json_repo import _atomic_write
    with _lock:
        _written[EXTERNAL_KEY] = clock
        state = _activity()
        state[EXTERNAL_KEY] = {"last_active": _iso(now or _now())}
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


# ───────────────────────────────────────────────────── the one-off clean-up
def _identifies_a_partner(entry: dict) -> bool:
    """A record that names a partner: anything of a partner's beyond the
    bare fact that an external user did something."""
    named = any(entry.get(k) for k in ("oid", "user", "name", "email", "username"))
    return named and is_partner(entry.get("user") or entry.get("email")
                                or entry.get("username"), bool(entry.get("external")))


def scrub_partners() -> dict:
    """Strip partner identity written before partners were anonymous
    (2026-10-09). Sign-ins are kept as anonymous "external user" lines, so
    the counts stay right; partners' "last active" rows are folded into the
    one external time; partners leave the signed-in list (users.json).
    Idempotent and cheap once clean, so it runs at every start."""
    from backend.repositories.json_repo import _atomic_write
    done = {"sign_ins": 0, "activity": 0, "users": 0}
    with _lock:
        events = _events()
        if any(_identifies_a_partner(e) for e in events):
            clean = []
            for e in events:
                if _identifies_a_partner(e):
                    e = {"at": e.get("at"), "event": e.get("event", "sign_in"), "external": True}
                    done["sign_ins"] += 1
                clean.append(e)
            path = access._owned(EVENTS_FILE)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
                fh.writelines(json.dumps(e, ensure_ascii=False) + "\n" for e in clean)
            os.replace(tmp, path)

        state = _activity()
        partners = [k for k, v in state.items()
                    if k != EXTERNAL_KEY and isinstance(v, dict) and _identifies_a_partner(
                        {**v, "oid": k})]
        if partners:
            latest = max([state[k].get("last_active") or "" for k in partners]
                         + [(state.get(EXTERNAL_KEY) or {}).get("last_active") or ""])
            for k in partners:
                state.pop(k)
            if latest:
                state[EXTERNAL_KEY] = {"last_active": latest}
            _atomic_write(access._owned(ACTIVITY_FILE), state)
            done["activity"] = len(partners)

    done["users"] = access.forget_partners()
    if any(done.values()):
        log.info("partner identity removed from the activity records: %s", done)
    return done


# ───────────────────────────────────────────────────────────────── reading
def report(*, since: str | None = None, until: str | None = None,
           today: str | None = None, q: str | None = None, user: str | None = None,
           offset: int = 0, limit: int = 50, now: datetime | None = None) -> dict:
    """Everything the Sign-ins tab shows.

    `since`/`until` bound the window and `today` is the start of the reader's
    day, all as ISO times from the browser -- "today" depends on where the
    reader sits, which the server does not know (the same reason the usage
    endpoints take bounds rather than named periods).

    People are PTC people only; external users appear as anonymous sign-ins
    and as one "active" time.
    """
    now = now or _now()
    lo, hi, day = _parse(since), _parse(until), _parse(today)
    known = {u.get("oid"): u for u in access.users_view()}
    activity = _activity()

    cutoff = now - timedelta(minutes=ACTIVE_MINUTES)
    active = []
    for oid, a in activity.items():
        if oid == EXTERNAL_KEY or not isinstance(a, dict) or a.get("external"):
            continue
        when = _parse(a.get("last_active"))
        if when and when >= cutoff:
            k = known.get(oid) or {}
            active.append({"oid": oid, "user": a.get("user"),
                           "name": a.get("name") or k.get("name"),
                           "last_active": a["last_active"], "groups": k.get("groups", [])})
    active.sort(key=lambda a: a["last_active"], reverse=True)
    external_last = (activity.get(EXTERNAL_KEY) or {}).get("last_active")
    external_when = _parse(external_last)

    def in_range(e: dict) -> bool:
        at = _parse(e.get("at")) or now
        return (lo is None or at >= lo) and (hi is None or at < hi)

    events = _events()
    in_window = [e for e in events if in_range(e)]
    today_events = [e for e in events
                    if day is not None and (_parse(e.get("at")) or now) >= day]

    people: dict[str, dict] = {}
    for e in in_window:
        if e.get("external") or not e.get("oid"):
            continue
        p = people.setdefault(e["oid"], {"oid": e["oid"], "user": e.get("user"),
                                         "name": e.get("name"),
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
                    if needle in (e.get("user") or "") or needle in (e.get("name") or "").lower()
                    or (e.get("external") and needle in "external user")]
    log_rows = sorted(log_rows, key=lambda e: e.get("at") or "", reverse=True)

    return {
        "active_minutes": ACTIVE_MINUTES,
        "active": active,
        "external_active": bool(external_when and external_when >= cutoff),
        "external_last_active": external_last,
        "counts": {
            "active": len(active),
            "today_people": len({e.get("oid") for e in today_events
                                 if not e.get("external") and e.get("oid")}),
            "today_external_sign_ins": sum(1 for e in today_events if e.get("external")),
            "window_people": len(people),
            "window_sign_ins": len(in_window),
            "window_external_sign_ins": sum(1 for e in in_window if e.get("external")),
        },
        "people": people_list,
        "log": {"total": len(log_rows), "offset": offset, "limit": limit,
                "items": log_rows[offset:offset + limit]},
        "recorded_since": events[0]["at"] if events else None,
    }
