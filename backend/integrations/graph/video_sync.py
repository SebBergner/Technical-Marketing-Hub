"""The "Demo Video" library, indexed as a source of its own.

Where it comes from: the Brightcove Gallery migration (docs/brightcove-
migration-plan.md) writes one document set per video into "Demo Video" on
EXT-TDD, with the video file inside it. Seb and Elio want the library to hold
demo videos from other places later too, so nothing here is Brightcove-only.

Decisions this module carries (Liwei):

* **A separate source** (2026-09-28): its own mirror file,
  `mirror/demo_video.json`, so the Demo Catalog's mirror and its shrink guard
  are untouched. `source` on the asset still says "sharepoint", because that
  is where it lives and what the page does today for SharePoint -- no new
  badge appears (all source badges are to go, brief §15).
* **Product = the `HubProducts` column** (2026-09-29): the Product filter and
  the left nav's counts come from it. The managed-metadata `Product` column
  holds PTC's full taxonomy; anything in it outside HubProducts (ThingWorx,
  Vuforia...) is searchable only, and never a product here. That also keeps
  the divested-product rule (taxonomy.is_excluded), which judges `products`,
  from hiding a video over a product it merely mentions.
* **Video Type = the `VideoType` column**, whose five values the Hub uses
  as they are (brief §15; backend.models.VideoType).

What counts as a video asset: a top-level folder whose Demo Type is a known
type. The migration writes Demo Type LAST, after the file is uploaded, so a
folder still being migrated is not listed half-done.

Every run reads the whole library. At a few hundred folders that is a couple
of delta pages and one children listing -- seconds -- and it avoids keeping a
second delta cursor in step.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from backend.integrations.graph.client import GraphClient, SiteRef
from backend.integrations.graph.sync import _latest_per_item, _relative_path, _with_fields
from backend.integrations.sync_report import report
from backend.models import Asset, video_type
from backend.services import sharepoint_mapping as m

log = logging.getLogger(__name__)

#: The mirror file's name. Not what the UI sees: assets say "sharepoint".
SOURCE_SYSTEM = "demo_video"
#: Asset ids get this prefix, so a video can never take a Demo Catalog kit's
#: slug. Ids are shared links and are never reused (json_repo identity), and
#: the two libraries can hold folders with the same name.
ID_PREFIX = "video-"
#: Below this many indexed videos the shrink guard stands aside. The guard
#: catches a partial read mistaken for a full one; while the library holds a
#: handful of test items, emptying it on purpose (Liwei, 2026-09-29: the tests
#: are deleted before the real migration) is the likelier event.
SHRINK_GUARD_FROM = 20

#: Internal column names on "Demo Video", read 2026-09-29 from the library.
COLUMNS = {
    "demo_type": ("Demo_x0020_Type",),
    "segment": ("Segment",),
    "language": ("Language", "Language0"),
    "hub_products": ("HubProducts",),
    "product": ("Product",),
    "description": ("DocumentSetDescription", "Description"),
    "long_description": ("LongDescription",),
    "video_type": ("VideoType",),
    "video_subtype": ("VideoSubtype",),
    "named_customer": ("NamedCustomer",),
    "gallery": ("Gallery",),
    "gallery_section": ("GallerySection",),
    "brightcove_id": ("BrightcoveID",),
    "original_publish_date": ("OriginalPublishDate",),
    "customer_facing": ("Customer_x0020_Facing",),
    "has_audio": ("Contains_x0020_Audio",),
}


def _field(fields: dict, key: str):
    for name in COLUMNS[key]:
        if fields.get(name) not in (None, "", []):
            return fields[name]
    return None


@dataclass
class VideoSyncResult:
    assets: int = 0
    resources: int = 0
    #: Top-level folders without a known Demo Type: still being migrated, or
    #: not a demo.
    skipped_no_demo_type: int = 0
    orphan_files: int = 0
    library: str | None = None
    #: Videos given their Brightcove poster as thumbnail; None when Brightcove
    #: is not configured here, so "not looked up" never reads as "none found".
    posters: int | None = None
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return report(
            SOURCE_SYSTEM,
            unchanged=False,
            indexed=self.assets,
            examined=self.assets + self.skipped_no_demo_type,
            skipped={"no_demo_type": self.skipped_no_demo_type},
            details={"library": self.library, "resources": self.resources,
                     "orphan_files": self.orphan_files, "posters": self.posters,
                     "errors": self.errors},
        )


def _search_text(fields: dict, hub_products: list[str]) -> str | None:
    """What a search should find that no displayed field says."""
    own = {p.lower() for p in hub_products}
    other_products = [p for p in m.parse_lookup(_field(fields, "product"))
                      if p.lower() not in own]
    parts = [m.clean_text(_field(fields, "long_description")),
             *other_products,
             m.clean_text(_field(fields, "video_type")),
             m.clean_text(_field(fields, "video_subtype")),
             m.clean_text(_field(fields, "gallery")),
             m.clean_text(_field(fields, "gallery_section"))]
    text = " ".join(p for p in parts if p)
    return text or None


def build_assets(items: list[dict]) -> tuple[list[Asset], VideoSyncResult]:
    """Top-level folders with a Demo Type become assets; files below are theirs."""
    result = VideoSyncResult()
    items = _latest_per_item(items)
    assets: dict[str, dict] = {}
    stated: dict[str, tuple[bool | None, bool | None]] = {}
    taken: set[str] = set()

    for item in items:
        if "folder" not in item or item.get("deleted") or _relative_path(item):
            continue
        if (item.get("parentReference") or {}).get("path") is None:
            continue                                  # the drive root
        name = m.clean_text(item.get("name"))
        fields = ((item.get("listItem") or {}).get("fields") or {})
        demo_type = m.clean_text(_field(fields, "demo_type"))
        if not name:
            continue
        if demo_type not in m.TYPE_MAP:
            result.skipped_no_demo_type += 1
            continue

        segment, all_segments = m.parse_segment(_field(fields, "segment"))
        hub_products = m.parse_lookup(_field(fields, "hub_products"))
        asset = m.blank_asset(ID_PREFIX + m.slugify(name, taken), name,
                              m.TYPE_MAP[demo_type])
        asset.update(
            description=m.clean_text(_field(fields, "description")),
            products=hub_products,
            language=m.parse_language(_field(fields, "language")),
            segment=segment,
            rails=all_segments[1:],
            content_depth=video_type(m.clean_text(_field(fields, "video_type"))),
            named_customer=m.clean_text(_field(fields, "named_customer")),
            brightcove_id=m.clean_text(_field(fields, "brightcove_id")),
            # The video's own publish date, so a migrated back catalogue does
            # not all read as uploaded on migration day (HLR-A8).
            uploaded_at=(m.as_date(_field(fields, "original_publish_date"))
                         or m.as_date(item.get("createdDateTime"))
                         or m.as_date(item.get("lastModifiedDateTime"))),
            web_url=item.get("webUrl"),
            source_item_id=item.get("id"),
            search_text=_search_text(fields, hub_products),
            long_description=m.clean_text(_field(fields, "long_description")),
        )
        stated[name] = (m.as_bool(_field(fields, "customer_facing")),
                        m.as_bool(_field(fields, "has_audio")))
        assets[name] = asset

    for item in items:
        if "file" not in item or item.get("deleted"):
            continue
        relative = _relative_path(item)
        if not relative:
            continue
        folder, _, subfolder = relative.partition("/")
        owner = assets.get(folder)
        if owner is None:
            result.orphan_files += 1
            continue
        owner["resources"].append(
            m.build_resource(m.clean_text(item.get("name")) or "", subfolder, item))
        result.resources += 1

    for name, asset in assets.items():
        m.derive_video_facts(asset)
        # The columns are what the sheet said, so they beat the filename rule.
        m.apply_stated_flags(asset, *stated.get(name, (None, None)))

    result.assets = len(assets)
    return [Asset.model_validate(a) for a in assets.values()], result


def add_posters(assets: list[Asset], result: VideoSyncResult, brightcove) -> None:
    """Each video's Brightcove poster as its thumbnail (Liwei, 2026-10-01).

    Every migrated video carries its BrightcoveID (155 of 155 on 2026-10-01)
    and none had a thumbnail, so their cards showed the placeholder cube. The
    address is stored, not the image: it is Brightcove's public CDN, and the
    card already falls back to its cover if an image ever fails to load.

    Read-only, and it fails alone: a Brightcove problem leaves the videos
    without posters and says so in the report; the library sync stands.
    """
    if brightcove is None:
        return
    wanted = [a.brightcove_id for a in assets if a.brightcove_id and not a.thumbnail_url]
    try:
        found = brightcove.cover_images(wanted)
    except Exception as exc:                                   # noqa: BLE001
        log.warning("brightcove posters failed: %s", exc)
        result.errors.append(f"posters: {str(exc)[:200]}")
        result.posters = 0
        return
    result.posters = 0
    for asset in assets:
        src = found.get(str(asset.brightcove_id or ""))
        if src and not asset.thumbnail_url:
            asset.thumbnail_url = src
            result.posters += 1


def sync_videos(client: GraphClient, repo, site: SiteRef | None = None,
                library: str | None = None, brightcove=None) -> VideoSyncResult:
    """Read the whole library and replace this source's mirror.

    `brightcove`: the client posters are read with; by default the one the
    settings describe, if any."""
    from backend.config import settings
    from backend.integrations.brightcove import get_brightcove_client

    library = library if library is not None else settings.graph_video_library
    site = site or client.resolve_site()
    drive = client.find_drive(site.site_id, library)
    if drive is None:
        raise ValueError(f"no library named {library!r} on {site.web_url}")

    page = client.delta(drive.drive_id)
    assets, result = build_assets(_with_fields(client, drive, page.items))
    result.library = library
    add_posters(assets, result,
                brightcove if brightcove is not None else get_brightcove_client())

    counter = getattr(repo, "count_source_rows", None)
    previous = counter(SOURCE_SYSTEM) if counter else 0
    repo.replace_source_rows(assets, source_system=SOURCE_SYSTEM,
                             allow_shrink=previous < SHRINK_GUARD_FROM)
    if stamp := getattr(repo, "record_sync", None):
        stamp(SOURCE_SYSTEM)
    log.info("demo video sync: %d video(s) from %r, %s poster(s)",
             result.assets, library, result.posters)
    return result
