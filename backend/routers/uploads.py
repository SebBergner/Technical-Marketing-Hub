"""Uploading a video or a demo kit through the Hub (2026-10-15).

The flow, as the upload page drives it:

    GET  /api/uploads/targets          where uploads may go, and each one's form
    POST /api/uploads                  metadata + file list; checked, then the
                                       new folder is created in SharePoint
    POST /api/uploads/{id}/files/{n}/session   a pre-authorised URL the browser
                                       sends file n to, in chunks
    POST /api/uploads/{id}/files/{n}/done      the file is in (checked here)
    POST /api/uploads/{id}/finish      metadata written; listed in the Hub at once
    POST /api/uploads/{id}/cancel      the uploader stops it

There is no review (Liwei, 2026-10-28): "Create new demo" publishes. Two
routes remain for uploads left from before, handled by hand:

    POST /api/uploads/{id}/publish     "Review content" lists one still waiting
    POST /api/uploads/{id}/resubmit    the uploader corrects one sent back; published

Metadata is required before anything is created (services/upload_targets.py).
"""
from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from backend.access import Perm
from backend.admin_auth import require_perm
from backend.config import settings
from backend.deps import CurrentUser, get_current_user, get_repo
from backend.integrations.graph.client import GraphError, get_graph_client
from backend.repositories.base import AssetRepository
from backend.services import upload_targets as ut
from backend.services import uploads

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/uploads", tags=["uploads"])

UPLOAD = require_perm(Perm.UPLOAD)
REVIEW = require_perm(Perm.REVIEW_CONTENT)


def _client():
    client = get_graph_client()
    if client is None:
        raise HTTPException(status_code=503, detail="SharePoint is not configured here.")
    return client


def _target(client, key: str, *, fresh: bool = False):
    from backend.integrations.graph import upload_writer as uw
    try:
        return uw.resolve(client, ut.target(key), fresh=fresh)
    except ut.UploadInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except GraphError as exc:
        raise HTTPException(status_code=502, detail=f"SharePoint: {exc}")


def _submitted_by(value: str | None, user: CurrentUser) -> str | None:
    """Who an API upload is for: a PTC address (it is credited as the demo's
    creator, and partners stay anonymous). Refused rather than ignored, so a
    script learns at once. A person uploading through the page is the
    submitter already."""
    value = (value or "").strip().lower()
    if not value:
        return None
    if not user.token_name:
        raise HTTPException(status_code=422, detail="submitted_by is for API tokens; "
                            "a person uploading is the submitter.")
    from backend.access import _is_internal_address
    if "@" not in value or not _is_internal_address(value):
        raise HTTPException(status_code=422, detail="submitted_by: a PTC email address.")
    return value


def _view(record: dict, user: CurrentUser | None = None, repo=None,
          ids: dict | None = None) -> dict:
    """An upload as the API answers it, with where to find the demo (Seb,
    2026-10-16): `sharepoint_url`, its folder; `hub_url`, a permanent Hub
    link that works at once and opens the demo's page once the Hub has read
    it (app.py, /demo/upload/{id}); `asset_id` and `asset_url` from then on,
    null before -- the Hub names a demo when it first reads it."""
    out = {k: v for k, v in record.items() if k != "values"}
    out["values"] = record.get("values")
    out["mine"] = bool(user) and record.get("uploaded_by", "").split(":", 1)[-1] == user.email
    base = settings.public_base_url
    out["sharepoint_url"] = record.get("web_url")
    out["hub_url"] = f"{base}/demo/upload/{record['id']}"
    if ids is None and repo is not None and hasattr(repo, "ids_by_folder"):
        ids = repo.ids_by_folder()
    asset_id = (ids or {}).get(record.get("folder_id"))
    out["asset_id"] = asset_id
    # An API upload that names nobody is credited to the token's owner;
    # say so in every answer, so the script's author notices (2026-10-21).
    out["warnings"] = []
    if str(record.get("uploaded_by") or "").startswith("token:") and not record.get("submitted_by"):
        out["warnings"].append(
            "submitted_by is empty: this upload is credited to the token's responsible person"
            + (f" ({record['person']})" if record.get("person") else "")
            + ". Send the PTC email address of the person it is for.")
    # Required on the page, only a warning through the API so far (A11,
    # Liwei 2026-10-26).
    if str(record.get("uploaded_by") or "").startswith("token:"):
        for f in ut.TARGETS[record["target"]].fields if record.get("target") in ut.TARGETS else ():
            if f.form_required and not (record.get("values") or {}).get(f.key):
                out["warnings"].append(f"{f.key} is empty: send it (or \"N/A\" when it does "
                                       "not apply). It will become required.")
        out["warnings"] += [p + " This will be refused later."
                            for p in ut.video_rules(record.get("values") or {})[1]]
    out["asset_url"] = f"{base}/#/asset/{quote(asset_id, safe='')}" if asset_id else None
    return out


def _mine_or_reviewer(record: dict, actor: str, user: CurrentUser) -> None:
    if record["uploaded_by"] != actor and not user.can(Perm.REVIEW_CONTENT):
        raise HTTPException(status_code=403, detail="Not your upload.")


def _sync_soon(repo: AssetRepository, actor: str) -> None:
    """Index the new folder now rather than at the next scheduled sync: in
    the background, queued behind a sync already running, never dropped
    (graph.sync_soon)."""
    from backend.routers.graph import sync_soon
    sync_soon(repo, actor)


def _indexed(repo, record: dict) -> bool:
    ids = repo.ids_by_folder() if hasattr(repo, "ids_by_folder") else {}
    return record.get("folder_id") in ids


# ───────────────────────────────────────────────────────────── the form
@router.get("/targets")
def targets(fresh: bool = False, actor: str = Depends(UPLOAD)):
    """The destination platforms, and the form of every target on the ones
    that are built."""
    client = _client()
    out = []
    for key in ut.TARGETS:
        spec = ut.target(key)
        try:
            resolved = _target(client, key, fresh=fresh)
            out.append(ut.form(spec, resolved.choices, resolved.skipped))
        except HTTPException as exc:
            # One library that cannot be read does not take the others down.
            out.append({**ut.form(spec, {}), "fields": [], "unavailable": exc.detail})
    return {"platforms": list(ut.PLATFORMS), "targets": out}


class FileIn(BaseModel):
    path: str
    size: int


class UploadIn(BaseModel):
    target: str
    kind: str
    values: dict
    files: list[FileIn]
    internal: bool = False
    #: With two or more videos, the one to preview the demo with (required).
    preview: str | None = None
    #: An API upload: the PTC person it is for, when one token serves several
    #: people (Seb, 2026-10-20). Optional; without it, every answer warns.
    submitted_by: str | None = None


@router.post("", status_code=201)
def start(body: UploadIn, repo: AssetRepository = Depends(get_repo),
          actor: str = Depends(UPLOAD), user: CurrentUser = Depends(get_current_user)):
    from backend.integrations.graph import upload_writer as uw
    from backend.integrations.graph.migration_writer import safe_folder_name
    submitted_by = _submitted_by(body.submitted_by, user)
    client = _client()
    from backend.services import taxonomy
    divested = [p for p in (body.values.get("products") or [])
                if isinstance(p, str) and taxonomy.is_excluded([p])]
    if divested:
        raise HTTPException(status_code=422, detail=", ".join(divested) + ": no longer sold by "
                            "PTC. The Hub lists no demo of these products, so it cannot be "
                            "created here.")
    try:
        spec = ut.target(body.target)
        kind = ut.kind_of(spec, body.kind)
        target = _target(client, spec.key)
        values = ut.clean_fields(spec, body.values, target.choices, form=not user.token_name)
        # A video's subtype follows its type (A15): refused on the page, a
        # warning through the API for now (_view).
        values, problems = ut.video_rules(values)
        if problems and not user.token_name:
            raise ut.UploadInvalid(" ".join(problems))
        files = ut.clean_files(spec, [f.model_dump() for f in body.files])
        preview = ut.preview_of(files, body.preview)
    except ut.UploadInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    unknown = uw.unknown_products(target, values.get("products") or [])
    if unknown:
        raise HTTPException(status_code=422, detail="Not in SharePoint's Product list: "
                            + ", ".join(unknown) + ". Ask an administrator to add the term.")
    name = safe_folder_name(values["title"])
    try:
        if uw.name_taken(client, target, name):
            raise HTTPException(status_code=409, detail=f'"{name}" already exists in '
                                f"{spec.library}. Choose another title.")
        folder = uw.create_folder(client, target, name)
    except GraphError as exc:
        raise HTTPException(status_code=502, detail=f"SharePoint: {exc}")
    record = uploads.create(repo, target=spec.key, kind=kind.key, values=values, files=files,
                            internal=body.internal, folder_id=folder["id"], folder_name=name,
                            web_url=folder.get("webUrl"), actor=actor, preview=preview,
                            submitted_by=submitted_by,
                            person=submitted_by or (user.token_owner if user.token_name
                                                    else user.email))
    log.info("upload %s started by %s: %s/%s", record["id"], actor, spec.library, name)
    return _view(record, user, repo)


@router.post("/{upload_id}/files/{index}/session")
def file_session(upload_id: str, index: int, repo: AssetRepository = Depends(get_repo),
                 actor: str = Depends(UPLOAD)):
    """A fresh upload URL for one file. The browser sends the bytes to it
    directly; asking again after an interruption starts that file over."""
    from backend.integrations.graph import upload_writer as uw
    record = _get(repo, upload_id)
    if record["uploaded_by"] != actor:
        raise HTTPException(status_code=403, detail="Not your upload.")
    if record["status"] != "uploading":
        raise HTTPException(status_code=422, detail=f"This upload is {record['status']}.")
    if not 0 <= index < len(record["files"]):
        raise HTTPException(status_code=404, detail="No such file in this upload.")
    client = _client()
    target = _target(client, record["target"])
    path = record["files"][index]["path"]
    try:
        parent = uw.ensure_subfolders(client, target, record["folder_id"], path)
        return uw.upload_session(client, target, parent, path.rsplit("/", 1)[-1])
    except GraphError as exc:
        if "HTTP 409" in str(exc):
            raise HTTPException(status_code=409, detail=f"{path} is already there.")
        raise HTTPException(status_code=502, detail=f"SharePoint: {exc}")


class DoneIn(BaseModel):
    item_id: str


@router.post("/{upload_id}/files/{index}/done")
def file_done(upload_id: str, index: int, body: DoneIn,
              repo: AssetRepository = Depends(get_repo), actor: str = Depends(UPLOAD),
              user: CurrentUser = Depends(get_current_user)):
    """Checked against SharePoint: the item exists, inside this upload's folder,
    at the size the form declared."""
    from backend.integrations.graph import upload_writer as uw
    record = _get(repo, upload_id)
    if record["uploaded_by"] != actor:
        raise HTTPException(status_code=403, detail="Not your upload.")
    if not 0 <= index < len(record["files"]):
        raise HTTPException(status_code=404, detail="No such file in this upload.")
    client = _client()
    target = _target(client, record["target"])
    item = uw.file_item(client, target, body.item_id)
    expected = record["files"][index]
    if not item or item.get("size") != expected["size"] \
            or item.get("name") != expected["path"].rsplit("/", 1)[-1]:
        raise HTTPException(status_code=422, detail=f"{expected['path']} did not arrive whole; "
                            "upload it again.")
    try:
        return _view(uploads.file_done(repo, upload_id, index, body.item_id, actor), user, repo)
    except uploads.UploadStateError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _write_and_submit(repo, record: dict, actor: str, values: dict,
                      user: CurrentUser | None = None) -> dict:
    from backend.integrations.graph import upload_writer as uw
    client = _client()
    target = _target(client, record["target"])
    kind = ut.kind_of(target.spec, record["kind"])
    fields, note = uw.metadata_fields(target, kind, values)
    preview_item = next((f.get("item_id") for f in record["files"]
                         if f["path"] == record.get("preview")), None)
    try:
        # Who submitted it, in SharePoint too where the library has the
        # column (2026-10-21): the API's submitted_by, or the person who used
        # the page. Read back by the sync as the demo's creator.
        submitter = record.get("submitted_by") or (
            None if str(record.get("uploaded_by") or "").startswith("token:")
            else record.get("person"))
        if submitter and target.has_submitted_by:
            fields[ut.SUBMITTED_COLUMN] = submitter
        # Who to ask about it (A4): the person it counts as made by -- the
        # uploader on the page; through the API submitted_by, else the
        # token's responsible person. Editable later on the Details card.
        if record.get("person") and target.has_demo_owner:
            fields[ut.OWNER_COLUMN] = record["person"]
        uw.write_metadata(client, target, record["folder_id"], fields, note)
        if preview_item:
            uw.mark_preview(client, target, preview_item)
    except GraphError as exc:
        uploads.failed(repo, record["id"], str(exc))
        raise HTTPException(status_code=502, detail=f"SharePoint: {exc}. Try Finish again.")
    # No review (Liwei, 2026-10-28): whoever may create a demo publishes it,
    # people and API tokens alike, and no Hub Tasks row is made for it.
    try:
        done = uploads.submit(repo, record["id"], actor, values, task=False)
        done = uploads.publish(repo, record["id"], actor, "Published on creation")
    except uploads.UploadStateError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    _sync_soon(repo, actor)
    return done


@router.post("/{upload_id}/finish")
def finish(upload_id: str, repo: AssetRepository = Depends(get_repo),
           actor: str = Depends(UPLOAD), user: CurrentUser = Depends(get_current_user)):
    """Every file in: write the metadata (last, as the migration does) and
    publish. Internal, if asked for, is marked when the demo appears."""
    record = _get(repo, upload_id)
    if record["uploaded_by"] != actor:
        raise HTTPException(status_code=403, detail="Not your upload.")
    if record["status"] != "uploading":
        raise HTTPException(status_code=422, detail=f"This upload is {record['status']}.")
    if any(not f["done"] for f in record["files"]):
        raise HTTPException(status_code=422, detail="Some files have not finished uploading.")
    return _view(_write_and_submit(repo, record, actor, record["values"], user), user, repo)


class ResubmitIn(BaseModel):
    values: dict


@router.post("/{upload_id}/resubmit")
def resubmit(upload_id: str, body: ResubmitIn, repo: AssetRepository = Depends(get_repo),
             actor: str = Depends(UPLOAD), user: CurrentUser = Depends(get_current_user)):
    """An upload sent back before review was removed (2026-10-28): corrected
    metadata, written to the same folder, and published."""
    record = _get(repo, upload_id)
    if record["uploaded_by"] != actor:
        raise HTTPException(status_code=403, detail="Not your upload.")
    if record["status"] != "sent_back":
        raise HTTPException(status_code=422, detail=f"This upload is {record['status']}.")
    client = _client()
    target = _target(client, record["target"])
    try:
        values = ut.clean_fields(target.spec, body.values, target.choices,
                                 form=not user.token_name)
        values, problems = ut.video_rules(values)
        if problems and not user.token_name:
            raise ut.UploadInvalid(" ".join(problems))
    except ut.UploadInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if values.get("title") != record["values"].get("title"):
        raise HTTPException(status_code=422, detail="The title is the folder's name and stays "
                            "as it was; rename the folder in SharePoint if it must change.")
    return _view(_write_and_submit(repo, record, actor, values, user), user, repo)


class NoteIn(BaseModel):
    note: str | None = None


# Left from before review was removed (2026-10-28): uploads still waiting
# are published, or cancelled, by hand from Admin -> Content review.
@router.post("/{upload_id}/publish")
def publish(upload_id: str, body: NoteIn, repo: AssetRepository = Depends(get_repo),
            actor: str = Depends(REVIEW), user: CurrentUser = Depends(get_current_user)):
    record = _get(repo, upload_id)
    try:
        done = uploads.publish(repo, upload_id, actor, body.note)
    except uploads.UploadStateError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    # Published but not yet read by a sync: it appears once one has, so ask.
    if not _indexed(repo, record):
        _sync_soon(repo, actor)
    # Internal, if asked for, was marked by folder when it was submitted
    # (services/uploads.submit), so it holds whether or not a sync has run.
    return _view(done, user, repo)


@router.post("/{upload_id}/index")
def index_now(upload_id: str, request: Request, repo: AssetRepository = Depends(get_repo),
              user: CurrentUser = Depends(get_current_user)):
    """Read the demo into the Hub now (a sync, queued if one is running) --
    for an upload whose folder the Hub has not seen yet."""
    from backend.admin_auth import _actor
    record = _get(repo, upload_id)
    actor = (_actor(request, user, Perm.REVIEW_CONTENT.value)
             or _actor(request, user, Perm.UPLOAD.value))
    if actor is None:
        raise HTTPException(status_code=403, detail="Not available for your account.")
    _mine_or_reviewer(record, actor, user)
    _sync_soon(repo, actor)
    return {"queued": True}


@router.get("/indexing")
def indexing(user: CurrentUser = Depends(get_current_user)):
    from backend.routers.graph import sync_running
    return {"running": sync_running()}


@router.post("/{upload_id}/cancel")
def cancel(upload_id: str, request: Request, repo: AssetRepository = Depends(get_repo),
           user: CurrentUser = Depends(get_current_user)):
    """Its uploader stops it; someone with Review content may cancel any one
    left from before review was removed (Admin -> Content review). The
    folder stays in SharePoint, for a person to delete there."""
    from backend.admin_auth import _actor
    _get(repo, upload_id)
    reviewer = _actor(request, user, Perm.REVIEW_CONTENT.value)
    actor = _actor(request, user, Perm.UPLOAD.value) or reviewer
    if actor is None:
        raise HTTPException(status_code=403, detail="Not available for your account.")
    request.state.hub_actor = actor           # for the Admin log
    try:
        return _view(uploads.cancel(repo, upload_id, actor, anyones=bool(reviewer)), user, repo)
    except uploads.UploadStateError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ───────────────────────────────────────────────────────────── lists
@router.get("")
def listing(status: str | None = None, mine: bool = False,
            limit: int = Query(100, ge=1, le=500), repo: AssetRepository = Depends(get_repo),
            user: CurrentUser = Depends(get_current_user)):
    """Reviewers see every upload; uploaders their own."""
    if not (user.can(Perm.UPLOAD) or user.can(Perm.REVIEW_CONTENT)):
        raise HTTPException(status_code=403, detail="Not available for your account.")
    # A token's uploads are recorded as token:<name> (2026-10-21: this read
    # user:None for a token, so ?mine=true always came back empty to one).
    me = (f"token:{user.token_name}" if user.token_name
          else f"{'dev' if user.is_dev_principal else 'user'}:{user.email}")
    records = uploads.all_records(repo)
    if mine or not user.can(Perm.REVIEW_CONTENT):
        records = [r for r in records if r["uploaded_by"] == me]
    if status:
        wanted = set(status.split(","))
        records = [r for r in records if r["status"] in wanted]
    ids = repo.ids_by_folder() if hasattr(repo, "ids_by_folder") else {}
    out = []
    for r in records[:limit]:
        out.append(_view(r, user, ids=ids))
    return out


def _get(repo, upload_id: str) -> dict:
    try:
        return uploads.get(repo, upload_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="No such upload.")

