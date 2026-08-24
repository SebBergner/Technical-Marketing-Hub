"""Turn a Graph drive into catalogue assets.

Applies the structural rule measured from the real site:

    An asset is a TOP-LEVEL folder in Demo Catalog carrying a Demo Type.
    Everything beneath it is a resource.

All 452 such folders sit at depth 0, so a file's owner is simply the first
segment of its path below the drive root. No prefix search, no heuristics.

Field mapping is shared with the xlsx importer via
`backend.services.sharepoint_mapping`, so the seed and the live catalogue
cannot drift apart.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from backend.integrations.graph.client import (
    DeltaTokenExpired, DriveRef, GraphClient, SiteRef,
)
from backend.models import Asset
from backend.services import sharepoint_mapping as m

log = logging.getLogger(__name__)

SOURCE_SYSTEM = "sharepoint"

#: Column display names as they appear in the Demo Catalog. Graph returns
#: fields under internal names, which differ — resolved by `_field`.
COLUMNS = {
    "demo_type": ("DemoType", "Demo_x0020_Type", "Demo Type"),
    "segment": ("Segment",),
    "language": ("Language", "Language0"),
    "product": ("Product", "Product0"),
    "product_version": ("ProductVersion", "Product_x0020_Version"),
    "description": ("Description", "Description0"),
    "owner": ("OwnedBy", "Owned_x0020_By"),
    "consensus_uuid": ("ConsensusUUID", "Consensus_x0020_UUID", "ConsensusDemoUUID"),
    "brightcove_id": ("BrightcoveID", "Brightcove_x0020_ID"),
}


def _field(fields: dict, key: str):
    """Read a column by any of its known internal names.

    Graph exposes SharePoint columns under internal names (`Demo_x0020_Type`),
    which are not the display names and vary with how a column was created.
    Once the real names are confirmed from a live tenant, this collapses to a
    single lookup — until then, accept the plausible spellings rather than
    silently returning nothing.
    """
    for candidate in COLUMNS.get(key, (key,)):
        if candidate in fields and fields[candidate] not in (None, ""):
            return fields[candidate]
    return None


@dataclass
class SyncResult:
    assets: int = 0
    resources: int = 0
    skipped_no_demo_type: int = 0
    orphan_files: int = 0
    delta_token: str | None = None
    full_resync: bool = False
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "assets": self.assets, "resources": self.resources,
            "skipped_no_demo_type": self.skipped_no_demo_type,
            "orphan_files": self.orphan_files,
            "full_resync": self.full_resync,
            "has_delta_token": bool(self.delta_token),
            "errors": self.errors,
        }


def _relative_path(item: dict, drive_root_marker: str = "/root:") -> str:
    """Path below the drive root, from the item's parentReference."""
    raw = ((item.get("parentReference") or {}).get("path") or "")
    if drive_root_marker in raw:
        raw = raw.split(drive_root_marker, 1)[1]
    return raw.strip("/")


def build_assets(items: list[dict]) -> tuple[list[Asset], SyncResult]:
    """Partition drive items into assets and their resources.

    Two passes, because a file can appear before its owning folder in a delta
    page and attribution would otherwise depend on ordering.
    """
    result = SyncResult()
    assets: dict[str, dict] = {}
    taken: set[str] = set()

    # Pass 1 — top-level folders carrying a Demo Type become assets.
    for item in items:
        if "folder" not in item or item.get("deleted"):
            continue
        if _relative_path(item):        # depth > 0, so it is internal structure
            continue

        name = m.clean_text(item.get("name"))
        fields = ((item.get("listItem") or {}).get("fields") or {})
        demo_type = m.clean_text(_field(fields, "demo_type"))
        if not name:
            continue
        if demo_type not in m.TYPE_MAP:
            result.skipped_no_demo_type += 1
            continue

        segment, all_segments = m.parse_segment(_field(fields, "segment"))
        asset = m.blank_asset(m.slugify(name, taken), name, m.TYPE_MAP[demo_type])
        asset.update(
            description=m.clean_text(_field(fields, "description")),
            products=m.parse_lookup(_field(fields, "product")),
            language=m.parse_language(_field(fields, "language")),
            segment=segment,
            rails=all_segments[1:],
            content_depth=m.content_depth(name),
            consensus_uuid=m.clean_text(_field(fields, "consensus_uuid")),
            brightcove_id=m.clean_text(_field(fields, "brightcove_id")),
            uploaded_at=m.as_date(item.get("lastModifiedDateTime")),
            web_url=item.get("webUrl"),
            source_item_id=item.get("id"),
        )
        assets[name] = asset

    # Pass 2 — every file belongs to its first path segment.
    for item in items:
        if "file" not in item or item.get("deleted"):
            continue
        relative = _relative_path(item)
        if not relative:
            continue                      # a loose file at the drive root
        folder, _, subfolder = relative.partition("/")
        owner = assets.get(folder)
        if owner is None:
            result.orphan_files += 1      # under a folder with no Demo Type
            continue
        filename = m.clean_text(item.get("name")) or ""
        owner["resources"].append(m.build_resource(filename, subfolder))
        result.resources += 1

    for asset in assets.values():
        m.derive_video_facts(asset)

    result.assets = len(assets)
    return [Asset.model_validate(a) for a in assets.values()], result


def sync_catalogue(client: GraphClient, repo, site: SiteRef | None = None,
                   drive_name: str | None = None,
                   delta_token: str | None = None) -> SyncResult:
    """Pull the catalogue and replace the mirror.

    Delta is used only to detect that something changed. A partial page cannot
    safely rebuild folder membership — a file may move between assets, and the
    page would not contain the folders needed to attribute it — so any change
    triggers a full enumeration. At this catalogue's size that costs seconds
    and removes a whole class of attribution bug.

    Portal-owned data is untouched: `replace_source_rows` is the only mirror
    writer, by design.
    """
    from backend.config import settings

    site = site or client.resolve_site()
    drive = client.find_drive(site.site_id, drive_name or settings.graph_list_name)
    if drive is None:
        raise ValueError(
            f"no drive named {drive_name or settings.graph_list_name!r} on {site.web_url}")

    full = delta_token is None
    if delta_token:
        try:
            page = client.delta(drive.drive_id, delta_token)
            if not page.items:
                log.info("graph sync: no changes")
                return SyncResult(delta_token=page.delta_token or delta_token)
        except DeltaTokenExpired:
            log.warning("graph delta token expired — full resync")
            full = True

    page = client.delta(drive.drive_id) if full else page
    assets, result = build_assets(_with_fields(client, drive, page.items))
    result.delta_token = page.delta_token
    result.full_resync = full

    repo.replace_source_rows(assets, source_system=SOURCE_SYSTEM)
    return result


def _with_fields(client: GraphClient, drive: DriveRef, items: list[dict]) -> list[dict]:
    """Attach SharePoint columns to top-level folders.

    Drive delta does not expand `listItem`, so the columns that decide what is
    an asset are absent. Only top-level folders need them — a few hundred
    lookups rather than one per item — so they are fetched from the children
    listing, which does support the expansion.
    """
    top_level = {i["id"] for i in items
                 if "folder" in i and not _relative_path(i) and not i.get("deleted")}
    if not top_level:
        return items

    expanded = {c["id"]: c for c in client.list_children(drive.drive_id, "root")}
    for item in items:
        if item["id"] in top_level and item["id"] in expanded:
            item["listItem"] = expanded[item["id"]].get("listItem", {})
    return items
