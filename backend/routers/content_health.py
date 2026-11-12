"""Content health: the content tools, out of the Admin page (Liwei, 2026-11-11).

Admin had grown too many tabs, and these are about the catalogue, not about
running the Hub. They are for the people who keep it -- Maintain content --
who until now could not open Admin at all. Four tabs on /content-health:

* Health check -- what in SharePoint keeps a demo out of the Hub or out of
  its right place: folders with no Demo Type, files loose at a library's
  root, demo folders with no files, demos with no product or segment, and
  two archives of the same name in one demo (`/checks`);
* Content review -- Admin -> Content review, moved (`/review`);
* Content access -- PTC Only demos, access requests and hidden demos, moved
  from Admin -> Content access; the GXC cards stay in Admin, because their
  switch is Manage users (`/access`, `/access-requests`, `/hidden`);
* Searches -- what people searched for and did not find (`/searches`), from
  Admin -> Hub usage, which keeps its "Most searched".

Content dashboard went with it: Hub -> Dashboard shows the same, better.
The Hub's own Content to review (#/review) is unchanged.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from backend.access import Perm
from backend.admin_auth import require_perm
from backend.deps import get_repo
from backend.repositories.base import AssetRepository

log = logging.getLogger(__name__)


#: Maintain content, as every action here already needed; also the shared
#: Admin sign-in, which holds every permission (admin_auth.require_perm).
MAINTAINER = Depends(require_perm(Perm.MAINTAIN))
router = APIRouter(prefix="/api/content-health", tags=["content-health"],
                   dependencies=[MAINTAINER])

#: The Admin log areas each tab's "Recent changes" may show -- and no others.
CHANGE_CATEGORIES = frozenset({"Content access", "Content review", "Uploads"})


# ─────────────────────────────────────────────────────────── health check
ARCHIVES = frozenset({"zip", "rar", "7z"})
#: A search with this many results or fewer is "few" (Searches tab).
FEW_RESULTS = 2


def _owner(r: dict) -> str | None:
    return r.get("demo_owner_name") or r.get("demo_owner") or r.get("creator")


def _library(asset_id: str) -> str:
    """Where a SharePoint demo lives, from its id's prefix (sync.py,
    video_sync.py, demo_pages.py, vm_pages.py)."""
    for prefix, name in (("gxc-", "GXC Video"), ("video-", "Demo Video"),
                         ("page-", "Demo page"), ("vm-", "Virtual machines")):
        if asset_id.startswith(prefix):
            return name
    return "Demo Catalog"


def _row(r: dict, **extra) -> dict:
    return {"asset_id": r.get("id"), "title": r.get("title"), "type": r.get("type"),
            "library": _library(r.get("id") or ""),
            "source": r.get("source"), "segment": r.get("segment"),
            "owner": _owner(r), "web_url": r.get("web_url"), **extra}


def _same_name_archives(r: dict) -> list[str]:
    """Archives in one folder of the demo that differ only in their
    extension: "Consumer Foot Bath.zip" and "Consumer Foot Bath.rar"."""
    seen: dict[tuple, set] = defaultdict(set)
    for res in r.get("resources") or []:
        ext = (res.get("extension") or "").lower()
        if ext in ARCHIVES:
            stem = re.sub(r"\.[^.]+$", "", res.get("name") or "").strip().lower()
            seen[(res.get("subfolder") or "", stem)].add(ext)
    return sorted(f"{stem}.{'/.'.join(sorted(exts))}" for (_, stem), exts in seen.items()
                  if len(exts) > 1)


@router.get("/checks")
def checks(repo: AssetRepository = Depends(get_repo)):
    """Each check: its rows, worst first where that means anything.

    The skipped folders and loose files come from the last full SharePoint
    sync of the Demo Catalog (`read_at`), which is the only thing that sees
    them; the rest from the demos the Hub lists now."""
    health = (repo.sync_state("sharepoint") if hasattr(repo, "sync_state") else {}) \
        .get("health") or {}
    records = repo.listed_records() if hasattr(repo, "listed_records") else {}
    empty, no_product, no_segment, archives = [], [], [], []
    for r in records.values():
        if r.get("source") != "sharepoint":
            continue            # Consensus and the page sources are edited where they live
        # A VM is a machine to book, and a demo known only from its SharePoint
        # page has no folder (demo_pages.py): neither is ever "empty".
        library = _library(r.get("id") or "")
        if not r.get("resource_count") and r.get("type") != "vm"                 and library != "Demo page":
            empty.append(_row(r))
        if not r.get("products"):
            no_product.append(_row(r))
        # A CAD dataset has no Segment column (sync.py), so it is never asked for one.
        if not r.get("segment") and r.get("type") != "cad_model":
            no_segment.append(_row(r))
        if dupes := _same_name_archives(r):
            archives.append(_row(r, files=dupes))
    for rows in (empty, no_product, no_segment, archives):
        rows.sort(key=lambda x: (x["title"] or "").lower())
    skipped = sorted(health.get("skipped_folders") or [], key=lambda f: -(f.get("files") or 0))
    return {"read_at": health.get("read_at"),
            "skipped_folders": skipped,
            "loose_files": health.get("loose_files") or [],
            "empty": empty, "no_product": no_product, "no_segment": no_segment,
            "same_name_archives": archives}


# ───────────────────────────────────────────────────────────── searches
#: A recorded search's filters: (query parameter, AssetQuery field, words).
_FILTERS = (("type", "types", "Type"), ("umbrella", "umbrella_families", "Product"),
            ("family", "product_families", "Product"), ("segment", "segments", "Segment"),
            ("stage", "funnel_stages", "Funnel stage"), ("language", "languages", "Language"),
            ("published", "published", "Published"), ("depth", "content_depths", "Video type"),
            ("tag", "tags", "Tag"), ("customer_facing", None, "Customer facing"),
            ("archived", None, "Archived"))
_TYPE_WORDS = {"video": "Video", "ldk": "LDK", "vdk": "VDK", "vm": "Virtual Machine",
               "cad_model": "CAD Dataset"}


def _filters_key(filters: dict | None) -> tuple:
    return tuple(sorted((k, tuple(sorted(v))) for k, v in (filters or {}).items() if v))


def _filters_words(key: tuple) -> str | None:
    """{"type": ["vm"], "family": ["Windchill"]} -> "Type: Virtual Machine ·
    Product: Windchill"; None for a plain search."""
    words = dict((k, w) for k, _, w in _FILTERS)
    parts = []
    for k, values in key:
        shown = [_TYPE_WORDS.get(v, v) if k == "type" else v for v in values]
        parts.append(f"{words.get(k, k)}: {', '.join(shown)}")
    return " · ".join(parts) or None


def _finds_now(repo: AssetRepository, q: str, key: tuple) -> int | None:
    """What the same words and filters find today."""
    from backend.repositories.base import AssetQuery
    from backend.models import video_type_filter
    query = AssetQuery(text=q, limit=1)
    fields = {k: f for k, f, _ in _FILTERS}
    for k, values in key:
        field_name = fields.get(k)
        if k == "customer_facing":
            query.customer_facing = values[0] == "true"
        elif k == "depth":
            query.content_depths = video_type_filter(list(values))
        elif field_name:
            setattr(query, field_name, list(values))
    try:
        counter = getattr(repo, "count", None)
        return counter(query) if counter else repo.list(query).total
    except Exception:                                      # noqa: BLE001
        return None


#: Searches, worked out once a day (Liwei, 2026-11-12: "no need for live
#: data"): {(days, gxc): (the day, the answer)}. Per worker, so each worker
#: works it out on its first request of the day; a few seconds each.
_daily: dict[tuple, tuple[str, dict]] = {}


@router.get("/searches")
def searches(days: int | None = Query(None, ge=1, le=3650),
             since: str | None = None, until: str | None = None,
             repo: AssetRepository = Depends(get_repo)):
    """Content health -> Searches (2026-11-12): what people search for,
    what they do not find, and what is rising, in the last `days` and
    against the days before -- worked out by services/search_insights.py,
    which says how. Counts of people, never who.

    By `days` (or none: all time), the answer is worked out on the first
    request of a UTC day and kept for the rest of it; `computed_at` says
    when. `since`/`until` ask for an exact window, worked out each time."""
    from datetime import datetime, timedelta, timezone
    from backend.services import search_insights as si
    from backend.services.usage import events as _events

    def when(value: str | None):
        if not value:
            return None
        try:
            d = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=422, detail=f"not a date: {value!r}")
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

    def work(start, end) -> dict:
        records = repo.listed_records().values() if hasattr(repo, "listed_records") else []
        out = si.insights(_events(repo), start, end,
                          finds_now=lambda q, key: _finds_now(repo, q, key),
                          vocab=si.vocabulary(records), filters_words=_filters_words)
        out["computed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return out

    if since or until:
        return work(when(since), when(until) or datetime.now(timezone.utc))
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    key = (days, bool(getattr(repo, "gxc", True)))
    hit = _daily.get(key)
    if hit and hit[0] == today:
        return hit[1]
    answer = work(now - timedelta(days=days) if days else None, now)
    _daily[key] = (today, answer)
    return answer


# ─────────────────────────────────────────────────────── content review
@router.get("/review")
def review(min_age_days: int | None = Query(None, ge=0), idle_days: int | None = Query(None, ge=1),
           repo: AssetRepository = Depends(get_repo)):
    from backend.services import content_review as cr
    return cr.content_review(
        repo, min_age_days=cr.REVIEW_MIN_AGE_DAYS if min_age_days is None else min_age_days,
        idle_days=cr.REVIEW_IDLE_DAYS if idle_days is None else idle_days)


# ─────────────────────────────────────────────────────── content access
@router.get("/access")
def content_access(repo: AssetRepository = Depends(get_repo)):
    """Every PTC Only demo and why (2026-10-07). Changes go through
    PUT /api/assets/{id}/access, which the detail page uses too."""
    try:
        return repo.content_access()
    except NotImplementedError:
        raise HTTPException(status_code=501, detail="needs the file-backed catalogue")


@router.get("/access-requests")
def access_requests(status: str | None = None, limit: int = Query(100, ge=1, le=500),
                    repo: AssetRepository = Depends(get_repo)):
    """Requests to make demos PTC Only or Open (2026-10-15), newest first;
    `status=pending` for the ones waiting."""
    from backend.services import access_requests as ar
    return ar.listing(repo, status=status, limit=limit)


class DecisionIn(BaseModel):
    approve: bool
    note: str | None = None


@router.post("/access-requests/{request_id}/decision")
def decide(request_id: str, body: DecisionIn, request: Request,
           repo: AssetRepository = Depends(get_repo),
           actor: str = Depends(require_perm(Perm.MAINTAIN))):
    """Approve -- which applies the change -- or reject, with a note."""
    from backend.services import access_requests as ar
    try:
        decided = ar.decide(repo, request_id, body.approve, actor, body.note)
    except LookupError:
        raise HTTPException(status_code=404, detail="no such request")
    except ar.RequestError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    # The Admin log names the demo, not the request's id.
    request.state.hub_target = decided["asset_id"]
    if body.approve:
        who = decided["requested_by"].split(":", 1)[-1]
        try:
            repo.set_access(decided["asset_id"], decided["level"], actor,
                            f"Requested by {who}: {decided['reason']}")
        except KeyError:
            raise HTTPException(status_code=404, detail="the demo is no longer listed")
    log.info("access request %s %s by %s", request_id, decided["status"], actor)
    return decided


class HideIn(BaseModel):
    asset_id: str


@router.get("/hidden")
def list_hidden(repo: AssetRepository = Depends(get_repo)):
    try:
        return repo.hidden()
    except NotImplementedError:
        raise HTTPException(status_code=501, detail="needs the file-backed catalogue")


@router.post("/hidden")
def hide(body: HideIn, repo: AssetRepository = Depends(get_repo),
         actor: str = Depends(require_perm(Perm.MAINTAIN))):
    """Hide a demo from the Hub -- every list, search and page -- without
    touching SharePoint or Consensus."""
    try:
        items = repo.hide(body.asset_id, actor)
    except KeyError:
        raise HTTPException(status_code=422, detail=f"no listed demo with id {body.asset_id!r}")
    except NotImplementedError:
        raise HTTPException(status_code=501, detail="needs the file-backed catalogue")
    log.info("demo hidden from the Hub by %s: %s", actor, body.asset_id)
    return items


@router.delete("/hidden/{asset_id}")
def unhide(asset_id: str, repo: AssetRepository = Depends(get_repo),
           actor: str = Depends(require_perm(Perm.MAINTAIN))):
    try:
        items = repo.unhide(asset_id)
    except NotImplementedError:
        raise HTTPException(status_code=501, detail="needs the file-backed catalogue")
    log.info("demo unhidden by %s: %s", actor, asset_id)
    return items


# ─────────────────────────────────────────────────────── recent changes
@router.get("/changes")
def changes(category: str = Query(..., description="comma-separated Admin log areas"),
            limit: int = Query(15, ge=1, le=100), repo: AssetRepository = Depends(get_repo)):
    """A tab's "Recent changes": the Admin log, only in the areas this page
    is about -- never sign-ins, groups or anyone's activity lookups."""
    from backend import admin_log
    wanted = [c.strip() for c in category.split(",") if c.strip()]
    if not wanted or any(c not in CHANGE_CATEGORIES for c in wanted):
        raise HTTPException(status_code=422, detail="not an area of this page")
    items: list[dict] = []
    for c in wanted:
        items += admin_log.read(gxc=getattr(repo, "gxc", True), category=c,
                                limit=limit)["items"]
    items.sort(key=lambda e: e.get("at") or "", reverse=True)
    return {"items": items[:limit]}
