"""The Customer Data Disclaimer pop-up (backend/disclaimer.py, Elio 2026-11-05)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from backend import disclaimer
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
