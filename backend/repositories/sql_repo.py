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
    Asset, AssetStats, AssetSummary, Capability, Facets, FacetValue, Page, ValueRoadmap,
)
from backend.repositories.base import AssetQuery, AssetRepository
from backend.tables import (
    AssetCuration, AssetIdentity, AssetSource, AssetStatsRow, AssetValueRoadmap, utcnow,
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

        if query.text:
            like = f"%{query.text.lower()}%"
            stmt = stmt.where(or_(
                func.lower(AssetSource.title).like(like),
                func.lower(func.coalesce(AssetSource.description, "")).like(like),
            ))

        for column, values in (
            (AssetSource.type, query.types),
            (AssetSource.funnel_stage, query.funnel_stages),
            (AssetSource.segment, query.segments),
            (AssetSource.industry, query.industries),
            (AssetSource.language, query.languages),
            (AssetSource.content_depth, query.content_depths),
        ):
            if values:
                stmt = stmt.where(column.in_(values))

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

        if query.sort == "most_viewed":
            rows.sort(key=lambda r: (r[1].views if r[1] else 0), reverse=True)
        elif query.sort == "title":
            rows.sort(key=lambda r: r[0].title.lower())
        else:  # recent
            rows.sort(key=lambda r: (r[0].uploaded_at or datetime.min.date()), reverse=True)

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

    # --------------------------------------------------------------- mapping
    @staticmethod
    def _common(src: AssetSource, stats: AssetStatsRow | None) -> dict:
        return dict(
            id=src.asset_id, type=src.type, title=src.title, description=src.description,
            products=src.products or [], funnel_stage=src.funnel_stage,
            content_depth=src.content_depth, language=src.language, segment=src.segment,
            industry=src.industry, value_drivers=src.value_drivers or [],
            customer_facing=src.customer_facing, has_narrated_audio=src.has_narrated_audio,
            named_customer=src.named_customer, uploaded_at=src.uploaded_at,
            duration_seconds=src.duration_seconds, thumbnail_url=src.thumbnail_url,
            source_item_id=src.drive_item_id, brightcove_id=src.brightcove_id,
            consensus_uuid=src.consensus_uuid,
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
