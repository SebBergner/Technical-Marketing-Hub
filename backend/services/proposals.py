"""Generate metadata proposals from the integrations we can already reach.

The catalogue's single biggest gap is `consensus_uuid`: SharePoint holds none,
so 98% of 452 assets cannot be shared externally. Filling that by hand is 446
lookups. This turns the existing Consensus matcher into reviewable proposals so
a person confirms rather than searches.

Nothing here writes to an asset. A proposal is a suggestion with a confidence
and a stated reason; a human decides. That is not caution for its own sake —
an earlier, looser matcher produced five confident-looking false positives
against the real catalogue, and the same class of error will recur.

Once Graph write access exists, accepted proposals are pushed to the SharePoint
column and arrive back through normal sync. Until then they queue as
`pending_writeback`.
"""
from __future__ import annotations

from backend.integrations.consensus import ConsensusClient, ConsensusDemo
from backend.models import (
    AssetSummary, MetadataProposal, ProposalOrigin, ProposalState,
)
from backend.services.consensus_match import STRONG_MATCH, reconcile

#: Field name on the Asset that these proposals target.
CONSENSUS_FIELD = "consensus_uuid"


def propose_consensus_uuids(
    assets: list[AssetSummary],
    demos: list[ConsensusDemo],
    threshold: float = 0.72,
    include_ambiguous: bool = True,
) -> list[MetadataProposal]:
    """Match the catalogue against Consensus and turn the result into proposals.

    Three of the reconciliation buckets become proposals, and they are NOT
    equivalent — the reviewer needs to know which is which:

      * `proposals`  — asset has no UUID, one confident match. The bulk.
      * `conflicts`  — asset already records a UUID that disagrees. Rare and
                       important: overwriting one silently would be worse than
                       leaving the gap.
      * `ambiguous`  — two candidates too close to separate. Carried with a
                       named runner-up so the reviewer sees the actual choice,
                       rather than being hidden and silently lost.
    """
    report = reconcile(assets, demos, threshold=threshold)
    current = {a.id: a.consensus_uuid for a in assets}
    out: list[MetadataProposal] = []

    def build(match, evidence: str) -> MetadataProposal:
        return MetadataProposal(
            asset_id=match.asset_id,
            asset_title=match.asset_title,
            field=CONSENSUS_FIELD,
            proposed_value=match.demo.uuid,
            current_value=current.get(match.asset_id),
            confidence=match.confidence,
            origin=ProposalOrigin.CONSENSUS,
            state=ProposalState.PENDING,
            evidence=evidence,
        )

    for match in report.proposals:
        strength = "strong" if match.confidence >= STRONG_MATCH else "probable"
        out.append(build(match, f"{strength} title match: {match.demo.title!r}"))

    for match in report.conflicts:
        out.append(build(
            match,
            f"CONFLICT — this asset already records {current.get(match.asset_id)!r}, "
            f"but the best title match is {match.demo.title!r}. Confirm which is right.",
        ))

    if include_ambiguous:
        for match in report.ambiguous:
            runner = match.runner_up.title if match.runner_up else "another demo"
            out.append(build(
                match,
                f"AMBIGUOUS — {match.demo.title!r} and {runner!r} score almost "
                f"the same. Pick one manually rather than trusting the ranking.",
            ))

    return _flag_shared_uuids(out)


def _flag_shared_uuids(proposals: list[MetadataProposal]) -> list[MetadataProposal]:
    """Warn when one Consensus demo is proposed for several assets.

    Observed on the live tenant: the LDK and VDK variants of a kit both match
    the same demo, because Consensus registers one recording while SharePoint
    keeps the two formats apart. Sometimes that is correct — one demo genuinely
    represents both — and sometimes only one should claim it. Either way the
    reviewer has to see it, because accepting both silently makes the UUID
    ambiguous as a join key, and the whole point of that column is to be one.
    """
    counts: dict[str, list[str]] = {}
    for proposal in proposals:
        if proposal.proposed_value:
            counts.setdefault(proposal.proposed_value, []).append(proposal.asset_id)

    for proposal in proposals:
        sharers = counts.get(proposal.proposed_value or "", [])
        if len(sharers) > 1:
            others = [a for a in sharers if a != proposal.asset_id]
            proposal.evidence = (
                f"SHARED UUID — this demo is also proposed for {len(others)} other "
                f"asset(s): {', '.join(others[:3])}. A Consensus UUID is a join key, "
                f"so confirm which asset should own it. {proposal.evidence}"
            )
    return proposals


def generate_all(assets: list[AssetSummary], client: ConsensusClient,
                 threshold: float = 0.72, limit: int = 2000) -> list[MetadataProposal]:
    """Run every proposal source currently available.

    Only Consensus today. The filename parser was dropped after measuring the
    real catalogue: SharePoint already carries product, type, segment and
    language as managed columns at 100% coverage, and the video filenames turned
    out to be far less regular than the mockup's curated titles suggested.
    Brightcove would be a third source if API access is confirmed.
    """
    demos = client.list_demos(limit=limit)
    return propose_consensus_uuids(assets, demos, threshold=threshold)
