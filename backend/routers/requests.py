"""Demo request intake.

The one endpoint in this application that originates data rather than
reflecting it. Everything else the Portal holds about SharePoint is a
rebuildable mirror; a submitted request exists nowhere until this runs, which
shapes the whole design:

**Local first, always.** The submission is appended to `owned/requests.jsonl`
before Graph is touched. If SharePoint is unreachable the request is still
recorded and the response says so, rather than showing a success screen for
something that went nowhere — which is exactly what the form did before it
was wired to anything at all.

**Never a silent success.** `synced` is in the response because "we have your
request" and "the team can see your request" are different promises, and the
UI has to be able to tell them apart.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from backend.auth import CurrentUser, require_authenticated
from backend.config import settings
from backend.deps import get_repo
from backend.integrations.graph.client import get_graph_client
from backend.integrations.graph.requests_list import (
    ATTACHMENT_FOLDER, ATTACHMENT_LIBRARY, MAX_ATTACHMENT_BYTES,
    RequestWriteError, attachment_rejection, build_fields, create_request_item,
    upload_attachment,
)
from backend.models import AssetRequest, AssetRequestCreate
from backend.repositories.base import AssetRepository

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/requests", tags=["requests"])


class RequestAccepted(AssetRequest):
    """What the form gets back.

    `synced` false is not an error — the request is safe — but the UI must say
    "recorded, not yet visible to the team" rather than "sent".
    """
    warning: str | None = None
    #: Files that reached the library, by name.
    attachments: list[str] = []
    #: Files that did not, each with the reason. Never silent: a dropped
    #: attachment the requester does not hear about is the whole failure this
    #: feature was added to stop.
    attachments_rejected: list[str] = []


@router.post("", response_model=RequestAccepted, status_code=201)
async def submit_request(
    body: AssetRequestCreate,
    repo: AssetRepository = Depends(get_repo),
    user: CurrentUser = Depends(require_authenticated),
) -> RequestAccepted:
    """Record a request locally, then push it to SharePoint."""
    return await _submit(body, [], repo, user)


@router.post("/with-files", response_model=RequestAccepted, status_code=201)
async def submit_request_with_files(
    request: str = Form(...),
    files: list[UploadFile] = File(default=[]),
    repo: AssetRepository = Depends(get_repo),
    user: CurrentUser = Depends(require_authenticated),
) -> RequestAccepted:
    """The same submission, with attachments.

    A separate route rather than one that accepts either shape: multipart and
    JSON need different parsing, and a single endpoint doing both would have
    to guess. The request itself arrives as a JSON string in one form field,
    so the model still validates it exactly as the JSON route does.
    """
    try:
        body = AssetRequestCreate.model_validate_json(request)
    except ValueError as exc:
        raise HTTPException(status_code=422,
                            detail=f"The request could not be read: {exc}") from exc
    return await _submit(body, files, repo, user)


async def _submit(body: AssetRequestCreate, files: list, repo, user) -> RequestAccepted:
    now = datetime.now(timezone.utc)
    # Readable in the list and sortable by eye: the date, then enough randomness
    # that two people submitting in the same second cannot collide.
    request_id = f"REQ-{now:%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"

    record = AssetRequest(
        **body.model_dump(),
        id=request_id,
        submitted_at=now,
        status="new",
    )

    # Behind Easy Auth the signed-in identity wins: the requester fields exist
    # so somebody can file on another's behalf, not so they can file *as*
    # someone else.
    #
    # The dev principal is not an identity. It is a local stand-in, and letting
    # it win overwrote a real "liwchen@ptc.com" with "dev@localhost" and said
    # nothing — the form's answer was silently discarded, which is the failure
    # this codebase keeps refusing to ship.
    if user.email and not user.is_dev_principal:
        record.requester_email = user.email
        if getattr(user, "name", None):
            record.requester_name = record.requester_name or user.name

    # Read and screen the files first, so what was rejected is known before
    # anything is written and can travel with the record rather than being
    # discovered afterwards.
    accepted: list[tuple[str, bytes]] = []
    rejected: list[str] = []
    for upload in files or []:
        content = await upload.read()
        reason = attachment_rejection(upload.filename or "attachment", len(content))
        if reason:
            rejected.append(reason)
        else:
            accepted.append((upload.filename or "attachment", content))

    # Irreplaceable, so it lands before anything that can fail.
    repo.save_request(record)

    client = get_graph_client()
    if client is None:
        log.warning("request %s stored locally; Graph is not configured", request_id)
        return RequestAccepted(
            **record.model_dump(),
            attachments_rejected=rejected,
            warning="Recorded, but Microsoft Graph is not configured here, so it "
                    "has not reached the SharePoint list the team works from."
                    + (" Attachments were not stored either."
                       if accepted else ""))

    try:
        site = client.resolve_site(settings.graph_site_url)
        created = create_request_item(client, site.site_id,
                                      build_fields(record, request_id=request_id))
    except RequestWriteError as exc:
        log.exception("request %s could not reach SharePoint", request_id)
        return RequestAccepted(
            **record.model_dump(),
            attachments_rejected=rejected,
            warning=f"{exc} It is saved here and can be pushed again once the "
                    f"problem is fixed; nothing has been lost.")
    except Exception as exc:                                  # noqa: BLE001
        log.exception("request %s: unexpected failure writing to SharePoint",
                      request_id)
        return RequestAccepted(
            **record.model_dump(),
            attachments_rejected=rejected,
            warning=f"Recorded here, but writing to SharePoint failed "
                    f"unexpectedly ({exc}). Nothing has been lost.")

    repo.mark_request_synced(request_id, created["id"])
    record.sharepoint_item_id = created["id"]
    record.synced = True
    log.info("request %s written to SharePoint as item %s", request_id, created["id"])

    # Attachments go up AFTER the item exists, so a file can never be orphaned
    # under a request id that was never recorded. A failure here costs the
    # file, not the request, and the requester is told which.
    stored: list[str] = []
    for filename, content in accepted:
        try:
            item = upload_attachment(client, site.site_id, request_id,
                                     filename, content)
            stored.append(item.get("name") or filename)
        except RequestWriteError as exc:
            log.warning("request %s: attachment failed: %s", request_id, exc)
            rejected.append(str(exc))

    warning = None
    if rejected:
        warning = ("The request is recorded. Some files were not stored: "
                   + " ".join(rejected))
    return RequestAccepted(**record.model_dump(), attachments=stored,
                           attachments_rejected=rejected, warning=warning)


@router.get("/unsynced", response_model=list[AssetRequest])
def list_unsynced(
    repo: AssetRepository = Depends(get_repo),
    user: CurrentUser = Depends(require_authenticated),
) -> list[AssetRequest]:
    """Requests held locally that never reached SharePoint.

    Without this the failure mode is invisible: a submission saved during an
    outage would sit in a file nobody thinks to look at.
    """
    reader = getattr(repo, "unsynced_requests", None)
    if reader is None:
        raise HTTPException(status_code=501,
                            detail="This repository does not store requests.")
    return reader()
