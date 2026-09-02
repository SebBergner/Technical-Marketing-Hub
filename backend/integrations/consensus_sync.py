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

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field

from backend.integrations.consensus import ConsensusClient, ConsensusDemo
from backend.integrations.consensus_v2 import (
    ConsensusV2Client, folder_path, is_indexable, viewer_url,
    _as_date as _v2_date,
)
from backend.integrations.sync_report import report
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
    #: True when this pull produced byte-identical content to the last one.
    #: Consensus has no delta API, so it always re-reads everything -- without
    #: this the report is the same numbers every time and cannot be told apart
    #: from "nothing happened".
    unchanged: bool = False
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return report(
            SOURCE_SYSTEM,
            unchanged=self.unchanged,
            indexed=self.indexed,
            examined=self.demos_seen,
            skipped={"not_public": self.skipped_private},
            details={
                "with_segment": self.with_segment,
                "with_product": self.with_product,
                "no_convention": self.indexed - self.with_segment,
                "errors": self.errors,
            },
        )


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
            web_url=marketing_view(raw.get("previewLink")),
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


def fingerprint(assets: list[Asset]) -> str:
    """A stable digest of everything this sync would store.

    Consensus offers no delta, so the only way to answer "did anything actually
    change?" is to compare the result with the last one. Without it the report
    shows identical numbers on every run and a reader cannot tell a no-op from
    a full refresh — which is exactly the confusion the numbers are meant to
    remove.
    """
    payload = json.dumps([a.model_dump(mode="json") for a in assets],
                         sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def marketing_view(link: str | None) -> str | None:
    """Turn V1's `?preview=sales` link into the marketing one.

    V1 returns exactly one link per demo and it is always the sales preview.
    The marketing preview is the same URL with a different mode, so it costs a
    string replacement rather than the `marketing/createlink` call it first
    looked like it would — which matters, because that call is **not
    idempotent**: two calls for one demo returned two different hashes, so
    using it would have meant creating and caching a link per demo forever.

    Why marketing: the sales preview greets the viewer with First Viewer /
    Second Viewer buttons, which make sense when a named recipient opens a
    DemoBoard and no sense at all on a link the Hub hands to a colleague.
    """
    if not link:
        return None
    if "preview=sales" in link:
        return link.replace("preview=sales", "preview=marketing")
    if "preview=" in link:
        return link
    return link + ("&" if "?" in link else "?") + "preview=marketing"


def media_from_v1(client: ConsensusClient | None) -> dict[str, dict]:
    """uuid -> {thumbnail, preview_link}, borrowed from V1.

    V2 is better in every way except two: it returns no images at all, and it
    dropped `previewLink`. V1 carries `previewThumbs` on 95% of demos and the
    real viewer URL on all of them, both in the same response — so one call
    covers both and V2 stays authoritative for everything else.

    The link matters as much as the picture. A reconstructed
    `play.goconsensus.com/<uuid>` opens a page that does not play; the genuine
    link carries `?preview=sales` and does. Reconstruction stays as a fallback
    for when V1 is unreachable, but it is second best and this is first.

    Failure here is not failure of the sync — a catalogue with no images still
    works, one with no tags is the thing we set out to fix.
    """
    if client is None or not client.is_configured():
        return {}
    try:
        return {
            d.uuid: {
                "thumbnail": next(iter((d.raw or {}).get("previewThumbs") or []), None),
                "preview_link": marketing_view((d.raw or {}).get("previewLink")),
            }
            for d in client.list_demos(limit=2000)
        }
    except Exception as exc:                       # noqa: BLE001
        log.warning("consensus: V1 media unavailable (%s); indexing without "
                    "images, and with reconstructed viewer links", exc)
        return {}


def build_assets_v2(demos: list[dict],
                    media: dict[str, dict] | None = None,
                    ) -> tuple[list[Asset], ConsensusSyncResult]:
    """Turn V2 demo records into catalogue assets.

    Strictly better than the V1 path: tags carry segment, product, funnel stage
    and industry directly, so `internalTitle` parsing drops to a fallback for
    the 58% of demos that carry no tags. `usage` finally fills view counts,
    which V1 could not supply at all.
    """
    result = ConsensusSyncResult(demos_seen=len(demos))
    taken: set[str] = set()
    assets: list[Asset] = []

    for demo in demos:
        if not is_indexable(demo):
            result.skipped_private += 1
            continue

        extra = (media or {}).get(demo.get("uuid")) or {}
        tags = [t for t in (demo.get("tags") or []) if t and t.strip()]
        by_tag = taxonomy.classify_tags(tags)
        # internalTitle is the fallback, not the source: tags are maintained
        # deliberately, the naming convention only sometimes.
        parsed = parse_internal_title(demo.get("internalTitle"))

        products = by_tag["products"] or (
            [parsed["product"]] if parsed["product"] else [])
        segment = by_tag["segment"] or parsed["segment"]
        title = (demo.get("title") or demo.get("internalTitle") or "").strip()

        assets.append(Asset(
            id=_slug(title, taken),
            type=AssetType.VIDEO,
            source=SOURCE_SYSTEM,
            title=title,
            description=_v2_description(demo),
            products=products,
            segment=segment,
            funnel_stage=by_tag["funnel_stage"],
            content_depth=by_tag["content_depth"],
            industry=by_tag["industry"],
            tags=tags,
            language=(demo.get("language") or {}).get("code") or "en",
            duration_seconds=parsed["duration_seconds"],
            thumbnail_url=extra.get("thumbnail"),
            # The real link first; reconstruct only when V1 could not be asked.
            web_url=extra.get("preview_link") or viewer_url(demo),
            source_item_id=demo.get("uuid"),
            consensus_uuid=demo.get("uuid"),
            uploaded_at=_v2_date(demo.get("creationDate")),
            customer_facing=True,
            external_views=int(demo.get("usage") or 0) or None,
        ))
        result.with_segment += bool(segment)
        result.with_product += bool(products)

    result.indexed = len(assets)
    return assets, result


def _v2_description(demo: dict) -> str | None:
    """Prefer the description, fall back to the folder path.

    V2 descriptions are often empty, and the folder hierarchy —
    "PTC Digital Thread / Event Support / PTC NEXT - Spring 2026" — is real
    context that would otherwise be discarded, and it is searchable.
    """
    text = (demo.get("description") or "").strip()
    if text and text.lower() != (demo.get("title") or "").strip().lower():
        return text
    path = folder_path(demo)
    return " / ".join(path) if path else None


class WouldDowngrade(RuntimeError):
    """A V1 sync would replace richer V2 data with poorer V1 data.

    The mirror is replaced wholesale, so running V1 over a V2 mirror discards
    every tag, funnel stage, content depth and view count -- silently, and
    exactly the metadata V2 was adopted for. The likeliest cause is a lapsed
    token, which is not a reason to throw the data away.
    """


def sync_demos_v2(client: ConsensusV2Client, repo,
                  v1_client: ConsensusClient | None = None) -> ConsensusSyncResult:
    """Index Consensus through V2, with V1 supplying only the images."""
    demos = client.all_demos()
    assets, result = build_assets_v2(demos, media_from_v1(v1_client))
    digest = fingerprint(assets)
    previous = (getattr(repo, "sync_state", lambda _: {})(SOURCE_SYSTEM) or {})
    result.unchanged = bool(previous.get("fingerprint"))         and previous["fingerprint"] == digest
    repo.replace_source_rows(assets, source_system=SOURCE_SYSTEM)
    if stamp := getattr(repo, "record_sync", None):
        stamp(SOURCE_SYSTEM, digest, api="v2")
    log.info("consensus v2 sync: %s", result.as_dict())
    return result


def sync_demos(client: ConsensusClient, repo, limit: int = 2000,
               allow_downgrade: bool = False) -> ConsensusSyncResult:
    """Pull public Consensus demos and replace that source's mirror.

    Uses the same `replace_source_rows` contract as the Graph sync, so
    Portal-owned data is untouched and the two sources cannot overwrite each
    other's rows.
    """
    previous_api = (getattr(repo, "sync_state", lambda _: {})(SOURCE_SYSTEM)
                    or {}).get("api")
    if previous_api == "v2" and not allow_downgrade:
        raise WouldDowngrade(
            "This mirror was built from Consensus V2 and a V1 sync would "
            "replace it, discarding every tag, funnel stage, content depth and "
            "view count -- the metadata V2 exists to provide. The usual cause "
            "is an expired CONSENSUS_V2_TOKEN; refresh it at "
            "https://app.goconsensus.com/api/v2/docs/portal/ rather than "
            "syncing over the data. Pass allow_downgrade to overrule this.")

    demos = client.list_demos(limit=limit)
    assets, result = build_assets(demos)

    digest = fingerprint(assets)
    previous = (getattr(repo, "sync_state", lambda _: {})(SOURCE_SYSTEM) or {})
    result.unchanged = bool(previous.get("fingerprint"))         and previous["fingerprint"] == digest

    # Still written even when unchanged: the mirror is cheap to rewrite, and
    # skipping it would leave a gap if the mirror had been cleared by hand.
    repo.replace_source_rows(assets, source_system=SOURCE_SYSTEM)
    if stamp := getattr(repo, "record_sync", None):
        stamp(SOURCE_SYSTEM, digest, api="v1")
    log.info("consensus sync: %s", result.as_dict())
    return result
