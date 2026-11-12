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
from pydantic import BaseModel, Field

from backend.access import Perm
from backend.auth import CurrentUser, require_authenticated
from backend.config import settings
from backend.deps import get_repo
from backend.repositories.base import AssetRepository
from backend.services import my_hub
from backend.services import playlists as pl

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


class NoteIn(BaseModel):
    text: str = Field(max_length=2000)


@router.post("/requests/{request_id}/notes")
def add_request_note(request_id: str, body: NoteIn,
                     user: CurrentUser = Depends(require_authenticated)):
    """Add a note to one's own request (Liwei, 2026-11-12). What was asked
    is not changed once sent; a note adds to it, dated and signed, in the
    Notes column the team reads. Not after Delivered or Declined."""
    from datetime import date
    from backend.integrations.graph.client import get_graph_client
    from backend.integrations.graph.requests_list import (
        CLOSED_STATUSES, NOTE_MAX, RequestWriteError, append_note)
    if user.is_partner:
        raise HTTPException(status_code=403, detail="Requests are for PTC employees.")
    text = " ".join((body.text or "").split())
    if len(text) < 3:
        raise HTTPException(status_code=422, detail="Write the note first.")
    if len(text) > NOTE_MAX:
        raise HTTPException(status_code=422, detail=f"At most {NOTE_MAX} characters.")
    me = (user.email or "").strip().lower()
    _requests_cache.clear()                     # the status now, not two minutes ago
    rows = _all_requests()
    if rows is None:
        raise HTTPException(status_code=503,
                            detail="The team's list cannot be reached just now; try again later.")
    row = next((r for r in rows if r["request_id"] == request_id and me
                and r["requester"] == me), None)
    if row is None:
        raise HTTPException(status_code=404, detail="No such request of yours.")
    if row["status"] in CLOSED_STATUSES:
        raise HTTPException(status_code=409,
                            detail=f"This request is {row['status']}; it takes no more notes.")
    who = user.name if user.name and "@" not in user.name else me
    note = f"[{date.today().isoformat()}, {who}] {text}"
    client = get_graph_client()
    try:
        site = client.resolve_site(settings.graph_site_url)
        notes = append_note(client, site.site_id, row["item_id"], note)
    except RequestWriteError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    _requests_cache.clear()
    log.info("note added to request %s by its requester", request_id)
    return {"request_id": request_id, "notes": notes}


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


# ───────────────────────────────────────────────────── playlists (phase 2)

class PlaylistIn(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    #: Create: the demos to start with. Update: the same demos, reordered.
    items: list[str] | None = Field(default=None, max_length=pl.MAX_ITEMS)


def _owner_name(user: CurrentUser) -> str | None:
    """Shown on a shared playlist: a PTC person's display name; a partner's
    never, and never an address (some sign-ins give the address as the name)."""
    name = (user.name or "").strip()
    return None if user.is_partner or not name or "@" in name else name


def _brief(record: dict, repo: AssetRepository) -> dict:
    """A playlist on My Hub and in the Save menu: its name, how many demos,
    and the first few to draw its cover."""
    summaries = getattr(repo, "summaries", None)
    visible = summaries(record["items"]) if summaries else []
    return {"id": record["id"], "name": record["name"], "count": len(visible),
            "items": record["items"], "updated_at": record.get("updated_at"),
            # Enough of each demo for its card's cover, picture or product mark.
            "covers": [{"id": a.id, "thumbnail_url": a.thumbnail_url, "type": a.type,
                        "title": a.title, "products": a.products,
                        "product_families": a.product_families}
                       for a in visible[:4]]}


def _refuse(exc: Exception):
    if isinstance(exc, KeyError):
        raise HTTPException(status_code=404, detail="No such playlist.")
    if isinstance(exc, PermissionError):
        raise HTTPException(status_code=403, detail=str(exc))
    raise HTTPException(status_code=422, detail=str(exc))


@router.get("/playlists")
def my_playlists(user: CurrentUser = Depends(require_authenticated),
                 repo: AssetRepository = Depends(get_repo)):
    return {"items": [_brief(r, repo) for r in pl.mine(_key(user))]}


@router.post("/playlists", status_code=201)
def create_playlist(body: PlaylistIn, user: CurrentUser = Depends(require_authenticated),
                    repo: AssetRepository = Depends(get_repo)):
    items = [i for i in (body.items or []) if repo.get(i) is not None]
    try:
        record = pl.create(_key(user), body.name or "", _owner_name(user), items)
    except pl.PlaylistError as exc:
        _refuse(exc)
    return _brief(record, repo)


@router.get("/playlists/{playlist_id}")
def open_playlist(playlist_id: str, user: CurrentUser = Depends(require_authenticated),
                  repo: AssetRepository = Depends(get_repo)):
    """Anyone signed in, by its link: the demos this person may open, in
    order, and how many others it holds."""
    record = pl.get(playlist_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No such playlist.")
    summaries = getattr(repo, "summaries", None)
    visible = summaries(record["items"]) if summaries else []
    is_mine = record["owner"] == pl.owner_digest(_key(user))
    return {"id": record["id"], "name": record["name"], "mine": is_mine,
            "owner_name": None if is_mine else record.get("owner_name"),
            "updated_at": record.get("updated_at"),
            "items": [a.model_dump(mode="json") for a in visible],
            "unavailable": len(record["items"]) - len(visible)}


@router.patch("/playlists/{playlist_id}")
def change_playlist(playlist_id: str, body: PlaylistIn,
                    user: CurrentUser = Depends(require_authenticated),
                    repo: AssetRepository = Depends(get_repo)):
    try:
        record = pl.update(_key(user), playlist_id, name=body.name, items=body.items)
    except (KeyError, PermissionError, pl.PlaylistError) as exc:
        _refuse(exc)
    return _brief(record, repo)


@router.put("/playlists/{playlist_id}/items/{asset_id}")
def add_to_playlist(playlist_id: str, asset_id: str,
                    user: CurrentUser = Depends(require_authenticated),
                    repo: AssetRepository = Depends(get_repo)):
    if repo.get(asset_id) is None:
        raise HTTPException(status_code=404, detail=f"no asset with id '{asset_id}'")
    try:
        record = pl.set_item(_key(user), playlist_id, asset_id, True)
    except (KeyError, PermissionError, pl.PlaylistError) as exc:
        _refuse(exc)
    return _brief(record, repo)


@router.delete("/playlists/{playlist_id}/items/{asset_id}")
def remove_from_playlist(playlist_id: str, asset_id: str,
                         user: CurrentUser = Depends(require_authenticated),
                         repo: AssetRepository = Depends(get_repo)):
    try:
        record = pl.set_item(_key(user), playlist_id, asset_id, False)
    except (KeyError, PermissionError, pl.PlaylistError) as exc:
        _refuse(exc)
    return _brief(record, repo)


@router.delete("/playlists/{playlist_id}", status_code=204)
def delete_playlist(playlist_id: str, user: CurrentUser = Depends(require_authenticated)):
    try:
        pl.delete(_key(user), playlist_id)
    except (KeyError, PermissionError) as exc:
        _refuse(exc)


@router.post("/playlists/{playlist_id}/copy", status_code=201)
def copy_playlist(playlist_id: str, user: CurrentUser = Depends(require_authenticated),
                  repo: AssetRepository = Depends(get_repo)):
    """Save a copy of a shared playlist as one's own: only the demos this
    person can open, under the same name."""
    record = pl.get(playlist_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No such playlist.")
    summaries = getattr(repo, "summaries", None)
    visible = [a.id for a in summaries(record["items"])] if summaries else []
    try:
        copy = pl.create(_key(user), record["name"], _owner_name(user), visible)
    except pl.PlaylistError as exc:
        _refuse(exc)
    return _brief(copy, repo)
