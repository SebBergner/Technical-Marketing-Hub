"""Developer inspection endpoints.

Backs static/debug.html. Read-only and deliberately separate from the product
UI, which lives in index.html.
"""
from __future__ import annotations

import os

from fastapi import APIRouter

from backend.auth import AuthMode, security_warnings
from backend.config import BASE_DIR, settings

router = APIRouter(prefix="/api/debug", tags=["debug"])


@router.get("/backend")
def backend_info():
    """Which storage and integrations are actually live right now.

    Worth surfacing: the difference between the JSON store and SQL, or between
    the Consensus stub and the real client, is invisible from the data alone
    and has caused confusion before.
    """
    data_dir = settings.data_dir
    return {
        "storage_backend": settings.storage_backend,
        "data_dir": data_dir,
        "data_dir_exists": os.path.isdir(data_dir),
        "consensus_configured": settings.consensus_configured,
        "graph_configured": settings.graph_configured,
        "seed_path_exists": os.path.exists(settings.seed_path),
        #: App Service local disk does not survive a redeploy, and anything
        #: under owned/ is irreplaceable. Data living inside the repo is
        #: therefore NOT durable — it must be moved to a mounted volume before
        #: real users submit anything.
        "storage_is_durable": not os.path.abspath(data_dir).startswith(
            os.path.abspath(BASE_DIR)
        ),
        "auth_mode": settings.auth_mode,
        "auth_enforcing": settings.auth_mode == AuthMode.EASYAUTH.value,
        #: Non-empty means access control is weaker than it looks.
        "security_warnings": security_warnings(),
    }
