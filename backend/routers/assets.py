"""Asset catalogue endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from backend.config import settings
from backend.deps import CurrentUser, get_current_user, get_repo
from backend.integrations.graph.client import GraphClient, GraphError
from backend.models import AdvancedSearchHit, Asset, AssetSummary, Page, video_type_filter
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
    include_older_vms: bool = Query(
        default=False,
        description="also list VMs a newer version of the same VM supersedes"),
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
        industries=industry, value_drivers=driver, languages=language, content_depths=video_type_filter(depth),
        sources=source, product_families=family,
        umbrella_families=umbrella, tags=tag,
        customer_facing=customer_facing, has_narrated_audio=has_narrated_audio,
        has_consensus_uuid=has_consensus_uuid, rail=rail, editor_picks_only=editor_picks,
        include_older_vms=include_older_vms,
        sort=sort, limit=limit, offset=offset,
    ))


def promoted_summaries(repo: AssetRepository) -> list[AssetSummary]:
    """The promoted assets, in their order, through `get()` -- the same
    funnel as a details page, so a divested or removed asset simply drops
    out instead of showing as a broken card."""
    out = []
    for asset_id in repo.promoted()["asset_ids"]:
        asset = repo.get(asset_id)
        if asset is not None:
            out.append(AssetSummary.model_validate(
                asset.model_dump(include=set(AssetSummary.model_fields))))
    return out


@router.get("/promoted", response_model=list[AssetSummary])
def promoted(repo: AssetRepository = Depends(get_repo)):
    """What the Home page features, in the order chosen on the Admin page.
    Declared before `/{asset_id}`, like advanced-search."""
    try:
        return promoted_summaries(repo)
    except NotImplementedError:
        raise HTTPException(status_code=501, detail="needs the file-backed catalogue")


@router.get("/advanced-search", response_model=Page[AdvancedSearchHit])
def advanced_search(
    q: str = Query(min_length=2, description="every term must be in the demo's "
                   "title, details (description, tags, products...) or a file name"),
    type: list[str] = Query(default=[]),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    repo: AssetRepository = Depends(get_repo),
    user: CurrentUser = Depends(get_current_user),
):
    """Advanced Search: the ordinary search plus the names of every listed
    file in each demo's folder (Liwei, 2026-09-30). One row per demo, with
    the files that matched. Declared before `/{asset_id}`, which would
    otherwise take "advanced-search" for an id."""
    try:
        page = repo.advanced_search(AssetQuery(text=q, types=type, limit=limit, offset=offset))
    except NotImplementedError:
        raise HTTPException(status_code=501,
                            detail="Advanced Search needs the file-backed catalogue")
    if user.is_partner:
        page.items = [h.model_copy(update={"files": _without_file_ids(h.files)})
                      if _locked_for(user, h.asset) else h for h in page.items]
    return page


def _locked_for(user: CurrentUser, asset) -> bool:
    """A partner on a demo whose SharePoint folder is closed to partners."""
    return bool(getattr(asset, "partner_restricted", False)) and user.is_partner


def _without_file_ids(resources: list) -> list:
    """The files, listed by name, without the ids that open or download them."""
    return [r.model_copy(update={"item_id": None}) for r in resources]


@router.get("/{asset_id}", response_model=Asset)
def get_asset(asset_id: str, repo: AssetRepository = Depends(get_repo),
              user: CurrentUser = Depends(get_current_user)):
    asset = repo.get(asset_id)
    if asset is None:
        if repo.is_hidden(asset_id):
            raise HTTPException(status_code=404, detail="This demo is hidden from the Hub.")
        raise HTTPException(status_code=404, detail=f"no asset with id '{asset_id}'")
    if _locked_for(user, asset):
        asset = asset.model_copy(update={"resources": _without_file_ids(asset.resources),
                                         "files_locked": True})
    return asset


def _file_facts(repo: AssetRepository, asset_id: str, item_id: str) -> dict:
    """The name and kind behind an item id, for the event log.

    Resolved from the asset we have already loaded rather than from Graph:
    `_require_listed_file` has just proved the file is listed on this asset,
    so the answer is in memory and costs nothing. A file that somehow is not
    found still records the event, with the id alone — a download that
    happened is worth logging even when its label is not available.
    """
    asset = repo.get(asset_id)
    for resource in (asset.resources if asset else []):
        if resource.item_id == item_id:
            return {"item_id": item_id, "file": resource.name, "kind": resource.kind}
    return {"item_id": item_id}


def _record(repo: AssetRepository, event: str, asset_id: str | None = None, **fields) -> None:
    """Best-effort usage event. A repository without the method (SQL) or a
    disk hiccup must never turn a working page or download into a 500 — the
    counter exists to inform, not to gate."""
    recorder = getattr(repo, "record_usage_event", None)
    if recorder is None:
        return
    try:
        recorder(event, asset_id=asset_id, **fields)
    except Exception:                                    # noqa: BLE001
        log.warning("could not record a %s event", event, exc_info=True)


class SearchEventIn(BaseModel):
    q: str
    results: int


@router.post("/search-event", status_code=204)
def record_search(body: SearchEventIn, repo: AssetRepository = Depends(get_repo)):
    """What someone searched for, and how many results they got.

    Posted by the page once typing settles, NOT derived from the /api/assets
    calls that back the search box: those fire per keystroke, so the log would
    fill with "w", "wi", "win" and the one real query would be buried in its
    own prefixes.

    The zero-result ones are the point (Liwei, 2026-09-21). "People keep
    searching for X and we have nothing" is the most direct evidence there is
    for what to commission next, and it cannot be recovered afterwards.
    """
    query = (body.q or "").strip()
    if not query:
        return
    _record(repo, "search", None, q=query[:120], results=max(0, body.results))


@router.post("/{asset_id}/view", status_code=204)
def record_view(asset_id: str, repo: AssetRepository = Depends(get_repo)):
    """Fire-and-forget from the preview page."""
    if repo.get(asset_id) is None:
        raise HTTPException(status_code=404, detail=f"no asset with id '{asset_id}'")
    _record(repo, "view", asset_id)


def _require_partner_access(asset_id: str, repo: AssetRepository, user: CurrentUser) -> None:
    """Partners may not open or download a file from a demo whose SharePoint
    folder is closed to the partner group (2026-10-06)."""
    asset = repo.get(asset_id)
    if asset is not None and _locked_for(user, asset):
        raise HTTPException(status_code=403,
                            detail="These files are not available to your account.")


def _require_listed_file(asset_id: str, item_id: str, repo: AssetRepository) -> None:
    """Both file endpoints below need this same check: `item_id` must belong
    to a resource actually listed on this asset. Graph would happily resolve
    any valid item id in the drive regardless of which asset it is nominally
    under, so without this an asset's detail page would double as a way to
    fetch any file in the whole Demo Catalog by id -- not a secret today,
    since the catalogue is public read, but a needless widening of what these
    endpoints are for."""
    asset = repo.get(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"no asset with id '{asset_id}'")
    if not any(r.item_id == item_id for r in asset.resources):
        raise HTTPException(
            status_code=404,
            detail=f"'{item_id}' is not a file listed on asset '{asset_id}'")


def _asset_drive(client: GraphClient, asset_id: str):
    """The library this asset's files are in.

    A file's item id only resolves in its own drive. Demo Video assets
    (backend/integrations/graph/video_sync.py, ids "video-...") live in that
    library; everything else here is the Demo Catalog. Asking the Demo
    Catalog for a Demo Video file returned nothing, so download and preview
    failed on every migrated video (Liwei, 2026-09-30).
    """
    from backend.integrations.graph.video_sync import ID_PREFIX
    library = (settings.graph_video_library if asset_id.startswith(ID_PREFIX)
               and settings.graph_video_library else settings.graph_list_name)
    site = client.resolve_site()
    drive = client.find_drive(site.site_id, library)
    if drive is None:
        raise HTTPException(
            status_code=502,
            detail=f"no drive named {library!r} on {site.web_url}")
    return drive


@router.get("/{asset_id}/files/{item_id}/download")
def download_file(asset_id: str, item_id: str,
                  repo: AssetRepository = Depends(get_repo),
                  client: GraphClient = Depends(require_client),
                  user: CurrentUser = Depends(get_current_user)):
    """A file inside a SharePoint asset's folder, resolved and handed off.

    Redirects to Graph's pre-authenticated download URL rather than proxying
    the bytes -- the same choice already made for video preview
    (`GraphClient.download_url`'s own docstring: "resolve it at play time,
    never at list time"). That URL expires in about an hour, so it is never
    stored; this endpoint exists only to mint one on demand.
    """
    _require_listed_file(asset_id, item_id, repo)
    _require_partner_access(asset_id, repo, user)
    try:
        drive = _asset_drive(client, asset_id)
        url = client.download_url(drive.drive_id, item_id)
    except GraphError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not url:
        raise HTTPException(
            status_code=502,
            detail="SharePoint did not return a download link for this file")

    # Recorded here rather than at the top: a Graph failure above is not a
    # download, and counting before the work would inflate the figure with
    # every error. What this measures is "a download link was handed out" --
    # the redirect means we never learn whether the bytes arrived, so it is a
    # floor on real downloads, not an exact count.
    #
    # The file's own name and kind travel with the event (2026-09-21, Liwei:
    # "点击下载的又是什么"). An asset-level counter could say a kit was
    # downloaded forty times and never say whether people took the talk track
    # or the .mp4 -- which is the part that tells you what to make more of.
    _record(repo, "download", asset_id, **_file_facts(repo, asset_id, item_id))
    return RedirectResponse(url, status_code=302)


@router.get("/{asset_id}/files/{item_id}/preview")
def preview_file(asset_id: str, item_id: str,
                 repo: AssetRepository = Depends(get_repo),
                 client: GraphClient = Depends(require_client),
                 user: CurrentUser = Depends(get_current_user)):
    """An embeddable viewer for a file, so it can be looked at before deciding
    to download it.

    Same shape as download_file() above, and the same reason to resolve it
    fresh rather than cache it -- see GraphClient.preview()'s own docstring.
    One endpoint for every kind: video, Word, PowerPoint and (untested but
    presumably) PDF and images all resolve through the same Graph call.
    """
    _require_listed_file(asset_id, item_id, repo)
    _require_partner_access(asset_id, repo, user)
    try:
        drive = _asset_drive(client, asset_id)
        url = client.preview(drive.drive_id, item_id)
    except GraphError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not url:
        raise HTTPException(
            status_code=502,
            detail="SharePoint did not return a preview link for this file")

    # Liwei's call, 2026-09-21: a preview is the stronger signal of the two.
    # Plenty of people watch a walkthrough and never download anything, and
    # without this they are indistinguishable from people who opened the page
    # and left.
    _record(repo, "preview", asset_id, **_file_facts(repo, asset_id, item_id))
    return RedirectResponse(url, status_code=302)
