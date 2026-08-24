"""Metadata proposal generation, storage and review.

The proposal loop exists because 446 of 452 assets have no Consensus UUID and
filling them by hand is 446 lookups. Its correctness rests on one property:
**nothing is ever applied automatically.** These tests hold that line, and they
run against both storage backends.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import app
from backend.deps import get_repo
from backend.integrations.consensus import ConsensusDemo, StubConsensusClient
from backend.models import (
    Asset, AssetType, MetadataProposal, ProposalOrigin, ProposalState,
)
from backend.repositories.json_repo import JsonAssetRepository
from backend.repositories.sql_repo import SqlAssetRepository
from backend.routers.curation import get_client
from backend.services.proposals import CONSENSUS_FIELD, propose_consensus_uuids
from backend.tables import Base


def asset(asset_id, title, uuid=None):
    return Asset(id=asset_id, type=AssetType.LDK, title=title, consensus_uuid=uuid)


def demo(uuid, title):
    return ConsensusDemo(uuid=uuid, title=title, is_published=True)


# ───────────────────────────────────────────────────── generation (pure)
def test_confident_match_becomes_a_pending_proposal():
    proposals = propose_consensus_uuids(
        [asset("a1", "Windchill Overview VDK v.2")],
        [demo("u1", "Windchill Overview VDK v.2")])

    assert len(proposals) == 1
    p = proposals[0]
    assert p.field == CONSENSUS_FIELD
    assert p.proposed_value == "u1"
    assert p.state == ProposalState.PENDING
    assert p.origin == ProposalOrigin.CONSENSUS
    assert p.confidence == 1.0
    assert "strong title match" in p.evidence


def test_no_match_produces_no_proposal():
    """A gap is better than a wrong join key."""
    assert propose_consensus_uuids(
        [asset("a1", "Something Nobody Registered")],
        [demo("u1", "Completely Unrelated Demo")]) == []


def test_existing_uuid_that_disagrees_is_flagged_as_conflict():
    """Never silently overwrite a UUID a human already recorded."""
    proposals = propose_consensus_uuids(
        [asset("a1", "Windchill Overview", uuid="already-set")],
        [demo("u1", "Windchill Overview")])

    assert len(proposals) == 1
    assert "CONFLICT" in proposals[0].evidence
    assert proposals[0].current_value == "already-set"
    assert proposals[0].state == ProposalState.PENDING


def test_shared_uuid_across_assets_is_flagged():
    """Seen live: the LDK and VDK variants of a kit match the same demo.

    A Consensus UUID is a join key — accepting both silently would make it
    ambiguous, defeating the column's whole purpose.
    """
    proposals = propose_consensus_uuids(
        [asset("a-ldk", "Windchill AI Assistant LDK"),
         asset("a-vdk", "Windchill AI Assistant VDK")],
        [demo("shared-1", "Windchill AI Assistant")])

    assert len(proposals) == 2
    assert all("SHARED UUID" in p.evidence for p in proposals)
    assert "a-vdk" in proposals[0].evidence
    assert "a-ldk" in proposals[1].evidence


def test_unique_uuid_is_not_flagged_as_shared():
    proposals = propose_consensus_uuids(
        [asset("a1", "Windchill Overview VDK v.2")],
        [demo("u1", "Windchill Overview VDK v.2")])
    assert "SHARED UUID" not in proposals[0].evidence


# ─────────────────────────────────────────────── storage, both backends
@pytest.fixture(params=["json", "sql"])
def repo(request, tmp_path):
    if request.param == "json":
        return JsonAssetRepository(str(tmp_path))
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return SqlAssetRepository(sessionmaker(bind=engine, expire_on_commit=False)())


def make_proposal(asset_id="a1", value="u1", confidence=0.9):
    return MetadataProposal(
        asset_id=asset_id, asset_title=f"Asset {asset_id}", field=CONSENSUS_FIELD,
        proposed_value=value, confidence=confidence,
        origin=ProposalOrigin.CONSENSUS, state=ProposalState.PENDING)


def test_save_and_list(repo):
    assert repo.save_proposals([make_proposal("a1"), make_proposal("a2")]) == 2
    page = repo.list_proposals()
    assert page.total == 2
    assert {p.asset_id for p in page.items} == {"a1", "a2"}


def test_listed_lowest_confidence_first(repo):
    """Reviewer time belongs on the uncertain ones."""
    repo.save_proposals([
        make_proposal("high", confidence=0.99),
        make_proposal("low", confidence=0.73),
        make_proposal("mid", confidence=0.85),
    ])
    assert [p.asset_id for p in repo.list_proposals().items] == ["low", "mid", "high"]


def test_accept_then_reject_are_recorded(repo):
    repo.save_proposals([make_proposal("a1")])

    decided = repo.decide_proposal("a1", CONSENSUS_FIELD, "accepted", "me@ptc.com")
    assert decided.state == ProposalState.ACCEPTED
    assert decided.decided_by == "me@ptc.com"
    assert decided.decided_at is not None

    assert repo.list_proposals(state="accepted").total == 1
    assert repo.list_proposals(state="pending").total == 0


def test_deciding_a_missing_proposal_returns_none(repo):
    assert repo.decide_proposal("nope", CONSENSUS_FIELD, "accepted", "me") is None


def test_regenerating_never_clobbers_a_human_decision(repo):
    """Re-running the generator must not reopen a settled question."""
    repo.save_proposals([make_proposal("a1", value="u1")])
    repo.decide_proposal("a1", CONSENSUS_FIELD, "rejected", "me@ptc.com")

    written = repo.save_proposals([make_proposal("a1", value="u-different")])

    assert written == 0, "a decided proposal must be left alone"
    stored = repo.list_proposals().items[0]
    assert stored.state == ProposalState.REJECTED
    assert stored.proposed_value == "u1", "the rejected value must not be replaced"


def test_regenerating_does_refresh_pending_ones(repo):
    repo.save_proposals([make_proposal("a1", value="u1")])
    assert repo.save_proposals([make_proposal("a1", value="u2")]) == 1
    assert repo.list_proposals().items[0].proposed_value == "u2"


def test_summary_counts_the_writeback_backlog(repo):
    repo.save_proposals([make_proposal("a1"), make_proposal("a2"), make_proposal("a3")])
    repo.decide_proposal("a1", CONSENSUS_FIELD, "accepted", "me")
    repo.decide_proposal("a2", CONSENSUS_FIELD, "rejected", "me")

    summary = repo.proposal_summary()
    assert summary.total == 3
    assert summary.by_state == {"accepted": 1, "rejected": 1, "pending": 1}
    assert summary.by_field == {CONSENSUS_FIELD: 3}
    # Accepted but not yet pushed to SharePoint.
    assert summary.pending_writeback == 1


# ──────────────────────────────────────────────────────── API endpoints
FIXTURE_ASSETS = [
    Asset(id="wc-overview", type=AssetType.VDK, title="Windchill Overview"),
    Asset(id="unmatched", type=AssetType.LDK, title="Nothing Like This Exists"),
]
FIXTURE_DEMOS = [demo("uuid-wc", "Windchill Overview")]


@pytest.fixture()
def api(tmp_path):
    store = JsonAssetRepository(str(tmp_path))
    store.replace_source_rows(FIXTURE_ASSETS, "test")
    # Pin the stub: a developer's .env must never make tests call production.
    app.dependency_overrides[get_client] = lambda: StubConsensusClient(list(FIXTURE_DEMOS))
    app.dependency_overrides[get_repo] = lambda: store
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def test_propose_endpoint_stores_and_summarises(api):
    body = api.post("/api/curation/propose").json()
    assert body["generated"] == 1
    assert body["stored"] == 1
    assert body["summary"]["by_state"] == {"pending": 1}


def test_accepting_does_not_modify_the_asset(api):
    """SharePoint owns the value. Writing it locally would be overwritten by
    the next sync, so an accepted proposal only queues."""
    api.post("/api/curation/propose")

    decision = api.post(
        f"/api/curation/proposals/wc-overview/{CONSENSUS_FIELD}/accept").json()
    assert decision["proposal"]["state"] == "accepted"
    assert decision["awaiting_writeback"] is True

    asset_after = api.get("/api/assets/wc-overview").json()
    assert asset_after["consensus_uuid"] is None, \
        "the asset must not change until SharePoint does"


def test_invalid_decision_is_rejected(api):
    api.post("/api/curation/propose")
    assert api.post(
        f"/api/curation/proposals/wc-overview/{CONSENSUS_FIELD}/maybe").status_code == 422


def test_deciding_unknown_proposal_404s(api):
    assert api.post(
        f"/api/curation/proposals/ghost/{CONSENSUS_FIELD}/accept").status_code == 404


def test_proposals_endpoint_filters_by_state(api):
    api.post("/api/curation/propose")
    assert api.get("/api/curation/proposals?state=pending").json()["total"] == 1
    assert api.get("/api/curation/proposals?state=accepted").json()["total"] == 0
    assert api.get("/api/curation/proposals?state=nonsense").status_code == 422
