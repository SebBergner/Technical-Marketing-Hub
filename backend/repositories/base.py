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

from backend.models import Asset, AssetSummary, Facets, Page

SortKey = Literal["recent", "most_viewed", "title"]


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
    customer_facing: bool | None = None
    has_narrated_audio: bool | None = None
    has_consensus_uuid: bool | None = None
    rail: str | None = None
    editor_picks_only: bool = False
    sort: SortKey = "recent"
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
    def get(self, asset_id: str) -> Asset | None: ...

    @abstractmethod
    def facets(self) -> Facets: ...

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
