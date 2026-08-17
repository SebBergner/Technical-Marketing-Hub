"""FastAPI dependencies."""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header

from backend.config import settings
from backend.repositories.base import AssetRepository
from backend.repositories.json_repo import JsonAssetRepository


def build_repo() -> AssetRepository:
    """Pick the storage backend from config.

    "json" is the default: SharePoint stays the system of record and the Portal
    keeps only a server-side index, so there is no database to provision.
    "sql" is retained and tested for when the catalogue outgrows files.
    """
    if settings.storage_backend == "sql":
        from backend.db import SessionLocal
        from backend.repositories.sql_repo import SqlAssetRepository
        return SqlAssetRepository(SessionLocal())
    return JsonAssetRepository(settings.data_dir)


def get_repo() -> AssetRepository:
    return build_repo()


@dataclass
class CurrentUser:
    email: str | None
    name: str | None
    is_authenticated: bool

    @property
    def can_curate(self) -> bool:
        """Placeholder. Becomes an Entra ID group check when roles are defined."""
        return self.is_authenticated


async def get_current_user(
    x_ms_client_principal_name: str | None = Header(default=None),
    x_ms_client_principal_id: str | None = Header(default=None),
) -> CurrentUser:
    """Stub, shaped for App Service Easy Auth.

    Easy Auth injects `X-MS-CLIENT-PRINCIPAL-*` headers once Entra ID sign-in is
    switched on, so enabling authentication becomes configuration rather than a
    refactor — every endpoint already depends on this.

    Until then it resolves to an anonymous user. Note the ordering constraint
    from the architecture doc: this must be real *before* any SharePoint
    write-back path ships.
    """
    if x_ms_client_principal_name:
        return CurrentUser(
            email=x_ms_client_principal_name,
            name=x_ms_client_principal_name,
            is_authenticated=True,
        )
    return CurrentUser(email=None, name=None, is_authenticated=False)
