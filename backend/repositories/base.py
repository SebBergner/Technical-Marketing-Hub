"""Repository interface.

Filtering is expressed as an `AssetQuery` object rather than a pile of keyword
arguments, so the same filter spec can be pushed down into SQL — or, later,
into whatever else backs the catalogue — instead of loading everything into
memory and filtering in Python.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

from backend.models import (
    Asset, AssetRequest, AssetSummary, Facets, MetadataProposal, Page,
    ProposalSummary,
)

#: "relevance" degrades to "recent" when there is no search text, so it is one
#: concept rather than two and can safely be the default.
SortKey = Literal["relevance", "recent", "most_viewed", "title"]


@dataclass
class AssetQuery:
    text: str | None = None
    types: list[str] = field(default_factory=list)
    products: list[str] = field(default_factory=list)
    funnel_stages: list[str] = field(default_factory=list)
    segments: list[str] = field(default_factory=list)
    industries: list[str] = field(default_factory=list)
    value_drivers: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    content_depths: list[str] = field(default_factory=list)
    #: Which platforms to include: "sharepoint", "consensus".
    sources: list[str] = field(default_factory=list)
    #: The product filter that reaches both platforms. `products` matches the
    #: specific module and so is effectively SharePoint-only.
    product_families: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    customer_facing: bool | None = None
    has_narrated_audio: bool | None = None
    has_consensus_uuid: bool | None = None
    rail: str | None = None
    editor_picks_only: bool = False
    sort: SortKey = "relevance"
    limit: int = 50
    offset: int = 0


class AssetRepository(ABC):
    """Read and write the catalogue.

    Write methods exist because the Portal owns curation, stats and identity
    even though it does not own the content metadata. Note the deliberate
    asymmetry: `replace_source_rows` is the *only* way mirror data may be
    written, which is what keeps a sync run from destroying human-authored
    values (see tables.py).
    """

    @abstractmethod
    def list(self, query: AssetQuery) -> Page[AssetSummary]: ...

    @abstractmethod
    def save_request(self, request: "AssetRequest") -> None:
        """Append one intake submission.

        Append-only and irreplaceable: a request exists nowhere else until it
        reaches SharePoint, and it must survive that write failing.
        """

    @abstractmethod
    def mark_request_synced(self, request_id: str, item_id: str) -> None:
        """Record which SharePoint item a request became."""

    @abstractmethod
    def get(self, asset_id: str) -> Asset | None: ...

    @abstractmethod
    def facets(self, query: AssetQuery | None = None) -> Facets:
        """Counts over the whole catalogue, or over one filtered slice.

        Scoped counts are what make a filter panel honest. With Type=VDK
        chosen, "Creo (382)" is a lie -- 382 is the whole catalogue, and
        clicking it narrows to far fewer. The count has to describe what you
        would actually get.
        """

    @abstractmethod
    def rails(self) -> dict[str, list[str]]:
        """Gallery rail name -> ordered asset ids."""

    @abstractmethod
    def increment_stat(self, asset_id: str, stat: str, amount: int = 1) -> None: ...

    @abstractmethod
    def replace_source_rows(self, assets: list[Asset], source_system: str) -> int:
        """Wholesale-replace the mirror for one source system.

        Resolves or creates the stable identity for each item, so slugs survive
        across syncs. Portal-owned data is untouched.
        """

    # ---- Portal-owned writes. Kept separate from the mirror writer above so
    # ---- that a sync run physically cannot reach them.
    @abstractmethod
    def set_curation(self, asset_id: str, **fields) -> None:
        """Editorial state: is_editor_pick, rails, rail_order, notes."""

    @abstractmethod
    def set_roadmap(self, asset_id: str, roadmap: dict) -> None:
        """The AI-derived Value Roadmap index."""

    @abstractmethod
    def set_stats(self, asset_id: str, stats: dict) -> None:
        """Absolute counter values. Use increment_stat for deltas."""

    @abstractmethod
    def record_share_event(self, asset_id: str, channel: str,
                           target_ref: str | None, shared_by: str | None) -> None:
        """Append to the distribution log. Append-only — never rewritten."""

    # ---- Metadata proposals: suggested values awaiting human confirmation.
    # ---- Portal-owned, and never applied to an asset automatically.
    @abstractmethod
    def save_proposals(self, proposals: list[MetadataProposal]) -> int:
        """Upsert by (asset_id, field).

        A decision a human already made outranks a freshly generated
        suggestion, so rows not in `pending` are left alone.
        """

    @abstractmethod
    def list_proposals(self, state: str | None = None, field: str | None = None,
                       limit: int = 100, offset: int = 0) -> Page[MetadataProposal]:
        """Lowest confidence first — reviewers should spend time on the
        uncertain ones, not confirm the obvious."""

    @abstractmethod
    def decide_proposal(self, asset_id: str, field: str, state: str,
                        decided_by: str | None) -> MetadataProposal | None:
        """Record accept/reject. Returns None if there is no such proposal."""

    @abstractmethod
    def mark_proposal_written(self, asset_id: str, field: str) -> MetadataProposal | None:
        """Record that an accepted value reached SharePoint.

        Separate from `decide_proposal` because it must NOT overwrite
        `decided_by` — who authorised a value and who ran the job that pushed
        it are different facts, and the first is the one worth keeping.
        """

    @abstractmethod
    def record_metadata_edit(self, asset_id: str, field: str, old_value: str | None,
                             new_value: str | None, changed_by: str,
                             write_status: str = "written",
                             error: str | None = None) -> None:
        """Append to the write-back audit trail.

        App-only Graph writes appear in SharePoint as the *application*, not the
        person, so SharePoint's own version history cannot answer "who did
        this". If we do not record it here, the answer is unrecoverable.
        """

    @abstractmethod
    def proposal_summary(self) -> ProposalSummary: ...
