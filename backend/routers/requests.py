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

from fastapi import APIRouter, Depends, HTTPException

from backend.auth import CurrentUser, require_authenticated
from backend.config import settings
from backend.deps import get_repo
from backend.integrations.graph.client import get_graph_client
from backend.integrations.graph.requests_list import (
    RequestWriteError, build_fields, create_request_item,
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


@router.post("", response_model=RequestAccepted, status_code=201)
def submit_request(
    body: AssetRequestCreate,
    repo: AssetRepository = Depends(get_repo),
    user: CurrentUser = Depends(require_authenticated),
) -> RequestAccepted:
    """Record a request locally, then push it to SharePoint."""
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

    # Irreplaceable, so it lands before anything that can fail.
    repo.save_request(record)

    client = get_graph_client()
    if client is None:
        log.warning("request %s stored locally; Graph is not configured", request_id)
        return RequestAccepted(
            **record.model_dump(),
            warning="Recorded, but Microsoft Graph is not configured here, so it "
                    "has not reached the SharePoint list the team works from.")

    try:
        site = client.resolve_site(settings.graph_site_url)
        created = create_request_item(client, site.site_id,
                                      build_fields(record, request_id=request_id))
    except RequestWriteError as exc:
        log.exception("request %s could not reach SharePoint", request_id)
        return RequestAccepted(
            **record.model_dump(),
            warning=f"{exc} It is saved here and can be pushed again once the "
                    f"problem is fixed; nothing has been lost.")
    except Exception as exc:                                  # noqa: BLE001
        log.exception("request %s: unexpected failure writing to SharePoint",
                      request_id)
        return RequestAccepted(
            **record.model_dump(),
            warning=f"Recorded here, but writing to SharePoint failed "
                    f"unexpectedly ({exc}). Nothing has been lost.")

    repo.mark_request_synced(request_id, created["id"])
    record.sharepoint_item_id = created["id"]
    record.synced = True
    log.info("request %s written to SharePoint as item %s", request_id, created["id"])
    return RequestAccepted(**record.model_dump())


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
