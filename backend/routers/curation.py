"""Metadata curation — generate, review and decide on proposals.

Backs the human half of the enrichment loop:

    Consensus match  ->  proposal (confidence + evidence)
                          |
                          v
                    human accepts / rejects
                          |
                          v
                 written back to SharePoint  [needs Graph write]

No proposal is ever applied to an asset by this module. SharePoint stays the
system of record, so an accepted proposal queues as `pending_writeback` until
Graph write access exists and a job pushes it to the column — after which it
returns through normal sync.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.deps import CurrentUser, get_current_user, get_repo
from backend.integrations.consensus import (
    ConsensusClient, ConsensusError, get_consensus_client,
)
from backend.models import MetadataProposal, Page, ProposalState, ProposalSummary
from backend.repositories.base import AssetQuery, AssetRepository
from backend.services.proposals import generate_all

router = APIRouter(prefix="/api/curation", tags=["curation"])


def get_client() -> ConsensusClient:
    return get_consensus_client()


class ProposeResponse(BaseModel):
    generated: int
    stored: int
    #: Generated but not stored, because a human had already decided them.
    skipped_already_decided: int
    summary: ProposalSummary


class DecisionResponse(BaseModel):
    proposal: MetadataProposal
    #: True while the value exists only in the Portal. Clears when a write-back
    #: job pushes it to SharePoint.
    awaiting_writeback: bool


@router.get("/summary", response_model=ProposalSummary)
def summary(repo: AssetRepository = Depends(get_repo)):
    """Counts by state, field and origin, plus the write-back backlog."""
    return repo.proposal_summary()


@router.post("/propose", response_model=ProposeResponse)
def propose(
    threshold: float = Query(default=0.72, ge=0.0, le=1.0),
    repo: AssetRepository = Depends(get_repo),
    client: ConsensusClient = Depends(get_client),
):
    """Regenerate proposals from the integrations.

    Safe to re-run: proposals a human has already accepted or rejected are left
    untouched, so a rerun only refreshes what is still pending.
    """
    assets = repo.list(AssetQuery(limit=5000)).items
    try:
        proposals = generate_all(assets, client, threshold=threshold)
    except ConsensusError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    stored = repo.save_proposals(proposals)
    return ProposeResponse(
        generated=len(proposals),
        stored=stored,
        skipped_already_decided=len(proposals) - stored,
        summary=repo.proposal_summary(),
    )


@router.get("/proposals", response_model=Page[MetadataProposal])
def list_proposals(
    state: str | None = Query(default=None, pattern="^(pending|accepted|rejected|written)$"),
    field: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    repo: AssetRepository = Depends(get_repo),
):
    """Lowest confidence first — reviewer time belongs on the uncertain ones."""
    return repo.list_proposals(state=state, field=field, limit=limit, offset=offset)


@router.post("/proposals/{asset_id}/{field}/{decision}", response_model=DecisionResponse)
def decide(
    asset_id: str,
    field: str,
    decision: str,
    repo: AssetRepository = Depends(get_repo),
    user: CurrentUser = Depends(get_current_user),
):
    """Accept or reject one proposal.

    Accepting does NOT modify the asset. SharePoint owns the value, so the
    decision is recorded and queued; the Portal would otherwise hold a value
    that the next sync silently overwrites.
    """
    if decision not in {"accept", "reject"}:
        raise HTTPException(status_code=422, detail="decision must be accept or reject")

    state = ProposalState.ACCEPTED if decision == "accept" else ProposalState.REJECTED
    proposal = repo.decide_proposal(asset_id, field, state.value, user.email)
    if proposal is None:
        raise HTTPException(
            status_code=404,
            detail=f"no proposal for asset '{asset_id}' field '{field}'")

    return DecisionResponse(
        proposal=proposal,
        awaiting_writeback=(proposal.state == ProposalState.ACCEPTED),
    )
