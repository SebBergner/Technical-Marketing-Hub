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


def _row(r: dict, **extra) -> dict:
    return {"asset_id": r.get("id"), "title": r.get("title"), "type": r.get("type"),
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
        # A VM is a machine to book, not files (vm_pages.py): never "empty".
        if not r.get("resource_count") and r.get("type") != "vm":
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
@router.get("/searches")
def searches(since: str | None = None, until: str | None = None,
             repo: AssetRepository = Depends(get_repo)):
    """What people searched for and found nothing or almost nothing, in a
    window -- the most direct evidence of what the catalogue is missing.
    Grouped by the words as typed, ignoring case and spacing; how many
    people searched for each, never who."""
    from backend.routers.admin import _events
    tally: dict[str, dict] = {}
    total = 0
    for e in _events(repo, since, until):
        if e.get("event") != "search":
            continue
        q = " ".join(str(e.get("q") or "").split())
        if not q:
            continue
        total += 1
        n = e.get("results") or 0
        row = tally.setdefault(q.lower(), {"q": q, "times": 0, "zero": 0, "few": 0,
                                           "people": set(), "last_at": "", "best": 0})
        row["times"] += 1
        if n == 0:
            row["zero"] += 1
        elif n <= FEW_RESULTS:
            row["few"] += 1
        row["best"] = max(row["best"], n)
        if e.get("user"):
            row["people"].add(e["user"])
        row["last_at"] = max(row["last_at"], e.get("at") or "")
    rows = []
    for row in tally.values():
        if row["zero"] + row["few"] == 0:
            continue
        rows.append({"q": row["q"], "times": row["times"], "zero_results": row["zero"],
                     "few_results": row["few"], "most_results": row["best"],
                     "people": len(row["people"]), "last_at": row["last_at"][:10] or None})
    rows.sort(key=lambda r: (-(r["zero_results"] + r["few_results"]), -r["people"], r["q"].lower()))
    return {"searches": total, "few_results_max": FEW_RESULTS, "rows": rows}


# ─────────────────────────────────────────────────────── content review
@router.get("/review")
def review(min_age_days: int | None = Query(None, ge=0), idle_days: int | None = Query(None, ge=1),
           repo: AssetRepository = Depends(get_repo)):
    from backend.routers import admin
    return admin.content_review(
        min_age_days=admin.REVIEW_MIN_AGE_DAYS if min_age_days is None else min_age_days,
        idle_days=admin.REVIEW_IDLE_DAYS if idle_days is None else idle_days, repo=repo)


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
