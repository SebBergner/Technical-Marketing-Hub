"""The one door to what VM pages say that only a signed-in person may see.

Everything else about a VM travels on the ordinary asset detail. The sealed
part -- passwords, admin tables, login sections -- is stored apart from it
(mirror/private/, see backend/integrations/graph/vm_pages.py) and served only
here, to someone who has actually signed in.

"Actually" is the point of `_require_person`. The ordinary
`require_authenticated` also lets the local development principal through,
which is right for a laptop. On App Service it would mean that one wrong
setting -- AUTH_MODE left at `disabled` -- publishes every password in the
catalogue to anyone with the URL. security_warnings() would shout about that
setting, but a warning is not a guard, so this door checks for itself.
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, HTTPException

from backend.auth import APP_SERVICE_MARKER, CurrentUser, get_current_user
from backend.deps import get_repo
from backend.models import AssetType
from backend.repositories.base import AssetRepository

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/vms", tags=["vms"])


async def _require_person(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.is_authenticated:
        return user
    if user.is_dev_principal and not os.environ.get(APP_SERVICE_MARKER):
        return user
    raise HTTPException(status_code=401, detail="Sign in to see login details.")


@router.get("/{asset_id}/credentials")
def credentials(asset_id: str, repo: AssetRepository = Depends(get_repo),
                user: CurrentUser = Depends(_require_person)):
    """The sealed sections and blocks of one VM page, keyed as the public
    record's placeholders are: `sections[section_id]` for a whole sealed
    section, `blocks["section_id:index"]` for a single sealed block."""
    asset = repo.get(asset_id)
    if asset is None or asset.type != AssetType.VM:
        raise HTTPException(status_code=404)
    reader = getattr(repo, "vm_secrets", None)
    secrets = (reader(asset_id) if reader else None) or {}
    # Who looked, not what they saw: an audit line that stays useful without
    # itself becoming a copy of the secret.
    log.info("vm credentials viewed: %s by %s", asset_id, user.email or "dev")
    return {"sections": secrets.get("sections") or {},
            "blocks": secrets.get("blocks") or {}}
