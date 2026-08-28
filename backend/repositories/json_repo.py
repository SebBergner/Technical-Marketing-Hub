"""File-backed implementation of AssetRepository.

Chosen over Azure SQL so that SharePoint stays the centre of gravity and the
Portal keeps only a server-side index. At this catalogue's size (hundreds to a
few thousand assets) loading into memory and filtering in Python is faster than
a round trip to a database, so nothing is lost on performance.

The mirror/owned split is physically visible here, which is an improvement on
the SQL version where it was only a convention:

    <DATA_DIR>/
      mirror/<source_system>.json   rebuildable cache — sync replaces wholesale
      owned/identity.json           stable slug <-> source id   ← irreplaceable
      owned/curation.json           editor's picks, rails
      owned/roadmap.json            AI-derived index
      owned/stats.json              view / share counters
      owned/requests.jsonl          intake submissions          ← irreplaceable

Anything under `owned/` cannot be reconstructed from SharePoint. Two operational
consequences follow, and neither is hypothetical:

1. **Azure App Service local disk is ephemeral.** It does not survive a restart,
   a redeploy, or scale-out. Point `DATA_DIR` at an Azure Files mount before
   real users submit anything, or those submissions are lost on the next
   `git push`.
2. **Writes assume a single instance.** `os.replace` makes each write atomic, so
   a file can never be left corrupt, but two processes doing read-modify-write
   can still lose an update. Fine for one instance; scale-out needs a real store.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from collections import Counter
from datetime import date
from typing import Any

from backend.models import (
    Asset, AssetStats, AssetSummary, Capability, Facets, FacetValue, MetadataProposal,
    Page, ProposalState, ProposalSummary, ValueRoadmap,
)
from backend.repositories.base import AssetQuery, AssetRepository
from backend.services import relevance, taxonomy
from backend.tables import utcnow

log = logging.getLogger(__name__)

#: Lowest precedence when two sources claim one asset id. The spreadsheet seed
#: is a stand-in for SharePoint until Graph access exists, so real data always
#: beats it -- see _dedupe_by_id.
_FALLBACK_SOURCE = "seed"

_MIRROR_FIELDS = (
    "id", "type", "source", "title", "description", "products", "funnel_stage", "content_depth",
    "language", "segment", "industry", "value_drivers", "tags", "customer_facing",
    "has_narrated_audio", "named_customer", "uploaded_at", "duration_seconds",
    "thumbnail_url", "web_url", "source_item_id", "brightcove_id", "consensus_uuid",
    "resources", "resource_counts", "resource_count", "video_count", "main_video",
)


def _atomic_write(path: str, payload: Any) -> None:
    """Write via a temp file and rename, so a crash mid-write cannot corrupt."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False, default=str)
    os.replace(tmp, path)


def _read(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (ValueError, OSError):
        return default


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _dedupe_by_id(tagged: list[tuple[str, dict]]) -> list[dict]:
    """One asset id must appear once, whatever the mirror holds.

    Sources are separate files, so nothing stops two of them describing the
    same asset -- and identity resolution deliberately gives them the SAME
    slug, because they are the same thing. The result is a catalogue that
    lists it twice: doubled facet counts, and get() returning whichever row it
    reaches first. Seen on the first real Graph sync, 2026-08-26, when the
    spreadsheet seed and the live sync both stayed: 907 rows for 455 assets.

    The sync now retires the seed, so this should not trigger. It is kept
    because emitting a duplicate id is never a correct answer, and a future
    source could reintroduce the collision. Real data always beats the seed,
    and anything unexpected is logged rather than silently resolved.
    """
    seen: dict[str, tuple[str, dict]] = {}
    collisions = 0
    for source, record in tagged:
        key = record.get("id")
        current = seen.get(key)
        if current is None:
            seen[key] = (source, record)
            continue
        collisions += 1
        # Real data beats the stand-in; anything else keeps what it had.
        if current[0] == _FALLBACK_SOURCE and source != _FALLBACK_SOURCE:
            seen[key] = (source, record)
    if collisions:
        log.warning(
            "mirror holds %d duplicate asset id(s); the catalogue is showing one row "
            "each. Two sources are describing the same assets -- run a Graph sync, "
            "which retires the spreadsheet seed.", collisions)
    return [record for _, record in seen.values()]


class JsonAssetRepository(AssetRepository):
    #: Guards read-modify-write within the process. See the module docstring on
    #: why this is not sufficient across processes.
    _lock = threading.RLock()

    def __init__(self, data_dir: str):
        self._mirror_cache: dict[str, tuple[float, list]] = {}
        self.dir = data_dir
        self.mirror_dir = os.path.join(data_dir, "mirror")
        self.owned_dir = os.path.join(data_dir, "owned")

    # ------------------------------------------------------------ file paths
    def _mirror_path(self, source_system: str) -> str:
        return os.path.join(self.mirror_dir, f"{source_system}.json")

    def _owned_path(self, name: str) -> str:
        return os.path.join(self.owned_dir, f"{name}.json")

    # ---------------------------------------------------------------- loading
    def _load_mirror(self) -> list[dict]:
        """Cached per file.

        Without a cache, `get()` re-parsed the whole catalogue on every call —
        at 452 assets and a 1.2 MB file, a loop over the catalogue became
        hundreds of full parses.

        The cache key includes mtime, but mtime ALONE is not enough: filesystem
        timestamp resolution is coarse enough that two writes in the same tick
        look identical, so a sync could serve stale rows. Writers therefore
        invalidate explicitly via `_invalidate`.
        """
        tagged: list[tuple[str, dict]] = []
        if os.path.isdir(self.mirror_dir):
            for name in sorted(os.listdir(self.mirror_dir)):
                if not name.endswith(".json"):
                    continue
                path = os.path.join(self.mirror_dir, name)
                stamp = os.path.getmtime(path)
                cached = self._mirror_cache.get(path)
                if cached is None or cached[0] != stamp:
                    cached = (stamp, _read(path, []))
                    self._mirror_cache[path] = cached
                # The filename IS the source system, which is what lets a
                # collision be resolved rather than merely detected.
                source = name[:-len(".json")]
                tagged.extend((source, record) for record in cached[1])
        identity = self._load("identity")
        # Retired items keep their identity row but leave the catalogue.
        live = [(src, r) for src, r in tagged
                if not (identity.get(r["id"], {}) or {}).get("retired_at")]
        return _dedupe_by_id(live)

    def _load(self, name: str) -> dict[str, dict]:
        return _read(self._owned_path(name), {})

    def _save(self, name: str, payload: dict) -> None:
        _atomic_write(self._owned_path(name), payload)

    def _invalidate(self, path: str | None = None) -> None:
        """Drop cached mirror data. Never rely on mtime alone to notice a write."""
        if path is None:
            self._mirror_cache.clear()
        else:
            self._mirror_cache.pop(path, None)

    # ------------------------------------------------------------------- read
    def _rows(self, query: AssetQuery) -> list[dict]:
        curation = self._load("curation")
        rows = self._load_mirror()

        def keep(record: dict) -> bool:
            # Membership comes from the scorer, so a record can never be
            # excluded by one rule and ranked by another.
            if query.text and not relevance.matches(
                    query.text, record.get("title"), record.get("description")):
                return False

            for field, wanted in (("type", query.types),
                                  ("source", query.sources),
                                  ("funnel_stage", query.funnel_stages),
                                  ("segment", query.segments),
                                  ("industry", query.industries),
                                  ("language", query.languages),
                                  ("content_depth", query.content_depths)):
                if wanted and record.get(field) not in wanted:
                    return False

            for field, wanted in (("products", query.products),
                                  ("value_drivers", query.value_drivers),
                                  ("tags", query.tags)):
                if wanted and not (set(record.get(field) or []) & set(wanted)):
                    return False

            if query.product_families and not (
                    set(taxonomy.families_of(record.get("products")))
                    & set(query.product_families)):
                return False

            if query.customer_facing is not None \
                    and bool(record.get("customer_facing", True)) != query.customer_facing:
                return False
            if query.has_narrated_audio is not None \
                    and record.get("has_narrated_audio") != query.has_narrated_audio:
                return False
            if query.has_consensus_uuid is True and not record.get("consensus_uuid"):
                return False
            if query.has_consensus_uuid is False and record.get("consensus_uuid"):
                return False

            own = curation.get(record["id"]) or {}
            if query.editor_picks_only and not own.get("is_editor_pick"):
                return False
            if query.rail and query.rail not in (own.get("rails") or []):
                return False
            return True

        return [r for r in rows if keep(r)]

    def list(self, query: AssetQuery) -> Page[AssetSummary]:
        rows = self._rows(query)
        stats = self._load("stats")
        indexed = set(self._load("roadmap"))

        def recency(record: dict) -> date:
            return _as_date(record.get("uploaded_at")) or date.min

        if query.sort == "most_viewed":
            rows.sort(key=lambda r: (stats.get(r["id"], {}) or {}).get("views", 0), reverse=True)
        elif query.sort == "title":
            rows.sort(key=lambda r: r.get("title", "").lower())
        elif query.sort == "relevance" and query.text:
            # Recency breaks ties, so equally-relevant results keep the old order.
            rows.sort(key=lambda r: (*relevance.ranking(query.text, r.get("title"),
                                                        r.get("description")),
                                     recency(r)), reverse=True)
        else:
            rows.sort(key=recency, reverse=True)

        window = rows[query.offset: query.offset + query.limit]
        return Page[AssetSummary](
            items=[AssetSummary(**self._common(r, stats),
                                has_roadmap=r["id"] in indexed) for r in window],
            total=len(rows), limit=query.limit, offset=query.offset,
        )

    def get(self, asset_id: str) -> Asset | None:
        record = next((r for r in self._load_mirror() if r["id"] == asset_id), None)
        if record is None:
            return None

        own = self._load("curation").get(asset_id) or {}
        roadmap = self._load("roadmap").get(asset_id)

        data = self._common(record, self._load("stats"))
        data.update(
            has_roadmap=roadmap is not None,
            resources=record.get("resources") or [],
            main_video=record.get("main_video"),
            rails=own.get("rails") or [],
            is_editor_pick=bool(own.get("is_editor_pick")),
            value_roadmap=self._to_roadmap(roadmap),
        )
        return Asset(**data)

    def facets(self) -> Facets:
        rows = self._load_mirror()

        def scalar(field: str) -> list[FacetValue]:
            counts = Counter(r.get(field) for r in rows if r.get(field))
            return [FacetValue(value=v, count=n) for v, n in sorted(counts.items())]

        def multi(field: str) -> list[FacetValue]:
            counts = Counter(v for r in rows for v in (r.get(field) or []))
            return [FacetValue(value=v, count=n) for v, n in sorted(counts.items())]

        # Families are derived, not stored: the mapping is code, so a change to
        # it must take effect without a re-sync.
        family_counts = Counter(
            f for r in rows for f in taxonomy.families_of(r.get("products")))

        return Facets(
            types=scalar("type"), products=multi("products"),
            funnel_stages=scalar("funnel_stage"), segments=scalar("segment"),
            industries=scalar("industry"), value_drivers=multi("value_drivers"),
            languages=scalar("language"), content_depths=scalar("content_depth"),
            sources=scalar("source"), tags=multi("tags"),
            product_families=[FacetValue(value=v, count=n)
                              for v, n in sorted(family_counts.items())],
            total=len(rows),
        )

    def rails(self) -> dict[str, list[str]]:
        out: dict[str, list[tuple[int, str]]] = {}
        for asset_id, own in self._load("curation").items():
            for rail in (own or {}).get("rails") or []:
                out.setdefault(rail, []).append(((own or {}).get("rail_order") or 0, asset_id))
        return {rail: [aid for _, aid in sorted(items)] for rail, items in out.items()}

    # ------------------------------------------------------------------ write
    def increment_stat(self, asset_id: str, stat: str, amount: int = 1) -> None:
        if stat not in {"views", "downloads", "launches", "shares"}:
            raise ValueError(f"unknown stat: {stat}")
        with self._lock:
            stats = self._load("stats")
            row = stats.setdefault(asset_id, {})
            row[stat] = (row.get(stat) or 0) + amount
            self._save("stats", stats)

    def replace_source_rows(self, assets: list[Asset], source_system: str) -> int:
        """The ONLY sanctioned writer of mirror data.

        Rewrites one source's mirror file and maintains identity. Everything
        under owned/ is left completely alone — that is the whole point.
        """
        with self._lock:
            identity = self._load("identity")
            now = utcnow().isoformat(timespec="seconds")
            seen: set[str] = set()
            records: list[dict] = []

            for asset in assets:
                payload = asset.model_dump(mode="json")
                records.append({k: payload[k] for k in _MIRROR_FIELDS if k in payload})
                seen.add(asset.id)

                row = identity.setdefault(asset.id, {"first_seen_at": now})
                # source_system means "who provides this NOW", not "who first
                # saw it". setdefault alone left assets that moved between
                # sources -- seed -> sharepoint -- still labelled with the old
                # one, so retiring that source retired assets it no longer
                # owned. 288 of 455 vanished from the catalogue this way on
                # 2026-08-26. first_seen_at is what must never move.
                row["source_system"] = source_system
                row["source_item_id"] = asset.source_item_id or asset.id
                row["retired_at"] = None

            # Items this source no longer provides are retired, never deleted —
            # the slug must never be reused or old shared links would resolve
            # to the wrong content.
            for asset_id, row in identity.items():
                if row.get("source_system") == source_system and asset_id not in seen:
                    row.setdefault("retired_at", now)
                    row["retired_at"] = row["retired_at"] or now

            path = self._mirror_path(source_system)
            _atomic_write(path, records)
            self._invalidate(path)
            self._save("identity", identity)
            return len(seen)

    # ------------------------------------------------- owned-data write paths
    def set_curation(self, asset_id: str, **fields: Any) -> None:
        with self._lock:
            curation = self._load("curation")
            curation.setdefault(asset_id, {}).update(fields)
            self._save("curation", curation)

    def set_roadmap(self, asset_id: str, roadmap: dict) -> None:
        with self._lock:
            roadmaps = self._load("roadmap")
            roadmaps[asset_id] = roadmap
            self._save("roadmap", roadmaps)

    def set_stats(self, asset_id: str, stats: dict) -> None:
        with self._lock:
            all_stats = self._load("stats")
            all_stats[asset_id] = stats
            self._save("stats", all_stats)

    def record_share_event(self, asset_id: str, channel: str,
                           target_ref: str | None, shared_by: str | None) -> None:
        """Append one JSON line.

        JSONL rather than a rewritten array: appends are far safer under
        concurrency than read-modify-write, and a truncated final line loses one
        event instead of the whole log.
        """
        path = os.path.join(self.owned_dir, "share_events.jsonl")
        os.makedirs(self.owned_dir, exist_ok=True)
        entry = {"asset_id": asset_id, "channel": channel, "target_ref": target_ref,
                 "shared_by": shared_by, "created_at": utcnow().isoformat(timespec="seconds")}
        with self._lock, open(path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def count_source_rows(self, source_system: str) -> int:
        """How many mirror rows one source currently contributes."""
        return len(_read(os.path.join(self.mirror_dir, f"{source_system}.json"), []))

    # ------------------------------------------------------------ sync state
    def get_sync_token(self, source_system: str) -> str | None:
        return (self._load("sync_state").get(source_system) or {}).get("delta_token")

    def set_sync_token(self, source_system: str, token: str | None) -> None:
        with self._lock:
            state = self._load("sync_state")
            row = state.setdefault(source_system, {})
            row["delta_token"] = token
            row["last_success_at"] = utcnow().isoformat(timespec="seconds")
            self._save("sync_state", state)

    def record_sync(self, source_system: str, fingerprint: str | None = None) -> None:
        """Stamp a successful sync for a source with no delta cursor.

        Consensus has no delta, so it never called set_sync_token and its
        freshness was simply unknown. Nothing refreshes the mirror
        automatically, so "when was this last pulled" is the one question a
        stale catalogue cannot answer about itself.
        """
        with self._lock:
            state = self._load("sync_state")
            row = state.setdefault(source_system, {})
            row["last_success_at"] = utcnow().isoformat(timespec="seconds")
            if fingerprint is not None:
                row["fingerprint"] = fingerprint
            self._save("sync_state", state)

    def sync_state(self, source_system: str) -> dict:
        return self._load("sync_state").get(source_system) or {}

    # ---------------------------------------------------- metadata proposals
    @staticmethod
    def _key(asset_id: str, field: str) -> str:
        """Asset ids are slugs ([a-z0-9-]) and field names are identifiers, so
        `::` cannot occur inside either half."""
        return f"{asset_id}::{field}"

    def save_proposals(self, proposals: list[MetadataProposal]) -> int:
        with self._lock:
            stored = self._load("proposals")
            written = 0
            for proposal in proposals:
                key = self._key(proposal.asset_id, proposal.field)
                existing = stored.get(key)
                # A human decision outranks a regenerated suggestion.
                if existing and existing.get("state") != ProposalState.PENDING.value:
                    continue
                stored[key] = proposal.model_dump(mode="json")
                written += 1
            self._save("proposals", stored)
            return written

    def list_proposals(self, state: str | None = None, field: str | None = None,
                       limit: int = 100, offset: int = 0) -> Page[MetadataProposal]:
        rows = list(self._load("proposals").values())
        if state:
            rows = [r for r in rows if r.get("state") == state]
        if field:
            rows = [r for r in rows if r.get("field") == field]
        # Lowest confidence first: the uncertain ones need the human.
        rows.sort(key=lambda r: (r.get("confidence") if r.get("confidence") is not None else 1.0))
        window = rows[offset: offset + limit]
        return Page[MetadataProposal](
            items=[MetadataProposal.model_validate(r) for r in window],
            total=len(rows), limit=limit, offset=offset,
        )

    def decide_proposal(self, asset_id: str, field: str, state: str,
                        decided_by: str | None) -> MetadataProposal | None:
        with self._lock:
            stored = self._load("proposals")
            key = self._key(asset_id, field)
            row = stored.get(key)
            if row is None:
                return None
            row["state"] = state
            row["decided_by"] = decided_by
            row["decided_at"] = utcnow().isoformat(timespec="seconds")
            stored[key] = row
            self._save("proposals", stored)
            return MetadataProposal.model_validate(row)

    def mark_proposal_written(self, asset_id: str, field: str) -> MetadataProposal | None:
        with self._lock:
            stored = self._load("proposals")
            key = self._key(asset_id, field)
            row = stored.get(key)
            if row is None:
                return None
            # decided_by is deliberately left alone: it names who authorised the
            # value, which is not who ran the job that pushed it.
            row["state"] = ProposalState.WRITTEN.value
            row["written_at"] = utcnow().isoformat(timespec="seconds")
            stored[key] = row
            self._save("proposals", stored)
            return MetadataProposal.model_validate(row)

    def record_metadata_edit(self, asset_id: str, field: str, old_value: str | None,
                             new_value: str | None, changed_by: str,
                             write_status: str = "written",
                             error: str | None = None) -> None:
        """Append one JSON line, same reasoning as the share log: an append
        cannot lose earlier entries the way a rewritten array can."""
        path = os.path.join(self.owned_dir, "metadata_edits.jsonl")
        os.makedirs(self.owned_dir, exist_ok=True)
        entry = {
            "asset_id": asset_id, "field": field,
            "old_value": old_value, "new_value": new_value,
            "changed_by": changed_by, "write_status": write_status, "error": error,
            "changed_at": utcnow().isoformat(timespec="seconds"),
        }
        with self._lock, open(path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def metadata_edits(self, asset_id: str | None = None) -> list[dict]:
        path = os.path.join(self.owned_dir, "metadata_edits.jsonl")
        if not os.path.exists(path):
            return []
        rows = []
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue      # a torn final line loses one entry, not the log
                if asset_id is None or entry.get("asset_id") == asset_id:
                    rows.append(entry)
        return rows

    def proposal_summary(self) -> ProposalSummary:
        rows = list(self._load("proposals").values())
        return ProposalSummary(
            total=len(rows),
            by_state=dict(Counter(r.get("state") for r in rows)),
            by_field=dict(Counter(r.get("field") for r in rows)),
            by_origin=dict(Counter(r.get("origin") for r in rows)),
            pending_writeback=sum(
                1 for r in rows if r.get("state") == ProposalState.ACCEPTED.value),
        )

    # --------------------------------------------------------------- mapping
    @staticmethod
    def _common(record: dict, stats: dict) -> dict:
        counters = stats.get(record["id"]) or {}
        return dict(
            id=record["id"], type=record["type"],
            source=record.get("source") or "sharepoint",
            title=record["title"], description=record.get("description"),
            web_url=record.get("web_url"),
            products=record.get("products") or [],
            funnel_stage=record.get("funnel_stage"),
            content_depth=record.get("content_depth"),
            language=record.get("language") or "en",
            segment=record.get("segment"), industry=record.get("industry"),
            value_drivers=record.get("value_drivers") or [],
            tags=record.get("tags") or [],
            customer_facing=bool(record.get("customer_facing", True)),
            has_narrated_audio=record.get("has_narrated_audio"),
            named_customer=record.get("named_customer"),
            uploaded_at=_as_date(record.get("uploaded_at")),
            duration_seconds=record.get("duration_seconds"),
            thumbnail_url=record.get("thumbnail_url"),
            source_item_id=record.get("source_item_id"),
            brightcove_id=record.get("brightcove_id"),
            consensus_uuid=record.get("consensus_uuid"),
            resource_count=record.get("resource_count") or 0,
            video_count=record.get("video_count") or 0,
            resource_counts=record.get("resource_counts") or {},
            stats=AssetStats(
                views=counters.get("views", 0), downloads=counters.get("downloads", 0),
                launches=counters.get("launches", 0), shares=counters.get("shares", 0),
            ),
        )

    @staticmethod
    def _to_roadmap(payload: dict | None) -> ValueRoadmap | None:
        if not payload:
            return None
        return ValueRoadmap(
            description=payload.get("description"),
            value_drivers=payload.get("value_drivers") or [],
            capabilities=[Capability(**c) for c in (payload.get("capabilities") or [])],
            indexed_at=payload.get("indexed_at"), model=payload.get("model"),
        )
