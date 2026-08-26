"""FastAPI dependencies."""
from __future__ import annotations

from fastapi import Depends

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


# Identity lives in backend.auth so there is exactly one place that decides
# whether a request is authenticated and what it may do. Re-exported here
# because every router already imports its dependencies from this module.
from backend.auth import (            # noqa: E402,F401
    ANONYMOUS, CurrentUser, Role, get_current_user, require_authenticated,
    require_curator, security_warnings,
)
