"""The Admin page's own endpoints: sign-in, one aggregated overview, and
users & groups.

Every route needs the "View Admin" permission (backend/access.py) except the
three session routes; a change needs its own permission on top -- Manage the
Home page, Run sync, Manage users & groups. The shared Admin sign-in
(backend/admin_auth.py) holds all of them while it still exists. The overview
is a single call on purpose. The alternative — the page fanning
out to /api/debug/backend, /api/auth/me, /api/consensus/oauth/status,
/api/taxonomy and the repository — would have spread an admin view across
five endpoints with five different audiences, some of them public. One
endpoint keeps "what an admin may see" in one place, where it can be read.

Nothing here writes to SharePoint. The sync buttons on the page call
/api/graph/sync and /api/consensus/sync (Run sync); approving a metadata
proposal needs Edit metadata, which the shared sign-in never has.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from backend import access
from backend.access import ADMIN_SESSION_PERMS, Perm
from backend.admin_auth import (
    clear_session, has_admin_session, issue_session, require_perm, verify_password,
)
from backend import auto_sync
from backend.auth import security_warnings
from backend.config import settings
from backend.deps import get_repo
from backend.integrations.consensus_oauth import get_oauth
from backend.repositories.base import AssetQuery, AssetRepository

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

#: Every Admin page call needs the page itself; a change needs its own
#: permission on top (backend/access.py).
VIEW_ADMIN = Depends(require_perm(Perm.VIEW_ADMIN))


class LoginIn(BaseModel):
    username: str
    password: str


@router.get("/session")
def session_state(request: Request):
    """Whether this browser may open the Admin page, and how.

    Deliberately public: the page has to know which of three things to render
    (the form, the dashboard, or "no admin configured on this deployment")
    before it can authenticate, and none of those answers is a secret.
    `signed_in` is true for a signed-in person with View Admin, as well as
    for the shared Admin sign-in; `via` says which.
    """
    from backend.auth import principal_from_request
    user = principal_from_request(request)
    person = user.is_authenticated and user.can(Perm.VIEW_ADMIN)
    password = has_admin_session(request)
    return {
        "configured": settings.admin_configured,
        "signed_in": person or password,
        "via": "sso" if person else ("password" if password else None),
        "user": user.as_dict() if person else None,
        "permissions": sorted(user.permissions) if person else (
            sorted(ADMIN_SESSION_PERMS) if password else []),
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


def _sharepoint_libraries(repo: AssetRepository) -> list[dict]:
    """Everything one SharePoint sync indexes, one row each.

    The card showed the Demo Catalog alone: one library name, one count.
    The same sync has also read the VM pages (2026-09-23) and the "Demo
    Video" library (2026-09-30), each with a mirror of its own, so each gets
    its own row and count (Liwei, 2026-09-30). A further source is one more
    entry here. `ok` is that source's part of the last attempt (the Demo
    Catalog's own outcome is the card's "Last attempt").
    """
    from backend.integrations.graph.video_sync import SOURCE_SYSTEM as VIDEO
    from backend.integrations.graph.vm_pages import SOURCE_SYSTEM as VM_PAGES
    from backend.integrations.graph.demo_pages import SOURCE_SYSTEM as DEMO_PAGES
    last = (repo.sync_state("sharepoint") if hasattr(repo, "sync_state") else {}) or {}
    result = last.get("last_result") or {}
    count = getattr(repo, "count_source_rows", None)
    rows = [
        {"name": settings.graph_list_name, "source": "sharepoint", "summary_key": None},
        {"name": settings.graph_video_library, "source": VIDEO, "summary_key": "demo_video"},
        {"name": "Virtual Machines pages", "source": VM_PAGES, "summary_key": "vm_pages"},
        # 2026-10-05/06: the Demo Catalog's pages, and which demo folders
        # partners may download from. Both ride along with the same sync.
        {"name": "Demo Catalog pages", "source": DEMO_PAGES, "summary_key": "demo_pages",
         "unit": "pages"},
        {"name": "Partner downloads", "source": None, "summary_key": "partner_access"},
    ]
    out = []
    for r in rows:
        if not r["name"]:
            continue                      # switched off (e.g. GRAPH_VIDEO_LIBRARY blank)
        part = result.get(r["summary_key"]) if r["summary_key"] else None
        entry = {"name": r["name"], "source": r["source"],
                 "assets": count(r["source"]) if count and r["source"] else None,
                 "unit": r.get("unit", "assets"),
                 "ok": part.get("ok") if isinstance(part, dict) else None,
                 "error": part.get("error") if isinstance(part, dict) else None}
        if r["summary_key"] == "partner_access":
            access = repo.partner_access() if hasattr(repo, "partner_access") else {}
            closed = sum(1 for v in access.values() if v)
            entry["text"] = (f"{closed} of {len(access)} folders closed to partners"
                             if access else "not checked yet")
        out.append(entry)
    return out


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


@router.get("/overview", dependencies=[VIEW_ADMIN])
def overview(repo: AssetRepository = Depends(get_repo)):
    """One payload, in the order the page reads it."""
    oauth = get_oauth()
    oauth_status = oauth.status()

    assets = repo.list(AssetQuery(limit=10 ** 6, include_older_vms=True)).items
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
                "libraries": _sharepoint_libraries(repo),
            },
            "consensus": {
                "v1_configured": settings.consensus_configured,
                "v2_configured": settings.consensus_v2_configured,
                "v2_authorised": oauth_status.get("authorised"),
                # Which route V2 can actually authenticate by, if any. Without
                # this the page reported "not configured" on any deployment
                # using CONSENSUS_V2_TOKEN, because `consensus_v2_configured`
                # only ever asked about the OAuth pair -- so the Azure slots,
                # where the hand-supplied token is the only route available
                # before SSO, looked broken while syncing perfectly well.
                "v2_route": ("oauth" if oauth_status.get("authorised")
                             else "token" if settings.consensus_v2_token
                             else None),
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
        # No "usage" block: it served the first version of this page, which
        # read per-asset counters. Usage now comes from the event log via
        # /api/admin/usage, and leaving the old shape here meant scanning
        # every asset on each overview load to build something no caller
        # read. Removed 2026-09-22.
        "proposals": {"pending": _pending_proposals(repo)},
        "requests": {"unsynced": _unsynced_requests(repo)},
        "auto_sync": _auto_sync_view(),
    }


# ───────────────────────────────────────────────────────── the daily sync
class AutoSyncIn(BaseModel):
    enabled: bool
    #: The two daily run hours (UTC), one switch for both (Liwei, 2026-09-30).
    hours_utc: list[int] | None = Field(default=None, min_length=1,
                                        max_length=auto_sync.RUNS_PER_DAY)
    #: The single hour an older page sends; sets the first run only.
    hour_utc: int | None = Field(default=None, ge=0, le=23)


def _auto_sync_view() -> dict:
    state = auto_sync.load_state()
    upcoming = auto_sync.next_slot(state)
    return {
        "enabled": state["enabled"],
        "hours_utc": state["hours_utc"],
        "hour_utc": state["hours_utc"][0],
        "changed_by": state.get("changed_by"),
        "changed_at": state.get("changed_at"),
        "next_run_at": upcoming.isoformat(timespec="seconds") if upcoming else None,
        "last_run": state.get("last_run"),
        # Whether the loop runs in this process at all. False only in tests
        # and scripts -- but if it ever reads False on Azure, the switch
        # would be a switch connected to nothing, and the page should say so.
        "scheduler_running": settings.auto_sync_scheduler,
    }


@router.put("/auto-sync", dependencies=[VIEW_ADMIN])
def set_auto_sync(body: AutoSyncIn, actor: str = Depends(require_perm(Perm.RUN_SYNC))):
    """Switch the daily sync on or off, and choose its hour (UTC).

    The same permission as the sync buttons (Run sync): the schedule does
    nothing a button press could not, it only presses it daily.
    """
    if body.hours_utc is not None and any(not 0 <= h <= 23 for h in body.hours_utc):
        raise HTTPException(status_code=422, detail="each hour must be 0-23")
    hours = body.hours_utc if body.hours_utc is not None else (
        body.hour_utc if body.hour_utc is not None else auto_sync.load_state()["hours_utc"])
    auto_sync.configure(body.enabled, hours, actor)
    return _auto_sync_view()


@router.get("/content", dependencies=[VIEW_ADMIN])
def content_summary(repo: AssetRepository = Depends(get_repo)):
    """The content dashboard (HLR-F1), counted over what the Hub lists."""
    from backend.services import content_dashboard
    return content_dashboard.summary(repo)


@router.get("/content/assets", dependencies=[VIEW_ADMIN])
def content_assets(dim: str, value: str, repo: AssetRepository = Depends(get_repo)):
    """The assets behind one bar of the content dashboard."""
    from backend.services import content_dashboard
    try:
        return content_dashboard.assets_in(repo, dim, value)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"no dimension {dim!r}")


class HideIn(BaseModel):
    asset_id: str


@router.get("/hidden", dependencies=[VIEW_ADMIN])
def list_hidden(repo: AssetRepository = Depends(get_repo)):
    try:
        return repo.hidden()
    except NotImplementedError:
        raise HTTPException(status_code=501, detail="needs the file-backed catalogue")


@router.post("/hidden", dependencies=[VIEW_ADMIN])
def hide_demo(body: HideIn, repo: AssetRepository = Depends(get_repo),
              actor: str = Depends(require_perm(Perm.MANAGE_HOME))):
    """Hide a demo from the Hub -- every list, search and page -- without
    touching SharePoint or Consensus. Manage the Home page, on the Admin page
    (Liwei, 2026-10-06: never the curator key alone)."""
    try:
        items = repo.hide(body.asset_id, actor)
    except KeyError:
        raise HTTPException(status_code=422, detail=f"no listed demo with id {body.asset_id!r}")
    except NotImplementedError:
        raise HTTPException(status_code=501, detail="needs the file-backed catalogue")
    log.info("demo hidden from the Hub by %s: %s", actor, body.asset_id)
    return items


@router.delete("/hidden/{asset_id}", dependencies=[VIEW_ADMIN])
def unhide_demo(asset_id: str, repo: AssetRepository = Depends(get_repo),
                actor: str = Depends(require_perm(Perm.MANAGE_HOME))):
    try:
        items = repo.unhide(asset_id)
    except NotImplementedError:
        raise HTTPException(status_code=501, detail="needs the file-backed catalogue")
    log.info("demo unhidden by %s: %s", actor, asset_id)
    return items


class HubSettingsIn(BaseModel):
    #: Links from the Hub to a demo's SharePoint page ("Demo page" and "Open
    #: demo page"). Off by default: whether to expose SharePoint is not yet
    #: agreed (Liwei, 2026-10-05).
    show_demo_page_links: bool | None = None
    #: Demos known only from their SharePoint page (no project folder) listed
    #: in the Hub at all. On by default.
    show_page_only_demos: bool | None = None


@router.get("/hub-settings", dependencies=[VIEW_ADMIN])
def get_hub_settings(repo: AssetRepository = Depends(get_repo)):
    try:
        return repo.hub_settings()
    except NotImplementedError:
        raise HTTPException(status_code=501, detail="needs the file-backed catalogue")


@router.put("/hub-settings", dependencies=[VIEW_ADMIN])
def set_hub_settings(body: HubSettingsIn, actor: str = Depends(require_perm(Perm.MANAGE_HOME)),
                     repo: AssetRepository = Depends(get_repo)):
    try:
        values = body.model_dump(exclude_none=True)
        if not values:
            raise HTTPException(status_code=422, detail="nothing to change")
        state = repo.set_hub_settings(actor, **values)
        log.info("hub settings by %s: %s", actor, body.model_dump())
        return state
    except NotImplementedError:
        raise HTTPException(status_code=501, detail="needs the file-backed catalogue")


#: Home shows every promoted asset; past a dozen it stops being a shortlist.
MAX_PROMOTED = 12


class PromotedIn(BaseModel):
    asset_ids: list[str] = Field(max_length=MAX_PROMOTED)


def _promoted_view(repo: AssetRepository) -> dict:
    from backend.routers.assets import promoted_summaries   # local: router cycle
    state = repo.promoted()
    return {**state, "max": MAX_PROMOTED,
            "assets": [a.model_dump(mode="json") for a in promoted_summaries(repo)]}


@router.get("/promoted", dependencies=[VIEW_ADMIN])
def get_promoted(repo: AssetRepository = Depends(get_repo)):
    try:
        return _promoted_view(repo)
    except NotImplementedError:
        raise HTTPException(status_code=501, detail="needs the file-backed catalogue")


@router.put("/promoted", dependencies=[VIEW_ADMIN])
def set_promoted(body: PromotedIn, actor: str = Depends(require_perm(Perm.MANAGE_HOME)),
                 repo: AssetRepository = Depends(get_repo)):
    """Choose what the Home page features, and in which order (Seb, via
    Liwei 2026-10-01). Manage the Home page: this edits a Portal-owned list,
    never SharePoint."""
    unknown = [i for i in body.asset_ids if repo.get(i) is None]
    if unknown:
        raise HTTPException(status_code=422, detail=f"no asset with id {unknown[0]!r}")
    try:
        repo.set_promoted(body.asset_ids, actor)
        log.info("home promotions set by %s: %s", actor, body.asset_ids)
        return _promoted_view(repo)
    except NotImplementedError:
        raise HTTPException(status_code=501, detail="needs the file-backed catalogue")


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


@router.get("/usage", dependencies=[VIEW_ADMIN])
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


@router.get("/usage/asset/{asset_id}", dependencies=[VIEW_ADMIN])
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


@router.get("/source/{source}", dependencies=[VIEW_ADMIN])
def source_detail(source: str, repo: AssetRepository = Depends(get_repo)):
    """One source's own page: how its syncs have gone.

    Consensus's own play counts are deliberately not here (Liwei, 2026-09-22).
    They were tried on the main usage view, moved here, and are now nowhere:
    this sheet answers "is the sync working", and a tally Consensus keeps on
    its own platform, about its own audience, is not an answer to that. It
    shared a panel with sync history only because both happened to be about
    the same source.

    The figures still exist per asset as `external_views`, so putting them
    somewhere they belong is a UI decision, not a re-integration.
    """
    runs = getattr(repo, "sync_runs", lambda **_: [])(source_system=source, limit=30)
    payload = {
        "source": source,
        "state": _source_state(repo, source),
        "runs": runs,
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


@router.get("/usage/breakdown", dependencies=[VIEW_ADMIN])
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


@router.get("/usage/untouched", dependencies=[VIEW_ADMIN])
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
    for asset in repo.list(AssetQuery(limit=10 ** 6, include_older_vms=True)).items:
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


# ──────────────────────────────────────────────────────── content access
@router.get("/content-access", dependencies=[VIEW_ADMIN])
def get_content_access(repo: AssetRepository = Depends(get_repo)):
    """Every Internal demo and why (2026-10-07). Changes go through
    PUT /api/assets/{id}/access, which the detail page uses too."""
    try:
        return repo.content_access()
    except NotImplementedError:
        raise HTTPException(status_code=501, detail="needs the file-backed catalogue")


# ────────────────────────────────────────────────────────── users & groups
MANAGE_USERS = require_perm(Perm.MANAGE_USERS)


class GroupIn(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=300)
    permissions: list[str] | None = None
    members: list[str] | None = Field(default=None, max_length=500)


def _access_view() -> dict:
    return {
        "catalogue": access.catalogue(),
        "groups": access.load_state()["groups"],
        "bootstrap_admins": sorted(access._bootstrap_admins()),
        "users": access.users_view(),
        "audit": access.audit_log(100),
    }


@router.get("/access", dependencies=[VIEW_ADMIN])
def get_access():
    """Groups, their permissions and members, who has signed in, and the
    audit log -- the Users & groups tab in one call."""
    return _access_view()


@router.post("/access/groups", dependencies=[VIEW_ADMIN], status_code=201)
def create_group(body: GroupIn, actor: str = Depends(MANAGE_USERS)):
    try:
        access.create_group(body.name or "", body.description or "",
                            body.permissions or [], body.members or [], actor)
    except access.AccessError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _access_view()


@router.put("/access/groups/{group_id}", dependencies=[VIEW_ADMIN])
def update_group(group_id: str, body: GroupIn, actor: str = Depends(MANAGE_USERS)):
    try:
        access.update_group(group_id, actor, **body.model_dump(exclude_none=True))
    except KeyError:
        raise HTTPException(status_code=404, detail=f"no group {group_id!r}")
    except access.AccessError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _access_view()


@router.delete("/access/groups/{group_id}", dependencies=[VIEW_ADMIN])
def delete_group(group_id: str, actor: str = Depends(MANAGE_USERS)):
    try:
        access.delete_group(group_id, actor)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"no group {group_id!r}")
    except access.AccessError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _access_view()


# ─────────────────────────────────────────────────────────────── sign-ins
@router.get("/activity", dependencies=[VIEW_ADMIN])
def get_activity(since: str | None = None, until: str | None = None,
                 today: str | None = None, q: str | None = None, user: str | None = None,
                 offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500)):
    """The Sign-ins tab: who is active now, sign-ins in a window, and the log
    (backend/activity.py). Bounds come from the browser, as for /usage."""
    from backend import activity
    return activity.report(since=since, until=until, today=today, q=q, user=user,
                           offset=offset, limit=limit)

