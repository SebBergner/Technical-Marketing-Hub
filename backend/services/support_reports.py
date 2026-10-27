"""Reports about content, and asking for help (A2, Seb 2026-10-07; Summit;
Liwei 2026-10-23/28).

"Report an issue" on a demo's page (about that demo) and "Get help" at the
foot of the sidebar (about the Hub itself) both make a report: a category,
what is wrong, and the demo when there is one. It is
kept here (owned/support_reports.json) and copied to the Hub Tasks list as a
"Support request" row (integrations/graph/hub_tasks.py), where whoever
handles it changes its status in SharePoint. The Hub reads the status back
for "My reports" and for the counts on Admin -> Report owners.

Who hears about it is decided here, not in Power Automate: each segment has
its owners (owned/report_owners.json, managed on Admin -> Report owners), and
the addresses of the owners of the demo's segment who have Notify on are
written to the row's NotifyTo column; the flow only mails those. A demo in
no listed segment (IoT, none), Get help, and a segment with no owner
notified, go to General. Never to the demo's uploader (Summit).

Partners may report (Liwei 2026-10-28) and stay anonymous: the row and every
list say "partner"; only a one-way key lets them find their own reports.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

from backend.access import _is_internal_address, _norm_email

REPORTS = "support_reports.json"
OWNERS = "report_owners.json"
#: Liwei 2026-10-28; General takes everything the others do not.
SEGMENTS = ["CAD", "PLM", "ALM", "SLM", "SCO"]
GENERAL = "General"
#: As in the Hub Tasks Category column, apostrophes included (U+2019,
#: read off the list 2026-10-28): a choice must match exactly. Two sets
#: (Liwei 2026-10-28): a demo's page asks about that demo; Get help, in the
#: sidebar, about the Hub itself, and always goes to General.
DEMO_CATEGORIES = ["File won’t open or is missing", "Content is outdated or wrong",
                   "Details are wrong (product, date, owner)",
                   "Demo environment or VM problem", "Other"]
HUB_CATEGORIES = ["Hub won’t load or is slow", "Demo list is out of date",
                  "Can’t find content", "Sign-in or access problem",
                  "Search or filters don’t work", "Other"]
CATEGORIES = list(dict.fromkeys(DEMO_CATEGORIES + HUB_CATEGORIES))
DETAILS_MAX = 2000
OWNERS_MAX = 20
STATUS_SECONDS = 60
_lock = threading.Lock()
_status_cache: dict = {"at": 0.0, "value": None}


class ReportError(ValueError):
    """What the person is told."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _path(repo, name: str) -> str:
    return os.path.join(repo.owned_dir, name)


def _load(repo, name: str, empty):
    try:
        with open(_path(repo, name), encoding="utf-8") as fh:
            value = json.load(fh)
        return value if isinstance(value, type(empty)) else empty
    except (FileNotFoundError, ValueError):
        return empty


def _save(repo, name: str, value) -> None:
    from backend.repositories.json_repo import _atomic_write
    _atomic_write(_path(repo, name), value)


def reporter_key(user) -> str:
    """Who made a report, one way: matched for "My reports", never shown."""
    who = f"{user.object_id or ''}|{_norm_email(user.email)}".lower()
    return hashlib.sha256(("hub-report:" + who).encode()).hexdigest()[:24]


# ─────────────────────────────────────────────────────────── owners
def owners(repo) -> dict[str, list[dict]]:
    """{segment: [{name, email, notify}]}, every segment present."""
    saved = _load(repo, OWNERS, {})
    return {s: list(saved.get(s) or []) for s in SEGMENTS + [GENERAL]}


def set_owners(repo, segment: str, people: list[dict]) -> list[dict]:
    if segment not in SEGMENTS + [GENERAL]:
        raise ReportError(f"No segment {segment!r}.")
    if len(people) > OWNERS_MAX:
        raise ReportError(f"At most {OWNERS_MAX} owners per segment.")
    clean, seen = [], set()
    for p in people:
        email = _norm_email(p.get("email"))
        name = " ".join(str(p.get("name") or "").split())[:120]
        if not email or "@" not in email:
            raise ReportError("Each owner needs an email address.")
        if not _is_internal_address(email):
            raise ReportError(f"{email} is not a PTC address: owners are PTC staff.")
        if email in seen:
            raise ReportError(f"{email} is listed twice.")
        seen.add(email)
        clean.append({"name": name or email, "email": email, "notify": bool(p.get("notify", True))})
    with _lock:
        saved = _load(repo, OWNERS, {})
        saved[segment] = clean
        _save(repo, OWNERS, saved)
    return clean


def route(repo, segment: str | None) -> dict:
    """Which segment a report counts under, and whom to tell."""
    lists = owners(repo)
    seg = segment if segment in SEGMENTS else GENERAL
    told = [o["email"] for o in lists[seg] if o.get("notify")]
    fell_back = False
    if not told and seg != GENERAL:
        told = [o["email"] for o in lists[GENERAL] if o.get("notify")]
        fell_back = True
    return {"segment": seg, "notify_to": told, "fell_back": fell_back}


# ─────────────────────────────────────────────────────────── reports
def submit(repo, user, *, category: str, details: str, asset=None) -> dict:
    if category not in (DEMO_CATEGORIES if asset else HUB_CATEGORIES):
        raise ReportError("Choose one of the categories.")
    details = (details or "").strip()
    if len(details) < 5:
        raise ReportError("Say what is wrong, or what you need.")
    if len(details) > DETAILS_MAX:
        raise ReportError(f"At most {DETAILS_MAX} characters.")
    partner = bool(user.is_partner)
    routed = route(repo, getattr(asset, "segment", None) if asset else None)
    record = {
        "id": secrets.token_hex(6), "at": _now(), "category": category, "details": details,
        "asset_id": asset.id if asset else None, "title": asset.title if asset else None,
        "demo_segment": getattr(asset, "segment", None) if asset else None,
        **routed,
        # Anonymous for partners (Liwei 2026-10-23): no name, no address.
        "reported_by": "partner" if partner else _norm_email(user.email) or None,
        "reporter": reporter_key(user),
    }
    with _lock:
        items = _load(repo, REPORTS, [])
        items.append(record)
        _save(repo, REPORTS, items)
    from backend.integrations.graph import hub_tasks
    hub_tasks.note_report(repo, record)
    return record


def listing(repo) -> list[dict]:
    """Newest first."""
    return sorted(_load(repo, REPORTS, []), key=lambda r: r.get("at") or "", reverse=True)


def statuses(repo, fresh: bool = False) -> dict[str, str]:
    """{report id: TaskStatus} as the Hub Tasks list says now, cached for a
    minute; {} without Graph (every report then reads as Open)."""
    now = time.monotonic()
    if not fresh and _status_cache["value"] is not None \
            and now - _status_cache["at"] < STATUS_SECONDS:
        return _status_cache["value"]
    from backend.integrations.graph import hub_tasks
    try:
        value = hub_tasks.read_statuses("report:")
    except Exception:                                       # noqa: BLE001
        value = None
    if value is None:
        return _status_cache["value"] or {}
    _status_cache.update(at=now, value=value)
    return value


def _view(record: dict, status: dict[str, str], *, for_owner: bool) -> dict:
    out = {k: record.get(k) for k in ("id", "at", "category", "details", "asset_id", "title",
                                      "segment", "fell_back")}
    out["status"] = status.get(record["id"], "Open")
    if for_owner:
        out["reported_by"] = record.get("reported_by")
        out["notify_to"] = record.get("notify_to") or []
    return out


def mine(repo, user) -> list[dict]:
    key = reporter_key(user)
    status = statuses(repo)
    return [_view(r, status, for_owner=False) for r in listing(repo) if r.get("reporter") == key]


def by_segment(repo, segment: str) -> list[dict]:
    status = statuses(repo)
    return [_view(r, status, for_owner=True) for r in listing(repo) if r.get("segment") == segment]


def counts(repo) -> dict[str, dict]:
    """Per segment: open, total, the last 30 days, and whether anyone there
    is notified (a segment without one hands its reports to General)."""
    status = statuses(repo)
    month = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    lists = owners(repo)
    out = {s: {"open": 0, "total": 0, "last_30": 0,
               "notified": any(o.get("notify") for o in lists[s])}
           for s in SEGMENTS + [GENERAL]}
    for r in listing(repo):
        c = out.get(r.get("segment")) or out[GENERAL]
        c["total"] += 1
        c["open"] += status.get(r["id"], "Open") == "Open"
        c["last_30"] += (r.get("at") or "") >= month
    return out
