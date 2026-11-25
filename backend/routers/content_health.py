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
    from backend.services import consensus_overrides as co
    empty, no_product, no_segment, archives = [], [], [], []
    consensus_no_product, consensus_differs = [], []
    for r in records.values():
        if r.get("source") == "consensus":
            # Set on the Hub, since the Hub never writes to Consensus
            # (consensus_overrides.py, 2026-11-18).
            if not r.get("products"):
                consensus_no_product.append(_row(r, library="Consensus"))
            if diffs := co.differences(r):
                consensus_differs.append(_row(r, library="Consensus", differences=diffs))
            continue
        if r.get("source") != "sharepoint":
            continue            # the page sources are edited where they live
        # A VM is a machine to book, and a demo known only from its SharePoint
        # page has no folder (demo_pages.py): neither is ever "empty".
        library = _library(r.get("id") or "")
        if not r.get("resource_count") and r.get("type") != "vm"                 and library != "Demo page":
            empty.append(_row(r))
        # GXC videos are not asked for one (Liwei, 2026-11-25): the IoT/AR rows
        # keep Product empty on purpose (2026-11-02), and they made
        # production's count 335 where 87 could be fixed.
        if not r.get("products") and not r.get("gxc") \
                and not (r.get("id") or "").startswith("gxc-"):
            no_product.append(_row(r))
        # A CAD dataset has no Segment column (sync.py), so it is never asked for one.
        if not r.get("segment") and r.get("type") != "cad_model":
            no_segment.append(_row(r))
        if dupes := _same_name_archives(r):
            archives.append(_row(r, files=dupes))
    for rows in (empty, no_product, no_segment, archives,
                 consensus_no_product, consensus_differs):
        rows.sort(key=lambda x: (x["title"] or "").lower())
    skipped = sorted(health.get("skipped_folders") or [], key=lambda f: -(f.get("files") or 0))
    return {"read_at": health.get("read_at"),
            "skipped_folders": skipped,
            "loose_files": health.get("loose_files") or [],
            "empty": empty, "no_product": no_product, "no_segment": no_segment,
            "same_name_archives": archives,
            "consensus_no_product": consensus_no_product,
            "consensus_differs": consensus_differs}


# ─────────────────────────────────────────────── fix products, many at once
#: Where each kind of demo takes its product list from, and its label.
_FIX_LABELS = {"demo_catalog": "Demo Catalog", "demo_video": "Demo Video",
               "consensus": "Consensus"}
#: At most this many demos per save, so one request stays short.
MAX_FIX_ITEMS = 100


def _product_choices(rows: list[dict]) -> tuple[dict[str, list[str]], list[str]]:
    """{fix key: the products that library accepts}, and the keys whose list
    could not be read from SharePoint (then the catalogue's own products of
    that library stand in, and the save still checks against SharePoint)."""
    from backend.services import consensus_overrides as co
    out = {"consensus": co.choices(rows)["products"]}
    fallback = []
    for key in ("demo_catalog", "demo_video"):
        try:
            from backend.routers.uploads import _client, _target
            out[key] = list((_target(_client(), key).choices or {}).get("products") or [])
        except Exception as exc:                            # noqa: BLE001
            log.warning("Fix products: %s product list not read: %s", key, exc)
            prefix = "video-" if key == "demo_video" else None
            out[key] = sorted({p for r in rows for p in (r.get("products") or [])
                               if r.get("source") == "sharepoint"
                               and (r.get("id") or "").startswith("video-") == bool(prefix)})
            fallback.append(key)
    return out, fallback


def _fix_key(record: dict, where: str) -> str:
    if where == "consensus":
        return "consensus"
    return "demo_video" if (record.get("id") or "").startswith("video-") else "demo_catalog"


@router.get("/products")
def products_to_fix(repo: AssetRepository = Depends(get_repo)):
    """Content health -> Fix products: every demo with no product that the
    Hub can fill in, with a suggestion where its title or description names
    one (services/product_fix.py)."""
    from backend.services import product_fix as pf
    from backend.services import taxonomy
    records = repo.listed_records() if hasattr(repo, "listed_records") else {}
    rows = list(records.values())
    choices, fallback = _product_choices(rows)
    by_family = pf.family_segments(rows)
    out = []
    for r in rows:
        where = pf.needs_product(r)
        if not where:
            continue
        key = _fix_key(r, where)
        hint = pf.suggestion(r, choices.get(key) or [])
        segment = None if r.get("segment") else (
            pf.segment_for(hint["products"], by_family) if hint else None)
        out.append(_row(r, fix=key, library=_FIX_LABELS[key], suggested=hint,
                        suggested_segment=segment))
    rank = {"title": 0, "description": 1}
    out.sort(key=lambda x: (rank.get((x["suggested"] or {}).get("from"), 2),
                            (x["title"] or "").lower()))
    # {product: its family's segment}, so the page suggests the segment again
    # when a person changes the products (2026-11-25: changing Codebeamer AI
    # to Arbortext kept "ALM (suggested)").
    product_segments = {}
    for p in sorted({p for c in choices.values() for p in c}):
        segment = pf.segment_for([p], by_family)
        if segment:
            product_segments[p] = segment
    return {"rows": out, "choices": choices, "fallback": fallback,
            "libraries": _FIX_LABELS, "product_segments": product_segments,
            "segments": [s for s in taxonomy.SEGMENTS if s not in taxonomy.RETIRED_SEGMENTS]}


class FixItem(BaseModel):
    asset_id: str
    products: list[str]
    segment: str | None = None


class FixIn(BaseModel):
    items: list[FixItem]


@router.post("/products")
def fix_products(body: FixIn, repo: AssetRepository = Depends(get_repo),
                 actor: str = Depends(require_perm(Perm.MAINTAIN))):
    """Write each demo's product (and its segment, if it has none), one by
    one; a failure stops only its own demo. SharePoint demos are written to
    their folder as Edit does; Consensus demos are set on the Hub. Each
    result says what changed or why not."""
    from backend.integrations.graph.client import GraphError
    from backend.services import consensus_overrides as co
    from backend.services import metadata_edit as me
    from backend.services import product_fix as pf
    from backend.services import upload_targets as ut
    if not body.items or len(body.items) > MAX_FIX_ITEMS:
        raise HTTPException(status_code=422,
                            detail=f"Send between 1 and {MAX_FIX_ITEMS} demos at a time.")
    records = repo.listed_records() if hasattr(repo, "listed_records") else {}
    mirror = repo._load_mirror() if hasattr(repo, "_load_mirror") else list(records.values())
    client, targets, wrote, results = None, {}, False, []
    for item in body.items:
        result = {"asset_id": item.asset_id, "ok": False}
        results.append(result)
        record = records.get(item.asset_id)
        products = [p.strip() for p in item.products if p and p.strip()]
        where = pf.needs_product(record) if record else None
        if record is None:
            result["error"] = "Not a listed demo."
            continue
        if record.get("products"):
            result["error"] = "It has a product already; change it with Edit on its page."
            continue
        if where is None:
            result["error"] = "This demo's product is not set here."
            continue
        if not products:
            result["error"] = "Choose at least one product."
            continue
        segment = item.segment if item.segment and not record.get("segment") else None
        try:
            if where == "consensus":
                values = {"products": products}
                if segment:
                    values["segment"] = segment
                changed = co.save(repo, record, values, actor, mirror)
            else:
                from backend.routers.uploads import _client, _target
                key = me.target_key(record)
                client = client or _client()
                target = targets.get(key) or targets.setdefault(key, _target(client, key))
                folder = record["source_item_id"]
                current = me.values_of(target.spec, (client.get_list_item(
                    target.drive_id, folder) or {}).get("fields") or {})
                if current.get("products"):
                    result["error"] = ("SharePoint already has a product for it ("
                                       + ", ".join(current["products"])
                                       + "); the Hub shows it after the next sync.")
                    continue
                values = {"products": products}
                if segment and not current.get("segment"):
                    values["segment"] = [segment]
                changed = me.changes(target.spec, target, values, current)
                if changed:
                    me.write(client, target, folder, changed, None)
                    me.remember(repo, item.asset_id, me.hub_values(key, changed))
                    wrote = True
                changed = sorted(changed)
        except (ut.UploadInvalid, co.OverrideInvalid, me.EditConflict, me.NotEditable) as exc:
            result["error"] = str(exc)
            continue
        except GraphError as exc:
            result["error"] = f"SharePoint: {exc}"
            continue
        result.update(ok=True, changed=list(changed))
    if wrote:
        from backend.routers.uploads import _sync_soon
        _sync_soon(repo, actor)
    done = sum(1 for r in results if r["ok"])
    log.info("Fix products by %s: %d of %d saved", actor, done, len(results))
    return {"saved": done, "results": results}


# ───────────────────────────────────────────────────────────── searches
@router.get("/searches")
def searches(days: int | None = Query(None, ge=1, le=3650),
             repo: AssetRepository = Depends(get_repo)):
    """Content health -> Searches: what people search for, what they do not
    find, and what is rising, in the last `days` (none: all time) and
    against the days before. Worked out ahead of time, every day at 04:00 in
    Boston, or when someone presses Refresh (services/search_insights_store.py),
    never on a page load. `pending` until the first time; `refresh` says
    whether Refresh may be pressed. Counts of people, never who."""
    from backend.services import search_insights_store as store
    state = store.load()
    gxc = bool(getattr(repo, "gxc", True))
    answer = (state.get("results") or {}).get(store.period_key(days, gxc))
    out = dict(answer) if answer else {"pending": True}
    out["computed_at"] = state.get("computed_at") if answer else None
    out["refresh"] = store.refresh_view(state)
    return out


@router.post("/searches/refresh", status_code=202)
def refresh_searches(actor: str = Depends(require_perm(Perm.MAINTAIN))):
    """Work Searches out again now, in the background. Then not again, by
    anyone, for an hour; 429 says until when."""
    from backend.services import search_insights_store as store
    try:
        return store.request_refresh(actor)
    except store.Cooldown as exc:
        raise HTTPException(status_code=429, detail=f"Refresh is {exc}.")


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
