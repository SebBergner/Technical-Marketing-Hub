"""Pydantic models — the shape of data at the application's edges.

These describe what the REST API returns and what the integrations must produce.
They are deliberately separate from the SQLAlchemy tables in `tables.py`: the
tables describe storage (and are split mirror/owned), while these describe the
single joined view the frontend consumes.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


# ------------------------------------------------------------------ taxonomy
class AssetType(str, Enum):
    VIDEO = "video"
    LDK = "ldk"          # Live Demo Kit
    VDK = "vdk"          # Video Demo Kit  (expansion still to be confirmed)
    VM = "vm"            # Virtual Machine
    WIKI = "wiki"        # present in the mockup, absent from the requirements doc


class FunnelStage(str, Enum):
    AWARENESS = "Awareness"
    CONSIDERATION = "Consideration"
    DECISION = "Decision"
    POST_SALE = "Post-Sale"


class ContentDepth(str, Enum):
    """Same vocabulary the Request-New-Asset form recommends, so what gets
    requested and what gets tagged are one taxonomy."""
    TEASER = "Teaser"
    OVERVIEW = "Overview"
    EXPLAINER = "Explainer"
    WALKTHROUGH = "Walkthrough"


class LifecyclePhase(str, Enum):
    PLAN = "PLAN"
    DEFINE = "DEFINE"
    DESIGN = "DESIGN"
    IMPROVE = "IMPROVE"
    VALIDATE = "VALIDATE"


# ------------------------------------------------------------------ sub-models
class Capability(BaseModel):
    phase: LifecyclePhase
    title: str
    chips: list[str] = Field(default_factory=list)
    narration: str | None = None


class ValueRoadmap(BaseModel):
    """AI-derived. Never hand-entered, and null until the asset is indexed —
    the UI shows an honest 'not indexed yet' state rather than inventing one."""
    description: str | None = None
    value_drivers: list[str] = Field(default_factory=list)
    capabilities: list[Capability] = Field(default_factory=list)
    indexed_at: datetime | None = None
    model: str | None = None


class AssetStats(BaseModel):
    views: int = 0
    downloads: int = 0
    launches: int = 0
    shares: int = 0


# ------------------------------------------------------------------ asset
class AssetBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str                                   # stable slug — never changes, never reused
    type: AssetType
    title: str
    description: str | None = None

    products: list[str] = Field(default_factory=list)
    funnel_stage: FunnelStage | None = None
    content_depth: ContentDepth | None = None
    language: str = "en"
    segment: str | None = None                # CAD / PLM / IPL
    industry: str | None = None
    value_drivers: list[str] = Field(default_factory=list)

    customer_facing: bool = True
    has_narrated_audio: bool | None = None    # gates external sharing for video
    named_customer: str | None = None

    uploaded_at: date | None = None
    duration_seconds: int | None = None
    thumbnail_url: str | None = None

    # cross-references — the four ID spaces the Portal exists to correlate
    source_item_id: str | None = None         # SharePoint list item
    brightcove_id: str | None = None          # where the stream comes from
    consensus_uuid: str | None = None         # how it goes out externally

    stats: AssetStats = Field(default_factory=AssetStats)

    #: Whether a Value Roadmap exists, without shipping the whole thing in list
    #: responses. Lets the UI show an honest "not indexed yet" state in a grid.
    has_roadmap: bool = False

    @property
    def can_share_externally(self) -> bool:
        """Consensus can only send content already registered there. Without a
        UUID the share is impossible, and the UI must say so rather than fake it."""
        return bool(self.consensus_uuid) and self.customer_facing


class AssetSummary(AssetBase):
    """What list endpoints return — no Value Roadmap, which is large."""


class Asset(AssetBase):
    """Full detail, including the derived index."""
    value_roadmap: ValueRoadmap | None = None
    web_url: str | None = None
    rails: list[str] = Field(default_factory=list)
    is_editor_pick: bool = False


# ------------------------------------------------------------------ facets
class FacetValue(BaseModel):
    value: str
    label: str | None = None
    count: int


class Facets(BaseModel):
    """Drives the sidebar counts and every filter dropdown, so neither is
    hardcoded in the markup any more."""
    types: list[FacetValue] = Field(default_factory=list)
    products: list[FacetValue] = Field(default_factory=list)
    funnel_stages: list[FacetValue] = Field(default_factory=list)
    segments: list[FacetValue] = Field(default_factory=list)
    industries: list[FacetValue] = Field(default_factory=list)
    value_drivers: list[FacetValue] = Field(default_factory=list)
    languages: list[FacetValue] = Field(default_factory=list)
    content_depths: list[FacetValue] = Field(default_factory=list)
    total: int = 0


# ------------------------------------------------------------------ paging
class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


# ------------------------------------------------------------------ requests
class RecommendedAsset(BaseModel):
    level: ContentDepth
    channels: list[str] = Field(default_factory=list)
    decision: str | None = None               # use-as-is | refresh | new


class AssetRequestCreate(BaseModel):
    asset_type: AssetType
    products: list[str] = Field(default_factory=list)
    brief: str | None = None
    narrative: str | None = None
    video_kind: str | None = None
    target_length: str | None = None
    named_customer: str | None = None
    distribution_channels: list[str] = Field(default_factory=list)
    recommendations: list[RecommendedAsset] = Field(default_factory=list)
    needed_by: date | None = None
    starting_materials: list[str] = Field(default_factory=list)
    requester_name: str | None = None
    requester_email: str | None = None
    requester_team: str | None = None


class AssetRequest(AssetRequestCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    submitted_at: datetime
    status: str = "new"
