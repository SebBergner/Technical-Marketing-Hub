"""The Admin page's own endpoints: sign-in, and one aggregated overview.

Everything here is behind `require_admin` except the two session routes, and
the overview is a single call on purpose. The alternative — the page fanning
out to /api/debug/backend, /api/auth/me, /api/consensus/oauth/status,
/api/taxonomy and the repository — would have spread an admin view across
five endpoints with five different audiences, some of them public. One
endpoint keeps "what an admin may see" in one place, where it can be read.

Nothing here writes to SharePoint. The sync buttons on the page call
/api/graph/sync and /api/consensus/sync, which accept an admin session by way
of `admin_or_curator`; approving a metadata proposal deliberately does not,
and stays curator-only until SSO exists.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from backend.admin_auth import (
    clear_session, has_admin_session, issue_session, require_admin, verify_password,
)
from backend.auth import security_warnings
from backend.config import settings
from backend.deps import get_repo
from backend.integrations.consensus_oauth import get_oauth
from backend.repositories.base import AssetQuery, AssetRepository

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


class LoginIn(BaseModel):
    username: str
    password: str


@router.get("/session")
def session_state(request: Request):
    """Whether this browser is signed in — and whether an admin exists at all.

    Deliberately public: the page has to know which of three things to render
    (the form, the dashboard, or "no admin configured on this deployment")
    before it can authenticate, and none of those answers is a secret.
    """
    return {
        "configured": settings.admin_configured,
        "signed_in": has_admin_session(request),
    }


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response):
    """Deliberately vague on failure, and slow to nobody.

    One message for a wrong username and a wrong password: naming which half
    was wrong turns a shared credential into two guessing games instead of
    one. There is no lockout — with a single account it would be a denial of
    service anyone could trigger — so the password needs to be long enough
    that guessing is hopeless. That is an operational requirement, written
    down here because nothing in the code can enforce it.
    """
    if not settings.admin_configured:
        return Response(status_code=503)
    if not verify_password(body.username, body.password):
        log.warning("admin sign-in refused")
        return Response(status_code=401)
    issue_session(request, response)
    log.info("admin signed in")
    return {"signed_in": True}


@router.post("/logout")
def logout(response: Response):
    clear_session(response)
    return {"signed_in": False}


# ───────────────────────────────────────────────────────────────── the overview
def _iso_age_days(stamp: str | None) -> float | None:
    if not stamp:
        return None
    try:
        when = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return round((datetime.now(timezone.utc) - when).total_seconds() / 86400, 1)


def _source_state(repo: AssetRepository, source: str) -> dict:
    state = repo.sync_state(source) if hasattr(repo, "sync_state") else {}
    return {
        "last_success_at": state.get("last_success_at"),
        "days_since_success": _iso_age_days(state.get("last_success_at")),
        "last_attempt_at": state.get("last_attempt_at"),
        "last_attempt_ok": state.get("last_attempt_ok"),
        "last_error": state.get("last_error"),
        "last_result": state.get("last_result"),
        "assets": repo.count_source_rows(source)
        if hasattr(repo, "count_source_rows") else None,
    }


#: Coverage worth reporting, and only fields a person could actually fill in.
#: `industry` is left out: it is empty across the whole SharePoint catalogue
#: and near-empty on Consensus, so a 99.7% gap would dominate the list while
#: describing a dimension nobody maintains.
_COVERAGE_FIELDS = ("segment", "products", "funnel_stage", "content_depth",
                    "description", "thumbnail_url")


@router.get("/overview", dependencies=[Depends(require_admin)])
def overview(repo: AssetRepository = Depends(get_repo)):
    """One payload, in the order the page reads it."""
    oauth = get_oauth()
    oauth_status = oauth.status()

    assets = repo.list(AssetQuery(limit=10 ** 6)).items
    total = len(assets)

    coverage = []
    for field in _COVERAGE_FIELDS:
        missing = sum(1 for a in assets if not getattr(a, field, None))
        coverage.append({
            "field": field,
            "missing": missing,
            "total": total,
            "percent_missing": round(missing * 100 / total, 1) if total else 0,
        })

    # Consensus's own view counts are the only usage figure with any history.
    # Kept apart from our counters rather than summed: every SharePoint asset
    # has no view count at all, so one combined number would describe a
    # population that does not exist (§7.3 of the handover).
    external = [a for a in assets if getattr(a, "external_views", None)]
    top_external = sorted(external, key=lambda a: -a.external_views)[:10]

    own = [(a, a.stats) for a in assets if a.stats and (
        a.stats.views or a.stats.downloads or a.stats.shares or a.stats.launches)]

    return {
        "environment": {
            # Which slot am I looking at. Staging and production are identical
            # on screen and hold different data, and this page can trigger a
            # sync -- so it says where it is before it says anything else.
            "site_name": os.getenv("WEBSITE_SITE_NAME") or "local",
            "slot": os.getenv("WEBSITE_SLOT_NAME") or "local",
            "data_dir": settings.data_dir,
            "storage_is_durable": not os.path.abspath(settings.data_dir).startswith(
                os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__)))))),
        },
        "integrations": {
            "sharepoint": {
                "configured": settings.graph_configured,
                "site_url": settings.graph_site_url,
                "library": settings.graph_list_name,
                **_source_state(repo, "sharepoint"),
            },
            "consensus": {
                "v1_configured": settings.consensus_configured,
                "v2_configured": settings.consensus_v2_configured,
                "v2_authorised": oauth_status.get("authorised"),
                "v2_token_expires_in": oauth_status.get("access_token_expires_in"),
                "scopes": oauth_status.get("scopes"),
                **_source_state(repo, "consensus"),
            },
            "auth": {
                "mode": settings.auth_mode,
                "curator_groups_configured": bool(settings.auth_curator_groups),
                "warnings": security_warnings(),
            },
            # Named so the page can say "not connected" rather than stay
            # silent about them: both appear in the mock-up and in .env.example,
            # and neither has ever been reachable from here.
            "not_connected": ["Brightcove", "Seismic / PTC Velocity"],
        },
        "catalogue": {"total": total, "coverage": coverage},
        "usage": {
            "consensus_views": {
                "assets_with_counts": len(external),
                "total_views": sum(a.external_views for a in external),
                "top": [{"id": a.id, "title": a.title, "views": a.external_views}
                        for a in top_external],
            },
            "own_counters": {
                "assets_touched": len(own),
                "views": sum(s.views for _, s in own),
                "downloads": sum(s.downloads for _, s in own),
                "shares": sum(s.shares for _, s in own),
                # The page prints this beside the numbers. They started at
                # zero on this date, and without it a small number reads as
                # "nobody uses the Hub" instead of "nobody was counting".
                "counting_since": "2026-09-21",
            },
        },
        "proposals": {"pending": _pending_proposals(repo)},
        "requests": {"unsynced": _unsynced_requests(repo)},
    }


def _pending_proposals(repo: AssetRepository) -> int | None:
    """Read-only on purpose: deciding one writes back to SharePoint, which an
    admin session is not allowed to do. Surfaced anyway because the whole
    proposals system has existed server-side with no UI at all."""
    lister = getattr(repo, "list_proposals", None)
    if lister is None:
        return None
    try:
        return lister(state="pending").total
    except Exception:                                    # noqa: BLE001
        log.warning("could not count proposals", exc_info=True)
        return None


def _unsynced_requests(repo: AssetRepository) -> int | None:
    counter = getattr(repo, "unsynced_requests", None)
    if counter is None:
        return None
    try:
        return len(counter())
    except Exception:                                    # noqa: BLE001
        log.warning("could not count unsynced requests", exc_info=True)
        return None


# ─────────────────────────────────────────────────────────────────── usage
def _events(repo: AssetRepository, since: str | None, until: str | None) -> list[dict]:
    reader = getattr(repo, "usage_events", None)
    return reader(since=since, until=until) if reader else []


def _tally(events: list[dict], key: str = "event") -> dict:
    out: dict = {}
    for e in events:
        out[e.get(key)] = out.get(e.get(key), 0) + 1
    return out


@router.get("/usage", dependencies=[Depends(require_admin)])
def usage(since: str | None = None, until: str | None = None,
          repo: AssetRepository = Depends(get_repo)):
    """What the Hub itself was used for, in a window.

    The window is passed in as ISO bounds rather than a named period, because
    "this week" depends on where the reader is sitting and the browser already
    knows — resolving it here would quietly give everyone Redmond's week.

    Consensus's own play counts are deliberately NOT here (Liwei, 2026-09-21):
    they measure a different platform's audience, and standing them beside our
    figures invited exactly the comparison that §7.3 warns against. They live
    on the Consensus source page, where the population they describe is the
    page's subject.
    """
    events = _events(repo, since, until)
    by_type = _tally(events)

    touched = {e["asset_id"] for e in events if e.get("asset_id")}

    searches = [e for e in events if e.get("event") == "search"]
    search_tally: dict[str, dict] = {}
    for e in searches:
        row = search_tally.setdefault(e.get("q", ""), {"q": e.get("q", ""), "times": 0,
                                                       "zero_results": 0})
        row["times"] += 1
        if not e.get("results"):
            row["zero_results"] += 1

    return {
        "window": {"since": since, "until": until},
        "totals": {
            "views": by_type.get("view", 0),
            "previews": by_type.get("preview", 0),
            "downloads": by_type.get("download", 0),
            "searches": by_type.get("search", 0),
            "assets_touched": len(touched),
        },
        "daily": _daily(events),
        # Against the window immediately before this one, same length. A count
        # on its own says nothing about whether it is good -- "95 downloads"
        # only means something beside "68 last month". Absent when there is no
        # earlier window to compare with (the "all time" range).
        "previous": _previous_totals(repo, since, until),
        "searches": {
            "top": sorted(search_tally.values(), key=lambda r: -r["times"])[:15],
            "zero_result": sorted(
                [r for r in search_tally.values() if r["zero_results"]],
                key=lambda r: -r["zero_results"])[:15],
        },
        # Loud on purpose: a demo log and a real one must never be mistaken
        # for each other. See scripts/seed_usage_events.py.
        "synthetic": any(e.get("synthetic") for e in events),
    }


def _daily(events: list[dict]) -> list[dict]:
    """Per-day counts, for the chart. Days with nothing are omitted rather
    than zero-filled here — the page knows the window and can draw the gaps,
    and inventing rows is how a quiet week starts looking like a busy one."""
    days: dict[str, dict] = {}
    for e in events:
        day = (e.get("at") or "")[:10]
        if not day:
            continue
        row = days.setdefault(day, {"day": day, "view": 0, "preview": 0,
                                    "download": 0, "search": 0})
        if e["event"] in row:
            row[e["event"]] += 1
    return [days[d] for d in sorted(days)]


@router.get("/usage/asset/{asset_id}", dependencies=[Depends(require_admin)])
def usage_for_asset(asset_id: str, since: str | None = None,
                    until: str | None = None,
                    repo: AssetRepository = Depends(get_repo)):
    """One demo's own history, including which files people actually took."""
    events = [e for e in _events(repo, since, until)
              if e.get("asset_id") == asset_id]
    by_type = _tally(events)

    files: dict[str, dict] = {}
    for e in events:
        if e["event"] not in ("download", "preview"):
            continue
        name = e.get("file") or e.get("item_id") or "—"
        row = files.setdefault(name, {"file": name, "kind": e.get("kind"),
                                      "download": 0, "preview": 0})
        row[e["event"]] += 1

    asset = repo.get(asset_id)
    return {
        "asset": {"id": asset_id,
                  "title": asset.title if asset else asset_id,
                  "type": asset.type if asset else None,
                  "source": asset.source if asset else None},
        "window": {"since": since, "until": until},
        "totals": {
            "views": by_type.get("view", 0),
            "previews": by_type.get("preview", 0),
            "downloads": by_type.get("download", 0),
        },
        "daily": _daily(events),
        "files": sorted(files.values(),
                        key=lambda r: (-r["download"], -r["preview"])),
        "synthetic": any(e.get("synthetic") for e in events),
    }


@router.get("/source/{source}", dependencies=[Depends(require_admin)])
def source_detail(source: str, repo: AssetRepository = Depends(get_repo)):
    """One source's own page: how its syncs have gone, and — for Consensus —
    the play counts it keeps itself."""
    runs = getattr(repo, "sync_runs", lambda **_: [])(source_system=source, limit=30)
    payload = {
        "source": source,
        "state": _source_state(repo, source),
        "runs": runs,
    }
    if source == "consensus":
        assets = [a for a in repo.list(AssetQuery(sources=["consensus"],
                                                  limit=10 ** 6)).items
                  if getattr(a, "external_views", None)]
        payload["plays"] = {
            "assets_with_counts": len(assets),
            "total_views": sum(a.external_views for a in assets),
            "top": [{"id": a.id, "title": a.title, "views": a.external_views}
                    for a in sorted(assets, key=lambda a: -a.external_views)[:20]],
            # Said here rather than left for the reader to assume: this is
            # Consensus's own tally of plays on its own platform, not a
            # measure of anything the Hub did.
            "note": "Counted by Consensus on its own platform, before and "
                    "independently of this Hub.",
        }
    return payload


def _previous_totals(repo: AssetRepository, since: str | None,
                     until: str | None) -> dict | None:
    """The same-length window ending where this one starts.

    Returns None for an unbounded range: "all time" has nothing before it, and
    inventing a comparison there would be arithmetic pretending to be insight.
    """
    if not since:
        return None
    try:
        start = datetime.fromisoformat(since)
        end = datetime.fromisoformat(until) if until else datetime.now()
    except ValueError:
        return None
    span = end - start
    if span.total_seconds() <= 0:
        return None
    events = _events(repo, (start - span).isoformat(timespec="seconds"),
                     start.isoformat(timespec="seconds"))
    by_type = _tally(events)
    return {
        "since": (start - span).isoformat(timespec="seconds"),
        "until": start.isoformat(timespec="seconds"),
        "views": by_type.get("view", 0),
        "previews": by_type.get("preview", 0),
        "downloads": by_type.get("download", 0),
        "searches": by_type.get("search", 0),
    }


#: What a row can be grouped by. Anything with thousands of demos behind it
#: needs to be readable before it is complete, and a roll-up answers "where is
#: the attention going" in a screenful where a list of every demo cannot.
BREAKDOWNS = {
    "demo": lambda a: [a.id] if a else [],
    "product": lambda a: (a.product_families or ["(no product)"]) if a else [],
    "segment": lambda a: [a.segment or "(no segment)"] if a else [],
    "source": lambda a: [a.source or "(unknown)"] if a else [],
    "type": lambda a: [a.type or "(unknown)"] if a else [],
}


@router.get("/usage/breakdown", dependencies=[Depends(require_admin)])
def usage_breakdown(dimension: str = "demo", since: str | None = None,
                    until: str | None = None, q: str | None = None,
                    sort: str = "view", limit: int = 25, offset: int = 0,
                    scope_dim: str | None = None, scope_key: str | None = None,
                    repo: AssetRepository = Depends(get_repo)):
    """Usage grouped by one dimension, searchable, sortable and paged.

    Paged on the server rather than sliced in the browser: at a thousand demos
    the honest answer to "show me the table" is a page of it plus a count, and
    a page that quietly dropped the other 975 rows would be the kind of number
    that misleads precisely because it looks complete.
    """
    if dimension not in BREAKDOWNS:
        raise HTTPException(status_code=400,
                            detail=f"unknown dimension {dimension!r}")
    if sort not in ("view", "preview", "download"):
        sort = "view"

    key_of = BREAKDOWNS[dimension]
    events = [e for e in _events(repo, since, until) if e.get("asset_id")]

    # One repository read per asset touched, not per event.
    assets = {aid: repo.get(aid) for aid in {e["asset_id"] for e in events}}

    # Drilling in: "by product" -> click Windchill -> the demos inside it.
    # Narrowing the events rather than the finished rows keeps every number
    # below -- including the share column -- relative to the scope on screen.
    if scope_dim and scope_key:
        if scope_dim not in BREAKDOWNS:
            raise HTTPException(status_code=400,
                                detail=f"unknown scope {scope_dim!r}")
        scope_of = BREAKDOWNS[scope_dim]
        events = [e for e in events
                  if scope_key in [str(k) for k in scope_of(assets.get(e["asset_id"]))]]

    groups: dict[str, dict] = {}
    for e in events:
        asset = assets.get(e["asset_id"])
        for key in (key_of(asset) or ["(no longer in the catalogue)"]):
            row = groups.setdefault(str(key), {
                "key": str(key), "view": 0, "preview": 0, "download": 0})
            if e["event"] in row:
                row[e["event"]] += 1

    rows = list(groups.values())
    if dimension == "demo":
        for row in rows:
            asset = assets.get(row["key"])
            row["label"] = asset.title if asset else (
                row["key"] + " (no longer in the catalogue)")
            row["source"] = asset.source if asset else None
            row["type"] = asset.type if asset else None
    else:
        for row in rows:
            row["label"] = row["key"]

    if q:
        needle = q.strip().lower()
        rows = [r for r in rows if needle in r["label"].lower()]

    grand = sum(r[sort] for r in rows) or 1
    for row in rows:
        row["share"] = round(row[sort] * 100 / grand, 1)

    rows.sort(key=lambda r: (-r[sort], r["label"].lower()))
    return {
        "dimension": dimension,
        "scope": {"dimension": scope_dim, "key": scope_key} if scope_key else None,
        "sort": sort,
        "total_rows": len(rows),
        "rows": rows[offset:offset + limit],
        "offset": offset,
        "limit": limit,
    }


@router.get("/usage/untouched", dependencies=[Depends(require_admin)])
def usage_untouched(since: str | None = None, until: str | None = None,
                    q: str | None = None, limit: int = 25, offset: int = 0,
                    repo: AssetRepository = Depends(get_repo)):
    """Demos nobody opened in this window.

    Its own view rather than a tail of zeroes on the main table: at this
    catalogue's size most demos are untouched in any given week, so mixing
    them in would bury the ones that were used under hundreds of rows that
    say nothing. Separated, the same fact becomes the more useful question —
    which content is not earning its place.
    """
    touched = {e["asset_id"] for e in _events(repo, since, until)
               if e.get("asset_id")}
    rows = []
    for asset in repo.list(AssetQuery(limit=10 ** 6)).items:
        if asset.id in touched:
            continue
        if q and q.strip().lower() not in (asset.title or "").lower():
            continue
        rows.append({"asset_id": asset.id, "label": asset.title,
                     "source": asset.source, "type": asset.type,
                     "uploaded_at": str(asset.uploaded_at) if asset.uploaded_at else None})
    rows.sort(key=lambda r: (r["label"] or "").lower())
    return {"total_rows": len(rows), "rows": rows[offset:offset + limit],
            "offset": offset, "limit": limit, "touched": len(touched)}
