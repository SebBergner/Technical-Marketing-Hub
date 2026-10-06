"""Demo pages: the EXT-TDD site's "SitePages/Demo Catalog/" pages as a source.

Liwei, 2026-10-05: the Lamborghini IPL demo has a page and no Demo Catalog
project folder, and it has to be in the Hub. Many demos have both. So:

    page + project folder   the folder's demo, as today, with the page's
                            thumbnail and a quiet link to the page
    project folder only     unchanged
    page only               a demo built from the page alone: its title,
                            description, products and thumbnail, and the page
                            as its link -- no files, so nothing to preview or
                            download

A page carries its own metadata as Site Pages columns (Demo Type, Product,
Segment, Language, ShortDescription), and its thumbnail as `thumbnailWebUrl`.
Which project folder it belongs to is not a column: the page's web parts say
it -- a Document library web part opened on the folder, or Quick links into
its files (measured 2026-10-05: 259 of 278 pages reference a Demo Catalog
folder, 230 of them a folder the Hub lists; 31 reference more than one, e.g.
a Codebeamer page also linking another kit, hence `pick_folder`).

Every page is mirrored with the folder it points at. Whether that folder is a
Hub demo is decided when the catalogue is read (json_repo._apply_demo_pages),
not here: the Demo Catalog mirror is another source's, and a folder that gains
its Demo Type later should start matching without this sync re-running.
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import unquote

from backend.integrations.graph.client import GraphClient, SiteRef
from backend.integrations.sync_report import report
from backend.models import Asset
from backend.services import sharepoint_mapping as m
from backend.services import taxonomy

log = logging.getLogger(__name__)

GRAPH = "https://graph.microsoft.com/v1.0"
SOURCE_SYSTEM = "demo_pages"
DEMO_PAGES_FOLDER = "/SitePages/Demo Catalog/"
#: Chinese translations of the same pages live in a subfolder; the English
#: page is the demo.
TRANSLATION_FOLDERS = ("/zh-chs/",)
SHRINK_GUARD_FROM = 50

#: The page's Demo Type column says "Video Demo Kit" where the Demo Catalog's
#: says "Virtual Demo Kit" (both measured 2026-10-05); either is a VDK.
PAGE_TYPE_MAP = {"live demo kit": "ldk", "video demo kit": "vdk",
                 "virtual demo kit": "vdk", "video": "video"}

#: A Demo Catalog folder inside a link or a web part property. Stops at "&"
#: (the Document library web part's `selectedFolderKey` appends
#: "&listurl=..."); a "&" inside a folder name arrives URL-encoded and is
#: decoded per match, after the boundary is found.
_FOLDER = re.compile(r"/Demo(?:%20| )Catalog/([^/\"?#&\\]+)", re.I)


@dataclass
class DemoPageSyncResult:
    pages: int = 0
    with_folder: int = 0
    skipped_no_demo_type: int = 0
    canvases_read: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return report(
            SOURCE_SYSTEM, unchanged=False, indexed=self.pages,
            examined=self.pages + self.skipped_no_demo_type,
            skipped={"no_demo_type": self.skipped_no_demo_type},
            details={"with_folder": self.with_folder,
                     "canvases_read": self.canvases_read, "errors": self.errors},
        )


def _norm(text: str | None) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (text or "").lower()))


def folders_in(canvas: dict) -> tuple[str | None, Counter]:
    """The folder a Document library web part is opened on (explicit), and a
    count of every Demo Catalog folder the page's web parts mention."""
    explicit = None
    for sec in canvas.get("horizontalSections") or []:
        for col in sec.get("columns") or []:
            for wp in col.get("webparts") or []:
                props = ((wp.get("data") or {}).get("properties") or {})
                if props.get("isDocumentLibrary") and props.get("selectedFolderPath") \
                        and "Demo Catalog" in str(props.get("selectedListUrl") or ""):
                    explicit = explicit or str(props["selectedFolderPath"]).split("/")[0]
    blob = json.dumps(canvas, ensure_ascii=False).replace("\\/", "/")
    seen = Counter()
    for match in _FOLDER.finditer(blob):
        name = unquote(match.group(1)).strip()
        if name and not name.lower().endswith(".aspx"):
            seen[name] += 1
    return explicit, seen


def pick_folder(title: str | None, explicit: str | None, seen: Counter) -> str | None:
    """Which folder the page is about, when it mentions several.

    The Document library web part's folder first -- an author chose it; then
    a folder whose name says what the page title says; then the one the page
    links into most."""
    if explicit:
        return explicit
    if not seen:
        return None
    wanted = _norm(title)
    for name in seen:
        if _norm(name) == wanted:
            return name
    for name in seen:
        n = _norm(name)
        if n and wanted and (n in wanted or wanted in n):
            return name
    return seen.most_common(1)[0][0]


def build_asset(page: dict, fields: dict, folder: str | None, taken: set[str]) -> Asset | None:
    """One page as a catalogue row. None when the page names no Demo Type:
    which kind of demo it is cannot be guessed."""
    demo_type = PAGE_TYPE_MAP.get(str(fields.get("Demo_x0020_Type") or "").strip().lower())
    if demo_type is None:
        return None
    title = m.clean_text(fields.get("Title") or page.get("title")) or page.get("name")
    asset = m.blank_asset("page-" + m.slugify(title, taken), title, demo_type)
    # On pages Segment is managed metadata ({"Label": "CAD", ...}), not the
    # Demo Catalog's plain text (measured 2026-10-05): labels first.
    segment, _ = m.parse_segment(m.parse_lookup(fields.get("Segment")))
    language = fields.get("Language")
    asset.update(
        description=m.clean_text(fields.get("ShortDescription") or fields.get("Description")
                                 or page.get("description")),
        products=m.parse_lookup(fields.get("Product")),
        segment=taxonomy.normalise_segment(segment),
        language=m.parse_language(language[0] if isinstance(language, list) and language else language),
        uploaded_at=m.as_date(fields.get("Created") or page.get("createdDateTime")),
        thumbnail_url=page.get("thumbnailWebUrl") or None,
        web_url=page.get("webUrl"),
        page_url=page.get("webUrl"),
        page_folder=folder,
        source_item_id=page.get("id"),
    )
    asset["source"] = "sharepoint"
    return Asset.model_validate(asset)


def _page_items(client: GraphClient, site: SiteRef) -> dict[str, dict]:
    """Site Pages list fields, keyed by the page's URL."""
    # The library is hidden from GET /lists; by name it answers to its
    # display name ("Site Pages"), not to its URL name (measured 2026-10-05).
    pages_list = None
    for name in ("Site Pages", "SitePages"):
        pages_list = client._request("GET", f"{GRAPH}/sites/{site.site_id}/lists/{name}",
                                     params={"$select": "id"})
        if pages_list:
            break
    if not pages_list:
        raise ValueError("the Site Pages library could not be found")
    items = client._paged(f"{GRAPH}/sites/{site.site_id}/lists/{pages_list['id']}/items",
                          params={"$expand": "fields", "$select": "id,webUrl,fields", "$top": "200"})
    return {unquote(i.get("webUrl") or ""): (i.get("fields") or {}) for i in items}


def sync_demo_pages(client: GraphClient, repo, site: SiteRef | None = None) -> DemoPageSyncResult:
    """Read every Demo Catalog page and replace this source's mirror.

    A page's web parts are read only when the page changed since the last
    sync: the folder it points at is kept on its mirror row, so an unchanged
    page costs nothing beyond the page list."""
    site = site or client.resolve_site()
    result = DemoPageSyncResult()
    pages = [p for p in client._paged(
                 f"{GRAPH}/sites/{site.site_id}/pages/microsoft.graph.sitePage",
                 params={"$select": "id,name,title,webUrl,description,thumbnailWebUrl,"
                                    "createdDateTime,lastModifiedDateTime"})
             if DEMO_PAGES_FOLDER in unquote(p.get("webUrl") or "")
             and not any(t in unquote(p.get("webUrl") or "") for t in TRANSLATION_FOLDERS)]
    fields_by_url = _page_items(client, site)
    reader = getattr(repo, "source_rows", None)
    previous = {r.get("source_item_id"): r for r in (reader(SOURCE_SYSTEM) if reader else [])}

    taken: set[str] = set()
    assets: list[Asset] = []
    for page in pages:
        fields = fields_by_url.get(unquote(page.get("webUrl") or ""), {})
        before = previous.get(page.get("id"))
        if before and before.get("page_modified") == page.get("lastModifiedDateTime"):
            folder = before.get("page_folder")
        else:
            try:
                full = client._request(
                    "GET", f"{GRAPH}/sites/{site.site_id}/pages/{page['id']}/microsoft.graph.sitePage",
                    params={"$expand": "canvasLayout"})
                result.canvases_read += 1
                explicit, seen = folders_in(full.get("canvasLayout") or {})
                folder = pick_folder(fields.get("Title") or page.get("title"), explicit, seen)
            except Exception as exc:                                 # noqa: BLE001
                result.errors.append(f"{page.get('name')}: {str(exc)[:120]}")
                folder = before.get("page_folder") if before else None
        asset = build_asset(page, fields, folder, taken)
        if asset is None:
            result.skipped_no_demo_type += 1
            continue
        asset.page_modified = page.get("lastModifiedDateTime")
        assets.append(asset)
        result.pages += 1
        result.with_folder += bool(folder)

    counter = getattr(repo, "count_source_rows", None)
    previous_count = counter(SOURCE_SYSTEM) if counter else 0
    repo.replace_source_rows(assets, source_system=SOURCE_SYSTEM,
                             allow_shrink=previous_count < SHRINK_GUARD_FROM)
    if stamp := getattr(repo, "record_sync", None):
        stamp(SOURCE_SYSTEM)
    log.info("demo pages sync: %d page(s), %d with a folder, %d canvas(es) read",
             result.pages, result.with_folder, result.canvases_read)
    return result
