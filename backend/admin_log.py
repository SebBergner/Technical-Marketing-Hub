"""The Admin log: every change made through the Admin page's API (Liwei,
2026-10-14).

Append-only, and meant to stay that way:

* nothing in the Hub can change or delete an entry -- there is no endpoint
  for it, only `record()` (append) and `read()`;
* each entry carries the hash of the one before it (`prev`) and its own
  (`hash`), so an entry edited or removed in the file itself breaks the
  chain from that point on, and the Admin page says where (`verify()`).

What is recorded is decided in one place, `middleware()` below: every request
that changes something on the Admin-related endpoints (WATCHED), whoever made
it and whatever the answer -- a refused attempt (401/403) included -- plus
the lookups of one person's usage, which are reads but about a person. The
request's JSON body is kept as the detail, with anything that looks like a
password or secret blanked out; uploads are noted by size only.

The file is owned/admin_log.jsonl, beside the other Hub-owned records that a
sync never touches.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from datetime import datetime, timezone

from backend.config import settings

LOG_FILE = "admin_log.jsonl"
GENESIS = "0" * 64
_lock = threading.Lock()

#: (method, route) -> what it does, in the words the Admin page shows.
ACTIONS: dict[tuple[str, str], str] = {
    ("POST", "/api/admin/login"): "Signed in with the admin password",
    ("POST", "/api/admin/logout"): "Signed out of the admin session",
    ("PUT", "/api/admin/auto-sync"): "Changed the daily sync",
    ("POST", "/api/admin/hidden"): "Hid a demo",
    ("DELETE", "/api/admin/hidden/{asset_id}"): "Unhid a demo",
    ("PUT", "/api/admin/hub-settings"): "Changed the Hub's display options",
    ("PUT", "/api/admin/promoted"): "Changed the Featured demos",
    ("POST", "/api/admin/access/groups"): "Created a group",
    ("PUT", "/api/admin/access/groups/{group_id}"): "Changed a group",
    ("DELETE", "/api/admin/access/groups/{group_id}"): "Deleted a group",
    ("POST", "/api/admin/api-tokens"): "Created an API token",
    ("POST", "/api/admin/api-tokens/{token_id}/revoke"): "Revoked an API token",
    ("POST", "/api/admin/sample-activity"): "Loaded sample activity",
    ("DELETE", "/api/admin/sample-activity"): "Removed sample activity",
    ("GET", "/api/admin/activity/person"): "Looked up a person's activity",
    ("PUT", "/api/assets/{asset_id}/access"): "Set a demo Open or Internal",
    ("POST", "/api/assets/{asset_id}/access-requests"): "Requested an access change",
    ("POST", "/api/assets/{asset_id}/access-requests/{request_id}/withdraw"):
        "Withdrew an access request",
    ("POST", "/api/admin/access-requests/{request_id}/decision"): "Decided an access request",
    ("GET", "/api/admin/admin-log.csv"): "Exported the Admin log",
    ("POST", "/api/uploads"): "Started an upload",
    ("POST", "/api/uploads/{upload_id}/files/{index}/session"): "Opened a file upload",
    ("POST", "/api/uploads/{upload_id}/files/{index}/done"): "Uploaded a file",
    ("POST", "/api/uploads/{upload_id}/finish"): "Finished an upload",
    ("POST", "/api/uploads/{upload_id}/cancel"): "Cancelled an upload",
    ("POST", "/api/uploads/{upload_id}/resubmit"): "Resubmitted an upload",
    ("POST", "/api/uploads/{upload_id}/publish"): "Published an upload",
    ("POST", "/api/uploads/{upload_id}/send-back"): "Sent an upload back",
    ("PUT", "/api/assets/{asset_id}/still-current"): "Set Still current",
    ("PUT", "/api/assets/{asset_id}/archive"): "Archived or restored a demo",
    ("POST", "/api/graph/sync"): "Ran the SharePoint sync",
    ("POST", "/api/graph/writeback"): "Wrote metadata back to SharePoint",
    ("POST", "/api/consensus/sync"): "Ran the Consensus sync",
    ("POST", "/api/consensus/oauth/revoke"): "Disconnected Consensus",
    ("POST", "/api/curation/proposals/{asset_id}/{field}/{decision}"):
        "Decided a metadata proposal",
    ("POST", "/api/migration/brightcove/sheets"): "Uploaded a migration sheet",
    ("POST", "/api/migration/brightcove/runs"): "Started a migration run",
    ("POST", "/api/migration/brightcove/runs/{batch_id}/pause"): "Paused a migration run",
    ("POST", "/api/migration/brightcove/runs/{batch_id}/resume"): "Resumed a migration run",
}
#: Reads worth a line: about one person, not about the catalogue.
_LOGGED_READS = {route for (method, route) in ACTIONS if method == "GET"}
WATCHED = re.compile(r"^/api/(admin|graph|consensus/(sync|oauth)|curation/proposals|migration)/"
                     r"|^/api/assets/[^/]+/(access|still-current|archive)$"
                     r"|^/api/assets/[^/]+/access-requests(/|$)"
                     r"|^/api/uploads(/|$)")

#: What area of the Hub an entry is about, for filtering and for each Admin
#: tab's "Recent changes" (2026-10-15). Worked out when read, from the path,
#: so entries written before categories existed have one too and the hash
#: chain is untouched. First match wins.
CATEGORIES: list[tuple[str, re.Pattern]] = [
    ("Content access", re.compile(r"^/api/assets/[^/]+/(access|access-requests)"
                                  r"|^/api/admin/(hidden|access-requests)")),
    ("Content review", re.compile(r"^/api/assets/[^/]+/(still-current|archive)$")),
    ("Uploads", re.compile(r"^/api/uploads(/|$)")),
    ("Users & groups", re.compile(r"^/api/admin/(access|api-tokens)(/|$)")),
    ("Sign-in", re.compile(r"^/api/admin/(login|logout)$")),
    ("Home page", re.compile(r"^/api/admin/(promoted|hub-settings)$")),
    ("Sync", re.compile(r"^/api/(graph/sync|consensus/(sync|oauth)|admin/auto-sync)")),
    ("Metadata", re.compile(r"^/api/(graph/writeback|curation/)")),
    ("Migration", re.compile(r"^/api/migration/")),
    ("Usage data", re.compile(r"^/api/admin/(sample-activity|activity/person|admin-log)")),
]


def category_of(path: str) -> str:
    return next((name for name, rx in CATEGORIES if rx.search(path or "")), "Other")
_SECRET = re.compile(r"pass|secret|token|key", re.I)
_BODY_LIMIT = 16 * 1024


def _path() -> str:
    return os.path.join(settings.data_dir, "owned", LOG_FILE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _digest(prev: str, entry: dict) -> str:
    body = json.dumps(entry, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256((prev + body).encode("utf-8")).hexdigest()


def _last(path: str) -> tuple[int, str]:
    """(seq, hash) of the newest entry, or (0, GENESIS) for an empty log."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 64 * 1024))
            lines = fh.read().decode("utf-8", "replace").splitlines()
    except FileNotFoundError:
        return 0, GENESIS
    for line in reversed(lines):
        try:
            e = json.loads(line)
            return int(e["seq"]), e["hash"]
        except (ValueError, KeyError, TypeError):
            continue
    return 0, GENESIS


def record(actor: str, action: str, *, method: str = "", path: str = "",
           status: int | None = None, target: str | None = None,
           detail: dict | None = None) -> dict:
    """Append one entry. The only way anything gets into the log."""
    path_ = _path()
    with _lock:
        os.makedirs(os.path.dirname(path_), exist_ok=True)
        seq, prev = _last(path_)
        entry = {"seq": seq + 1, "at": _now(), "actor": actor or "anonymous",
                 "action": action, "method": method, "path": path, "status": status,
                 "target": target, "detail": detail or {}, "prev": prev}
        entry["hash"] = _digest(prev, entry)
        with open(path_, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def _entries() -> list[dict]:
    try:
        with open(_path(), encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]
    except FileNotFoundError:
        return []


def verify(entries: list[dict] | None = None) -> dict:
    """Walk the chain. `intact` False names the first entry that does not
    follow from the one before it -- edited, removed or inserted."""
    entries = _entries() if entries is None else entries
    prev = GENESIS
    for i, e in enumerate(entries):
        body = {k: v for k, v in e.items() if k != "hash"}
        if e.get("prev") != prev or e.get("seq") != i + 1 or _digest(prev, body) != e.get("hash"):
            return {"intact": False, "entries": len(entries), "broken_at": i + 1}
        prev = e["hash"]
    return {"intact": True, "entries": len(entries), "broken_at": None}


def _result(entry: dict) -> str:
    status = entry.get("status") or 0
    return "done" if 200 <= status < 400 else ("refused" if status in (401, 403) else "failed")


def read(*, since: str | None = None, until: str | None = None, q: str | None = None,
         category: str | None = None, result: str | None = None,
         offset: int = 0, limit: int | None = 50) -> dict:
    """Newest first, filtered by period, area (category), result (done /
    refused / failed) and a word in who, what or target."""
    entries = _entries()
    check = verify(entries)
    for e in entries:
        e["category"] = category_of(e.get("path", ""))
        e["result"] = _result(e)
    rows = entries
    if category:
        wanted = {c.strip() for c in category.split(",") if c.strip()}
        rows = [e for e in rows if e["category"] in wanted]
    if result:
        rows = [e for e in rows if e["result"] == result]
    if since:
        rows = [e for e in rows if e["at"] >= since[:19]]
    if until:
        rows = [e for e in rows if e["at"] < until[:19]]
    if q:
        needle = q.strip().lower()
        rows = [e for e in rows
                if needle in " ".join(str(e.get(k) or "") for k in
                                      ("actor", "action", "target", "path")).lower()
                or needle in json.dumps(e.get("detail") or {}, ensure_ascii=False).lower()]
    rows = list(reversed(rows))
    page = rows[offset:] if limit is None else rows[offset:offset + limit]
    return {"total": len(rows), "offset": offset,
            "items": [{k: v for k, v in e.items() if k not in ("prev", "hash")} for e in page],
            "categories": [name for name, _ in CATEGORIES] + ["Other"],
            "integrity": check}


def to_csv(rows: list[dict]) -> str:
    """The rows as CSV, for an auditor's spreadsheet: one line per entry,
    the detail as compact JSON, times in UTC."""
    import csv
    import io
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["seq", "time_utc", "actor", "category", "action", "target", "result",
                "status", "method", "path", "detail"])
    for e in rows:
        w.writerow([e.get("seq"), e.get("at"), e.get("actor"), e.get("category"),
                    e.get("action"), e.get("target") or "", e.get("result"),
                    e.get("status"), e.get("method"), e.get("path"),
                    json.dumps(e.get("detail") or {}, ensure_ascii=False,
                               separators=(",", ":"))])
    return out.getvalue()


def _redact(value):
    if isinstance(value, dict):
        return {k: ("•••" if _SECRET.search(str(k)) else _redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def _detail(content_type: str, body: bytes, truncated: bool, query: str) -> dict:
    detail: dict = {}
    if query:
        from urllib.parse import parse_qsl
        detail["query"] = _redact(dict(parse_qsl(query)))
    if not body:
        return detail
    if "application/json" in content_type and not truncated:
        try:
            detail["body"] = _redact(json.loads(body))
        except ValueError:
            detail["body_bytes"] = len(body)
    else:
        # An upload: its size, never its contents.
        detail["body_bytes"] = len(body) if not truncated else f">{_BODY_LIMIT}"
    return detail


def _target(detail: dict) -> str | None:
    """What a change was about, when the path does not say: the demo or the
    group named in the body ("Hid a demo" posts {"asset_id": ...})."""
    body = detail.get("body")
    if isinstance(body, dict):
        for key in ("asset_id", "name", "email"):
            if isinstance(body.get(key), str) and body[key]:
                return body[key]
    return None


def _who(scope) -> str:
    """The actor for a route not gated by require_perm(), which leaves none."""
    from starlette.requests import Request

    from backend.admin_auth import has_admin_session
    from backend.auth import principal_from_request
    request = Request(scope)
    user = principal_from_request(request)
    if user.is_dev_principal:
        return f"dev:{user.email}"
    if user.is_authenticated:
        return f"user:{user.email}"
    return "admin-session" if has_admin_session(request) else "anonymous"


def middleware(app):
    """ASGI middleware: one entry per watched request, after it is answered.

    Innermost (added before the session and the sign-in gate), so the route
    has been matched by the time the answer comes back, and require_perm()
    has left the actor in request.state.
    """
    async def wrapped(scope, receive, send):
        if scope["type"] != "http" or not WATCHED.search(scope.get("path", "")):
            return await app(scope, receive, send)
        method = scope.get("method", "GET")
        if method in ("HEAD", "OPTIONS"):
            return await app(scope, receive, send)

        chunks: list[bytes] = []
        size = 0
        status: dict = {}

        async def tee_receive():
            nonlocal size
            message = await receive()
            if message.get("type") == "http.request":
                part = message.get("body", b"")
                size += len(part)
                if size <= _BODY_LIMIT:
                    chunks.append(part)
            return message

        async def tee_send(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await app(scope, tee_receive, tee_send)
        finally:
            route = getattr(scope.get("route"), "path", None) or scope.get("path", "")
            if method == "GET" and route not in _LOGGED_READS:
                pass
            else:
                try:
                    headers = {k.decode("latin-1"): v.decode("latin-1")
                               for k, v in scope.get("headers", [])}
                    state = scope.get("state") or {}
                    params = scope.get("path_params") or {}
                    detail = _detail(headers.get("content-type", ""), b"".join(chunks),
                                     size > _BODY_LIMIT,
                                     scope.get("query_string", b"").decode("latin-1"))
                    target = (state.get("hub_target")
                              or " / ".join(str(v) for v in params.values()) or _target(detail))
                    record(state.get("hub_actor") or _who(scope),
                           ACTIONS.get((method, route), f"{method} {route}"),
                           method=method, path=scope.get("path", ""),
                           status=status.get("code", 500), target=target, detail=detail)
                except Exception:     # the log must never break the request
                    import logging
                    logging.getLogger(__name__).exception("admin log entry not written")

    return wrapped
