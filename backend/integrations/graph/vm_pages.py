"""Virtual machines, from the EXT-TDD site's "Virtual Machines" pages.

Where the data comes from, measured 2026-09-23
----------------------------------------------
Three places on the site mention VMs, and only one is alive:

* **SitePages/Virtual Machines/** -- 38 pages (plus translation drafts),
  7 edited this year and 19 last year. The source of truth, and what this
  module reads.
* the "Virtual Machine Catalog" library -- 49 entries, newest 2024-02-23,
  half marked Archived, "Supported Demos" empty on every one. Not used.
* the "VM - Related Demos" list -- one item. Not used.

The pages have no shared template. The ACD page has a dozen sections (live
demo server, cloud template, setup steps, requirements, installed software,
credentials, related VM); the current Windchill page has two and an embedded
PDF. So nothing here assumes a section exists: a page is read as headings
and what is under them, plus the links and files its web parts carry.

Credentials: in the Hub, but sealed
-----------------------------------
Several pages carry working passwords -- the ACD page's OS login, a demo
password, an admin table. Liwei's decision (2026-09-23) was to keep them in
the Hub but show them only to someone signed in. What that means here:

* a block or section that looks like a credential is **sealed**: its content
  is removed from the public record and replaced by a marker, and the content
  goes into a separate file (mirror/private/vm_credentials.json) that the
  catalogue loader never reads -- it only reads top-level *.json in mirror/.
  One endpoint reads it, and requires a signed-in user.
* the test is deliberately greedy. A heading about credentials or logins
  seals its whole section; a line mentioning a password, a table whose header
  says so, seal themselves. Sealing too much costs a click after signing in;
  sealing too little publishes a password. Until SSO exists nobody on Azure
  is signed in, so sealed content is shown to nobody there -- fail closed.
* one last pass (`_assert_nothing_leaks`) scans everything public for the
  same patterns and seals whatever slipped through, rather than trusting the
  first pass to be complete.

Related assets, and how much to trust each
------------------------------------------
    page      the VM page links to the demo            -- the author said so
    supports  the page's "Supported Demo Material" web part names it
    inferred  same dataset (e.g. "Snowmobile") and product family
Every relation carries its `via`, and the UI says which, because a link
someone wrote and a match worked out from a title are not equally reliable.

A supports-query can also name a whole slice -- `Segment:"PLM" AND
WORDS(LDK)` on the older Windchill pages. That becomes a filter link ("every
PLM LDK"), not a list of hundreds.
"""
from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
from urllib.parse import unquote, urlparse

from backend.models import (
    Asset, AssetType, UsedByVm, VmBlock, VmDetail, VmDocument, VmLink, VmRelated,
    VmSection, VmSupportsFilter,
)
from backend.services import taxonomy

log = logging.getLogger(__name__)

SOURCE_SYSTEM = "vm_pages"
TENANT = "https://ptccloud.sharepoint.com"
VM_FOLDER = "/SitePages/Virtual Machines/"
DEMO_PAGES_FOLDER = "/SitePages/Demo Catalog/"

# ──────────────────────────────────────────────────────────── what is secret
#: A section under one of these headings is sealed whole.
_SECRET_HEADING = re.compile(
    r"credential|password|passwd|\busers? (?:and|&) pass|\blog ?-?in\b|\bsign ?-?in\b|account",
    re.I)
#: A line, table row or label mentioning one of these is sealed.
_SECRET_LINE = re.compile(
    r"pass ?-?word|passwd|\bpwd\b|\bpw\s*[:=]|\bsecret\b|api[ _-]?key|\btoken\b|"
    r"client[ _-]?secret|connection string", re.I)
#: A table whose header row mentions one of these is sealed whole.
_SECRET_HEADER = re.compile(r"pass ?-?word|passwd|\bpass\b|\bpwd\b|credential", re.I)


def is_secret_line(text: str | None) -> bool:
    return bool(text) and bool(_SECRET_LINE.search(text))


# ──────────────────────────────────────────────────────────── HTML → blocks
@dataclass
class _Event:
    kind: str                       # heading | p | li | table
    text: str = ""
    rows: list[list[str]] | None = None
    links: list[tuple[str, str]] = field(default_factory=list)


class _TextWebPart(HTMLParser):
    """The rich-text web part's HTML, as headings and blocks in reading order.

    SharePoint's editor emits a small vocabulary -- h1-h4, p, ul/ol/li,
    tables, a, br, and inline spans -- so a flat event stream is enough.
    Text is taken, never markup: nothing from the source is ever rendered as
    HTML in the Hub.
    """
    _BLOCKS = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.events: list[_Event] = []
        self._kind: str | None = None
        self._buf: list[str] = []
        self._links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._a_text: list[str] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    # -- flushing
    def _flush(self):
        text = _clean("".join(self._buf))
        if text or self._links:
            kind = self._kind or "p"
            if kind.startswith("h") and kind[1:].isdigit():
                kind = "heading"
            elif kind not in ("li",):
                kind = "p"
            self.events.append(_Event(kind, text, links=list(self._links)))
        self._buf, self._links, self._kind = [], [], None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._flush()
            self._table = []
            return
        if self._table is not None:
            if tag == "tr":
                self._row = []
            elif tag in ("td", "th"):
                self._cell = []
            elif tag == "br" and self._cell is not None:
                self._cell.append(" ")
            elif tag == "a":
                self._href = dict(attrs).get("href")
                self._a_text = []
            return
        if tag in self._BLOCKS:
            self._flush()
            self._kind = tag
        elif tag == "br":
            self._buf.append("\n")
        elif tag == "a":
            self._href = dict(attrs).get("href")
            self._a_text = []

    def handle_endtag(self, tag):
        if self._table is not None:
            if tag in ("td", "th") and self._row is not None and self._cell is not None:
                self._row.append(_clean("".join(self._cell)))
                self._cell = None
            elif tag == "tr" and self._row is not None:
                if any(c for c in self._row):
                    self._table.append(self._row)
                self._row = None
            elif tag == "table":
                if self._table:
                    self.events.append(_Event("table", rows=self._table,
                                              links=list(self._links)))
                self._table, self._links = None, []
            elif tag == "a":
                self._close_link()
            return
        if tag == "a":
            self._close_link()
        elif tag in self._BLOCKS:
            self._flush()

    def _close_link(self):
        if self._href:
            label = _clean("".join(self._a_text)) or self._href
            self._links.append((label, self._href))
        self._href, self._a_text = None, []

    def handle_data(self, data):
        if self._href is not None:
            self._a_text.append(data)
        if self._cell is not None:
            self._cell.append(data)
        elif self._table is None:
            self._buf.append(data)

    def close(self):
        super().close()
        self._flush()


def _clean(text: str) -> str:
    text = html.unescape(text).replace(" ", " ").replace("​", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


# ────────────────────────────────────────────────────────────────── links
def absolute(url: str) -> str:
    url = html.unescape(url or "").strip()
    return TENANT + url if url.startswith("/") else url


_DOC_EXT = re.compile(r"\.(pdf|docx?|xlsx?|pptx?|zip|7z|txt|csv|vsdx?)$", re.I)


def classify_link(url: str, label: str = "") -> str:
    """What a link points at, which decides where it goes on the Hub page."""
    u = unquote(absolute(url))
    path = urlparse(u).path
    if not u or u.startswith("#") or u.lower().startswith(("mailto:", "javascript:")):
        return "skip"
    host = urlparse(u).netloc.lower()
    if "portal.ptc.io" in host:
        return "cloud_portal"
    if VM_FOLDER in path:
        return "vm_page"
    if DEMO_PAGES_FOLDER in path:
        return "demo_page"
    if u.lower().startswith("ftp:") or re.search(r"\bftp\b|download", label, re.I):
        return "download"
    if _DOC_EXT.search(path):
        return "document"
    if "/Demo Catalog/" in path:
        return "demo_folder"
    return "other"


def page_key(url: str) -> str:
    """The filename of a SharePoint page, for matching links to pages."""
    return unquote(urlparse(absolute(url)).path).rsplit("/", 1)[-1].lower()


def _demo_folder(url: str) -> tuple[str, str | None]:
    """(top folder under Demo Catalog, file name or None)."""
    path = unquote(urlparse(absolute(url)).path)
    rest = path.split("/Demo Catalog/", 1)[-1].strip("/")
    parts = [p for p in rest.split("/") if p]
    if not parts:
        return "", None
    name = parts[-1] if _DOC_EXT.search(parts[-1]) else None
    return parts[0].lower(), (name.lower() if name else None)


# ─────────────────────────────────────────────────────────── one page
@dataclass
class ParsedPage:
    sections: list[VmSection]
    secrets: dict                       # sealed content, keyed for the UI
    actions: list[VmLink]
    documents: list[tuple[str, str]]    # (name, url)
    link_urls: list[str]                # every link, for relations
    supports_titles: list[str]
    supports_filters: list[VmSupportsFilter]
    sealed_count: int


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:60] or "section"


def _webparts(layout: dict):
    for hs in layout.get("horizontalSections") or []:
        for col in hs.get("columns") or []:
            yield from col.get("webparts") or []
    yield from (layout.get("verticalSection") or {}).get("webparts") or []


def _texts(spc: dict) -> dict[str, str]:
    return {t.get("key"): t.get("value") or "" for t in spc.get("searchablePlainTexts") or []}


def _links(spc: dict) -> dict[str, str]:
    return {l.get("key"): l.get("value") or "" for l in spc.get("links") or []}


def parse_page(layout: dict) -> ParsedPage:
    """A page's canvas, as public sections plus everything sealed out of them.

    Pure: no network, no repository. The unit tests drive it directly.
    """
    events: list[_Event] = []
    actions: list[VmLink] = []
    documents: list[tuple[str, str]] = []
    link_urls: list[str] = []
    supports_titles: list[str] = []
    supports_filters: list[VmSupportsFilter] = []

    for wp in _webparts(layout or {}):
        otype = str(wp.get("@odata.type", ""))
        if otype.endswith("textWebPart"):
            parser = _TextWebPart()
            parser.feed(wp.get("innerHtml") or "")
            parser.close()
            events.extend(parser.events)
            continue
        data = wp.get("data") or {}
        kind = (data.get("title") or "").strip().lower()
        spc = data.get("serverProcessedContent") or {}
        texts, links = _texts(spc), _links(spc)

        if kind in ("button", "call to action"):
            label = texts.get("label") or texts.get("title") or texts.get("buttonText") or ""
            url = next((v for k, v in links.items() if k != "baseUrl" and v), "")
            if url:
                link_urls.append(url)
                _add_action(actions, label, url)
        elif kind == "quick links":
            for key, url in links.items():
                m = re.match(r"items\[(\d+)\]\.sourceItem\.url", key or "")
                if not m or not url:
                    continue
                label = texts.get(f"items[{m.group(1)}].title") or ""
                link_urls.append(url)
                _add_action(actions, label, url)
        elif kind in ("file and media", "file viewer", "document embed"):
            url = links.get("serverRelativeUrl") or links.get("wopiurl") or ""
            if url:
                name = unquote(urlparse(absolute(url)).path).rsplit("/", 1)[-1]
                documents.append((name, url))
                link_urls.append(url)
        elif kind == "document library":
            props = data.get("properties") or {}
            url = props.get("selectedListUrl") or ""
            if url:
                label = texts.get("listTitle") or "Document library"
                link_urls.append(url)
                _add_action(actions, label, url, kind="other")
        elif kind == "highlighted content":
            query = ((data.get("properties") or {}).get("query") or {}).get("advancedQueryText") or ""
            titles, filters = parse_supports_query(query)
            supports_titles += titles
            supports_filters += filters

    for ev in events:
        for label, url in ev.links:
            link_urls.append(url)
            if classify_link(url, label) == "document":
                documents.append((label if _DOC_EXT.search(label) else
                                  unquote(urlparse(absolute(url)).path).rsplit("/", 1)[-1], url))

    sections, secrets, sealed = _sections(events)
    actions = [a for a in actions if not is_secret_line(a.label)]
    return ParsedPage(sections, secrets, actions, _dedupe_docs(documents), link_urls,
                      supports_titles, supports_filters, sealed)


def _add_action(actions: list[VmLink], label: str, url: str, kind: str | None = None):
    kind = kind or classify_link(url, label)
    if kind in ("skip", "vm_page", "demo_page", "demo_folder", "document"):
        return          # relations and documents are shown elsewhere
    url = absolute(url)
    if any(a.url == url for a in actions):
        return
    label = (label or "").strip()
    if not label or _BARE_URL.match(label):
        # Pages paste the address itself as the link text; a button reading
        # "https://portal.ptc.io/ProvPortal/..." says less than what it does.
        label = _ACTION_LABEL.get(kind, url)
    actions.append(VmLink(label=label[:120], url=url, kind=kind))


_BARE_URL = re.compile(r"^(https?|ftp)://", re.I)
_ACTION_LABEL = {"cloud_portal": "Open the PTC Cloud Portal", "download": "Download"}


def _complete_description(description: str | None, sections: list[VmSection]) -> str | None:
    """SharePoint stores a page's description cut off mid-word (about 255
    characters of its first paragraph). When the page's first public
    paragraph is where it was cut from, use that paragraph whole."""
    if not description:
        return description
    for section in sections[:1]:
        for block in section.blocks:
            if block.sealed or block.kind != "p" or not block.text:
                continue
            text, cut = " ".join(block.text.split()), " ".join(description.split())
            if len(text) > len(cut) and text.startswith(cut):
                return text[:1000]
            return description
    return description


def _dedupe_docs(docs):
    seen, out = set(), []
    for name, url in docs:
        key = absolute(url).lower()
        if key not in seen:
            seen.add(key)
            out.append((name, url))
    return out


def _sections(events: list[_Event]):
    """Group events under their headings, sealing credentials on the way."""
    sections: list[VmSection] = []
    secrets: dict = {"sections": {}, "blocks": {}}
    sealed_count = 0
    used_ids: set[str] = set()
    current = VmSection(id="overview", heading=None)
    used_ids.add("overview")

    def start(heading: str):
        nonlocal current
        base = _slug(heading)
        sid, n = base, 2
        while sid in used_ids:
            sid, n = f"{base}-{n}", n + 1
        used_ids.add(sid)
        current = VmSection(id=sid, heading=heading,
                            sealed=bool(_SECRET_HEADING.search(heading)))

    def close():
        if current.blocks or current.heading:
            sections.append(current)

    for ev in events:
        if ev.kind == "heading":
            close()
            start(ev.text)
            continue
        block = VmBlock(kind=ev.kind, text=ev.text or None, rows=ev.rows,
                        links=[_to_link(l, u) for l, u in ev.links
                               if classify_link(u, l) != "skip"])
        current.blocks.append(block)
    close()

    for section in sections:
        if section.sealed:
            secrets["sections"][section.id] = [b.model_dump() for b in section.blocks]
            count = len(section.blocks)
            section.blocks = [VmBlock(kind="p", sealed=True)] if count else []
            sealed_count += 1
            continue
        for i, block in enumerate(section.blocks):
            if _block_is_secret(block):
                secrets["blocks"][f"{section.id}:{i}"] = block.model_dump()
                section.blocks[i] = VmBlock(kind=block.kind, sealed=True)
                sealed_count += 1

    sealed_count += _assert_nothing_leaks(sections, secrets)
    return [s for s in sections if s.blocks or s.heading], secrets, sealed_count


def _to_link(label: str, url: str) -> VmLink:
    return VmLink(label=(label or url)[:120], url=absolute(url),
                  kind=classify_link(url, label))


def _block_is_secret(block: VmBlock) -> bool:
    if block.kind == "table" and block.rows:
        if any(_SECRET_HEADER.search(c or "") for c in block.rows[0]):
            return True
        return any(is_secret_line(" ".join(r)) for r in block.rows)
    return is_secret_line(block.text) or any(is_secret_line(l.label) for l in block.links)


def _assert_nothing_leaks(sections: list[VmSection], secrets: dict) -> int:
    """Second pass over what will be public. Anything that still matches is
    sealed here, and logged -- it means the first pass has a gap."""
    extra = 0
    for section in sections:
        if section.sealed:
            continue
        for i, block in enumerate(section.blocks):
            if block.sealed:
                continue
            blob = " ".join(filter(None, [block.text] + [" ".join(r) for r in block.rows or []]
                                   + [l.label for l in block.links]))
            if is_secret_line(blob):
                log.warning("vm page: a credential survived the first pass in %r", section.heading)
                secrets["blocks"][f"{section.id}:{i}"] = block.model_dump()
                section.blocks[i] = VmBlock(kind=block.kind, sealed=True)
                extra += 1
    return extra


def parse_supports_query(query: str) -> tuple[list[str], list[VmSupportsFilter]]:
    """The "Supported Demo Material" web part's search query, understood.

        (title:"Snowmobile - Arbortext Content Delivery - LDK") ... WORDS(LDK)
            -> the named demo
        (Segment:"PLM") ... WORDS(LDK)
            -> a filter: every PLM LDK
    """
    titles = re.findall(r'title\s*:\s*"([^"]+)"', query or "", re.I)
    segments = re.findall(r'segment\s*:\s*"([^"]+)"', query or "", re.I)
    words = [w.lower() for w in re.findall(r"WORDS\(([^)]+)\)", query or "", re.I)]
    kind = AssetType.LDK if "ldk" in words else AssetType.VDK if "vdk" in words else None
    filters = []
    if not titles:
        for seg in segments:
            name = taxonomy.normalise_segment(seg) or seg
            label = f"Every {name} {kind.value.upper() if kind else 'demo'}"
            filters.append(VmSupportsFilter(label=label, segment=name, type=kind))
    return titles, filters


# ─────────────────────────────────────────────────────── facts from a title
#: Shorthand used in VM titles, mapped to the families the catalogue knows.
#: Only what the 38 pages actually use (2026-09-23).
_TITLE_ABBREVIATIONS = {
    "acd": "Arbortext Content Delivery",
    "cb": "Codebeamer",
    "twx": "ThingWorx",
    "modeler": "PTC Modeler",
}
_VERSION = re.compile(r"\b\d+(?:\.\d+){1,3}\b")


def products_in_title(title: str, known_products: set[str]) -> list[str]:
    """Products named in a VM title, most specific first.

    A full product name the catalogue already uses wins ("Arbortext Content
    Delivery"), then a family name ("Windchill", "ThingWorx"), then the
    shorthand above. Nothing is guessed beyond that: "3rd Party CAD" names no
    PTC product, and gets none.
    """
    low = title.lower()
    found: list[str] = []
    for product in sorted(known_products, key=len, reverse=True):
        if len(product) > 3 and re.search(r"\b" + re.escape(product.lower()) + r"\b", low):
            if not any(product.lower() in f.lower() for f in found):
                found.append(product)
    for family in sorted(taxonomy.known_families(), key=len, reverse=True):
        if re.search(r"\b" + re.escape(family.lower()) + r"\b", low):
            if not any(taxonomy.family_of(f) == family for f in found):
                found.append(family)
    for short, product in _TITLE_ABBREVIATIONS.items():
        if re.search(r"\b" + re.escape(short) + r"\b", low) and product not in found:
            if not any(taxonomy.family_of(f) == taxonomy.family_of(product) for f in found):
                found.append(product)
    return found


def version_in_title(title: str) -> str | None:
    """The version, when the title has exactly one. A bundle like
    "ALM (CB 3.3.0 RVS 13.5 Modeler 10.3)" has four, and picking one would
    label the VM with a single product's version."""
    versions = _VERSION.findall(title)
    return versions[0] if len(versions) == 1 else None


def segment_in_title(title: str) -> str | None:
    """Only when the title says it -- deriving a segment from the product
    would be a guess this module does not make."""
    for word in re.findall(r"[A-Za-z]+", title):
        if taxonomy.is_segment(word):
            return taxonomy.normalise_segment(word)
    return None


# ──────────────────────────────────────────────────────── matching titles
def normalise_title(title: str) -> str:
    t = (title or "").lower().replace("&", " and ")
    t = re.sub(r"\.aspx$", "", t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    t = re.sub(r"\bv ?\d+(?: \d+)*\b", " ", t)          # v1, v 1 0, v.1.0
    return re.sub(r"\s+", " ", t).strip()


@dataclass
class Catalogue:
    """What the VM pages are matched against: the rest of the mirror."""
    by_title: dict[str, dict]
    by_folder: dict[str, dict]
    by_file: dict[tuple[str, str], tuple[str, str]]    # (folder, file) -> (asset_id, item_id)
    datasets: set[str]
    products: set[str]
    records: list[dict]

    @classmethod
    def build(cls, records: list[dict]) -> "Catalogue":
        by_title, by_folder, by_file = {}, {}, {}
        prefixes: dict[str, int] = {}
        products: set[str] = set()
        for r in records:
            if r.get("type") == AssetType.VM.value:
                continue
            by_title.setdefault(normalise_title(r.get("title", "")), r)
            m = re.search(r"/Demo Catalog/([^/?&#]+)", unquote(r.get("web_url") or ""))
            if m:
                folder = m.group(1).strip().lower()
                by_folder.setdefault(folder, r)
                for res in r.get("resources") or []:
                    if res.get("item_id") and res.get("name"):
                        by_file[(folder, res["name"].lower())] = (r["id"], res["item_id"])
            products.update(p for p in r.get("products") or [] if taxonomy.is_product(p))
            head = (r.get("title") or "").split(" - ", 1)[0].strip()
            if " - " in (r.get("title") or "") and 2 < len(head) <= 30:
                prefixes[head.lower()] = prefixes.get(head.lower(), 0) + 1
        # A dataset is a title prefix several demos share ("Snowmobile - ...")
        # that is not itself a product or family ("ThingWorx Applications - ").
        families = {f.lower() for f in taxonomy.known_families()}
        datasets = {p for p, n in prefixes.items() if n >= 3
                    and p not in families and p not in {x.lower() for x in products}
                    and not any(p.startswith(f) for f in families)}
        return cls(by_title, by_folder, by_file, datasets, products, records)

    def match_title(self, title: str) -> dict | None:
        key = normalise_title(title)
        if not key:
            return None
        if key in self.by_title:
            return self.by_title[key]
        # "X LDK" on the page, "X LDK v1.0" in the catalogue, or the reverse.
        candidates = [(k, r) for k, r in self.by_title.items()
                      if k.startswith(key) or key.startswith(k)]
        candidates = [(k, r) for k, r in candidates if min(len(k), len(key)) >= 12]
        return max(candidates, key=lambda kr: len(kr[0]))[1] if candidates else None


#: Folders under Demo Catalog that hold documents, not demos. A VM page links
#: to "Release Notes" for its PDF; that is a document, not a related demo.
_NOT_DEMO_FOLDERS = {"release notes"}


# ──────────────────────────────────────────────────────────── the builder
@dataclass
class VmSyncResult:
    pages_seen: int = 0
    vms: int = 0
    duplicates_dropped: int = 0
    sealed: int = 0
    related_page: int = 0
    related_supports: int = 0
    related_inferred: int = 0
    supports_filters: int = 0
    documents: int = 0
    documents_previewable: int = 0
    unresolved_demo_links: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = dict(self.__dict__)
        d["unresolved_demo_links"] = sorted(set(self.unresolved_demo_links))[:25]
        return d


def is_vm_page(page: dict) -> bool:
    url = unquote(page.get("webUrl") or "")
    title = page.get("title") or ""
    return VM_FOLDER in url and not title.lower().startswith("translate into")


def build_vm_assets(pages: list[dict], layouts: dict[str, dict], demo_pages: dict[str, str],
                    catalogue: Catalogue) -> tuple[list[Asset], dict, VmSyncResult]:
    """Turn fetched pages into assets. Pure, like parse_page.

    `pages` are page metadata; `layouts` maps page id -> canvasLayout;
    `demo_pages` maps a Demo Catalog page's filename -> its title.
    """
    result = VmSyncResult(pages_seen=len(pages))

    # Two pages can share a title (a copy made while editing): keep the most
    # recently edited, since that is the one anybody is maintaining.
    newest: dict[str, dict] = {}
    for page in sorted(pages, key=lambda p: p.get("lastModifiedDateTime") or ""):
        key = normalise_title(page.get("title", ""))
        if key in newest:
            result.duplicates_dropped += 1
        newest[key] = page
    pages = list(newest.values())

    ids = {page_key(p.get("webUrl", "")): "vm-" + _slug(p.get("title", ""))
           for p in pages}
    titles = {v: p.get("title", "") for p in pages for k, v in ids.items()
              if k == page_key(p.get("webUrl", ""))}

    assets: list[Asset] = []
    all_secrets: dict = {}
    for page in pages:
        asset_id = ids[page_key(page.get("webUrl", ""))]
        title = (page.get("title") or "").strip()
        try:
            parsed = parse_page(layouts.get(page["id"]) or {})
        except Exception as exc:                       # noqa: BLE001
            log.exception("could not parse VM page %s", title)
            result.errors.append(f"{title}: {exc}")
            continue

        products = products_in_title(title, catalogue.products)
        families = set(taxonomy.families_of(products))
        related_vms: list[VmRelated] = []
        related: dict[str, VmRelated] = {}

        def add_demo(record: dict, via: str):
            if record["id"] in related or record.get("type") == AssetType.VM.value:
                return
            related[record["id"]] = VmRelated(asset_id=record["id"], title=record["title"],
                                              type=record["type"], via=via)

        for url in parsed.link_urls:
            kind = classify_link(url)
            if kind == "vm_page":
                other = ids.get(page_key(url))
                if other and other != asset_id and all(r.asset_id != other for r in related_vms):
                    related_vms.append(VmRelated(asset_id=other, title=titles.get(other, other),
                                                 type=AssetType.VM, via="page"))
            elif kind == "demo_page":
                page_title = demo_pages.get(page_key(url))
                record = catalogue.match_title(page_title or page_key(url))
                if record:
                    add_demo(record, "page")
                else:
                    result.unresolved_demo_links.append(page_title or page_key(url))
            elif kind == "demo_folder":
                folder, _ = _demo_folder(url)
                if folder in _NOT_DEMO_FOLDERS:
                    continue
                record = catalogue.by_folder.get(folder)
                if record:
                    add_demo(record, "page")
                elif folder:
                    result.unresolved_demo_links.append(folder)

        for named in parsed.supports_titles:
            record = catalogue.match_title(named)
            if record:
                add_demo(record, "supports")
            else:
                result.unresolved_demo_links.append(named)

        # Inferred last, so an explicit relation always keeps its stronger `via`.
        low = title.lower()
        for dataset in catalogue.datasets:
            if not re.search(r"\b" + re.escape(dataset) + r"\b", low):
                continue
            for record in catalogue.records:
                if record.get("type") == AssetType.VM.value:
                    continue
                if not (record.get("title") or "").lower().startswith(dataset + " - "):
                    continue
                if families and not families & set(taxonomy.families_of(record.get("products"))):
                    continue
                add_demo(record, "inferred")
                if sum(1 for r in related.values() if r.via == "inferred") >= 8:
                    break

        documents: list[VmDocument] = []
        for name, url in parsed.documents:
            folder, filename = _demo_folder(url) if "/Demo Catalog/" in unquote(url) else ("", None)
            hit = catalogue.by_file.get((folder, filename or name.lower()))
            documents.append(VmDocument(name=name, url=absolute(url),
                                        asset_id=hit[0] if hit else None,
                                        item_id=hit[1] if hit else None))

        public_text = " ".join(
            filter(None, [s.heading or "" for s in parsed.sections]
                   + [b.text or "" for s in parsed.sections for b in s.blocks if not b.sealed]
                   + [" ".join(r) for s in parsed.sections for b in s.blocks
                      if not b.sealed for r in (b.rows or [])]))
        description = (page.get("description") or "").strip() or None
        if is_secret_line(description):
            description = None
        description = _complete_description(description, parsed.sections)

        ordered = sorted(related.values(), key=lambda r: {"page": 0, "supports": 1}.get(r.via, 2))
        vm = VmDetail(
            version=version_in_title(title),
            page_modified_by=((page.get("lastModifiedBy") or {}).get("user") or {}).get("displayName"),
            ptc_only=bool(re.search(r"\bptc only\b", title, re.I)),
            sections=parsed.sections,
            actions=parsed.actions,
            documents=documents,
            related_vms=related_vms,
            related_demos=ordered,
            supports=parsed.supports_filters,
            sealed_count=parsed.sealed_count,
            search_text=public_text[:20000],
        )
        modified = (page.get("lastModifiedDateTime") or "")[:10]
        assets.append(Asset(
            id=asset_id, type=AssetType.VM, source="sharepoint", title=title,
            description=description,
            products=products,
            segment=segment_in_title(title),
            # An environment to demo from, not material to put in front of a
            # customer.
            customer_facing=False,
            tags=["PTC only"] if vm.ptc_only else [],
            uploaded_at=date.fromisoformat(modified) if modified else None,
            # The pages' banners are mostly stock images reused across
            # unrelated pages (the ACD page shows a Codebeamer VDK's), so
            # the Hub's own product cover is the more honest picture.
            thumbnail_url=None,
            web_url=page.get("webUrl"),
            source_item_id=page.get("id"),
            vm=vm,
        ))
        if parsed.secrets["sections"] or parsed.secrets["blocks"]:
            all_secrets[asset_id] = parsed.secrets

        result.vms += 1
        result.sealed += parsed.sealed_count
        result.related_page += sum(1 for r in ordered if r.via == "page")
        result.related_supports += sum(1 for r in ordered if r.via == "supports")
        result.related_inferred += sum(1 for r in ordered if r.via == "inferred")
        result.supports_filters += len(parsed.supports_filters)
        result.documents += len(documents)
        result.documents_previewable += sum(1 for d in documents if d.item_id)

    return assets, all_secrets, result


# ─────────────────────────────────────────────────────────────── the sync
GRAPH = "https://graph.microsoft.com/v1.0"


def sync_vm_pages(client, repo, site) -> VmSyncResult:
    """Fetch every VM page and replace the vm_pages mirror.

    One request for the page list, one per VM page for its canvas -- about
    forty in all, so no delta: re-reading everything is cheaper than being
    wrong about what changed.
    """
    pages = list(client._paged(
        f"{GRAPH}/sites/{site.site_id}/pages/microsoft.graph.sitePage",
        params={"$select": "id,name,title,webUrl,description,lastModifiedDateTime,"
                           "lastModifiedBy,createdDateTime"}))
    vm_pages = [p for p in pages if is_vm_page(p)]
    demo_pages = {page_key(p.get("webUrl", "")): p.get("title") or ""
                  for p in pages if DEMO_PAGES_FOLDER in unquote(p.get("webUrl") or "")}
    layouts = {}
    for page in vm_pages:
        detail = client._request(
            "GET", f"{GRAPH}/sites/{site.site_id}/pages/{page['id']}/microsoft.graph.sitePage",
            params={"$expand": "canvasLayout"})
        layouts[page["id"]] = (detail or {}).get("canvasLayout") or {}

    loader = getattr(repo, "_load_mirror", None)
    records = [r for r in (loader() if loader else []) if r.get("type") != AssetType.VM.value]
    catalogue = Catalogue.build(records)

    assets, secrets, result = build_vm_assets(vm_pages, layouts, demo_pages, catalogue)
    repo.replace_source_rows(assets, source_system=SOURCE_SYSTEM)
    writer = getattr(repo, "replace_vm_secrets", None)
    if writer:
        writer(secrets)
    log.info("vm sync: %s", result.as_dict())
    return result


def used_by_vms(asset: dict, vm_records: list[dict], limit: int = 6) -> list[UsedByVm]:
    """The reverse direction, for a demo's detail page: which VMs run it.

    Explicit relations first. Then VMs whose page says they support a whole
    slice the demo is in ("every PLM LDK") -- newest first, and capped,
    because the old Windchill 11 and 12 pages say the same thing and a demo
    should point at the environments people use now.
    """
    explicit, slices = [], []
    for vm in sorted(vm_records, key=lambda r: r.get("uploaded_at") or "", reverse=True):
        detail = vm.get("vm") or {}
        for rel in detail.get("related_demos") or []:
            if rel.get("asset_id") == asset.get("id"):
                explicit.append(UsedByVm(asset_id=vm["id"], title=vm["title"], via=rel.get("via")))
                break
        else:
            for f in detail.get("supports") or []:
                if f.get("segment") and f.get("segment") == asset.get("segment") \
                        and (not f.get("type") or f.get("type") == asset.get("type")):
                    slices.append(UsedByVm(asset_id=vm["id"], title=vm["title"], via="supports"))
                    break
    # Stronger evidence first, then newer; sorted() is stable, so equal ranks
    # keep the newest-first order they were collected in.
    rank = {"page": 0, "supports": 1, "inferred": 2}
    explicit.sort(key=lambda u: rank.get(u.via, 3))
    return (explicit + slices)[:limit]
