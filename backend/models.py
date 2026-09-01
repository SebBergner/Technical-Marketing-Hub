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


class ResourceKind(str, Enum):
    """What a file inside an asset folder is.

    Derived from the extension. The Demo Catalog holds ~3,400 files ending
    `.1` `.2` `.3` — Creo's versioned CAD format (`part.prt.1`), which is why
    a plain extension lookup is not enough.
    """
    VIDEO = "video"
    DOCUMENT = "document"      # docx, pptx, pdf
    DATASET = "dataset"        # zip, rar, 7z
    CAD = "cad"                # .creo, .xpr, .prt.N, .asm.N, .drw.N
    IMAGE = "image"
    OTHER = "other"


class Audience(str, Enum):
    """Who a resource may be shown to.

    PTC's own file naming carries this: 54% of the 1,219 catalogue videos are
    marked `Customer Facing`/`CF` or `Internal Only`/`Training`. It is a
    property of the individual file, not of the asset — one demo kit routinely
    ships both cuts.
    """
    CUSTOMER_FACING = "customer_facing"
    INTERNAL = "internal"
    UNKNOWN = "unknown"


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


class AssetResource(BaseModel):
    """One file inside an asset folder."""
    name: str
    kind: ResourceKind
    audience: Audience = Audience.UNKNOWN
    subfolder: str | None = None       # path below the asset folder, None = root
    extension: str | None = None
    has_audio: bool | None = None      # only when the filename says so


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
    #: Which platform this came from: "sharepoint", "consensus", "seed".
    #: The Portal is a federated index, so the UI labels every result with its
    #: origin — a demo kit to run and a recorded video to send are different
    #: things, and a reader must be able to tell them apart at a glance.
    source: str = "sharepoint"
    title: str
    description: str | None = None

    products: list[str] = Field(default_factory=list)
    #: The families those products roll up to, derived by
    #: backend.services.taxonomy. On the summary because the UI needs it per
    #: card -- colouring a cover, grouping a grid -- and a client that
    #: re-derives it from the product strings gets it wrong: "KEPServerEX" is
    #: Kepware and says so nowhere in its name. One rule, in one place.
    product_families: list[str] = Field(default_factory=list)
    funnel_stage: FunnelStage | None = None
    content_depth: ContentDepth | None = None
    language: str = "en"
    segment: str | None = None                # CAD / PLM / IPL
    industry: str | None = None
    value_drivers: list[str] = Field(default_factory=list)
    #: Free-form labels from the source platform, stored verbatim.
    #:
    #: Consensus maintains these by hand and a single demo's tags routinely
    #: span four of our dimensions at once — "PLM, Teaser, Prospecting,
    #: Windchill" is segment, depth, funnel stage and product. They are kept
    #: raw as well as classified, because the classifier only recognises
    #: vocabularies we have verified, and dropping the rest would throw away
    #: the signal a person deliberately added.
    tags: list[str] = Field(default_factory=list)

    customer_facing: bool = True
    has_narrated_audio: bool | None = None    # gates external sharing for video
    named_customer: str | None = None

    uploaded_at: date | None = None
    duration_seconds: int | None = None
    thumbnail_url: str | None = None
    #: Where to open this on its own platform. On list responses because a grid
    #: card links out; a Consensus result is useless without it.
    web_url: str | None = None

    # cross-references — the four ID spaces the Portal exists to correlate
    source_item_id: str | None = None         # SharePoint list item
    brightcove_id: str | None = None          # where the stream comes from
    consensus_uuid: str | None = None         # how it goes out externally

    stats: AssetStats = Field(default_factory=AssetStats)
    #: Views recorded by the SOURCE platform, not by us.
    #:
    #: Kept apart from `stats.views` on purpose. `stats` is Portal-owned — our
    #: own counters, which a sync must never overwrite — while this arrives
    #: with the record and is replaced wholesale like any other mirrored field.
    #: Writing Consensus's `usage` into stats.views silently discarded it,
    #: because Portal-owned data is not part of the mirror.
    external_views: int | None = None

    #: Whether a Value Roadmap exists, without shipping the whole thing in list
    #: responses. Lets the UI show an honest "not indexed yet" state in a grid.
    has_roadmap: bool = False

    #: Resource counts, cheap enough for list responses. The resources
    #: themselves only travel on the detail endpoint.
    resource_count: int = 0
    video_count: int = 0
    #: Complete count per ResourceKind, including kinds not listed individually.
    resource_counts: dict[str, int] = Field(default_factory=dict)

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
    rails: list[str] = Field(default_factory=list)
    is_editor_pick: bool = False

    #: Only the kinds a person would browse. CAD is excluded — 42% of the
    #: catalogue's files are Creo version files (`part.prt.1`) that nobody picks
    #: from a list; `resource_counts` still reports them.
    resources: list[AssetResource] = Field(default_factory=list)
    #: Filename of the video that represents this asset.
    #:
    #: Resolved automatically when the folder holds exactly one video, or
    #: exactly one marked Customer Facing — together that covers 281 of the 396
    #: assets that have any video. The remaining 122 need a human to choose, so
    #: this stays None rather than guessing.
    main_video: str | None = None


# ------------------------------------------------------- metadata proposals
class ProposalState(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    #: Confirmed by a human AND written back to SharePoint. Only reachable once
    #: Graph write access exists.
    WRITTEN = "written"


class ProposalOrigin(str, Enum):
    CONSENSUS = "consensus"
    BRIGHTCOVE = "brightcove"
    FILENAME = "filename"
    MANUAL = "manual"


class MetadataProposal(BaseModel):
    """A suggested value for one field of one asset, awaiting confirmation.

    Never applied automatically. Matching against the live Consensus tenant
    produced confident-looking false positives before the matcher was
    tightened, and the same class of error will recur — so a human decides,
    and the confidence exists to let them triage lowest-first.
    """
    model_config = ConfigDict(from_attributes=True)

    asset_id: str
    asset_title: str | None = None
    field: str
    proposed_value: str | None = None
    #: What the asset currently holds, so a reviewer sees the actual change.
    current_value: str | None = None
    confidence: float | None = None
    origin: ProposalOrigin
    state: ProposalState = ProposalState.PENDING
    #: Human-readable justification, e.g. the matched Consensus demo title.
    evidence: str | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
    #: When the accepted value reached SharePoint. Distinct from decided_at:
    #: acceptance and write-back are separate steps that can be days apart.
    written_at: datetime | None = None


class ProposalSummary(BaseModel):
    total: int = 0
    by_state: dict[str, int] = Field(default_factory=dict)
    by_field: dict[str, int] = Field(default_factory=dict)
    by_origin: dict[str, int] = Field(default_factory=dict)
    #: Accepted but not yet pushed to SharePoint — the Graph write backlog.
    pending_writeback: int = 0


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
    #: Which platform results come from. Always present, so the UI can label
    #: and filter by origin without a second call.
    sources: list[FacetValue] = Field(default_factory=list)
    #: The one product filter that reaches BOTH platforms. SharePoint records
    #: the specific module ("Windchill PDMLink") and Consensus the brand
    #: ("Windchill"); only the family is common to both.
    product_families: list[FacetValue] = Field(default_factory=list)
    #: Consensus's hand-maintained labels. Kept as their own facet rather than
    #: folded into the others, because a tag can mean anything and pretending
    #: otherwise would put unrelated content behind a filter.
    tags: list[FacetValue] = Field(default_factory=list)
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
    #: none | footage | story — the form's own values, mapped to readable
    #: labels on the way into SharePoint.
    customer_involvement: str | None = None
    named_customer: str | None = None
    distribution_channels: list[str] = Field(default_factory=list)
    #: Derived from the channels by CHANNEL_TO_DEPTH, and carried so the team
    #: can see what the requester was told to expect.
    content_depth: ContentDepth | None = None
    recommendations: list[RecommendedAsset] = Field(default_factory=list)
    needed_by: date | None = None
    #: Why that date — "product launch, trade show, exec review". A deadline
    #: with a reason behind it can be negotiated; one without cannot.
    compelling_event: str | None = None
    starting_materials: list[str] = Field(default_factory=list)
    requester_name: str | None = None
    requester_email: str | None = None
    requester_team: str | None = None
    notes: str | None = None


class AssetRequest(AssetRequestCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    submitted_at: datetime
    status: str = "new"
    #: The list item this became, once SharePoint has it. None means the local
    #: copy is the only one — see `synced`.
    sharepoint_item_id: str | None = None
    #: False when SharePoint could not be reached. The submission is safe
    #: either way; this is what says a retry is owed.
    synced: bool = False
