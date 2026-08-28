"""Asset catalogue endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.deps import get_repo
from backend.models import Asset, AssetSummary, Page
from backend.repositories.base import AssetRepository, AssetQuery

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
        sources=source, product_families=family, tags=tag,
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
