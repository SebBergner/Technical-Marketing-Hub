"""Who am I, and is access control actually switched on."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.auth import AuthMode, CurrentUser, get_current_user, security_warnings
from backend.config import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/me")
def me(user: CurrentUser = Depends(get_current_user)):
    """The caller's identity and roles, plus any misconfiguration.

    `warnings` is the important field: it is non-empty when access control is
    weaker than it looks — most importantly when this is running on App Service
    with AUTH_MODE unset, which makes every caller a curator.
    """
    return {
        "user": user.as_dict(),
        "mode": settings.auth_mode,
        "enforcing": settings.auth_mode == AuthMode.EASYAUTH.value,
        "curator_groups_configured": bool(settings.auth_curator_groups),
        "warnings": security_warnings(),
    }
