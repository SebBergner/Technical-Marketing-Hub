"""The Customer Data Disclaimer pop-up (backend/disclaimer.py, Elio 2026-11-05)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from backend import disclaimer, welcome
from backend.auth import CurrentUser, get_current_user

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
