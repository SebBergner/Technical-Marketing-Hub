"""Asset catalogue endpoints."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel

from backend.access import Perm
from backend.admin_auth import require_perm
from backend.config import settings
from backend.deps import CurrentUser, get_current_user, get_repo
from backend.integrations.graph.client import GraphClient, GraphError
from backend.models import AdvancedSearchHit, Asset, AssetSummary, Page, video_type_filter
from backend.repositories.base import AssetRepository, AssetQuery
from backend.routers.graph import require_client

log = logging.getLogger(__name__)

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
    published: list[str] = Query(
        default=[], description="age band (new | recent | aging | older) or a year "
                                "such as 2023; any one matches"),
    archived: bool = Query(default=False, description="also list archived demos "
                           "(only for 'See archived content'; ignored otherwise)"),
    customer_facing: bool | None = None,
    has_narrated_audio: bool | None = None,
    has_consensus_uuid: bool | None = None,
    rail: str | None = None,
    editor_picks: bool = False,
    include_older_vms: bool = Query(
        default=False,
        description="also list VMs a newer version of the same VM supersedes"),
    sort: str = Query(
        default="relevance",
        pattern="^(relevance|recent|oldest|most_viewed|title|type|product|segment|language)$",
        description="relevance ranks title matches above description matches and "
                    "opening matches above buried ones; with no search text it "
                    "is identical to recent. type, product, segment and language "
                    "are the table view's columns"),
    order: str | None = Query(
        default=None, pattern="^(asc|desc)$",
        description="for most_viewed, title, type, product, segment and language: "
                    "the direction (most_viewed defaults to desc, the rest to asc)"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    repo: AssetRepository = Depends(get_repo),
    user: CurrentUser = Depends(get_current_user),
):
    return repo.list(AssetQuery(
        include_archived=archived and user.can(Perm.VIEW_ARCHIVED),
        text=q, types=type, products=product, funnel_stages=stage, segments=segment,
        industries=industry, value_drivers=driver, languages=language, content_depths=video_type_filter(depth),
        sources=source, product_families=family,
        umbrella_families=umbrella, tags=tag, published=published,
        customer_facing=customer_facing, has_narrated_audio=has_narrated_audio,
        has_consensus_uuid=has_consensus_uuid, rail=rail, editor_picks_only=editor_picks,
        include_older_vms=include_older_vms,
        sort=sort, limit=limit, offset=offset,
        descending=(order == "desc") if order else sort == "most_viewed",
    ))


def promoted_summaries(repo: AssetRepository) -> list[AssetSummary]:
    """The promoted assets, in their order, through `get()` -- the same
    funnel as a details page, so a divested or removed asset simply drops
    out instead of showing as a broken card. An archived one too."""
    out = []
    for asset_id in repo.promoted()["asset_ids"]:
        asset = repo.get(asset_id)
        if asset is not None and not asset.archived:
            out.append(AssetSummary.model_validate(
                asset.model_dump(include=set(AssetSummary.model_fields))))
    return out


#: Every source the catalogue is built from (each sync's SOURCE_SYSTEM).
_SOURCES = ("sharepoint", "demo_video", "gxc_video", "demo_pages", "vm_pages", "consensus")


@router.get("/freshness")
def freshness(repo: AssetRepository = Depends(get_repo)):
    """When the catalogue last changed hands with its sources, and when it
    will next (Summit, 2026-10: say plainly that a SharePoint change shows
    up after the next sync, up to about twelve hours later).

    `updated_at`: the newest successful sync of any source, UTC. `hours_utc`:
    the daily runs, empty while the schedule is off."""
    from backend import auto_sync                       # local: no import cycle
    state = getattr(repo, "sync_state", None)
    stamps = [(state(s) or {}).get("last_success_at") for s in _SOURCES] if state else []
    schedule = auto_sync.load_state()
    return {"updated_at": max((t for t in stamps if t), default=None),
            "hours_utc": schedule["hours_utc"] if schedule.get("enabled") else []}


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
    page.items = [h.model_copy(update={"files": _without_file_ids(h.files)})
                  if _locked_for(user, h.asset) else h for h in page.items]
    return page


def _locked_for(user: CurrentUser, asset) -> bool:
    """Files listed by name only, without the ids that open them, for:

    * an Internal demo (2026-10-07) -- closed to partners in SharePoint, or
      marked on the Hub -- and somebody without "Access internal content".
      Partners lack it by default, which is the 2026-10-06 partner rule;
    * somebody whose groups allow neither Preview nor Download (2026-10-06).
    """
    if getattr(asset, "internal", False) and not user.can(Perm.INTERNAL):
        return True
    return ((user.is_authenticated or user.is_dev_principal)
            and not (user.can(Perm.PREVIEW) or user.can(Perm.DOWNLOAD)))


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
    if asset.archived and not user.can(Perm.VIEW_ARCHIVED):
        raise HTTPException(status_code=404, detail="This demo is archived.")
    # An upload not yet published: its uploader and reviewers only.
    if asset.upload_review and not user.can(Perm.REVIEW_CONTENT):
        from backend.services import uploads as _uploads
        record = _uploads.by_folder(repo, asset.source_item_id)
        if record is None or record["uploaded_by"].split(":", 1)[-1] != user.email:
            raise HTTPException(status_code=404, detail="This demo is waiting for review.")
    if _locked_for(user, asset):
        asset = asset.model_copy(update={"resources": _without_file_ids(asset.resources),
                                         "files_locked": True})
    if asset.gxc and not _gxc_downloads(repo):
        asset = asset.model_copy(update={"downloads_off": True})
    # Which values are only the Hub's inference: for the people who can fix
    # them (Edit metadata), not for visitors or partners (2026-10-28).
    if asset.assumed and not user.can(Perm.EDIT_METADATA):
        asset = asset.model_copy(update={"assumed": []})
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


def _who(user: CurrentUser | None) -> dict:
    """Who an event belongs to (meeting 2026-10-07): a PTC person by their
    PTC address -- they agree to activity tracking in their employment
    agreement -- and a partner only as "external", never who. Nothing for an
    anonymous caller or the local development principal."""
    if user is None or not user.is_authenticated:
        return {}
    if user.is_partner:
        return {"external": True}
    return {"user": (user.email or "").strip().lower() or None}


def _record(repo: AssetRepository, event: str, asset_id: str | None = None,
            user: CurrentUser | None = None, **fields) -> None:
    """Best-effort usage event. A repository without the method (SQL) or a
    disk hiccup must never turn a working page or download into a 500 — the
    counter exists to inform, not to gate."""
    recorder = getattr(repo, "record_usage_event", None)
    if recorder is None:
        return
    try:
        recorder(event, asset_id=asset_id, **fields, **_who(user))
    except Exception:                                    # noqa: BLE001
        log.warning("could not record a %s event", event, exc_info=True)


class SearchEventIn(BaseModel):
    q: str
    results: int


@router.post("/search-event", status_code=204)
def record_search(body: SearchEventIn, repo: AssetRepository = Depends(get_repo),
                  user: CurrentUser = Depends(get_current_user)):
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
    _record(repo, "search", None, user, q=query[:120], results=max(0, body.results))


@router.post("/{asset_id}/view", status_code=204)
def record_view(asset_id: str, repo: AssetRepository = Depends(get_repo),
                user: CurrentUser = Depends(get_current_user)):
    """Fire-and-forget from the preview page."""
    if repo.get(asset_id) is None:
        raise HTTPException(status_code=404, detail=f"no asset with id '{asset_id}'")
    _record(repo, "view", asset_id, user)


def _require_partner_access(asset_id: str, repo: AssetRepository, user: CurrentUser) -> None:
    """Nobody without "Access internal content" opens or downloads a file
    from an Internal demo -- which includes every demo whose SharePoint
    folder is closed to the partner group (2026-10-06/07)."""
    asset = repo.get(asset_id)
    if asset is not None and _locked_for(user, asset):
        raise HTTPException(status_code=403,
                            detail="These files are not available to your account.")


def _gxc_downloads(repo: AssetRepository) -> bool:
    """Admin's switch for GXC videos' downloads; off until switched on."""
    try:
        return bool(repo.hub_settings().get("gxc_downloads"))
    except NotImplementedError:
        return False


def _require_gxc_download(asset_id: str, repo: AssetRepository) -> None:
    """A GXC video downloads only while Admin allows it (Liwei, 2026-10-29).
    Previews still play: nobody pretends that stops a copy, it only takes
    away the button."""
    asset = repo.get(asset_id)
    if asset is not None and asset.gxc and not _gxc_downloads(repo):
        raise HTTPException(status_code=403,
                            detail="Downloads of GXC videos are switched off.")


def _require_perm(user: CurrentUser, perm: Perm) -> None:
    """Preview and Download are permissions of their own (backend/access.py).
    Only checked for somebody: an anonymous caller exists only where sign-in
    is not enforced, and is treated as before groups existed."""
    if (user.is_authenticated or user.is_dev_principal) and not user.can(perm):
        raise HTTPException(status_code=403,
                            detail="Your account does not have permission for this.")


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
    failed on every migrated video (Liwei, 2026-09-30). GXC Video's
    ("gxc-...", 2026-10-29) likewise.
    """
    from backend.integrations.graph.video_sync import library_of
    videos = library_of(asset_id)
    library = (videos.name if videos and videos.name else settings.graph_list_name)
    site = client.resolve_site()
    drive = client.find_drive(site.site_id, library)
    if drive is None:
        raise HTTPException(
            status_code=502,
            detail=f"no drive named {library!r} on {site.web_url}")
    return drive


@router.get("/{asset_id}/related")
def related(asset_id: str, limit: int = Query(default=6, ge=1, le=24),
            repo: AssetRepository = Depends(get_repo),
            user: CurrentUser = Depends(get_current_user)):
    """"You may also need" under a demo's page (A13, Summit; six, Liwei
    2026-10-28). The same demos anyone can list, so nothing to lock.

    `items`: picked by hand first (`picked`), then found. `not_related`:
    what was marked Not related on this page, so it can be let back -- only
    for someone with Edit metadata, who alone may change either."""
    try:
        items = repo.related(asset_id, limit)
        if items is None:
            raise HTTPException(status_code=404, detail="Asset not found")
        hidden = []
        if user.can(Perm.EDIT_METADATA):
            for other_id, mark in repo.not_related(asset_id).items():
                other = repo.get(other_id)
                if other is not None:
                    hidden.append({"id": other_id, "title": other.title, **mark})
    except NotImplementedError:
        raise HTTPException(status_code=501, detail="needs the file-backed catalogue")
    return {"items": [i.model_dump(mode="json") for i in items], "not_related": hidden}


# Picked by hand on a demo's page (Liwei, 2026-10-28): Edit metadata, no
# review, in the Admin log. A pick shows on both demos' pages; Not related
# keeps the scorer from offering a demo on this page only.
@router.put("/{asset_id}/related/{other_id}")
def add_related(asset_id: str, other_id: str, repo: AssetRepository = Depends(get_repo),
                actor: str = Depends(require_perm(Perm.EDIT_METADATA))):
    try:
        return {"picked": repo.add_related_pick(asset_id, other_id, actor)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"no asset with id '{exc.args[0]}'")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except NotImplementedError:
        raise HTTPException(status_code=501, detail="needs the file-backed catalogue")


@router.delete("/{asset_id}/related/{other_id}")
def remove_related(asset_id: str, other_id: str, repo: AssetRepository = Depends(get_repo),
                   actor: str = Depends(require_perm(Perm.EDIT_METADATA))):
    try:
        return {"picked": repo.remove_related_pick(asset_id, other_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="That demo was not picked here.")
    except NotImplementedError:
        raise HTTPException(status_code=501, detail="needs the file-backed catalogue")


class NotRelatedIn(BaseModel):
    not_related: bool


@router.put("/{asset_id}/not-related/{other_id}")
def mark_not_related(asset_id: str, other_id: str, body: NotRelatedIn,
                     repo: AssetRepository = Depends(get_repo),
                     actor: str = Depends(require_perm(Perm.EDIT_METADATA))):
    try:
        return {"not_related": sorted(repo.set_not_related(asset_id, other_id,
                                                           body.not_related, actor))}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"no asset with id '{asset_id}'")
    except NotImplementedError:
        raise HTTPException(status_code=501, detail="needs the file-backed catalogue")


@router.get("/{asset_id}/thumbnail")
def asset_thumbnail(asset_id: str, repo: AssetRepository = Depends(get_repo),
                    user: CurrentUser = Depends(get_current_user)):
    """A SharePoint-hosted picture, fetched by the Hub so every viewer sees it,
    signed into SharePoint or not (services/thumbnails.py, 2026-10-20). Seen by
    whoever may see the demo; 404 lets the card fall back to its cover."""
    from backend.integrations.graph.client import get_graph_client
    from backend.services import thumbnails
    get_asset(asset_id, repo, user)                      # the same 404s as the page
    source = getattr(repo, "thumbnail_source", lambda _id: None)(asset_id)
    if not thumbnails.is_sharepoint(source):
        raise HTTPException(status_code=404, detail="No SharePoint picture for this demo.")
    try:
        picture = thumbnails.get(repo.mirror_dir, get_graph_client(), source, wait=False)
    except thumbnails.Busy:
        # Never queue a viewer behind SharePoint: the cover now, the picture
        # once the background warm-up has it (not cached, so no-store).
        thumbnails.warm_soon(repo)
        return Response(status_code=404, headers={"Cache-Control": "no-store"})
    if picture is None:
        raise HTTPException(status_code=404, detail="Picture not available.")
    return Response(content=picture[0], media_type=picture[1],
                    headers={"Cache-Control": "private, max-age=86400"})


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
    _require_perm(user, Perm.DOWNLOAD)
    _require_listed_file(asset_id, item_id, repo)
    _require_partner_access(asset_id, repo, user)
    _require_gxc_download(asset_id, repo)
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
    _record(repo, "download", asset_id, user, **_file_facts(repo, asset_id, item_id))
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
    _require_perm(user, Perm.PREVIEW)
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
    _record(repo, "preview", asset_id, user, **_file_facts(repo, asset_id, item_id))
    return RedirectResponse(url, status_code=302)


class AccessIn(BaseModel):
    level: str
    reason: str | None = None


@router.put("/{asset_id}/access")
def set_access(asset_id: str, body: AccessIn, repo: AssetRepository = Depends(get_repo),
               actor: str = Depends(require_perm(Perm.MANAGE_ACCESS))):
    """Mark a demo Internal, or Open again (2026-10-07). Hub-owned data only
    (owned/content_access.json); SharePoint is never written. Opening a demo
    whose folder SharePoint closes to partners changes nothing: it stays
    Internal until the folder is opened there."""
    if body.level not in ("open", "internal"):
        raise HTTPException(status_code=422, detail="level must be 'open' or 'internal'")
    if body.level == "internal":
        _not_customer_facing(repo, asset_id)
    try:
        result = repo.set_access(asset_id, body.level, actor, body.reason)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"no asset with id '{asset_id}'")
    except NotImplementedError:
        raise HTTPException(status_code=501, detail="needs the file-backed catalogue")
    log.info("access of %s set to %s by %s", asset_id, body.level, actor)
    return result


def _not_customer_facing(repo: AssetRepository, asset_id: str) -> None:
    """PTC Only is never customer facing (Seb, 2026-10-28): before a demo is
    made PTC Only, its CustomerFacing column is written No. Not changed back
    when it is opened again. A demo the Hub does not write (Consensus, a page)
    only shows No (json_repo); SharePoint failing refuses the change."""
    from backend.services import metadata_edit as me
    asset = repo.get(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"no asset with id '{asset_id}'")
    try:
        key = me.target_key(asset.model_dump(mode="json"))
    except me.NotEditable:
        return
    from backend.routers.uploads import _client, _target
    client = _client()
    target = _target(client, key)
    if not any(f.key == "customer_facing" for f in me.edit_fields(target.spec)):
        return
    try:
        item = client.get_list_item(target.drive_id, asset.source_item_id) or {}
        if me.values_of(target.spec, item.get("fields") or {}).get("customer_facing") is False:
            return
        me.write(client, target, asset.source_item_id, {"customer_facing": False}, None)
    except GraphError as exc:
        raise HTTPException(status_code=502, detail=f"SharePoint: {exc}")
    values = me.hub_values(key, {"customer_facing": False})
    values["assumed"] = [a for a in asset.assumed if a != "customer_facing"]
    me.remember(repo, asset_id, values)


def _requests_view(repo, asset_id: str, user) -> dict:
    from backend.services import access_requests
    return {"pending": access_requests.pending_for(repo, asset_id),
            "history": access_requests.listing(repo, asset_id=asset_id, limit=20),
            "may_decide": user.can(Perm.MANAGE_ACCESS)}


@router.get("/{asset_id}/access-requests")
def get_access_requests(asset_id: str, repo: AssetRepository = Depends(get_repo),
                        actor: str = Depends(require_perm(Perm.MANAGE_ACCESS)),
                        user: CurrentUser = Depends(get_current_user)):
    """A demo's requests to change its access (2026-10-15). Nobody asks this
    way any more (Liwei, 2026-10-28: Report an issue instead); one left
    waiting from before is decided on the demo's page or on Admin ->
    Content access."""
    return _requests_view(repo, asset_id, user)


class StillCurrentIn(BaseModel):
    still_current: bool


@router.put("/{asset_id}/still-current")
def set_still_current(asset_id: str, body: StillCurrentIn,
                      repo: AssetRepository = Depends(get_repo),
                      actor: str = Depends(require_perm(Perm.REVIEW_CONTENT))):
    """Confirm the interface a demo shows still matches today's release, or
    withdraw that (Serge, 2026-10-13). Lasts STILL_CURRENT_MONTHS, then the
    age badge returns. Hub-owned (owned/content_review.json)."""
    try:
        result = repo.set_still_current(asset_id, body.still_current, actor,
                                        settings.still_current_months)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"no asset with id '{asset_id}'")
    except NotImplementedError:
        raise HTTPException(status_code=501, detail="needs the file-backed catalogue")
    log.info("still current of %s set to %s by %s", asset_id, body.still_current, actor)
    return result


class ArchiveIn(BaseModel):
    archived: bool
    reason: str | None = None


@router.put("/{asset_id}/archive")
def set_archived(asset_id: str, body: ArchiveIn, repo: AssetRepository = Depends(get_repo),
                 actor: str = Depends(require_perm(Perm.ARCHIVE))):
    """Archive a demo or restore it ("Archive content", 2026-10-28).

    A demo kit or video in SharePoint: its folder moves into the library's
    _Archive folder, or back (services/archive.py) -- refused when part of it
    has permissions of its own. Anything else (Consensus, a page-only demo):
    in the Hub only, as before. Nothing is deleted anywhere."""
    from backend.services import archive as ar
    from backend.services import metadata_edit as me
    asset = repo.get(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"no asset with id '{asset_id}'")
    try:
        key = me.target_key(asset.model_dump(mode="json"))
    except me.NotEditable:
        key = None
    moved = None
    if key and body.archived != asset.sharepoint_archived:
        from backend.routers.uploads import _client, _target, _sync_soon
        client = _client()
        target = _target(client, key)
        try:
            if body.archived:
                ar.archive(client, target.drive_id, asset.source_item_id)
            else:
                ar.restore(client, target.drive_id, asset.source_item_id)
        except ar.ArchiveRefused as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except GraphError as exc:
            raise HTTPException(status_code=502, detail=f"SharePoint: {exc}")
        moved = body.archived
        # Seen at once; the sync this starts confirms it.
        me.remember(repo, asset_id, {"sharepoint_archived": body.archived})
        _sync_soon(repo, actor)
    try:
        result = repo.set_archived(asset_id, body.archived, actor, body.reason,
                                   in_sharepoint=moved if key else None)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"no asset with id '{asset_id}'")
    except NotImplementedError:
        raise HTTPException(status_code=501, detail="needs the file-backed catalogue")
    log.info("archived=%s for %s by %s", body.archived, asset_id, actor)
    return result


# ── Editing on the Details card (A1, Liwei 2026-10-26) ─────────────────────
#: Administrators and TDD Team (the "Edit metadata" permission); no review,
#: every change in the Admin log (backend/admin_log.py watches these routes).
EDIT = Depends(require_perm(Perm.EDIT_METADATA))


def _editable(repo: AssetRepository, asset_id: str):
    """(the demo, its library key, a Graph client, the resolved library), or
    an HTTP error."""
    from backend.routers.uploads import _client, _target
    from backend.services import metadata_edit as me
    asset = repo.get(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"no asset with id '{asset_id}'")
    try:
        key = me.target_key(asset.model_dump(mode="json"))
    except me.NotEditable as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    client = _client()
    return asset, key, client, _target(client, key)


def _videos(asset: Asset) -> list[dict]:
    return [{"item_id": r.item_id, "name": r.name, "subfolder": r.subfolder}
            for r in asset.resources if r.kind == "video" and r.item_id]


@router.get("/{asset_id}/metadata")
def edit_form(asset_id: str, repo: AssetRepository = Depends(get_repo), actor: str = EDIT):
    """The editor: its fields, SharePoint's current values (read now, not
    from the mirror), the ETag to send back, the videos to preview with."""
    from backend.services import metadata_edit as me
    from backend.services import upload_targets as ut
    asset, key, client, target = _editable(repo, asset_id)
    try:
        item = client.get_list_item(target.drive_id, asset.source_item_id) or {}
    except GraphError as exc:
        raise HTTPException(status_code=502, detail=f"SharePoint: {exc}")
    if not item:
        raise HTTPException(status_code=404,
                            detail="The demo's folder is no longer in SharePoint.")
    preview = next((r.item_id for r in asset.resources if r.name == asset.main_video), None)
    values = me.values_of(target.spec, item.get("fields") or {})
    # PTC Only is never customer facing (2026-10-28): shown No and locked,
    # so saving writes No where SharePoint still says otherwise.
    locked = {}
    if asset.internal and "customer_facing" in values:
        values["customer_facing"] = False
        locked["customer_facing"] = ("A PTC Only demo is never customer facing. "
                                     "Make it Open first to change this.")
    return {"library": target.spec.library, "title": asset.title,
            "locked": locked,
            "etag": item.get("@odata.etag") or item.get("eTag"),
            "fields": me.form(target.spec, target),
            "video_rules": ut.subtype_rules(target.spec, target.choices),
            "values": values,
            # Empty in SharePoint, shown by the Hub anyway: said, not filled in.
            "hub_shows": me.hub_shows(asset, values),
            "videos": _videos(asset), "preview": preview,
            "thumbnail": {"chosen": bool(asset.thumbnail_chosen),
                          "can_choose": target.has_thumbnail_flag}}


class MetadataIn(BaseModel):
    values: dict
    etag: str | None = None


@router.put("/{asset_id}/metadata")
def save_metadata(asset_id: str, body: MetadataIn, repo: AssetRepository = Depends(get_repo),
                  actor: str = EDIT):
    """Write what changed to the demo's folder, at once."""
    from backend.routers.uploads import _sync_soon
    from backend.services import metadata_edit as me
    from backend.services import upload_targets as ut
    asset, key, client, target = _editable(repo, asset_id)
    try:
        item = client.get_list_item(target.drive_id, asset.source_item_id) or {}
        current = me.values_of(target.spec, item.get("fields") or {})
        sent = dict(body.values)
        if asset.internal and "customer_facing" in current:
            sent["customer_facing"] = False          # PTC Only (2026-10-28)
        changed = me.changes(target.spec, target, sent, current)
        if changed:
            me.write(client, target, asset.source_item_id, changed, body.etag)
    except ut.UploadInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except me.EditConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except GraphError as exc:
        raise HTTPException(status_code=502, detail=f"SharePoint: {exc}")
    if changed:
        values = me.hub_values(key, changed)
        # A value someone has now set is no longer the Hub's assumption.
        values["assumed"] = [a for a in asset.assumed
                             if a not in {me.STATES[k] for k in changed if k in me.STATES}]
        me.remember(repo, asset_id, values)
        _sync_soon(repo, actor)
        log.info("metadata of %s edited by %s: %s", asset_id, actor, sorted(changed))
    return {"changed": sorted(changed), "asset": repo.get(asset_id)}


class PreviewIn(BaseModel):
    item_id: str


@router.put("/{asset_id}/preview-video")
def set_preview_video(asset_id: str, body: PreviewIn,
                      repo: AssetRepository = Depends(get_repo), actor: str = EDIT):
    """The video the demo is previewed with (PreviewVideo): this one ticked,
    the demo's other videos cleared."""
    from backend.routers.uploads import _sync_soon
    from backend.services import metadata_edit as me
    from backend.services import upload_targets as ut
    asset, key, client, target = _editable(repo, asset_id)
    chosen = next((v for v in _videos(asset) if v["item_id"] == body.item_id), None)
    if chosen is None:
        raise HTTPException(status_code=422, detail="Choose one of this demo's videos.")
    try:
        me.tick(client, target, ut.PREVIEW_COLUMN, chosen["item_id"],
                [r.item_id for r in asset.resources if r.preview and r.item_id])
    except GraphError as exc:
        raise HTTPException(status_code=502, detail=f"SharePoint: {exc}")
    me.remember(repo, asset_id, {"main_video": chosen["name"]})
    _sync_soon(repo, actor)
    return {"preview": chosen["item_id"], "asset": repo.get(asset_id)}


@router.get("/{asset_id}/files/{item_id}/frame-source")
def frame_source(asset_id: str, item_id: str, repo: AssetRepository = Depends(get_repo),
                 actor: str = EDIT):
    """A short-lived address the editor plays a video from to pick a frame
    for the card (B5). SharePoint serves it with CORS open (measured
    2026-10-26), so the page can draw a frame onto a canvas."""
    asset, key, client, target = _editable(repo, asset_id)
    if not any(v["item_id"] == item_id for v in _videos(asset)):
        raise HTTPException(status_code=404, detail="Not one of this demo's videos.")
    try:
        url = client.download_url(target.drive_id, item_id)
    except GraphError as exc:
        raise HTTPException(status_code=502, detail=f"SharePoint: {exc}")
    if not url:
        raise HTTPException(status_code=404, detail="SharePoint gave no address for this video.")
    return {"url": url}


@router.put("/{asset_id}/thumbnail")
async def set_thumbnail(asset_id: str, file: UploadFile = File(...),
                        repo: AssetRepository = Depends(get_repo), actor: str = EDIT):
    """The card's picture (B5): an image uploaded, or a frame the page took
    from a video -- either way a picture saved in the demo's folder and
    ticked HubThumbnail, any picture ticked before cleared."""
    from backend.routers.uploads import _sync_soon
    from backend.services import metadata_edit as me
    from backend.services import upload_targets as ut
    asset, key, client, target = _editable(repo, asset_id)
    if not target.has_thumbnail_flag:
        raise HTTPException(status_code=422, detail=f"{target.spec.library} has no "
                            f"{ut.THUMBNAIL_COLUMN} column yet.")
    content_type = (file.content_type or "").lower()
    if content_type not in me.IMAGE_TYPES:
        raise HTTPException(status_code=422, detail="A JPG, PNG or WebP picture, please.")
    content = await file.read(me.MAX_IMAGE_BYTES + 1)
    if not content or len(content) > me.MAX_IMAGE_BYTES:
        raise HTTPException(status_code=422, detail="A picture of at most 5 MB, please.")
    try:
        item = me.put_thumbnail(client, target, asset.source_item_id, content, content_type)
        me.tick(client, target, ut.THUMBNAIL_COLUMN, item["id"],
                [r.item_id for r in asset.resources if r.hub_thumbnail and r.item_id])
    except GraphError as exc:
        raise HTTPException(status_code=502, detail=f"SharePoint: {exc}")
    me.remember(repo, asset_id, {"thumbnail_url": item.get("webUrl"), "thumbnail_chosen": True})
    _sync_soon(repo, actor)
    return {"asset": repo.get(asset_id)}


@router.delete("/{asset_id}/thumbnail")
def clear_thumbnail(asset_id: str, repo: AssetRepository = Depends(get_repo),
                    actor: str = EDIT):
    """Back to the automatic picture: the chosen one is unticked (the file
    stays in the folder)."""
    from backend.routers.uploads import _sync_soon
    from backend.services import metadata_edit as me
    from backend.services import upload_targets as ut
    asset, key, client, target = _editable(repo, asset_id)
    try:
        me.tick(client, target, ut.THUMBNAIL_COLUMN, None,
                [r.item_id for r in asset.resources if r.hub_thumbnail and r.item_id])
    except GraphError as exc:
        raise HTTPException(status_code=502, detail=f"SharePoint: {exc}")
    me.remember(repo, asset_id, {"thumbnail_url": None, "thumbnail_chosen": False})
    _sync_soon(repo, actor)
    return {"asset": repo.get(asset_id)}

