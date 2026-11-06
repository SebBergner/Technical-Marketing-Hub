"""The Customer Data Disclaimer everyone accepts before using the Hub.

Elio, 2026-11-05: PTC's customer data disclaimer as a pop-up with one
"Accept" button, shown once, then again every twelve months; and (Liwei's
question, Elio: "I love that idea") a record of who accepted, on Admin ->
Users & groups.

Recorded on the server against the signed-in account, not in a cookie: it
then follows the person to every browser and device, and the list is the
proof. One row per person (owned/disclaimer_acceptances.json), the latest
acceptance with how many times they have accepted.

Asked again when the last acceptance is ASK_AGAIN_DAYS old, or when the text
changes (VERSION): an acceptance is of the words it was shown.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from backend.config import settings

FILE = "disclaimer_acceptances.json"
ASK_AGAIN_DAYS = 365
#: Change it whenever TEXT changes: everyone is then asked again.
VERSION = "2026-11-05"

TITLE = "Customer Data Disclaimer"
#: Word for word from the disclaimer Elio sent (2026-11-05).
INTRO = ("PTC is providing customer datasets subject to your agreement to the following "
         "terms and conditions. Click the “accept” button below to indicate your "
         "acceptance of these terms and conditions and to represent and warrant to PTC that "
         "you have authority to bind your organization to such terms and conditions.")
TERMS = (
    "The dataset and the information contained therein are the confidential information "
    "of our customers. By clicking “accept”, you agree to limit your use of the "
    "dataset solely for use as part of demonstrations of PTC products, and not for any "
    "other purpose, and you agree not to provide the dataset to any third parties.",
    "You further agree that all intellectual property rights in and to the dataset are the "
    "property of our customers, and you will not modify or make any derivative works of "
    "the dataset, or claim any rights in or to the dataset.",
    "You understand that neither PTC nor our customers are providing any warranties with "
    "respect to the dataset, and that it is provided on an “as is” basis, and you "
    "agree that, to the extent consistent with applicable law, neither PTC nor our "
    "customers nor any of their respective affiliates, directors, officers or employees "
    "will have any liability associated with your use of the dataset.",
    "You agree that, upon the request of either PTC or our customers, you will discontinue "
    "all further use of the dataset and return or destroy all copies of the dataset in "
    "your possession.",
)


def _path(data_dir: str | None = None) -> str:
    return os.path.join(data_dir or settings.data_dir, "owned", FILE)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def key_of(user) -> str | None:
    """Whom an acceptance belongs to: the sign-in's email, else its account.
    None for a program using an API token, which accepts nothing."""
    if getattr(user, "token_name", None):
        return None
    for value in (getattr(user, "email", None), getattr(user, "username", None),
                  getattr(user, "object_id", None)):
        if value:
            return str(value).strip().lower()
    if getattr(user, "is_dev_principal", False):
        return "local-developer"
    return None


def load(data_dir: str | None = None) -> dict:
    try:
        with open(_path(data_dir), encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    return data if isinstance(data, dict) else {}


def due(row: dict | None, now: datetime | None = None) -> bool:
    """Whether this person must accept (again)."""
    if not row or row.get("version") != VERSION:
        return True
    try:
        at = datetime.fromisoformat(row["accepted_at"])
    except (KeyError, TypeError, ValueError):
        return True
    return (now or _now()) - at >= timedelta(days=ASK_AGAIN_DAYS)


def text() -> dict:
    return {"title": TITLE, "intro": INTRO, "terms": list(TERMS), "version": VERSION,
            "ask_again_days": ASK_AGAIN_DAYS}


def status(user, data_dir: str | None = None) -> dict:
    """What the Hub needs on load: whether to show it, and the words."""
    key = key_of(user)
    row = load(data_dir).get(key) if key else None
    return {**text(), "required": bool(key) and due(row),
            "accepted_at": (row or {}).get("accepted_at")}


def accept(user, data_dir: str | None = None, now: datetime | None = None) -> dict:
    """Record that this person accepted the current text. Returns their row."""
    from backend.file_safety import locked, replace_with
    key = key_of(user)
    if not key:
        raise ValueError("Only a signed-in person can accept the disclaimer.")
    path = _path(data_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    at = (now or _now()).isoformat(timespec="seconds")
    with locked(path):
        data = load(data_dir)
        before = data.get(key) or {}
        row = {"key": key,
               "email": getattr(user, "email", None) or before.get("email"),
               "name": getattr(user, "name", None) or before.get("name"),
               "accepted_at": at, "version": VERSION,
               "first_accepted_at": before.get("first_accepted_at") or at,
               "times": int(before.get("times") or 0) + 1}
        data[key] = row
        replace_with(path, lambda fh: json.dump(data, fh, ensure_ascii=False, indent=1))
    return row


def listing(data_dir: str | None = None, now: datetime | None = None) -> list[dict]:
    """Everyone who has accepted, newest first, with when it is due again."""
    now = now or _now()
    rows = []
    for row in load(data_dir).values():
        try:
            again = (datetime.fromisoformat(row["accepted_at"])
                     + timedelta(days=ASK_AGAIN_DAYS)).isoformat(timespec="seconds")
        except (KeyError, TypeError, ValueError):
            again = None
        rows.append({**row, "due_again_at": again, "current": not due(row, now)})
    return sorted(rows, key=lambda r: r.get("accepted_at") or "", reverse=True)
