"""Requests to make a demo Internal, or Open again (2026-10-15).

Elio, meeting 2026-10-07: marking existing demos Internal should be a
controlled, tracked process, not only a switch. So:

* anyone with "Request content access change" (PTC employees by default,
  never partners) asks, with a reason, from the demo's page;
* someone with "Manage content access" approves or rejects it -- on the
  demo's page or on Admin -> Content access -- with an optional note, and an
  approval applies the change;
* the requester may withdraw it while it is pending;
* every step is kept here, and also lands in the Admin log.

One pending request per demo at a time: a second one would only ask the
same question again. Hub-only, like the marks themselves
(owned/access_requests.json). SharePoint is written only as a copy: each
request is a row in the Hub Tasks list (integrations/graph/hub_tasks.py).
"""
from __future__ import annotations

import json
import os
import secrets
import threading
from datetime import datetime, timezone

FILE = "access_requests.json"
REASON_MAX = 1000
_lock = threading.Lock()


class RequestError(ValueError):
    """A request the rules refuse; the message is for the person asking."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _path(repo) -> str:
    return os.path.join(repo.owned_dir, FILE)


def _load(repo) -> list[dict]:
    try:
        with open(_path(repo), encoding="utf-8") as fh:
            items = json.load(fh)
        return items if isinstance(items, list) else []
    except (FileNotFoundError, ValueError):
        return []


def _save(repo, items: list[dict]) -> None:
    from backend.repositories.json_repo import _atomic_write
    _atomic_write(_path(repo), items)


def listing(repo, *, status: str | None = None, asset_id: str | None = None,
            limit: int = 200) -> list[dict]:
    """Newest first."""
    items = [r for r in _load(repo)
             if (not status or r["status"] == status)
             and (not asset_id or r["asset_id"] == asset_id)]
    return sorted(items, key=lambda r: r["requested_at"], reverse=True)[:limit]


def pending_for(repo, asset_id: str) -> dict | None:
    return next((r for r in _load(repo)
                 if r["asset_id"] == asset_id and r["status"] == "pending"), None)


def create(repo, asset, level: str, reason: str, actor: str) -> dict:
    if level not in ("internal", "open"):
        raise RequestError("Ask for 'internal' or 'open'.")
    reason = (reason or "").strip()
    if not reason:
        raise RequestError("Say why, so whoever decides knows what to weigh.")
    if len(reason) > REASON_MAX:
        raise RequestError(f"Keep the reason under {REASON_MAX} characters.")
    if level == "internal" and asset.internal:
        raise RequestError("This demo is already Internal.")
    if level == "open" and not asset.internal:
        raise RequestError("This demo is already Open.")
    if level == "open" and asset.internal_source == "sharepoint":
        raise RequestError("SharePoint closes this demo's folder to partners; it can only "
                           "be opened there.")
    with _lock:
        items = _load(repo)
        if any(r["asset_id"] == asset.id and r["status"] == "pending" for r in items):
            raise RequestError("A request for this demo is already waiting for a decision.")
        request = {"id": secrets.token_hex(6), "asset_id": asset.id, "title": asset.title,
                   "level": level, "reason": reason, "status": "pending",
                   "requested_by": actor, "requested_at": _now(),
                   "decided_by": None, "decided_at": None, "note": None}
        items.append(request)
        _save(repo, items)
    _task(repo, request)
    return request


def _task(repo, request: dict) -> None:
    """Its row in the Hub Tasks list (integrations/graph/hub_tasks.py)."""
    from backend.integrations.graph import hub_tasks
    hub_tasks.note_access(repo, request)


def _settle(repo, request_id: str, status: str, actor: str, note: str | None,
            check=None) -> dict:
    with _lock:
        items = _load(repo)
        request = next((r for r in items if r["id"] == request_id), None)
        if request is None:
            raise LookupError(request_id)
        if request["status"] != "pending":
            raise RequestError(f"This request was already {request['status']}.")
        if check:
            check(request)
        request.update(status=status, decided_by=actor, decided_at=_now(),
                       note=(note or "").strip()[:REASON_MAX] or None)
        _save(repo, items)
    _task(repo, request)
    return request


def decide(repo, request_id: str, approve: bool, actor: str, note: str | None) -> dict:
    """Approve or reject. The caller applies an approval (repo.set_access)."""
    return _settle(repo, request_id, "approved" if approve else "rejected", actor, note)


def withdraw(repo, request_id: str, actor: str) -> dict:
    def mine(request):
        if request["requested_by"] != actor:
            raise RequestError("Only the person who asked can withdraw a request.")
    return _settle(repo, request_id, "withdrawn", actor, None, check=mine)
