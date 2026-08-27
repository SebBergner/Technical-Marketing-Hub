"""Consensus demos as catalogue entries in their own right.

Until 2026-08-26 Consensus was only an enrichment source: a demo existed in the
Portal solely as a `consensus_uuid` hanging off a SharePoint asset. That was
abandoned once the two catalogues were measured against each other — they hold
different things at different granularity (SharePoint has 455 demo *kits*,
Consensus has recorded *videos*; 4 of 637 titles even mention LDK or VDK), so
only about 6 pairs can be joined at all.

So Consensus content is now indexed directly. The catalogue goes from "455
assets, 98% of them unshareable" to a federated index of both platforms, and no
join is needed for a user to find something. Relating the two is deferred to a
curated SharePoint list, maintained by a person.

What gets indexed, and what does not
------------------------------------
Only `isPublic` demos. The 146 that are not are customer-specific boards
(Schneider Electric, Thales Canada, GE Appliances, Siemens Energy), proofs of
concept and meeting recordings. Two reasons, and the second is the serious one:

  * they are unmaintained — **0 of 146 have a folder**, against 489 of 491 that
    do, and only 21% follow the naming convention against 65%
  * they name customers. Surfacing "Schneider Electric : …" in a catalogue any
    SE can search, and share from, is a confidentiality problem.

Where the metadata comes from
-----------------------------
Consensus has no product or segment field. It does have a pipe convention in
`internalTitle`, used by 65% of public demos:

    PLM | Windchill | PLM Overview | Walkthrough | 12:55
    ^segment ^product ^topic        ^kind         ^duration

The first two slots use the *same vocabulary as SharePoint* — 96% of segment
values are one of the five shared ones — which is what makes a single set of
filters work across both platforms. `language` needs no such parsing: it is a
structured field at 100% coverage, better than SharePoint's own.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from backend.integrations.consensus import ConsensusClient, ConsensusDemo
from backend.models import Asset, AssetType
from backend.services import taxonomy

log = logging.getLogger(__name__)

SOURCE_SYSTEM = "consensus"

#: Minimum pipes before `internalTitle` is treated as following the convention.
#: Two pipes means three slots, enough for segment and product to be deliberate
#: rather than a title that happens to contain punctuation.
_MIN_PIPES = 2

_DURATION = re.compile(r"^(\d{1,2}):(\d{2})$")


@dataclass
class ConsensusSyncResult:
    demos_seen: int = 0
    indexed: int = 0
    skipped_private: int = 0
    with_segment: int = 0
    with_product: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "demos_seen": self.demos_seen,
            "indexed": self.indexed,
            "skipped_private": self.skipped_private,
            "with_segment": self.with_segment,
            "with_product": self.with_product,
            "errors": self.errors,
        }


def parse_internal_title(internal_title: str | None) -> dict:
    """Pull segment, product, topic and duration out of the pipe convention.

    Returns empty values rather than guessing when the convention is absent —
    35% of public demos do not follow it, mostly one coherent block of
    PTC NEXT localised event content, and inventing a segment for those would
    put wrong content behind a filter.
    """
    out: dict = {"segment": None, "product": None, "topic": None,
                 "kind": None, "duration_seconds": None}
    if not internal_title or internal_title.count("|") < _MIN_PIPES:
        return out

    parts = [p.strip() for p in internal_title.split("|")]
    out["segment"] = taxonomy.normalise_segment(parts[0])
    if len(parts) > 1 and taxonomy.is_product(parts[1]):
        out["product"] = parts[1]
    if len(parts) > 2:
        out["topic"] = parts[2] or None
    if len(parts) > 3:
        out["kind"] = parts[3] or None

    # The duration lands in whichever slot is last, so look from the end.
    for part in reversed(parts):
        if match := _DURATION.match(part):
            out["duration_seconds"] = int(match.group(1)) * 60 + int(match.group(2))
            break
    return out


def _slug(title: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (title or "demo").lower()).strip("-") or "demo"
    slug = base
    n = 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    taken.add(slug)
    return slug


def build_assets(demos: list[ConsensusDemo]) -> tuple[list[Asset], ConsensusSyncResult]:
    """Turn public Consensus demos into catalogue assets."""
    result = ConsensusSyncResult(demos_seen=len(demos))
    taken: set[str] = set()
    assets: list[Asset] = []

    for demo in demos:
        raw = demo.raw or {}
        if not raw.get("isPublic"):
            result.skipped_private += 1
            continue

        parsed = parse_internal_title(raw.get("internalTitle"))
        products = [parsed["product"]] if parsed["product"] else []

        # A Consensus demo IS the shareable artefact, so it carries its own
        # uuid rather than pointing at one. can_share_externally follows.
        assets.append(Asset(
            id=_slug(demo.title, taken),
            type=AssetType.VIDEO,
            source=SOURCE_SYSTEM,
            title=demo.title,
            description=_description(demo),
            products=products,
            segment=parsed["segment"],
            language=(raw.get("language") or {}).get("code") or "en",
            duration_seconds=parsed["duration_seconds"],
            thumbnail_url=next(iter(raw.get("previewThumbs") or []), None),
            web_url=raw.get("previewLink"),
            source_item_id=demo.uuid,
            consensus_uuid=demo.uuid,
            uploaded_at=demo.created_at.date() if demo.created_at else None,
            customer_facing=True,
        ))
        result.with_segment += bool(parsed["segment"])
        result.with_product += bool(products)

    result.indexed = len(assets)
    return assets, result


def _description(demo: ConsensusDemo) -> str | None:
    """Consensus descriptions are 76% populated but often just repeat the
    title, which adds nothing to search and clutters a card. Drop those."""
    text = (demo.raw or {}).get("description") or demo.description
    if not text:
        return None
    text = str(text).strip()
    return None if text.lower() == (demo.title or "").strip().lower() else text


def sync_demos(client: ConsensusClient, repo, limit: int = 2000) -> ConsensusSyncResult:
    """Pull public Consensus demos and replace that source's mirror.

    Uses the same `replace_source_rows` contract as the Graph sync, so
    Portal-owned data is untouched and the two sources cannot overwrite each
    other's rows.
    """
    demos = client.list_demos(limit=limit)
    assets, result = build_assets(demos)
    repo.replace_source_rows(assets, source_system=SOURCE_SYSTEM)
    if stamp := getattr(repo, "record_sync", None):
        stamp(SOURCE_SYSTEM)
    log.info("consensus sync: %s", result.as_dict())
    return result
