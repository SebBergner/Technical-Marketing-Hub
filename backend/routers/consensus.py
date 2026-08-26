"""Consensus endpoints: lookup, reconciliation, and external sharing."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.deps import CurrentUser, get_repo, require_authenticated
from backend.integrations.consensus import (
    ConsensusClient, ConsensusError, ConsensusSchemaUnknown, ShareRecipient,
    get_consensus_client,
)
from backend.repositories.base import AssetQuery, AssetRepository
from backend.services.consensus_match import reconcile

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["consensus"])


def get_client() -> ConsensusClient:
    return get_consensus_client()


# ---------------------------------------------------------------- responses
class DemoOut(BaseModel):
    uuid: str
    title: str
    description: str | None = None
    preview_link: str | None = None
    is_published: bool | None = None
    folder: str | None = None
    #: Not available from demo/search or demosDetails — engagement lives behind
    #: the reports endpoints. Left null rather than faked.
    view_count: int | None = None


class MatchOut(BaseModel):
    asset_id: str
    asset_title: str
    demo_uuid: str
    demo_title: str
    confidence: float
    ambiguous: bool = False
    runner_up_title: str | None = None


class RecipientIn(BaseModel):
    email: str
    first_name: str | None = None
    last_name: str | None = None


class ShareRequest(BaseModel):
    asset_id: str
    #: Required by Consensus for a trackable DemoBoard — the customer or
    #: prospect it is for. Ignored when trackable is false.
    organization: str | None = None
    recipients: list[RecipientIn] = []
    opportunity: str | None = None
    title: str | None = None
    trackable: bool = True
    #: Creates the send flagged as a test, so the share path can be exercised
    #: end-to-end without polluting real reporting.
    is_test: bool = False


class ShareResponse(BaseModel):
    url: str
    demo_uuid: str
    asset_id: str
    #: demoboard = trackable, per-recipient · marketing = generated link
    #: preview = the demo's own link. Callers must know which they got.
    kind: str
    send_demo_uuid: str | None = None
    is_test: bool = False
    recipients: list[RecipientIn] = []


def _demo_out(demo) -> DemoOut:
    return DemoOut(uuid=demo.uuid, title=demo.title, description=demo.description,
                   preview_link=demo.preview_link, is_published=demo.is_published,
                   folder=demo.folder, view_count=demo.view_count)


def _match_out(match) -> MatchOut:
    return MatchOut(
        asset_id=match.asset_id, asset_title=match.asset_title,
        demo_uuid=match.demo.uuid, demo_title=match.demo.title,
        confidence=match.confidence, ambiguous=match.ambiguous,
        runner_up_title=match.runner_up.title if match.runner_up else None,
    )


# ------------------------------------------------------------------ status
@router.get("/consensus/status")
def status(client: ConsensusClient = Depends(get_client)):
    """Is the real client active, or are we still on the stub?"""
    return {"configured": client.is_configured(),
            "mode": "http" if client.is_configured() else "stub"}


@router.get("/consensus/probe")
def probe(client: ConsensusClient = Depends(get_client)):
    """Diagnostic — returns the raw upstream payload and how we mapped it.

    Run this first with real credentials. The response shows the actual field
    names, which is what `HttpConsensusClient._to_demo()` has to be corrected
    against; the mapping there is currently an educated guess.
    """
    try:
        return client.probe()
    except ConsensusError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ------------------------------------------------------------------ lookup
@router.get("/consensus/search", response_model=list[DemoOut])
def search(
    q: str = Query(min_length=2, description="free text over demo title and description"),
    limit: int = Query(default=10, ge=1, le=50),
    client: ConsensusClient = Depends(get_client),
):
    """Backs 'Check Consensus for something similar' in the request form.

    Replaces the mockup's hardcoded EXISTING_ASSET_MATCHES, which only ever had
    three Windchill rows and keyed off the first selected product.
    """
    try:
        return [_demo_out(d) for d in client.search(q, limit=limit)]
    except ConsensusError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ---------------------------------------------------------- reconciliation
@router.get("/consensus/reconcile")
def reconcile_catalogues(
    threshold: float = Query(default=0.72, ge=0.0, le=1.0),
    repo: AssetRepository = Depends(get_repo),
    client: ConsensusClient = Depends(get_client),
):
    """Gap report in both directions.

    - `portal_only`    — no Consensus counterpart, so it cannot be shared externally
    - `consensus_only` — registered in Consensus but absent from the Portal
    - `proposals`      — confident title matches for assets with no UUID yet
    - `conflicts`      — a recorded UUID that disagrees with the best match
    - `ambiguous`      — two plausible candidates; we refuse to choose

    Nothing is written. Proposals are for a human to confirm.
    """
    try:
        demos = client.list_demos()
    except ConsensusError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    assets = repo.list(AssetQuery(limit=1000)).items
    report = reconcile(assets, demos, threshold=threshold)

    return {
        "summary": report.summary(),
        "threshold": threshold,
        "proposals": [_match_out(m) for m in report.proposals],
        "conflicts": [_match_out(m) for m in report.conflicts],
        "ambiguous": [_match_out(m) for m in report.ambiguous],
        "portal_only": [
            {"asset_id": a.id, "title": a.title, "type": a.type.value}
            for a in report.portal_only
        ],
        "consensus_only": [_demo_out(d) for d in report.consensus_only],
    }


# ------------------------------------------------------------------- share
@router.post("/share/consensus", response_model=ShareResponse)
def share_to_consensus(
    body: ShareRequest,
    repo: AssetRepository = Depends(get_repo),
    client: ConsensusClient = Depends(get_client),
    user: CurrentUser = Depends(require_authenticated),
):
    """Generate a trackable DemoBoard link for an asset.

    409 when the asset has no `consensus_uuid`. That is not a validation
    nicety — Consensus can only send content already registered there, so the
    share is genuinely impossible and the UI must say so rather than fake a link.
    """
    asset = repo.get(body.asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"no asset with id '{body.asset_id}'")

    if not asset.consensus_uuid:
        raise HTTPException(
            status_code=409,
            detail=("This asset is not registered in Consensus, so it cannot be shared "
                    "externally. Register it in Consensus first, then record its Demo UUID."),
        )
    if not asset.customer_facing:
        raise HTTPException(
            status_code=409,
            detail="This asset is marked internal-only and cannot be shared with customers.",
        )

    if body.trackable and not body.organization:
        raise HTTPException(
            status_code=422,
            detail=("Consensus requires an 'organization' — the customer or prospect this "
                    "DemoBoard is for — to create a trackable share. Send trackable=false "
                    "for an untracked link instead."),
        )

    try:
        link = client.create_share_link(
            asset.consensus_uuid,
            trackable=body.trackable,
            organization=body.organization,
            recipients=[ShareRecipient(email=r.email, first_name=r.first_name,
                                       last_name=r.last_name) for r in body.recipients],
            opportunity=body.opportunity,
            title=body.title or asset.title,
            is_test=body.is_test,
        )
    except ConsensusSchemaUnknown as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except ConsensusError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Test sends are not real distribution — do not record them as such.
    if not link.is_test:
        repo.record_share_event(asset.id, "consensus", link.url, user.email)
        repo.increment_stat(asset.id, "shares")

    return ShareResponse(
        url=link.url, demo_uuid=link.demo_uuid, asset_id=asset.id, kind=link.kind,
        send_demo_uuid=link.send_demo_uuid, is_test=link.is_test,
        recipients=[RecipientIn(email=r.email, first_name=r.first_name,
                                last_name=r.last_name) for r in link.recipients],
    )
