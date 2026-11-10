"""The Customer Data Disclaimer pop-up (backend/disclaimer.py, Elio 2026-11-05)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse

from backend import disclaimer, welcome
from backend.auth import CurrentUser, get_current_user, require_authenticated
from backend.config import settings
from backend.integrations.graph.client import GraphClient, GraphError
from backend.routers.graph import require_client

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/disclaimer", tags=["disclaimer"])


@router.get("")
def disclaimer_status(user: CurrentUser = Depends(get_current_user)):
    """Whether this person must accept now, and the words to show."""
    return disclaimer.status(user)


@router.post("/accept")
def accept_disclaimer(user: CurrentUser = Depends(get_current_user)):
    try:
        row = disclaimer.accept(user)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    log.info("disclaimer %s accepted by %s", disclaimer.VERSION, row["key"])
    return {"accepted_at": row["accepted_at"], "version": row["version"]}


# ── the welcome pop-up that follows it (backend/welcome.py, Liwei 2026-11-08)
welcome_router = APIRouter(prefix="/api/welcome", tags=["disclaimer"])


@welcome_router.get("")
def welcome_status(user: CurrentUser = Depends(get_current_user)):
    """Whether to show the welcome (or what is new) to this person."""
    return welcome.status(user)


@welcome_router.post("/seen")
def welcome_seen(user: CurrentUser = Depends(get_current_user)):
    try:
        row = welcome.seen(user)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return row


def _guide_video(client: GraphClient) -> tuple[str, dict]:
    """The drive id and item of the training video: the newest video file in
    `settings.guide_video_folder` of the Demo Video library. 404 when the
    folder or a video in it is missing; GraphError is the caller's."""
    site = client.resolve_site()
    drive = client.find_drive(site.site_id, settings.graph_video_library)
    if drive is None:
        raise HTTPException(status_code=404, detail="No training video yet")
    folder = next((c for c in client.list_children(drive.drive_id)
                   if "folder" in c and c.get("name") == settings.guide_video_folder),
                  None)
    videos = [] if folder is None else [
        c for c in client.list_children(drive.drive_id, folder["id"])
        if ((c.get("file") or {}).get("mimeType") or "").startswith("video/")]
    if not videos:
        raise HTTPException(status_code=404, detail="No training video yet")
    return drive.drive_id, max(videos, key=lambda c: c.get("lastModifiedDateTime") or "")


@welcome_router.get("/video")
def guide_video(user: CurrentUser = Depends(require_authenticated),
                client: GraphClient = Depends(require_client)):
    """The Hub's training video at the top of the user guide (Liwei, 2026-11-10).

    A signed URL the <video> plays and seeks on. Anyone signed in may watch
    it. It is not a demo, so it is not counted in usage. 404 when there is no
    video, 502 when Graph fails."""
    try:
        drive_id, item = _guide_video(client)
        url = client.download_url(drive_id, item["id"])
    except GraphError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not url:
        raise HTTPException(status_code=502,
                            detail="SharePoint did not return a link for the video")
    return RedirectResponse(url, status_code=302)


@welcome_router.get("/video/info")
def guide_video_info(user: CurrentUser = Depends(require_authenticated),
                     client: GraphClient = Depends(require_client)):
    """What the guide's video card shows before play: the length, from
    SharePoint's video facet (None when it has not read it yet)."""
    try:
        _, item = _guide_video(client)
    except GraphError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    ms = (item.get("video") or {}).get("duration")
    return {"duration_seconds": round(ms / 1000) if ms else None}


@welcome_router.get("/video/poster")
def guide_video_poster(user: CurrentUser = Depends(require_authenticated),
                       client: GraphClient = Depends(require_client)):
    """The card's cover: SharePoint's own still of the video (its large
    thumbnail, 800 px wide). 404 when there is none; the card then keeps its
    plain background."""
    try:
        drive_id, item = _guide_video(client)
        thumbs = client.thumbnails(drive_id, item["id"])
    except GraphError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    url = next((s.get("url") for t in thumbs for s in [t.get("large") or {}] if s.get("url")),
               None)
    if not url:
        raise HTTPException(status_code=404, detail="No cover for the training video")
    return RedirectResponse(url, status_code=302)
