"""The welcome pop-up: once per person, and again after a big update.

Liwei, 2026-11-08: like the Customer Data Disclaimer, a short welcome the
first time someone signs in, pointing at the user guide (the "?" in the top
right corner, #/guide); shown once, and shown again only when a large patch
ships. It follows the disclaimer, never stands in front of it.

Recorded on the server against the sign-in, as the disclaimer is
(backend/disclaimer.py: same key, same file handling), so it is seen once
per person, not once per browser. One row per person in
owned/welcome_seen.json: the version last seen, and when.

A big update: change VERSION and put what changed in WHATS_NEW. Everyone
who saw an older version then sees the pop-up once more, headed "What's new"
with those points; someone new still gets the plain welcome.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from backend.config import settings
from backend.disclaimer import key_of

FILE = "welcome_seen.json"
#: Change it for a big update (and fill WHATS_NEW): everyone sees it again.
VERSION = "2026-11-08"
#: What the big update brought, a few short points; empty for the first welcome.
WHATS_NEW: tuple[str, ...] = ()


def _path(data_dir: str | None = None) -> str:
    return os.path.join(data_dir or settings.data_dir, "owned", FILE)


def load(data_dir: str | None = None) -> dict:
    try:
        with open(_path(data_dir), encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    return data if isinstance(data, dict) else {}


def status(user, data_dir: str | None = None) -> dict:
    """Whether to show it, and which: the first welcome or what is new."""
    key = key_of(user)
    row = load(data_dir).get(key) if key else None
    required = bool(key) and (row or {}).get("version") != VERSION
    return {"required": required, "version": VERSION,
            # Someone who saw an earlier one is told what changed; someone
            # new is welcomed (a list of changes means nothing to them yet).
            "kind": "whats_new" if row and WHATS_NEW else "welcome",
            "whats_new": list(WHATS_NEW)}


def seen(user, data_dir: str | None = None, now: datetime | None = None) -> dict:
    """Record that this person has seen the current version."""
    from backend.file_safety import locked, replace_with
    key = key_of(user)
    if not key:
        raise ValueError("Only a signed-in person sees the welcome.")
    path = _path(data_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    at = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    with locked(path):
        data = load(data_dir)
        before = data.get(key) or {}
        row = {"version": VERSION, "seen_at": at,
               "first_seen_at": before.get("first_seen_at") or at}
        data[key] = row
        replace_with(path, lambda fh: json.dump(data, fh, ensure_ascii=False, indent=1))
    return row
