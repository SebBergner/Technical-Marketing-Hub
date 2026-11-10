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


@welcome_router.get("/video")
def guide_video(user: CurrentUser = Depends(require_authenticated),
                client: GraphClient = Depends(require_client)):
    """The Hub's training video at the top of the user guide (Liwei, 2026-11-10).

    The newest video file in `settings.guide_video_folder` of the Demo Video
    library, as a signed URL the <video> plays and seeks on. Anyone signed in
    may watch it. It is not a demo, so it is not counted in usage. 404 when
    the folder or a video in it is missing, 502 when Graph fails."""
    try:
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
        newest = max(videos, key=lambda c: c.get("lastModifiedDateTime") or "")
        url = client.download_url(drive.drive_id, newest["id"])
    except GraphError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not url:
        raise HTTPException(status_code=502,
                            detail="SharePoint did not return a link for the video")
    return RedirectResponse(url, status_code=302)
