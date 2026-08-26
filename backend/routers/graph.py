"""Graph / SharePoint endpoints: diagnose access, then sync the catalogue."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from backend.config import settings
from backend.deps import CurrentUser, get_repo, require_authenticated, require_curator
from backend.integrations.graph.client import (
    GraphClient, GraphError, GraphPermissionError, get_graph_client,
)
from backend.integrations.graph.sync import SOURCE_SYSTEM, sync_catalogue
from backend.repositories.base import AssetRepository

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/graph", tags=["graph"])


def require_client() -> GraphClient:
    client = get_graph_client()
    if client is None:
        raise HTTPException(
            status_code=503,
            detail=("Microsoft Graph is not configured. Set GRAPH_TENANT_ID, "
                    "GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET and GRAPH_SITE_URL. "
                    "Pending the Entra ID app registration request to IT."),
        )
    return client


@router.get("/status")
def status():
    """Cheap, credential-free: is Graph wired up at all?"""
    return {
        "configured": settings.graph_configured,
        "site_url": settings.graph_site_url,
        "library": settings.graph_list_name,
        "source_system": SOURCE_SYSTEM,
    }


@router.get("/verify")
def verify(client: GraphClient = Depends(require_client),
           user: CurrentUser = Depends(require_authenticated)):
    """Run this FIRST when IT delivers credentials.

    Separates "bad credentials" from "missing per-site grant". Those two fail
    identically from the outside — a valid token plus 403 on everything — and
    telling them apart is the difference between a five-minute fix and a day
    spent debugging code that is not broken.
    """
    try:
        return client.verify_access()
    except GraphError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/sync")
def sync(full: bool = False, repo: AssetRepository = Depends(get_repo),
         client: GraphClient = Depends(require_client),
         user: CurrentUser = Depends(require_curator)):
    """Pull the Demo Catalog and replace the mirror. Requires the curator role.

    Portal-owned data — stable slugs, curation, the Value Roadmap index,
    counters — is untouched.
    """
    token = None if full else _load_token(repo)
    try:
        result = sync_catalogue(client, repo, delta_token=token)
    except GraphPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except GraphError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    _save_token(repo, result.delta_token)
    return result.as_dict()


# The delta cursor is Portal-owned state. It lives beside the other owned data
# rather than in the mirror, which sync is entitled to wipe.
def _load_token(repo: AssetRepository) -> str | None:
    getter = getattr(repo, "get_sync_token", None)
    return getter(SOURCE_SYSTEM) if getter else None


def _save_token(repo: AssetRepository, token: str | None) -> None:
    setter = getattr(repo, "set_sync_token", None)
    if setter and token:
        setter(SOURCE_SYSTEM, token)
