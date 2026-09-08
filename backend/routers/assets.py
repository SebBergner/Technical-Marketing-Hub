"""Asset catalogue endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse

from backend.config import settings
from backend.deps import get_repo
from backend.integrations.graph.client import GraphClient, GraphError
from backend.models import Asset, AssetSummary, Page
from backend.repositories.base import AssetRepository, AssetQuery
from backend.routers.graph import require_client

router = APIRouter(prefix="/api/assets", tags=["assets"])


@router.get("", response_model=Page[AssetSummary])
def list_assets(
    q: str | None = Query(default=None, description="free text over title and description"),
    type: list[str] = Query(default=[]),
    product: list[str] = Query(default=[]),
    stage: list[str] = Query(default=[]),
    segment: list[str] = Query(default=[]),
    industry: list[str] = Query(default=[]),
    driver: list[str] = Query(default=[]),
    language: list[str] = Query(default=[]),
    depth: list[str] = Query(default=[]),
    source: list[str] = Query(default=[], description="sharepoint | consensus"),
    tag: list[str] = Query(default=[], description="Consensus's own labels, verbatim"),
    family: list[str] = Query(
        default=[],
        description="product family — the only product filter that reaches every "
                    "platform. SharePoint records the specific module "
                    "('Windchill PDMLink'), Consensus the brand ('Windchill')."),
    umbrella: list[str] = Query(
        default=[],
        description="umbrella product family — the eight the navigation browses "
                    "by, decided by the team rather than derived. An asset can "
                    "be in none of them and still be searchable."),
    customer_facing: bool | None = None,
    has_narrated_audio: bool | None = None,
    has_consensus_uuid: bool | None = None,
    rail: str | None = None,
    editor_picks: bool = False,
    sort: str = Query(
        default="relevance", pattern="^(relevance|recent|most_viewed|title)$",
        description="relevance ranks title matches above description matches and "
                    "opening matches above buried ones; with no search text it "
                    "is identical to recent"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    repo: AssetRepository = Depends(get_repo),
):
    return repo.list(AssetQuery(
        text=q, types=type, products=product, funnel_stages=stage, segments=segment,
        industries=industry, value_drivers=driver, languages=language, content_depths=depth,
        sources=source, product_families=family,
        umbrella_families=umbrella, tags=tag,
        customer_facing=customer_facing, has_narrated_audio=has_narrated_audio,
        has_consensus_uuid=has_consensus_uuid, rail=rail, editor_picks_only=editor_picks,
        sort=sort, limit=limit, offset=offset,
    ))


@router.get("/{asset_id}", response_model=Asset)
def get_asset(asset_id: str, repo: AssetRepository = Depends(get_repo)):
    asset = repo.get(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"no asset with id '{asset_id}'")
    return asset


@router.post("/{asset_id}/view", status_code=204)
def record_view(asset_id: str, repo: AssetRepository = Depends(get_repo)):
    """Fire-and-forget from the preview page."""
    if repo.get(asset_id) is None:
        raise HTTPException(status_code=404, detail=f"no asset with id '{asset_id}'")
    repo.increment_stat(asset_id, "views")


@router.get("/{asset_id}/files/{item_id}/download")
def download_file(asset_id: str, item_id: str,
                  repo: AssetRepository = Depends(get_repo),
                  client: GraphClient = Depends(require_client)):
    """A file inside a SharePoint asset's folder, resolved and handed off.

    Redirects to Graph's pre-authenticated download URL rather than proxying
    the bytes -- the same choice already made for video preview
    (`GraphClient.download_url`'s own docstring: "resolve it at play time,
    never at list time"). That URL expires in about an hour, so it is never
    stored; this endpoint exists only to mint one on demand.

    `item_id` must belong to a resource actually listed on this asset. Graph
    would happily resolve any valid item id in the drive regardless of which
    asset it is nominally under, so without this check an asset's detail page
    would double as a way to fetch any file in the whole Demo Catalog by id --
    not a secret today, since the catalogue is public read, but a needless
    widening of what one endpoint is for.
    """
    asset = repo.get(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"no asset with id '{asset_id}'")
    if not any(r.item_id == item_id for r in asset.resources):
        raise HTTPException(
            status_code=404,
            detail=f"'{item_id}' is not a file listed on asset '{asset_id}'")

    try:
        site = client.resolve_site()
        drive = client.find_drive(site.site_id, settings.graph_list_name)
        if drive is None:
            raise HTTPException(
                status_code=502,
                detail=f"no drive named {settings.graph_list_name!r} on {site.web_url}")
        url = client.download_url(drive.drive_id, item_id)
    except GraphError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not url:
        raise HTTPException(
            status_code=502,
            detail="SharePoint did not return a download link for this file")
    return RedirectResponse(url, status_code=302)
