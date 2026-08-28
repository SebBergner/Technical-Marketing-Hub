"""SQL implementation of AssetRepository.

Runs unchanged against SQLite (local) and Azure SQL (production).

Note on JSON columns: `products` and `value_drivers` are JSON arrays, and
neither SQLite nor SQL Server gives us a portable way to filter inside them in
SQL. Those two facets are therefore filtered in Python after the SQL pass. At
the catalogue's size that is fine; if it ever stops being fine, the fix is
junction tables, not a different database.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.models import (
    Asset, AssetStats, AssetSummary, Capability, Facets, FacetValue, MetadataProposal,
    Page, ProposalState, ProposalSummary, ValueRoadmap,
)
from backend.repositories.base import AssetQuery, AssetRepository
from backend.services import relevance, taxonomy
from backend.tables import (
    AssetCuration, AssetIdentity, AssetSource, AssetStatsRow, AssetValueRoadmap,
    MetadataEdit, MetadataProposal as ProposalRow, ShareEvent, SyncState, utcnow,
)

_JSON_LIST_FIELDS = ("products", "value_drivers")


class SqlAssetRepository(AssetRepository):
    def __init__(self, session: Session):
        self.s = session

    # ------------------------------------------------------------------ read
    def _rows(self, query: AssetQuery):
        """Everything the SQL layer can filter; JSON-array facets handled after."""
        stmt = (
            select(AssetSource, AssetStatsRow, AssetCuration)
            .join(AssetIdentity, AssetIdentity.asset_id == AssetSource.asset_id)
            .outerjoin(AssetStatsRow, AssetStatsRow.asset_id == AssetSource.asset_id)
            .outerjoin(AssetCuration, AssetCuration.asset_id == AssetSource.asset_id)
            .where(AssetIdentity.retired_at.is_(None))
        )

        # One clause per term, ANDed: every word must appear somewhere, in any
        # order. A single LIKE on the whole query tested the words as one
        # contiguous phrase, so "Creo overview" missed "Creo Parametric
        # Overview". Kept in SQL rather than filtered in Python so the database
        # still does the narrowing.
        for term in relevance.terms(query.text):
            like = f"%{term}%"
            stmt = stmt.where(or_(
                func.lower(AssetSource.title).like(like),
                func.lower(func.coalesce(AssetSource.description, "")).like(like),
            ))

        for column, values in (
            (AssetSource.type, query.types),
            (AssetSource.source_system, query.sources),
            (AssetSource.funnel_stage, query.funnel_stages),
            (AssetSource.segment, query.segments),
            (AssetSource.industry, query.industries),
            (AssetSource.language, query.languages),
            (AssetSource.content_depth, query.content_depths),
        ):
            if values:
                stmt = stmt.where(column.in_(values))

        if query.product_families:
            # Families are derived in code, so they cannot be pushed into SQL.
            # Expanding to the member products keeps the filter in the query
            # rather than loading the catalogue and filtering in Python.
            wanted = set(query.product_families)
            known = {p for r in self.s.execute(select(AssetSource.products)).scalars()
                     for p in (r or [])}
            members = [p for p in known if taxonomy.family_of(p) in wanted]
            if members:
                stmt = stmt.where(or_(*[AssetSource.products.contains(p)
                                        for p in members]))
            else:
                stmt = stmt.where(AssetSource.asset_id.is_(None))   # match nothing

        if query.customer_facing is not None:
            stmt = stmt.where(AssetSource.customer_facing == query.customer_facing)
        if query.has_narrated_audio is not None:
            stmt = stmt.where(AssetSource.has_narrated_audio == query.has_narrated_audio)
        if query.has_consensus_uuid is True:
            stmt = stmt.where(AssetSource.consensus_uuid.is_not(None))
        elif query.has_consensus_uuid is False:
            stmt = stmt.where(AssetSource.consensus_uuid.is_(None))
        if query.editor_picks_only:
            stmt = stmt.where(AssetCuration.is_editor_pick.is_(True))

        rows = self.s.execute(stmt).all()

        # JSON-array facets, filtered in Python — see module docstring.
        def matches(src, curation) -> bool:
            for field_name, wanted in (("products", query.products),
                                       ("value_drivers", query.value_drivers)):
                if wanted and not (set(getattr(src, field_name) or []) & set(wanted)):
                    return False
            if query.rail and query.rail not in ((curation.rails if curation else None) or []):
                return False
            return True

        return [(src, stats, curation) for src, stats, curation in rows
                if matches(src, curation)]

    def list(self, query: AssetQuery) -> Page[AssetSummary]:
        rows = self._rows(query)
        indexed = set(self.s.execute(select(AssetValueRoadmap.asset_id)).scalars().all())

        def recency(row) -> "date":
            return row[0].uploaded_at or datetime.min.date()

        if query.sort == "most_viewed":
            rows.sort(key=lambda r: (r[1].views if r[1] else 0), reverse=True)
        elif query.sort == "title":
            rows.sort(key=lambda r: r[0].title.lower())
        elif query.sort == "relevance" and query.text:
            rows.sort(key=lambda r: (*relevance.ranking(query.text, r[0].title,
                                                        r[0].description),
                                     recency(r)), reverse=True)
        else:  # recent
            rows.sort(key=recency, reverse=True)

        total = len(rows)
        window = rows[query.offset: query.offset + query.limit]
        return Page[AssetSummary](
            items=[AssetSummary(**self._common(src, stats),
                                has_roadmap=src.asset_id in indexed)
                   for src, stats, _ in window],
            total=total, limit=query.limit, offset=query.offset,
        )

    def get(self, asset_id: str) -> Asset | None:
        src = self.s.get(AssetSource, asset_id)
        if src is None:
            return None
        stats = self.s.get(AssetStatsRow, asset_id)
        curation = self.s.get(AssetCuration, asset_id)
        roadmap = self.s.get(AssetValueRoadmap, asset_id)

        data = self._common(src, stats)
        data.update(
            has_roadmap=roadmap is not None,
            web_url=src.web_url,
            resources=src.resources or [],
            main_video=src.main_video,
            rails=(curation.rails if curation else None) or [],
            is_editor_pick=bool(curation.is_editor_pick) if curation else False,
            value_roadmap=self._to_roadmap(roadmap),
        )
        return Asset(**data)

    def facets(self) -> Facets:
        rows = self.s.execute(
            select(AssetSource)
            .join(AssetIdentity, AssetIdentity.asset_id == AssetSource.asset_id)
            .where(AssetIdentity.retired_at.is_(None))
        ).scalars().all()

        def scalar(attr: str) -> list[FacetValue]:
            c = Counter(getattr(r, attr) for r in rows if getattr(r, attr))
            return [FacetValue(value=v, count=n) for v, n in sorted(c.items())]

        def multi(attr: str) -> list[FacetValue]:
            c = Counter(v for r in rows for v in (getattr(r, attr) or []))
            return [FacetValue(value=v, count=n) for v, n in sorted(c.items())]

        return Facets(
            types=scalar("type"),
            products=multi("products"),
            funnel_stages=scalar("funnel_stage"),
            segments=scalar("segment"),
            industries=scalar("industry"),
            value_drivers=multi("value_drivers"),
            languages=scalar("language"),
            content_depths=scalar("content_depth"),
            sources=scalar("source_system"),
            # Derived, not stored: the mapping lives in code, so changing it
            # must take effect without a re-sync.
            product_families=[
                FacetValue(value=v, count=n) for v, n in sorted(Counter(
                    f for r in rows for f in taxonomy.families_of(r.products)
                ).items())],
            total=len(rows),
        )

    def rails(self) -> dict[str, list[str]]:
        rows = self.s.execute(
            select(AssetCuration).where(AssetCuration.rails.is_not(None))
        ).scalars().all()
        out: dict[str, list[tuple[int, str]]] = {}
        for row in rows:
            for rail in row.rails or []:
                out.setdefault(rail, []).append((row.rail_order or 0, row.asset_id))
        return {rail: [aid for _, aid in sorted(items)] for rail, items in out.items()}

    # ----------------------------------------------------------------- write
    def increment_stat(self, asset_id: str, stat: str, amount: int = 1) -> None:
        if stat not in {"views", "downloads", "launches", "shares"}:
            raise ValueError(f"unknown stat: {stat}")
        row = self.s.get(AssetStatsRow, asset_id)
        if row is None:
            row = AssetStatsRow(asset_id=asset_id)
            self.s.add(row)
        setattr(row, stat, (getattr(row, stat) or 0) + amount)
        self.s.commit()

    # ---- Portal-owned writes -------------------------------------------
    def set_curation(self, asset_id: str, **fields) -> None:
        row = self.s.get(AssetCuration, asset_id) or AssetCuration(asset_id=asset_id)
        for key, value in fields.items():
            setattr(row, key, value)
        self.s.add(row)
        self.s.commit()

    def set_roadmap(self, asset_id: str, roadmap: dict) -> None:
        row = self.s.get(AssetValueRoadmap, asset_id) or AssetValueRoadmap(asset_id=asset_id)
        row.description = roadmap.get("description")
        row.value_drivers = roadmap.get("value_drivers") or []
        row.capabilities = roadmap.get("capabilities") or []
        row.model = roadmap.get("model")
        self.s.add(row)
        self.s.commit()

    def set_stats(self, asset_id: str, stats: dict) -> None:
        row = self.s.get(AssetStatsRow, asset_id) or AssetStatsRow(asset_id=asset_id)
        for key in ("views", "downloads", "launches", "shares"):
            setattr(row, key, stats.get(key, 0))
        self.s.add(row)
        self.s.commit()

    def record_share_event(self, asset_id: str, channel: str,
                           target_ref: str | None, shared_by: str | None) -> None:
        self.s.add(ShareEvent(asset_id=asset_id, channel=channel,
                              target_ref=target_ref, shared_by=shared_by))
        self.s.commit()

    def replace_source_rows(self, assets: list[Asset], source_system: str) -> int:
        """The ONLY sanctioned writer of mirror data.

        Portal-owned tables (curation, stats, roadmap, identity) are never
        cleared here — that is the whole point of the mirror/owned split.
        """
        seen: set[str] = set()

        for asset in assets:
            identity = self.s.get(AssetIdentity, asset.id)
            if identity is None:
                identity = AssetIdentity(
                    asset_id=asset.id,
                    source_system=source_system,
                    source_item_id=asset.source_item_id or asset.id,
                )
                self.s.add(identity)
            # Keep ownership current: source_system means "who provides this
            # now". Leaving it at whoever created the row makes an asset that
            # moved between sources look like it still belongs to the old one.
            identity.source_system = source_system
            identity.source_item_id = asset.source_item_id or asset.id
            identity.retired_at = None
            seen.add(asset.id)

            row = self.s.get(AssetSource, asset.id) or AssetSource(asset_id=asset.id)
            row.source_system = source_system
            row.type = asset.type.value
            row.title = asset.title
            row.description = asset.description
            row.products = asset.products
            row.funnel_stage = asset.funnel_stage.value if asset.funnel_stage else None
            row.content_depth = asset.content_depth.value if asset.content_depth else None
            row.language = asset.language
            row.segment = asset.segment
            row.industry = asset.industry
            row.value_drivers = asset.value_drivers
            row.customer_facing = asset.customer_facing
            row.has_narrated_audio = asset.has_narrated_audio
            row.named_customer = asset.named_customer
            row.uploaded_at = asset.uploaded_at
            row.duration_seconds = asset.duration_seconds
            row.thumbnail_url = asset.thumbnail_url
            row.web_url = asset.web_url
            row.brightcove_id = asset.brightcove_id
            row.consensus_uuid = asset.consensus_uuid
            row.resources = [r.model_dump(mode="json") for r in asset.resources]
            row.resource_counts = asset.resource_counts
            row.resource_count = asset.resource_count
            row.video_count = asset.video_count
            row.main_video = asset.main_video
            row.synced_at = utcnow()
            self.s.add(row)

        # Anything this source previously provided but no longer does is retired,
        # not deleted — the slug must never be reused.
        existing = self.s.execute(
            select(AssetSource.asset_id).where(AssetSource.source_system == source_system)
        ).scalars().all()
        for asset_id in existing:
            if asset_id not in seen:
                self.s.delete(self.s.get(AssetSource, asset_id))
                identity = self.s.get(AssetIdentity, asset_id)
                if identity:
                    identity.retired_at = utcnow()

        self.s.commit()
        return len(seen)

    # ------------------------------------------------------------ sync state
    def count_source_rows(self, source_system: str) -> int:
        """How many mirror rows one source currently contributes."""
        return int(self.s.execute(
            select(func.count()).select_from(AssetSource)
            .where(AssetSource.source_system == source_system)).scalar() or 0)

    def get_sync_token(self, source_system: str) -> str | None:
        row = self.s.get(SyncState, source_system)
        return row.delta_token if row else None

    def set_sync_token(self, source_system: str, token: str | None) -> None:
        row = self.s.get(SyncState, source_system) or SyncState(source_system=source_system)
        row.delta_token = token
        row.last_success_at = utcnow()
        self.s.add(row)
        self.s.commit()

    def record_sync(self, source_system: str, fingerprint: str | None = None,
                    api: str | None = None) -> None:
        """Stamp a successful sync for a source with no delta cursor.

        The fingerprint rides in the delta_token column: for a source without a
        delta API it serves the same purpose — "have we already seen this?".
        """
        row = self.s.get(SyncState, source_system) or SyncState(source_system=source_system)
        row.last_success_at = utcnow()
        if fingerprint is not None:
            row.delta_token = fingerprint
        self.s.add(row)
        self.s.commit()

    def sync_state(self, source_system: str) -> dict:
        row = self.s.get(SyncState, source_system)
        if row is None:
            return {}
        return {"delta_token": row.delta_token, "fingerprint": row.delta_token,
                "last_success_at": row.last_success_at.isoformat(timespec="seconds")
                                   if row.last_success_at else None}

    # ---------------------------------------------------- metadata proposals
    @staticmethod
    def _proposal_out(row: ProposalRow, title: str | None = None) -> MetadataProposal:
        return MetadataProposal(
            asset_id=row.asset_id, asset_title=title, field=row.field,
            proposed_value=row.proposed_value, confidence=row.confidence,
            origin=row.origin, state=row.state,
            decided_by=row.decided_by, decided_at=row.decided_at,
            written_at=row.written_at,
        )

    def save_proposals(self, proposals: list[MetadataProposal]) -> int:
        written = 0
        for proposal in proposals:
            row = self.s.get(ProposalRow, (proposal.asset_id, proposal.field))
            # A human decision outranks a regenerated suggestion.
            if row is not None and row.state != ProposalState.PENDING.value:
                continue
            if row is None:
                row = ProposalRow(asset_id=proposal.asset_id, field=proposal.field)
            row.proposed_value = proposal.proposed_value
            row.confidence = proposal.confidence
            row.origin = proposal.origin.value
            row.state = proposal.state.value
            self.s.add(row)
            written += 1
        self.s.commit()
        return written

    def list_proposals(self, state: str | None = None, field: str | None = None,
                       limit: int = 100, offset: int = 0) -> Page[MetadataProposal]:
        stmt = select(ProposalRow)
        if state:
            stmt = stmt.where(ProposalRow.state == state)
        if field:
            stmt = stmt.where(ProposalRow.field == field)
        rows = self.s.execute(stmt).scalars().all()
        # Lowest confidence first: the uncertain ones need the human.
        rows = sorted(rows, key=lambda r: (1.0 if r.confidence is None else r.confidence))
        window = rows[offset: offset + limit]

        titles = {}
        if window:
            found = self.s.execute(
                select(AssetSource.asset_id, AssetSource.title)
                .where(AssetSource.asset_id.in_([r.asset_id for r in window]))
            ).all()
            titles = dict(found)

        return Page[MetadataProposal](
            items=[self._proposal_out(r, titles.get(r.asset_id)) for r in window],
            total=len(rows), limit=limit, offset=offset,
        )

    def decide_proposal(self, asset_id: str, field: str, state: str,
                        decided_by: str | None) -> MetadataProposal | None:
        row = self.s.get(ProposalRow, (asset_id, field))
        if row is None:
            return None
        row.state = state
        row.decided_by = decided_by
        row.decided_at = utcnow()
        self.s.add(row)
        self.s.commit()
        src = self.s.get(AssetSource, asset_id)
        return self._proposal_out(row, src.title if src else None)

    def mark_proposal_written(self, asset_id: str, field: str) -> MetadataProposal | None:
        row = self.s.get(ProposalRow, (asset_id, field))
        if row is None:
            return None
        # decided_by is deliberately left alone: it names who authorised the
        # value, which is not who ran the job that pushed it.
        row.state = ProposalState.WRITTEN.value
        row.written_at = utcnow()
        self.s.add(row)
        self.s.commit()
        src = self.s.get(AssetSource, asset_id)
        return self._proposal_out(row, src.title if src else None)

    def record_metadata_edit(self, asset_id: str, field: str, old_value: str | None,
                             new_value: str | None, changed_by: str,
                             write_status: str = "written",
                             error: str | None = None) -> None:
        self.s.add(MetadataEdit(
            asset_id=asset_id, field=field, old_value=old_value, new_value=new_value,
            changed_by=changed_by, write_status=write_status, error=error,
            written_to_source_at=utcnow() if write_status == "written" else None,
        ))
        self.s.commit()

    def metadata_edits(self, asset_id: str | None = None) -> list[dict]:
        stmt = select(MetadataEdit).order_by(MetadataEdit.changed_at)
        if asset_id:
            stmt = stmt.where(MetadataEdit.asset_id == asset_id)
        return [{
            "asset_id": r.asset_id, "field": r.field,
            "old_value": r.old_value, "new_value": r.new_value,
            "changed_by": r.changed_by, "write_status": r.write_status,
            "error": r.error,
            "changed_at": r.changed_at.isoformat(timespec="seconds") if r.changed_at else None,
        } for r in self.s.execute(stmt).scalars()]

    def proposal_summary(self) -> ProposalSummary:
        rows = self.s.execute(select(ProposalRow)).scalars().all()
        return ProposalSummary(
            total=len(rows),
            by_state=dict(Counter(r.state for r in rows)),
            by_field=dict(Counter(r.field for r in rows)),
            by_origin=dict(Counter(r.origin for r in rows)),
            pending_writeback=sum(
                1 for r in rows if r.state == ProposalState.ACCEPTED.value),
        )

    # --------------------------------------------------------------- mapping
    @staticmethod
    def _common(src: AssetSource, stats: AssetStatsRow | None) -> dict:
        return dict(
            id=src.asset_id, type=src.type, source=src.source_system,
            title=src.title, description=src.description,
            products=src.products or [], funnel_stage=src.funnel_stage,
            content_depth=src.content_depth, language=src.language, segment=src.segment,
            industry=src.industry, value_drivers=src.value_drivers or [],
            customer_facing=src.customer_facing, has_narrated_audio=src.has_narrated_audio,
            named_customer=src.named_customer, uploaded_at=src.uploaded_at,
            duration_seconds=src.duration_seconds, thumbnail_url=src.thumbnail_url,
            web_url=src.web_url, source_item_id=src.drive_item_id, brightcove_id=src.brightcove_id,
            consensus_uuid=src.consensus_uuid,
            resource_count=src.resource_count or 0, video_count=src.video_count or 0,
            resource_counts=src.resource_counts or {},
            stats=AssetStats(
                views=stats.views if stats else 0,
                downloads=stats.downloads if stats else 0,
                launches=stats.launches if stats else 0,
                shares=stats.shares if stats else 0,
            ),
        )

    @classmethod
    def _to_summary(cls, src: AssetSource, stats: AssetStatsRow | None) -> AssetSummary:
        return AssetSummary(**cls._common(src, stats))

    @staticmethod
    def _to_roadmap(row: AssetValueRoadmap | None) -> ValueRoadmap | None:
        if row is None:
            return None
        return ValueRoadmap(
            description=row.description,
            value_drivers=row.value_drivers or [],
            capabilities=[Capability(**c) for c in (row.capabilities or [])],
            indexed_at=row.indexed_at, model=row.model,
        )
