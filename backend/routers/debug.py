"""Developer inspection endpoints.

Backs static/debug.html. Read-only and deliberately separate from the product
UI, which lives in index.html.
"""
from __future__ import annotations

import os

from fastapi import APIRouter

from backend.config import settings

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
        #: App Service local disk does not survive a redeploy. Anything under
        #: owned/ is irreplaceable, so this flag matters operationally.
        "storage_is_durable": not data_dir.startswith(
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
        ),
    }
