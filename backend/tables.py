"""SQLAlchemy tables.

Two groups, and the split is load-bearing:

  MIRROR  — a rebuildable cache of what SharePoint holds. A sync run replaces
            these rows wholesale. Anything human-authored here is destroyed on
            the next sync, so nothing human-authored may live here.

  OWNED   — the Portal is the system of record. Sync must never touch these.
            `asset_identity` is the critical one: it pins a stable slug to a
            source item, which is what keeps every shared link alive when
            titles change or files move.

Only generic SQLAlchemy types are used, so the same models run against SQLite
locally and Azure SQL in production.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """Naive UTC. The DateTime columns are timezone-naive, and mixing aware
    and naive values is a classic source of silent comparison bugs."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


# ══════════════════════════════════════════════════════════ OWNED — identity
class AssetIdentity(Base):
    """Stable slug <-> source item. Assigned once, never regenerated.

    This is the table that protects shared links: SharePoint titles change and
    files move, but `asset_id` does not, so a URL handed to a colleague in
    March still resolves in December. Losing it breaks every link ever shared.
    """
    __tablename__ = "asset_identity"

    asset_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    source_system: Mapped[str] = mapped_column(String(20), default="seed")
    source_item_id: Mapped[str | None] = mapped_column(String(200))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime)  # soft delete; slug never reused

    __table_args__ = (
        UniqueConstraint("source_system", "source_item_id", name="uq_identity_source"),
    )


# ══════════════════════════════════════════════════════════ MIRROR
class AssetSource(Base):
    """Mirror of the SharePoint catalogue row. Replaced wholesale by sync."""
    __tablename__ = "asset_source"

    asset_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("asset_identity.asset_id"), primary_key=True
    )
    source_system: Mapped[str] = mapped_column(String(20), default="seed")
    etag: Mapped[str | None] = mapped_column(String(120))       # If-Match on write-back

    type: Mapped[str] = mapped_column(String(20), index=True)
    title: Mapped[str] = mapped_column(String(400), index=True)
    description: Mapped[str | None] = mapped_column(Text)

    products: Mapped[list | None] = mapped_column(JSON, default=list)
    funnel_stage: Mapped[str | None] = mapped_column(String(30), index=True)
    content_depth: Mapped[str | None] = mapped_column(String(20))
    language: Mapped[str] = mapped_column(String(10), default="en", index=True)
    segment: Mapped[str | None] = mapped_column(String(40), index=True)
    industry: Mapped[str | None] = mapped_column(String(120))
    value_drivers: Mapped[list | None] = mapped_column(JSON, default=list)

    customer_facing: Mapped[bool] = mapped_column(Boolean, default=True)
    has_narrated_audio: Mapped[bool | None] = mapped_column(Boolean)
    named_customer: Mapped[str | None] = mapped_column(String(200))

    uploaded_at: Mapped[date | None] = mapped_column(Date, index=True)
    modified_at: Mapped[datetime | None] = mapped_column(DateTime)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)

    thumbnail_url: Mapped[str | None] = mapped_column(String(600))
    web_url: Mapped[str | None] = mapped_column(String(1000))
    drive_item_id: Mapped[str | None] = mapped_column(String(200))  # thumbnails / downloadUrl

    brightcove_id: Mapped[str | None] = mapped_column(String(60))
    consensus_uuid: Mapped[str | None] = mapped_column(String(60), index=True)

    status: Mapped[str | None] = mapped_column(String(20))          # draft|published|retired
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    # An asset is a SharePoint folder; these describe the files inside it.
    resources: Mapped[list | None] = mapped_column(JSON, default=list)
    resource_counts: Mapped[dict | None] = mapped_column(JSON, default=dict)
    resource_count: Mapped[int] = mapped_column(Integer, default=0)
    video_count: Mapped[int] = mapped_column(Integer, default=0)
    main_video: Mapped[str | None] = mapped_column(String(400))


# ══════════════════════════════════════════════════════════ OWNED — the rest
class AssetCuration(Base):
    """Editorial decisions. Human-authored, so it cannot live in the mirror."""
    __tablename__ = "asset_curation"

    asset_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("asset_identity.asset_id"), primary_key=True
    )
    is_editor_pick: Mapped[bool] = mapped_column(Boolean, default=False)
    rails: Mapped[list | None] = mapped_column(JSON, default=list)
    rail_order: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)


class AssetValueRoadmap(Base):
    """AI-derived index. Expensive to compute, so it is stored, not recomputed."""
    __tablename__ = "asset_value_roadmap"

    asset_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("asset_identity.asset_id"), primary_key=True
    )
    description: Mapped[str | None] = mapped_column(Text)
    value_drivers: Mapped[list | None] = mapped_column(JSON, default=list)
    capabilities: Mapped[list | None] = mapped_column(JSON, default=list)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime)
    model: Mapped[str | None] = mapped_column(String(60))


class AssetStatsRow(Base):
    __tablename__ = "asset_stats"

    asset_id: Mapped[str] = mapped_column(
        String(80), ForeignKey("asset_identity.asset_id"), primary_key=True
    )
    views: Mapped[int] = mapped_column(Integer, default=0)
    downloads: Mapped[int] = mapped_column(Integer, default=0)
    launches: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)


class ShareEvent(Base):
    __tablename__ = "share_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[str] = mapped_column(String(80), index=True)
    channel: Mapped[str] = mapped_column(String(20))            # consensus | velocity
    target_ref: Mapped[str | None] = mapped_column(String(400))
    shared_by: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AssetRequestRow(Base):
    """Intake submissions — the one genuinely irreplaceable table here."""
    __tablename__ = "asset_request"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    requester_name: Mapped[str | None] = mapped_column(String(200))
    requester_email: Mapped[str | None] = mapped_column(String(200), index=True)
    requester_team: Mapped[str | None] = mapped_column(String(200))
    payload: Mapped[dict] = mapped_column(JSON)
    recommendations: Mapped[list | None] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)


class SyncState(Base):
    """Where the Graph delta cursor lives. One row per source system."""
    __tablename__ = "sync_state"

    source_system: Mapped[str] = mapped_column(String(20), primary_key=True)
    delta_token: Mapped[str | None] = mapped_column(Text)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    items_seen: Mapped[int | None] = mapped_column(Integer)


class MetadataProposal(Base):
    """Auto-derived label suggestions awaiting human confirmation.

    Populated by the filename parser and the Consensus/Brightcove matchers;
    drained by the curation UI. Confidence drives review order.
    """
    __tablename__ = "metadata_proposal"

    asset_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    field: Mapped[str] = mapped_column(String(60), primary_key=True)
    proposed_value: Mapped[str | None] = mapped_column(String(400))
    confidence: Mapped[float | None] = mapped_column()
    origin: Mapped[str] = mapped_column(String(30))     # filename|consensus|brightcove|manual
    state: Mapped[str] = mapped_column(String(20), default="pending")
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)


class MetadataEdit(Base):
    """Audit trail for write-back.

    App-only Graph writes appear in SharePoint as the application, not the
    person, so the real author is only recoverable if we record it ourselves.
    """
    __tablename__ = "metadata_edit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[str] = mapped_column(String(80), index=True)
    field: Mapped[str] = mapped_column(String(60))
    old_value: Mapped[str | None] = mapped_column(String(400))
    new_value: Mapped[str | None] = mapped_column(String(400))
    changed_by: Mapped[str] = mapped_column(String(200))
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    written_to_source_at: Mapped[datetime | None] = mapped_column(DateTime)
    write_status: Mapped[str] = mapped_column(String(20), default="pending")
    error: Mapped[str | None] = mapped_column(Text)


#: Tables a sync run is allowed to write. Everything else is Portal-owned.
MIRROR_TABLES = {AssetSource.__tablename__}
