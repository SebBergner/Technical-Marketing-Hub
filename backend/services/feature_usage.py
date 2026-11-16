"""Feature usage: how many people opened which Hub feature (A16; Liwei, 2026-11-16).

The Hub is a single-page app: opening My Hub, the User guide or Get help only
changes the address bar's `#`, so the server never sees it. The page tells the
server once per feature per day (`POST /api/assets/feature-event`), the server
writes a usage event `{"event": "feature", "feature": "<id>"}` to the same log
as views and downloads, and Admin -> Hub usage reads them back here.

* **A fixed list.** Only the names in FEATURES are recorded; anything else the
  page sends is dropped. Counting a new feature = adding one line here (and
  one call where the page opens it).
* **Same person, same feature, same day = once.** The page keeps its own
  once-a-day note, the server keeps one too, and the report counts distinct
  (person, feature, day) so a repeated line cannot inflate a number.
* **Who** is written as for every usage event: a PTC person by address, a
  partner only as "external". A partner is therefore not a countable
  person: for partners the report gives visits (one per browser per day), and
  says so.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import date, datetime, timedelta, timezone

#: id, label -- Liwei, 2026-11-16. Order is the order of the Admin table.
FEATURES: tuple[tuple[str, str], ...] = (
    ("my_hub", "My Hub"),
    ("favorites", "Favorites"),
    ("playlists", "Playlists"),
    ("advanced_search", "Advanced Search"),
    ("table_view", "Table view"),
    ("user_guide", "User guide"),
    ("get_help", "Get help"),
    ("new_asset_inquiry", "New Asset Inquiry"),
    ("share_internally", "Share Internally"),
    ("create_demoboard", "Create DemoBoard"),
    ("report_asset", "Report asset"),
)
FEATURE_IDS = frozenset(f for f, _ in FEATURES)

#: The most weeks the trend column draws, newest last.
MAX_WEEKS = 12

_lock = threading.Lock()
_seen: set[tuple[str, str, str]] = set()
_seen_day = ""


def first_today(feature: str, who: dict, day: str) -> bool:
    """False when this person already told us about this feature today (in this
    server process; the report de-duplicates again, so several workers cannot
    inflate anything). A partner has no name to remember, so always True."""
    global _seen_day
    person = who.get("user")
    if not person:
        return True
    with _lock:
        if day != _seen_day:
            _seen.clear()
            _seen_day = day
        key = (day, person, feature)
        if key in _seen:
            return False
        _seen.add(key)
        return True


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _day(at: str | None) -> date | None:
    try:
        return date.fromisoformat((at or "")[:10])
    except ValueError:
        return None


def summarise(events: list[dict], since: str | None, until: str | None,
              today: date | None = None) -> dict:
    """One row per feature: PTC people, partner visits, days in use, and the
    people per week (the last MAX_WEEKS weeks of the window)."""
    today = today or datetime.now(timezone.utc).date()
    uses = [e for e in events if e.get("event") == "feature" and e.get("feature") in FEATURE_IDS]

    start = _day(since)
    if start is None:
        days = [d for d in (_day(e.get("at")) for e in uses) if d]
        start = min(days) if days else today
    end = _day(until) or today
    week_list: list[date] = []
    w = _monday(end)
    while w >= _monday(start) and len(week_list) < MAX_WEEKS:
        week_list.append(w)
        w -= timedelta(days=7)
    week_list.reverse()

    rows = []
    for fid, label in FEATURES:
        mine = [e for e in uses if e["feature"] == fid]
        people = {(e.get("user") or "").strip().lower() for e in mine if e.get("user")}
        # A partner is one line per browser per day, so lines are visits.
        partner_visits = sum(1 for e in mine if e.get("external") and not e.get("user"))
        used_days = {d for d in (_day(e.get("at")) for e in mine) if d}
        weekly = []
        for wk in week_list:
            span = {wk + timedelta(days=n) for n in range(7)}
            weekly.append(len({(e.get("user") or "").strip().lower() for e in mine
                               if e.get("user") and _day(e.get("at")) in span}))
        rows.append({"id": fid, "label": label, "people": len(people),
                     "partner_visits": partner_visits, "days": len(used_days),
                     "weekly": weekly})
    return {"rows": rows, "weeks": [w.isoformat() for w in week_list]}


def starred_and_listed(data_dir: str, since: str | None, until: str | None) -> dict:
    """People who starred a demo, and who made a playlist, in the window --
    read from the files themselves, so it includes 11/13, before the page
    reported anything. Stars that were later removed are not in the file, so
    this is "people who hold a star", not "people who ever starred". A
    partner's file looks like anyone's, so these include partners."""
    def inside(at: str | None) -> bool:
        at = at or ""
        return bool(at) and (not since or at >= since) and (not until or at <= until)

    starred = 0
    folder = os.path.join(data_dir, "owned", "me")
    if os.path.isdir(folder):
        for name in os.listdir(folder):
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(folder, name), encoding="utf-8") as fh:
                    state = json.load(fh)
            except (OSError, ValueError):
                continue
            if any(inside(f.get("at")) for f in (state.get("favorites") or [])
                   if isinstance(f, dict)):
                starred += 1

    owners: set[str] = set()
    folder = os.path.join(data_dir, "owned", "playlists")
    if os.path.isdir(folder):
        for name in os.listdir(folder):
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(folder, name), encoding="utf-8") as fh:
                    record = json.load(fh)
            except (OSError, ValueError):
                continue
            if isinstance(record, dict) and record.get("owner") and inside(record.get("created_at")):
                owners.add(record["owner"])
    return {"starred_people": starred, "playlist_people": len(owners)}
