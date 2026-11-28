"""FastAPI dependencies."""
from __future__ import annotations

from fastapi import Depends

from backend.config import settings
from backend.repositories.base import AssetRepository
from backend.repositories.json_repo import JsonAssetRepository


# Identity lives in backend.auth so there is exactly one place that decides
# whether a request is authenticated and what it may do. Re-exported here
# because every router already imports its dependencies from this module.
from backend.auth import (            # noqa: E402,F401
    ANONYMOUS, CurrentUser, Role, get_current_user, require_authenticated,
    require_curator, security_warnings,
)


def build_repo(gxc: bool = True, gxc_granted: frozenset[str] = frozenset()) -> AssetRepository:
    """The catalogue, file-backed: SharePoint stays the system of record and
    the Portal keeps only a server-side index, so there is no database to
    provision. (A second, SQL-backed repository was removed on 2026-11-28:
    never used in production and a quarter the size of this one. The
    PostgreSQL plan swaps the storage primitives underneath instead.)

    `gxc`: whether GXC videos exist for the caller. The Hub's own jobs see
    everything; a request sees what its person may (get_repo).
    `gxc_granted`: without `gxc`, the GXC videos a personal link opened for
    them (backend/gxc_shares.py).
    """
    return JsonAssetRepository(settings.data_dir, gxc=gxc, gxc_granted=gxc_granted)


def get_repo(user: CurrentUser = Depends(get_current_user)) -> AssetRepository:
    """The catalogue as this person may see it: without GXC videos unless
    they have "Access GXC videos" (2026-10-29), except those a personal link
    granted them (B10, backend/gxc_shares.py), which open but are never
    listed. Every route reads through this, so the rule is kept in one place."""
    from backend import gxc_shares
    from backend.access import Perm
    if user.can(Perm.VIEW_GXC):
        return build_repo(gxc=True)
    granted = (gxc_shares.granted_ids(user.email) if gxc_shares.may_be_granted(user)
               else frozenset())
    return build_repo(gxc=False, gxc_granted=granted)
