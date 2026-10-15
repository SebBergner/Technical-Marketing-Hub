"""Uploading a video or a demo kit through the Hub (2026-10-15).

The flow, as the upload page drives it:

    GET  /api/uploads/targets          where uploads may go, and each one's form
    POST /api/uploads                  metadata + file list; checked, then the
                                       new folder is created in SharePoint
    POST /api/uploads/{id}/files/{n}/session   a pre-authorised URL the browser
                                       sends file n to, in chunks
    POST /api/uploads/{id}/files/{n}/done      the file is in (checked here)
    POST /api/uploads/{id}/finish      metadata written; waiting for review
    POST /api/uploads/{id}/publish     a reviewer lists it in the Hub
    POST /api/uploads/{id}/send-back   ... or asks for changes
    POST /api/uploads/{id}/resubmit    the uploader, with corrected metadata
    POST /api/uploads/{id}/cancel      the uploader stops it

"Upload content" uploads; "Review content" publishes and sends back. Metadata
is required before anything is created (services/upload_targets.py).
"""
from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.access import Perm
from backend.admin_auth import require_perm
from backend.deps import CurrentUser, get_current_user, get_repo
from backend.integrations.graph.client import GraphError, get_graph_client
from backend.repositories.base import AssetRepository
from backend.services import upload_targets as ut
from backend.services import uploads

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/uploads", tags=["uploads"])

UPLOAD = require_perm(Perm.UPLOAD)
REVIEW = require_perm(Perm.REVIEW_CONTENT)
_sync_lock = threading.Lock()


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


def _view(record: dict, user: CurrentUser | None = None) -> dict:
    out = {k: v for k, v in record.items() if k != "values"}
    out["values"] = record.get("values")
    out["mine"] = bool(user) and record.get("uploaded_by", "").split(":", 1)[-1] == user.email
    return out


def _mine_or_reviewer(record: dict, actor: str, user: CurrentUser) -> None:
    if record["uploaded_by"] != actor and not user.can(Perm.REVIEW_CONTENT):
        raise HTTPException(status_code=403, detail="Not your upload.")


def _sync_soon(repo: AssetRepository, actor: str) -> None:
    """Index the new folder now rather than at the next scheduled sync.
    In the background, and skipped if a sync is already running."""
    def run():
        if not _sync_lock.acquire(blocking=False):
            return
        try:
            from backend.routers.graph import run_sync
            run_sync(get_graph_client(), repo, f"upload by {actor}")
        except Exception:                                # noqa: BLE001
            log.exception("sync after upload failed; the next sync picks it up")
        finally:
            _sync_lock.release()
    threading.Thread(target=run, daemon=True).start()


# ───────────────────────────────────────────────────────────── the form
@router.get("/targets")
def targets(fresh: bool = False, actor: str = Depends(UPLOAD)):
    client = _client()
    return [ut.form(ut.target(key), _target(client, key, fresh=fresh).choices)
            for key in ut.TARGETS]


class FileIn(BaseModel):
    path: str
    size: int


class UploadIn(BaseModel):
    target: str
    kind: str
    values: dict
    files: list[FileIn]
    internal: bool = False


@router.post("", status_code=201)
def start(body: UploadIn, repo: AssetRepository = Depends(get_repo),
          actor: str = Depends(UPLOAD), user: CurrentUser = Depends(get_current_user)):
    from backend.integrations.graph import upload_writer as uw
    from backend.integrations.graph.migration_writer import safe_folder_name
    client = _client()
    try:
        spec = ut.target(body.target)
        kind = ut.kind_of(spec, body.kind)
        target = _target(client, spec.key)
        values = ut.clean_fields(spec, body.values, target.choices)
        files = ut.clean_files(spec, [f.model_dump() for f in body.files])
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
                            web_url=folder.get("webUrl"), actor=actor)
    log.info("upload %s started by %s: %s/%s", record["id"], actor, spec.library, name)
    return _view(record, user)


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
        return _view(uploads.file_done(repo, upload_id, index, body.item_id, actor), user)
    except uploads.UploadStateError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _write_and_submit(repo, record: dict, actor: str, values: dict) -> dict:
    from backend.integrations.graph import upload_writer as uw
    client = _client()
    target = _target(client, record["target"])
    kind = ut.kind_of(target.spec, record["kind"])
    fields, note = uw.metadata_fields(target, kind, values)
    try:
        uw.write_metadata(client, target, record["folder_id"], fields, note)
    except GraphError as exc:
        uploads.failed(repo, record["id"], str(exc))
        raise HTTPException(status_code=502, detail=f"SharePoint: {exc}. Try Finish again.")
    try:
        done = uploads.submit(repo, record["id"], actor, values)
    except uploads.UploadStateError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    _sync_soon(repo, actor)
    return done


@router.post("/{upload_id}/finish")
def finish(upload_id: str, repo: AssetRepository = Depends(get_repo),
           actor: str = Depends(UPLOAD), user: CurrentUser = Depends(get_current_user)):
    """Every file in: write the metadata (last, as the migration does) and wait
    for review. Internal, if asked for, is marked when the demo appears."""
    record = _get(repo, upload_id)
    if record["uploaded_by"] != actor:
        raise HTTPException(status_code=403, detail="Not your upload.")
    if record["status"] != "uploading":
        raise HTTPException(status_code=422, detail=f"This upload is {record['status']}.")
    if any(not f["done"] for f in record["files"]):
        raise HTTPException(status_code=422, detail="Some files have not finished uploading.")
    return _view(_write_and_submit(repo, record, actor, record["values"]), user)


class ResubmitIn(BaseModel):
    values: dict


@router.post("/{upload_id}/resubmit")
def resubmit(upload_id: str, body: ResubmitIn, repo: AssetRepository = Depends(get_repo),
             actor: str = Depends(UPLOAD), user: CurrentUser = Depends(get_current_user)):
    """After Send back: corrected metadata, written to the same folder."""
    record = _get(repo, upload_id)
    if record["uploaded_by"] != actor:
        raise HTTPException(status_code=403, detail="Not your upload.")
    if record["status"] != "sent_back":
        raise HTTPException(status_code=422, detail=f"This upload is {record['status']}.")
    client = _client()
    target = _target(client, record["target"])
    try:
        values = ut.clean_fields(target.spec, body.values, target.choices)
    except ut.UploadInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if values.get("title") != record["values"].get("title"):
        raise HTTPException(status_code=422, detail="The title is the folder's name and stays "
                            "as it was; rename the folder in SharePoint if it must change.")
    return _view(_write_and_submit(repo, record, actor, values), user)


class NoteIn(BaseModel):
    note: str | None = None


@router.post("/{upload_id}/publish")
def publish(upload_id: str, body: NoteIn, repo: AssetRepository = Depends(get_repo),
            actor: str = Depends(REVIEW), user: CurrentUser = Depends(get_current_user)):
    record = _get(repo, upload_id)
    try:
        done = uploads.publish(repo, upload_id, actor, body.note)
    except uploads.UploadStateError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    asset_id = (repo.ids_by_folder() if hasattr(repo, "ids_by_folder") else {}).get(
        record.get("folder_id"))
    if record.get("internal") and asset_id and hasattr(repo, "set_access"):
        repo.set_access(asset_id, "internal", actor, "Marked Internal when uploaded")
    return _view(done, user)


@router.post("/{upload_id}/send-back")
def send_back(upload_id: str, body: NoteIn, repo: AssetRepository = Depends(get_repo),
              actor: str = Depends(REVIEW), user: CurrentUser = Depends(get_current_user)):
    _get(repo, upload_id)
    try:
        return _view(uploads.send_back(repo, upload_id, actor, body.note or ""), user)
    except uploads.UploadStateError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/{upload_id}/cancel")
def cancel(upload_id: str, repo: AssetRepository = Depends(get_repo),
           actor: str = Depends(UPLOAD), user: CurrentUser = Depends(get_current_user)):
    _get(repo, upload_id)
    try:
        return _view(uploads.cancel(repo, upload_id, actor), user)
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
    me = f"{'dev' if user.is_dev_principal else 'user'}:{user.email}"
    records = uploads.all_records(repo)
    if mine or not user.can(Perm.REVIEW_CONTENT):
        records = [r for r in records if r["uploaded_by"] == me]
    if status:
        wanted = set(status.split(","))
        records = [r for r in records if r["status"] in wanted]
    ids = repo.ids_by_folder() if hasattr(repo, "ids_by_folder") else {}
    out = []
    for r in records[:limit]:
        view = _view(r, user)
        view["asset_id"] = ids.get(r.get("folder_id"))
        out.append(view)
    return out


def _get(repo, upload_id: str) -> dict:
    try:
        return uploads.get(repo, upload_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="No such upload.")

