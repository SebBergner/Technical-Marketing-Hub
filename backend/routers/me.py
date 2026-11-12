"""My Hub (A3; Liwei, 2026-11-12): what is the signed-in person's own.

Favourites and recently viewed (services/my_hub.py), and the person's own
New Asset Inquiries with the status the team gives them in SharePoint's
Demo Requests list. My feedback and My demos have their own endpoints
already (/api/support/reports/mine, /api/uploads?mine=true); the page
calls those.

Nothing here takes a person as a parameter: every answer is about the
caller, and there is no way to ask about anyone else.
"""
from __future__ import annotations

import logging
import threading
import time

from fastapi import APIRouter, Depends, HTTPException

from backend.access import Perm
from backend.auth import CurrentUser, require_authenticated
from backend.config import settings
from backend.deps import get_repo
from backend.repositories.base import AssetRepository
from backend.services import my_hub

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/me", tags=["me"])

#: The Demo Requests list, read whole at most this often per worker.
REQUESTS_CACHE_SECONDS = 120
_requests_cache: dict[str, tuple[float, list[dict]]] = {}
_requests_lock = threading.Lock()


def _key(user: CurrentUser) -> str:
    key = my_hub.user_key(user)
    if key is None:
        raise HTTPException(status_code=401, detail="Sign-in required.")
    return key


@router.get("/favorites")
def favorite_ids(user: CurrentUser = Depends(require_authenticated)):
    """The ids only, for the stars on every card."""
    return {"ids": my_hub.favorites(_key(user))}


@router.put("/favorites/{asset_id}")
def add_favorite(asset_id: str, user: CurrentUser = Depends(require_authenticated),
                 repo: AssetRepository = Depends(get_repo)):
    if repo.get(asset_id) is None:
        raise HTTPException(status_code=404, detail=f"no asset with id '{asset_id}'")
    return {"ids": my_hub.set_favorite(_key(user), asset_id, True)}


@router.delete("/favorites/{asset_id}")
def remove_favorite(asset_id: str, user: CurrentUser = Depends(require_authenticated)):
    return {"ids": my_hub.set_favorite(_key(user), asset_id, False)}


@router.get("")
def my_hub_page(user: CurrentUser = Depends(require_authenticated),
                repo: AssetRepository = Depends(get_repo)):
    """The page's demo rows: favourites and recently viewed, as cards, only
    the ones this person can still open; and which other sections to show."""
    key = _key(user)
    summaries = getattr(repo, "summaries", None)
    favorites = summaries(my_hub.favorites(key)) if summaries else []
    seen = my_hub.recent(key)
    recent = summaries([r["id"] for r in seen]) if summaries else []
    when = {r["id"]: r["at"] for r in seen}
    return {"favorites": [f.model_dump(mode="json") for f in favorites],
            "recent": [dict(r.model_dump(mode="json"), viewed_at=when.get(r.id))
                       for r in recent],
            "sections": {"requests": not user.is_partner,
                         "demos": user.can(Perm.UPLOAD.value)}}


def _all_requests() -> list[dict] | None:
    """The Demo Requests list, from a short cache; None if it cannot be read."""
    from backend.integrations.graph.client import get_graph_client
    from backend.integrations.graph.requests_list import read_requests
    with _requests_lock:
        hit = _requests_cache.get("rows")
        if hit and time.monotonic() - hit[0] < REQUESTS_CACHE_SECONDS:
            return hit[1]
    client = get_graph_client()
    if client is None:
        return None
    try:
        site = client.resolve_site(settings.graph_site_url)
        rows = read_requests(client, site.site_id)
    except Exception:                                      # noqa: BLE001
        log.warning("could not read Demo Requests", exc_info=True)
        return None
    with _requests_lock:
        _requests_cache["rows"] = (time.monotonic(), rows)
    return rows


@router.get("/requests")
def my_requests(user: CurrentUser = Depends(require_authenticated),
                repo: AssetRepository = Depends(get_repo)):
    """The caller's New Asset Inquiries, newest first, with the status the
    team set in SharePoint and, once Delivered, what was delivered. Matched
    by the Requester column, which the form fills with the signed-in
    address -- so it holds on either slot, and a row the team entered by
    hand for this person shows too. A request still waiting to reach
    SharePoint (an outage) is listed from this slot's own record."""
    if user.is_partner:
        return {"items": [], "readable": True}
    me = (user.email or "").strip().lower()
    rows = _all_requests()
    items = [r for r in (rows or []) if me and r["requester"] == me]
    listed = {r["request_id"] for r in items}
    for local in (getattr(repo, "unsynced_requests", lambda: [])() or []):
        if (local.requester_email or "").lower() == me and local.id not in listed:
            items.append({"request_id": local.id, "title": None, "status": "Not sent yet",
                          "asset_type": local.asset_type, "products": "; ".join(local.products),
                          "brief": local.brief, "delivered": None,
                          "created_at": local.submitted_at.isoformat(), "item_id": None})
    for r in items:
        r.pop("requester", None)
    items.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return {"items": items, "readable": rows is not None}
