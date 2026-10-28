"""Who holds a Consensus licence: the people shown "Create DemoBoard".

Elio, Seb, 2026-10-28: until the Hub can ask Consensus, the list is
Consensus's own ManageUsersReport, exported by Elio and uploaded on Admin ->
Users & groups. Each upload replaces the whole list; a new one comes when
licences change. Everyone on it counts, whatever their Consensus role
(Liwei, 2026-10-28) -- the role is kept, so that could change later.

Hub-owned data (owned/consensus_licenses.json). A stopgap, Seb: a list kept
by hand is not the long-term answer.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import threading
from datetime import datetime, timezone

from backend.config import settings

FILE = "consensus_licenses.json"
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+$")
_lock = threading.Lock()
_cache: dict = {"key": None, "emails": frozenset()}


class LicenceFileInvalid(ValueError):
    """The upload is not a Consensus user report; the message says why."""


def _path() -> str:
    return os.path.join(settings.data_dir, "owned", FILE)


def parse(content: bytes) -> tuple[list[dict], int]:
    """(the people, how many rows had no usable email). Columns as Consensus
    names them: First Name, Last Name, Email, Role, Group, ..."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise LicenceFileInvalid("The file is not a UTF-8 CSV. Export it from Consensus "
                                 "(Manage users, Report) and upload that file as it is.")
    reader = csv.DictReader(io.StringIO(text))
    columns = {(c or "").strip().lower(): c for c in reader.fieldnames or []}
    if "email" not in columns:
        raise LicenceFileInvalid("No Email column. Upload Consensus's Manage users report "
                                 "as it is exported.")

    def get(row, name):
        key = columns.get(name)
        return (row.get(key) or "").strip() if key else ""
    people: dict[str, dict] = {}
    skipped = 0
    for row in reader:
        email = get(row, "email").lower()
        if not _EMAIL.match(email):
            skipped += 1
            continue
        people[email] = {"email": email,
                         "name": " ".join(p for p in (get(row, "first name"),
                                                      get(row, "last name")) if p),
                         "role": get(row, "role"), "group": get(row, "group")}
    if not people:
        raise LicenceFileInvalid("The file lists nobody with an email address.")
    return sorted(people.values(), key=lambda p: p["email"]), skipped


def load() -> dict | None:
    try:
        with open(_path(), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def replace(content: bytes, file_name: str | None, actor: str) -> dict:
    """The upload becomes the whole list. Returns the summary."""
    people, skipped = parse(content)
    state = {"file_name": file_name, "uploaded_by": actor,
             "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "skipped": skipped, "people": people}
    os.makedirs(os.path.dirname(_path()), exist_ok=True)
    with _lock:
        tmp = _path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=1)
        os.replace(tmp, _path())
    return summary(state)


def summary(state: dict | None) -> dict:
    if not state:
        return {"count": 0, "people": []}
    people = state.get("people") or []
    from backend.access import _is_internal_address
    return {"count": len(people),
            "partners": sum(1 for p in people if not _is_internal_address(p["email"])),
            "skipped": state.get("skipped", 0), "file_name": state.get("file_name"),
            "uploaded_by": state.get("uploaded_by"), "at": state.get("at"),
            "people": people}


def is_licensed(email: str | None) -> bool:
    """Whether this person is on the latest list. Read again only when the
    file changes."""
    if not email:
        return False
    try:
        stat = os.stat(_path())
        key = (_path(), stat.st_mtime_ns, stat.st_size)
    except FileNotFoundError:
        return False
    if _cache["key"] != key:
        state = load() or {}
        _cache["emails"] = frozenset(p["email"] for p in state.get("people") or [])
        _cache["key"] = key
    return email.strip().lower() in _cache["emails"]
