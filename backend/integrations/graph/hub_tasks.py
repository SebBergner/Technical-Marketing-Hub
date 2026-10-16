"""The Hub's to-dos, kept in a SharePoint list ("Hub Tasks", 2026-10-15).

Liwei, 2026-10-15: whatever waits for a person -- a new demo to review, a
request to make a demo Internal or Open -- gets a row in a list, so the team
can sort and filter it, set "Alert me", or hang a Power Automate flow on it
(new row -> Teams). The Hub has no e-mail of its own; this is how it tells
people.

The Hub's own records stay the store of record (owned/uploads.json,
owned/access_requests.json); the list is a copy, written after the fact and
never read back. So a Graph outage never stops a review or a request: what
the list should say is kept in owned/hub_tasks.json, sent in the background,
and anything that did not go through is sent again after the next sync.

Columns, checked against the real list on 2026-10-15 (one test row, #1):

    Title, RequestedBy, DecidedBy, HubLink, HubId (indexed)   single line
    Details                                                    multiple lines
    TaskType     choice: Upload review / Access request / Support request
    TaskStatus   choice: Open / Done / Rejected / Withdrawn / Cancelled
    DecidedAt    date only

Clearing a field (a resubmitted demo is Open again): Graph ignores null
without a word; a text column clears with "", a date column cannot be
cleared at all (400) -- so DecidedAt keeps the last decision's date until
the next one, and Details says the demo was resubmitted.

HubLink is plain text, shown as a link by the list's column formatting:
Graph refused a Hyperlink column in every shape (400), as it did for the
Demo Requests list on 2026-09-01. A row is found again by HubId
("upload:<id>", "access:<id>"), so a create whose answer was lost is never
made twice.

A row is only created for something that is waiting (Open). A demo published
on submission ("Create without review") never was a to-do, so it gets none.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from urllib.parse import quote

from backend.config import settings

log = logging.getLogger(__name__)

FILE = "hub_tasks.json"
DATE_FIELDS = ("DecidedAt",)      # cannot be cleared through Graph
_lock = threading.Lock()          # the state file: held only to read or write it
_send_lock = threading.Lock()     # one sender at a time; a request never waits on it

UPLOAD_STATUS = {"pending": "Open", "sent_back": "Rejected", "published": "Done",
                 "cancelled": "Cancelled"}
ACCESS_STATUS = {"pending": "Open", "approved": "Done", "rejected": "Rejected",
                 "withdrawn": "Withdrawn"}


def enabled() -> bool:
    return bool((settings.hub_tasks_list or "").strip())


def _path(repo) -> str:
    return os.path.join(repo.owned_dir, FILE)


def _load(repo) -> dict:
    try:
        with open(_path(repo), encoding="utf-8") as fh:
            value = json.load(fh)
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}


def _save(repo, state: dict) -> None:
    from backend.repositories.json_repo import _atomic_write
    _atomic_write(_path(repo), state)


def _who(actor: str | None) -> str | None:
    """An e-mail address for a person, "API token <name>" for a script."""
    if not actor:
        return None
    kind, _, rest = actor.partition(":")
    if kind == "token":
        return f"API token {rest}"
    return rest if kind in ("user", "dev") else actor


def _date(iso: str | None) -> str | None:
    return iso[:10] if iso else None


def _base() -> str:
    """The Hub's address, for HubLink (config.Settings.public_base_url)."""
    return settings.public_base_url


# ─────────────────────────────────────────────── what a row should say
def upload_fields(record: dict) -> dict | None:
    status = UPLOAD_STATUS.get(record.get("status"))
    if status is None:
        return None
    values = record.get("values") or {}
    what = "Video" if record.get("target") == "demo_video" else (record.get("kind") or "").upper()
    lines = [" · ".join(x for x in (what, ", ".join(values.get("products") or []),
                                    ", ".join(values.get("segment") or [])) if x)]
    if record.get("internal"):
        lines.append("Asks to be Internal.")
    if record.get("web_url"):
        lines.append(f"SharePoint: {record['web_url']}")
    if record.get("status") == "sent_back" and record.get("note"):
        lines.append(f"Sent back: {record['note']}")
    elif record.get("status") == "pending" and any(
            h.get("what") == "resubmitted" for h in record.get("history") or []):
        lines.append("Resubmitted after being sent back.")
    elif record.get("note") and status == "Done":
        lines.append(f"Note: {record['note']}")
    decided = status != "Open"
    return {"Title": f"Review: {record.get('title') or record.get('folder_name') or '(untitled)'}"[:255],
            "TaskType": "Upload review", "TaskStatus": status,
            "RequestedBy": _who(record.get("uploaded_by")),
            "HubLink": f"{_base()}/admin#review",
            "Details": "\n".join(lines),
            "DecidedBy": _who(record.get("reviewed_by") if record.get("status") != "cancelled"
                              else record.get("uploaded_by")) if decided else None,
            "DecidedAt": (_date(record.get("reviewed_at")) if record.get("status") != "cancelled"
                          else _date(record.get("updated_at"))) if decided else None}


def access_fields(request: dict) -> dict | None:
    status = ACCESS_STATUS.get(request.get("status"))
    if status is None:
        return None
    word = "Internal" if request.get("level") == "internal" else "Open"
    details = request.get("reason") or ""
    if request.get("note"):
        details += f"\nDecision note: {request['note']}"
    decided = status != "Open"
    return {"Title": f"Make {word}: {request.get('title') or request.get('asset_id')}"[:255],
            "TaskType": "Access request", "TaskStatus": status,
            "RequestedBy": _who(request.get("requested_by")),
            "HubLink": f"{_base()}/#/asset/{quote(request.get('asset_id') or '', safe='')}",
            "Details": details,
            "DecidedBy": _who(request.get("decided_by")) if decided else None,
            "DecidedAt": _date(request.get("decided_at")) if decided else None}


# ─────────────────────────────────────────────────────── recording
def note_upload(repo, record: dict) -> None:
    _note(repo, f"upload:{record['id']}", upload_fields(record))


def note_access(repo, request: dict) -> None:
    _note(repo, f"access:{request['id']}", access_fields(request))


def _note(repo, hub_id: str, fields: dict | None) -> None:
    """Remember what the row should say, and send it in the background.
    Never raises: the list is a copy, and the Hub's own step has happened."""
    if fields is None or not enabled():
        return
    try:
        with _lock:
            state = _load(repo)
            if hub_id not in state and fields.get("TaskStatus") != "Open":
                return              # never waited for anyone: never a to-do
            entry = state.setdefault(hub_id, {"item_id": None, "sent": {}})
            entry["want"] = {"HubId": hub_id, **fields}
            entry["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            _save(repo, state)
    except Exception:                                       # noqa: BLE001
        log.exception("Hub Tasks: could not record %s", hub_id)
        return
    flush_soon(repo)


def flush_soon(repo) -> None:
    if not enabled():
        return
    threading.Thread(target=flush, args=(repo,), name="hub-tasks", daemon=True).start()


def unsent(repo) -> int:
    return sum(1 for e in _load(repo).values() if _diff(e))


def _diff(entry: dict) -> dict:
    sent = entry.get("sent") or {}
    return {k: v for k, v in (entry.get("want") or {}).items() if sent.get(k) != v}


# ─────────────────────────────────────────────────────── sending
def flush(repo, client=None) -> dict:
    """Send every row whose list copy is behind. {sent, failed, skipped}."""
    out = {"sent": 0, "failed": 0, "skipped": 0}
    if not enabled():
        return out
    while True:
        if not _send_lock.acquire(blocking=False):
            return out              # a sender is at work; it reads the file again
        try:
            while _flush_once(repo, client, out):
                pass                # something changed while sending: once more
        except Exception:                                   # noqa: BLE001
            log.exception("Hub Tasks: sending stopped")
            return out
        finally:
            _send_lock.release()
        # A note that came in just as the sender finished found it busy.
        with _lock:
            if not any(_diff(e) and not e.get("error") for e in _load(repo).values()):
                return out


def _flush_once(repo, client, out: dict) -> bool:
    with _lock:
        pending = {h: json.loads(json.dumps(e)) for h, e in _load(repo).items() if _diff(e)}
    if not pending:
        return False
    if client is None:
        from backend.integrations.graph.client import get_graph_client
        client = get_graph_client()
        if client is None:
            return False
    base = _items_url(client)
    progressed = False
    for hub_id, entry in pending.items():
        try:
            out[_send(client, base, hub_id, entry)] += 1
            entry["error"] = None
            progressed = True
        except Exception as exc:                            # noqa: BLE001
            entry["error"] = str(exc)[:300]
            out["failed"] += 1
            log.warning("Hub Tasks: %s not sent: %s", hub_id, exc)
        with _lock:                 # keep what was sent; "want" may have moved on
            state = _load(repo)
            live = state.setdefault(hub_id, entry)
            live.update(item_id=entry.get("item_id"), sent=entry.get("sent") or {},
                        error=entry.get("error"))
            _save(repo, state)
    # Notes that arrived while sending go out now; failures wait for the
    # next sync rather than spinning here.
    with _lock:
        return progressed and any(_diff(e) and not e.get("error") for e in _load(repo).values())


def _items_url(client) -> str:
    site = client.resolve_site()
    return f"/sites/{site.site_id}/lists/{quote(settings.hub_tasks_list.strip())}/items"


def _send(client, base: str, hub_id: str, entry: dict) -> str:
    """One row. Updates entry's item_id and sent in place."""
    want = entry["want"]
    if not entry.get("item_id"):
        found = client._request("GET", base, params={
            "$filter": f"fields/HubId eq '{hub_id}'", "$select": "id"}) or {}
        hits = found.get("value") or []
        if hits:
            entry["item_id"], entry["sent"] = hits[0]["id"], {}
        elif want.get("TaskStatus") != "Open":
            # Never waited for anyone (published on submission, or decided
            # before the first write got through): no to-do to show.
            entry["sent"] = dict(want)
            return "skipped"
        else:
            body = {k: v for k, v in want.items() if v is not None}
            made = client._request("POST", base, json={"fields": body})
            entry["item_id"], entry["sent"] = made["id"], dict(want)
            return "sent"
    change = _diff(entry)
    body = {k: ("" if v is None else v) for k, v in change.items()
            if not (v is None and k in DATE_FIELDS)}
    if body:
        client._request("PATCH", f"{base}/{entry['item_id']}/fields", json=body)
    entry["sent"] = {**(entry.get("sent") or {}), **change}
    return "sent"
