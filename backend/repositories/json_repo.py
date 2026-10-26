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
import re
import threading
from collections import Counter
from dataclasses import replace
from datetime import date, datetime
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from backend.models import (
    AdvancedSearchHit, Asset, AssetRequest, AssetStats, AssetSummary, AssetType, Capability, Facets, FacetValue, MetadataProposal,
    Page, ProposalState, ProposalSummary, ValueRoadmap, video_type,
)
from backend.repositories.base import AssetQuery, AssetRepository
from backend.services import content_age, listing, relevance, taxonomy, thumbnails
from backend.tables import utcnow

log = logging.getLogger(__name__)

#: Lowest precedence when two sources claim one asset id. The spreadsheet seed
#: is a stand-in for SharePoint until Graph access exists, so real data always
#: beats it -- see _dedupe_by_id.
_FALLBACK_SOURCE = "seed"

#: The table view's sortable columns (Serge, 2026-10-23): what each sorts by.
#: None for a row with nothing there, which _by_column keeps last.
_COLUMNS = {
    "title": lambda r, stats: (r.get("title") or "").lower() or None,
    "type": lambda r, stats: r.get("type"),
    "product": lambda r, stats: next(iter(taxonomy.families_of(r.get("products"))), None),
    "segment": lambda r, stats: r.get("segment"),
    "language": lambda r, stats: r.get("language") or "en",
    "most_viewed": lambda r, stats: (stats.get(r["id"]) or {}).get("views", 0),
}


def _by_column(rows: list[dict], key, descending: bool, stats: dict) -> list[dict]:
    """Rows sorted on one column, either way, empty ones last; ties keep
    their order (newest first, the order rows arrive in)."""
    rows = sorted(rows, key=lambda r: _as_date(r.get("uploaded_at")) or date.min, reverse=True)
    present = [r for r in rows if key(r, stats) is not None]
    empty = [r for r in rows if key(r, stats) is None]
    present.sort(key=lambda r: key(r, stats), reverse=descending)
    return present + empty

_MIRROR_FIELDS = (
    "id", "type", "source", "title", "description", "products", "funnel_stage", "content_depth",
    "language", "segment", "industry", "value_drivers", "tags", "customer_facing",
    "has_narrated_audio", "named_customer", "uploaded_at", "date_stated", "duration_seconds",
    "thumbnail_url", "thumbnail_chosen", "web_url", "source_item_id", "brightcove_id",
    "consensus_uuid",
    "internal_title",
    "resources", "resource_counts", "resource_count", "video_count", "main_video",
    "external_views",
    # Who made it (sharepoint_mapping.content_creator, 2026-10-14), and who
    # submitted it through the Hub (submitted_by column, 2026-10-21).
    "creator", "submitted_by", "demo_owner", "product_version",
    # VM pages only. Public by construction: credentials are sealed out of it
    # before it is built (backend/integrations/graph/vm_pages.py) and live in
    # PRIVATE_DIR instead.
    "vm",
    # Search only; see Asset.search_text.
    "search_text",
    # Detail page only; see Asset.long_description.
    "long_description",
    # Demo pages (backend/integrations/graph/demo_pages.py).
    "page_url", "page_folder", "page_modified", "overview",
)

#: Under mirror/, and never read as catalogue data: _load_mirror only reads
#: *.json at the top level of mirror/. Holds what VM pages say that only a
#: signed-in person may see. Rebuilt by every VM sync, like the rest of mirror/.
PRIVATE_DIR = "private"
VM_SECRETS_FILE = "vm_credentials.json"
PARTNER_ACCESS_FILE = "partner_access.json"

#: The Type filter's own options, in the order Elio's dropdown shows them --
#: always present in facets().types, even at zero, same reasoning as
#: PRODUCT_FAMILIES in taxonomy.py: a value that only appeared once content
#: existed would look like a bug rather than the plan it is. VM is the one
#: at zero today -- Liwei/Elio, 2026-09-10, ahead of a demo: "I know VM isn't
#: in our data yet, it'll show 0". WIKI is deliberately not here: nothing in
#: the catalogue uses it, and it has no filter option to show.
FILTER_TYPES = (
    AssetType.VIDEO, AssetType.LDK, AssetType.VDK, AssetType.VM, AssetType.CAD_MODEL,
)


def _atomic_write(path: str, payload: Any) -> None:
    """Write via a temp file and rename, so a crash mid-write cannot corrupt."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False, default=str)
    os.replace(tmp, path)


def _ts(stamp: str | None) -> float:
    """An ISO time as a number for sorting; 0 for none."""
    try:
        return datetime.fromisoformat(stamp).timestamp() if stamp else 0.0
    except ValueError:
        return 0.0


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


def _searchable(record: dict) -> str | None:
    """The text a search looks at besides the title.

    For a VM that includes its page's public text, so "SQL Server 2019" finds
    the VM that has it installed. Public only: sealed content was removed
    before `search_text` was built, so a search cannot be used to probe for a
    password one character at a time.
    """
    text = record.get("description")
    extra = " ".join(x for x in ((record.get("vm") or {}).get("search_text"),
                                 record.get("search_text"),
                                 record.get("named_customer")) if x)
    return f"{text or ''} {extra}" if extra else text


def _folder_key(text: str | None) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _catalog_folder(record: dict) -> str | None:
    """The Demo Catalog folder a demo lives in, from its address
    (".../DocSetHome.aspx?id=/sites/EXT-TDD/Demo%20Catalog/<folder>").

    The `id` parameter is read as a parameter, so a folder named
    "Codebeamer FA&D Overview" keeps its "&" (it is %26 in the address)."""
    url = record.get("web_url") or ""
    query = parse_qs(urlparse(url).query).get("id")
    path = query[0] if query else unquote(urlparse(url).path)
    match = re.search(r"/Demo Catalog/([^/]+)", path)
    return match.group(1) if match else None


def _apply_demo_pages(tagged: list[tuple[str, dict]],
                      divested_folders: set[str] = frozenset(),
                      show_page_links: bool = False,
                      show_page_only: bool = True) -> list[tuple[str, dict]]:
    """Demo pages, matched to the demos their pages describe (Liwei, 2026-10-05).

    A page pointing at a folder the Hub lists adds to that demo -- its
    thumbnail and a link to the page -- and is not listed itself. A page with
    no such folder IS the demo: listed from the page alone, with no files.
    Decided here, at read time, so a folder that gains its Demo Type later
    starts matching without the page sync running again. Copies, never the
    cached records.

    `show_page_links` is the Admin switch (owned/hub_settings.json, off by
    default -- Liwei, 2026-10-05: management has not agreed on exposing
    SharePoint). Off, no page address leaves the server: the demo keeps its
    page thumbnail, a page-only demo is still listed, but neither carries a
    link to the page.

    `show_page_only`, the second switch (on by default): off, demos known
    only from their page are not listed at all; pages still lend their
    thumbnail to the demos whose folders they describe."""
    pages = [r for src, r in tagged if src == "demo_pages"]
    if not pages:
        return tagged
    folders = {}
    for src, r in tagged:
        if src == "sharepoint":
            key = _folder_key(_catalog_folder(r))
            if key:
                folders[key] = r["id"]
    # Two pages on one folder: the most recently changed one speaks for it.
    by_target: dict[str, dict] = {}
    unmatched = []
    for page in pages:
        key = _folder_key(page.get("page_folder"))
        if key and key in divested_folders:
            # The page's own Product column may name something current
            # (Integrity Lifecycle Manager's page says Codebeamer), but the
            # demo it describes is divested: it stays out with its folder.
            continue
        target = folders.get(key)
        if target is None and not key:
            # No folder in the page's web parts: a folder named exactly like
            # the page is the same demo (Lamborghini IPL's page links no files
            # but its folder exists -- 2026-10-06), so the two are not listed
            # twice.
            target = folders.get(_folder_key(page.get("title")))
        if target is None:
            unmatched.append(page)
        elif str(page.get("page_modified") or "") >= str(by_target.get(target, {}).get("page_modified") or ""):
            by_target[target] = page
    out = []
    for src, r in tagged:
        if src == "demo_pages":
            continue
        page = by_target.get(r["id"]) if src == "sharepoint" else None
        if page:
            r = {**r, "page_url": page.get("page_url") if show_page_links else None,
                 # A picture chosen on the Details card stays (B5).
                 "thumbnail_url": r.get("thumbnail_url") if r.get("thumbnail_chosen")
                                  else page.get("thumbnail_url") or r.get("thumbnail_url"),
                 # The author's intro, sections and file order (2026-10-21).
                 "overview": page.get("overview")}
        out.append((src, r))
    if show_page_only:
        out.extend(("demo_pages", p if show_page_links else {**p, "page_url": None, "web_url": None})
                   for p in unmatched)
    return out


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


class WouldShrinkMirror(RuntimeError):
    """A mirror replacement would discard most of what a source holds.

    Almost always a partial result mistaken for a complete one. The mirror is
    rebuildable, so the cost is a confusing catalogue rather than lost data —
    but a catalogue that quietly loses a third of itself is worse than a sync
    that refuses to run.
    """


def _person_names() -> dict[str, str]:
    """Address -> the name the person signed in with: the same "Last, First"
    SharePoint shows, so one person is one creator."""
    from backend import access
    names = {}
    for u in access.known_users():
        for key in (u.get("email"), u.get("username")):
            if key and u.get("name"):
                names[key.lower()] = u["name"]
    return names


def _name_of(email: str, names: dict[str, str]) -> str:
    from backend.activity import readable
    return names.get(email.lower()) or readable(email)


def _upload_people(records) -> dict[str, str]:
    """SharePoint folder id -> who made the demo, for demos created through
    the Hub (services/uploads.py `person`)."""
    if not isinstance(records, list) or not records:
        return {}
    names = _person_names()
    out = {}
    for r in records:
        who = (r.get("person") or "").lower()
        if who and r.get("folder_id") and r.get("status") != "cancelled":
            out[r["folder_id"]] = _name_of(who, names)
    return out


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
        divested_folders: set[str] = set()
        if os.path.isdir(self.mirror_dir):
            for name in sorted(os.listdir(self.mirror_dir)):
                if not name.endswith(".json"):
                    continue
                path = os.path.join(self.mirror_dir, name)
                stamp = os.path.getmtime(path)
                cached = self._mirror_cache.get(path)
                if cached is None or cached[0] != stamp:
                    records = _read(path, [])
                    # A mirror written before the five Video Types (2026-09-30)
                    # still says "Overview"; filters and facets read these raw
                    # records, so they are brought up to date here rather than
                    # waiting for the next sync.
                    for record in records:
                        if record.get("content_depth"):
                            record["content_depth"] = video_type(record["content_depth"])
                    cached = (stamp, records)
                    self._mirror_cache[path] = cached
                # The filename IS the source system, which is what lets a
                # collision be resolved rather than merely detected.
                source = name[:-len(".json")]
                # Divested products are dropped HERE, at the single funnel every
                # read passes through -- list, get, facets, search, the lot.
                # Filtering at each call site would work until one of them
                # forgot, and "PTC no longer owns this" is not a rule to enforce
                # in fourteen places. The sync also declines to index them, so
                # this is the guarantee rather than the mechanism: it holds even
                # against a mirror written by an older build.
                for record in cached[1]:
                    if not taxonomy.is_excluded(record.get("products")):
                        tagged.append((source, record))
                    elif source == "sharepoint":
                        divested_folders.add(_folder_key(_catalog_folder(record)))
        identity = self._load("identity")
        # Retired items keep their identity row but leave the catalogue.
        live = [(src, r) for src, r in tagged
                if not (identity.get(r["id"], {}) or {}).get("retired_at")]
        switches = self.hub_settings()
        rows = _dedupe_by_id(_apply_demo_pages(live, divested_folders,
                                               switches["show_demo_page_links"],
                                               switches["show_page_only_demos"]))
        # Uploaded through the Hub (2026-10-15, services/uploads.py), keyed
        # by the SharePoint folder so it holds from the moment the folder
        # exists: a date the uploader stated (Demo Catalog has no column for
        # it), and "pending" / "sent_back" until a reviewer publishes it.
        dates = self._load("publish_dates") or {}
        review = self._load("upload_review") or {}
        made_by = _upload_people(self._load("uploads"))
        named = _person_names() if made_by or any(r.get("submitted_by") or r.get("demo_owner")
                                                   for r in rows) else {}
        if dates or review or made_by or named:
            def stamp(r: dict) -> dict:
                key = r.get("source_item_id")
                if key in dates:
                    r = {**r, "uploaded_at": dates[key], "date_stated": True}
                if key in review:
                    r = {**r, "upload_review": review[key].get("status")}
                # SharePoint names the Hub's app as the files' creator of a
                # demo made through the Hub: its submitted_by column says who it was
                # (2026-10-21), else this slot's upload record (2026-10-20).
                # The Demo Owner column, where someone filled it (A4), first.
                if r.get("demo_owner"):
                    r = {**r, "creator": _name_of(r["demo_owner"], named)}
                elif r.get("submitted_by"):
                    r = {**r, "creator": _name_of(r["submitted_by"], named)}
                elif key in made_by:
                    r = {**r, "creator": made_by[key]}
                return r
            rows = [stamp(r) for r in rows]
        # Edited on the Details card and not synced yet (A1): shown now.
        edits = self._load("metadata_edits")
        if edits:
            from backend.services.metadata_edit import apply_edits
            rows = apply_edits(rows, edits, {
                s: (self._load("sync_state").get(s) or {}).get("last_success_at")
                for s in ("sharepoint", "demo_video")})
        # Hidden from the Hub on the Admin page (owned/hidden.json): out of
        # every read here, at the funnel, like a retired item.
        hidden = self._load("hidden") or {}
        if hidden:
            rows = [r for r in rows if r["id"] not in hidden]
        closed = {k for k, v in self.partner_access().items() if v}
        if closed:
            rows = [{**r, "partner_restricted": True} if r.get("source_item_id") in closed else r
                    for r in rows]
        # Internal (2026-10-07): a folder SharePoint closes to partners, or a
        # demo marked so on the Hub (owned/content_access.json). Either way,
        # only "Access internal content" opens its files.
        # Archived (2026-10-14): marked here, filtered in _rows, so that
        # whoever may see archived content can still reach it by id.
        archive = self._load("archived") or {}
        if archive:
            rows = [{**r, "archived": True, "archived_at": archive[r["id"]].get("at")}
                    if r["id"] in archive else r for r in rows]
        # Still current (2026-10-14): a reviewer's confirmation, while it lasts.
        reviews = self._load("content_review") or {}
        if reviews:
            today = utcnow().date().isoformat()
            live = {k: v for k, v in reviews.items() if (v.get("until") or "") >= today}
            rows = [{**r, "still_current_until": live[r["id"]]["until"],
                     "still_current_by": live[r["id"]].get("by")}
                    if r["id"] in live else r for r in rows]
        marked = dict(self._load("content_access") or {})
        # Internal asked for when a demo was created (services/uploads.py),
        # by folder: it holds before and after the demo is first indexed.
        by_folder = self._load("upload_internal") or {}
        if by_folder:
            for r in rows:
                if r.get("source_item_id") in by_folder:
                    marked.setdefault(r["id"], by_folder[r["source_item_id"]])
        if closed or marked:
            rows = [{**r, "internal": True,
                     "internal_source": "sharepoint" if r.get("partner_restricted") else "hub"}
                    if r.get("partner_restricted") or r["id"] in marked else r
                    for r in rows]
        return rows

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
            # Reachable by id, never met while browsing -- listing.py says why.
            if not listing.is_listed(record, query.include_older_vms):
                return False
            if record.get("archived") and not query.include_archived:
                return False
            if record.get("upload_review") and not query.include_pending:
                return False
            # Membership comes from the scorer, so a record can never be
            # excluded by one rule and ranked by another.
            if query.text and not relevance.matches(
                    query.text, record.get("title"), _searchable(record)):
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

            if query.umbrella_families and not (
                    set(taxonomy.umbrellas_of(record.get("products")))
                    & set(query.umbrella_families)):
                return False

            if query.published and not content_age.matches(
                    _as_date(record.get("uploaded_at")), query.published):
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

        if query.sort in _COLUMNS:
            rows = _by_column(rows, _COLUMNS[query.sort], query.descending, stats)
        elif query.sort == "oldest":
            # Undated last: "oldest" must not open on content with no date.
            rows.sort(key=lambda r: (recency(r) == date.min, recency(r)))
        elif query.sort == "relevance" and query.text:
            # Band first, then newest first (relevance.order_key, 2026-09-30).
            rows.sort(key=lambda r: relevance.order_key(query.text, r.get("title"),
                                                        _searchable(r), recency(r)),
                      reverse=True)
        else:
            rows.sort(key=recency, reverse=True)

        window = rows[query.offset: query.offset + query.limit]
        return Page[AssetSummary](
            items=[AssetSummary(**self._common(r, stats),
                                has_roadmap=r["id"] in indexed) for r in window],
            total=len(rows), limit=query.limit, offset=query.offset,
        )

    # ─────────────────────────────────────────── partner access
    def partner_access(self) -> dict[str, bool]:
        """{folder item id: closed to partners}, as the last sync read it.
        Under mirror/private/ -- rebuilt by every sync, never catalogue rows."""
        path = os.path.join(self.mirror_dir, PRIVATE_DIR, PARTNER_ACCESS_FILE)
        if not os.path.exists(path):
            return {}
        stamp = os.path.getmtime(path)
        cached = self._mirror_cache.get(path)
        if cached is None or cached[0] != stamp:
            cached = (stamp, _read(path, {}))
            self._mirror_cache[path] = cached
        return cached[1]

    def replace_partner_access(self, access: dict[str, bool]) -> None:
        folder = os.path.join(self.mirror_dir, PRIVATE_DIR)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, PARTNER_ACCESS_FILE)
        with self._lock:
            _atomic_write(path, access)
            self._invalidate(path)

    # ─────────────────────────────────────────── hidden from the Hub
    def hidden(self) -> list[dict]:
        """Demos an admin has hidden, most recent first."""
        state = self._load("hidden") or {}
        items = [{"asset_id": k, **v} for k, v in state.items()]
        return sorted(items, key=lambda i: i.get("hidden_at") or "", reverse=True)

    def is_hidden(self, asset_id: str) -> bool:
        return asset_id in (self._load("hidden") or {})

    def hide(self, asset_id: str, actor: str) -> list[dict]:
        """Hide one listed demo. Its title and type are kept with the entry,
        because a hidden demo is no longer readable through get()."""
        asset = self.get(asset_id)
        if asset is None:
            raise KeyError(asset_id)
        with self._lock:
            state = self._load("hidden") or {}
            state[asset_id] = {"title": asset.title, "type": getattr(asset.type, "value", asset.type),
                               "hidden_by": actor,
                               "hidden_at": utcnow().isoformat(timespec="seconds")}
            self._save("hidden", state)
        return self.hidden()

    def unhide(self, asset_id: str) -> list[dict]:
        with self._lock:
            state = self._load("hidden") or {}
            state.pop(asset_id, None)
            self._save("hidden", state)
        return self.hidden()

    # ─────────────────────────────────────────── Open / Internal
    def content_access(self) -> list[dict]:
        """Every Internal demo, and why: marked on the Hub (can be opened
        again here) or closed to partners in SharePoint (changed there)."""
        marked = dict(self._load("content_access") or {})
        by_folder = self._load("upload_internal") or {}
        out = []
        for r in self._load_mirror():
            if not r.get("internal"):
                continue
            mark = marked.get(r["id"]) or by_folder.get(r.get("source_item_id")) or {}
            out.append({"asset_id": r["id"], "title": r.get("title"), "type": r.get("type"),
                        "source": r.get("internal_source"),
                        "marked_by": mark.get("by"), "marked_at": mark.get("at"),
                        "reason": mark.get("reason"),
                        "also_marked": bool(mark) and r.get("internal_source") == "sharepoint"})
        return sorted(out, key=lambda i: (i["source"] != "hub", -_ts(i.get("marked_at")),
                                          (i.get("title") or "").lower()))

    def set_access(self, asset_id: str, level: str, actor: str,
                   reason: str | None = None) -> dict:
        """Mark one listed demo Internal, or Open again. Opening only removes
        the Hub's own mark: a folder SharePoint closes stays Internal."""
        if level not in ("open", "internal"):
            raise ValueError(level)
        if self.get(asset_id) is None:
            raise KeyError(asset_id)
        with self._lock:
            state = self._load("content_access") or {}
            if level == "internal":
                state[asset_id] = {"by": actor, "at": utcnow().isoformat(timespec="seconds"),
                                   "reason": (reason or "").strip() or None}
            else:
                state.pop(asset_id, None)
                # ... and a mark made when it was created, kept by folder.
                folder = next((r.get("source_item_id") for r in self._load_mirror()
                               if r["id"] == asset_id), None)
                created = self._load("upload_internal") or {}
                if folder in created:
                    created.pop(folder)
                    self._save("upload_internal", created)
            self._save("content_access", state)
        asset = self.get(asset_id)
        return {"asset_id": asset_id, "internal": asset.internal,
                "internal_source": asset.internal_source}

    # ─────────────────────────────────────────── Archived
    def archived(self) -> list[dict]:
        """Archived demos, most recent first, with who archived them and why."""
        state = self._load("archived") or {}
        items = [{"asset_id": k, **v} for k, v in state.items()]
        return sorted(items, key=lambda i: i.get("at") or "", reverse=True)

    def set_archived(self, asset_id: str, on: bool, actor: str,
                     reason: str | None = None) -> dict:
        """Archive a demo in the Hub, or restore it. SharePoint and Consensus
        are never touched: this only decides what the Hub lists."""
        asset = self.get(asset_id)
        if asset is None:
            raise KeyError(asset_id)
        with self._lock:
            state = self._load("archived") or {}
            if on:
                state[asset_id] = {"title": asset.title,
                                   "type": getattr(asset.type, "value", asset.type),
                                   "by": actor, "at": utcnow().isoformat(timespec="seconds"),
                                   "reason": (reason or "").strip()[:300] or None}
            else:
                state.pop(asset_id, None)
            self._save("archived", state)
        return {"asset_id": asset_id, "archived": on}

    # ─────────────────────────────────────────── Still current
    def content_reviews(self) -> dict[str, dict]:
        """{asset id: {by, at, until}}, expired ones included (owned/)."""
        return self._load("content_review") or {}

    def ids_by_folder(self) -> dict[str, str]:
        """SharePoint folder id -> the Hub's asset id, for every indexed
        folder, uploads waiting for review included (services/uploads.py)."""
        return {r["source_item_id"]: r["id"] for r in self._load_mirror()
                if r.get("source_item_id")}

    def set_still_current(self, asset_id: str, on: bool, actor: str,
                          months: int = 12) -> dict:
        """Confirm a demo is Still current for `months`, or withdraw it."""
        if self.get(asset_id) is None:
            raise KeyError(asset_id)
        with self._lock:
            state = self._load("content_review") or {}
            if on:
                today = utcnow().date()
                until = date(today.year + (today.month - 1 + months) // 12,
                             (today.month - 1 + months) % 12 + 1, min(today.day, 28))
                state[asset_id] = {"by": actor, "at": utcnow().isoformat(timespec="seconds"),
                                   "until": until.isoformat()}
            else:
                state.pop(asset_id, None)
            self._save("content_review", state)
        asset = self.get(asset_id)
        return {"asset_id": asset_id, "age_band": asset.age_band,
                "still_current_until": asset.still_current_until,
                "still_current_by": asset.still_current_by}

    # ─────────────────────────────────────────── Hub display settings
    def hub_settings(self) -> dict:
        state = self._load("hub_settings") or {}
        return {"show_demo_page_links": bool(state.get("show_demo_page_links")),
                # On unless switched off: these demos (Lamborghini IPL...) are
                # why the page source exists.
                "show_page_only_demos": bool(state.get("show_page_only_demos", True)),
                "changed_by": state.get("changed_by"), "changed_at": state.get("changed_at")}

    def set_hub_settings(self, actor: str, **values) -> dict:
        """Portal-owned display switches (owned/hub_settings.json)."""
        with self._lock:
            state = self._load("hub_settings") or {}
            state.update(values, changed_by=actor,
                         changed_at=utcnow().isoformat(timespec="seconds"))
            self._save("hub_settings", state)
        return self.hub_settings()

    # ─────────────────────────────────────────── promoted on Home
    def promoted(self) -> dict:
        state = self._load("promoted") or {}
        return {"asset_ids": list(state.get("asset_ids") or []),
                "changed_by": state.get("changed_by"),
                "changed_at": state.get("changed_at")}

    def set_promoted(self, asset_ids: list[str], actor: str) -> dict:
        """Replace the whole ordered list. owned/promoted.json -- never
        mirror/, so no sync can touch it."""
        with self._lock:
            self._save("promoted", {
                "asset_ids": list(dict.fromkeys(asset_ids)),
                "changed_by": actor,
                "changed_at": utcnow().isoformat(timespec="seconds"),
            })
        return self.promoted()

    def advanced_search(self, query: AssetQuery) -> Page[AdvancedSearchHit]:
        """Every listed demo whose own fields, or whose files' names, hold
        every term of the query.

        Goes through `_rows()` with the text taken out, so the filters and the
        mirror funnel (divestment, older VMs) are exactly the ordinary list's;
        only the text test differs. "Details" is broader than the ordinary
        search on purpose -- tags, products, segment and Video Type count too.
        """
        stats = self._load("stats")
        hits = []
        for record in self._rows(replace(query, text=None)):
            title = record.get("title")
            details = " ".join(x for x in (
                _searchable(record),
                " ".join(record.get("tags") or []),
                " ".join(record.get("products") or []),
                " ".join(record.get("value_drivers") or []),
                record.get("segment"), record.get("content_depth"),
                record.get("industry")) if x)
            own = relevance.score(query.text, title, details)
            files = [f for f in (record.get("resources") or [])
                     if relevance.names(query.text, f.get("name"))]
            if not own and not files:
                continue
            matched_in = []
            if own >= relevance.TITLE_ALL_TERMS:
                matched_in.append("title")
            elif own:
                matched_in.append("details")
            key = relevance.advanced_order_key(
                query.text, title, details, len(files),
                _as_date(record.get("uploaded_at")) or date.min)
            hits.append((key, record, matched_in, files))

        hits.sort(key=lambda h: h[0], reverse=True)
        window = hits[query.offset: query.offset + query.limit]
        indexed = set(self._load("roadmap"))
        return Page[AdvancedSearchHit](
            items=[AdvancedSearchHit(
                       asset=AssetSummary(**self._common(r, stats),
                                          has_roadmap=r["id"] in indexed),
                       matched_in=m, files=f)
                   for _, r, m, f in window],
            total=len(hits), limit=query.limit, offset=query.offset,
        )

    def thumbnail_source(self, asset_id: str) -> str | None:
        """The asset's own thumbnail address, before public_url() rewrites a
        SharePoint one -- what /api/assets/{id}/thumbnail fetches."""
        record = next((r for r in self._load_mirror() if r["id"] == asset_id), None)
        return (record or {}).get("thumbnail_url")

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
            long_description=record.get("long_description"),
            overview=record.get("overview"),
            rails=own.get("rails") or [],
            is_editor_pick=bool(own.get("is_editor_pick")),
            value_roadmap=self._to_roadmap(roadmap),
        )
        if record.get("type") == AssetType.VM.value:
            data["vm"] = record.get("vm")
        else:
            from backend.integrations.graph.vm_pages import used_by_vms   # local: cycle
            # The VMs to use today: an older version is reachable from the
            # newest, not offered alongside it.
            vms = [r for r in self._load_mirror() if r.get("type") == AssetType.VM.value
                   and not listing.is_superseded_vm(r)]
            if vms:
                data["used_by_vms"] = used_by_vms(record, vms)
        return Asset(**data)

    # ─────────────────────────────────────────── sealed VM page content
    def replace_vm_secrets(self, secrets: dict) -> None:
        """Replace the sealed content of every VM page at once.

        Kept apart from the mirror file on purpose: the public record cannot
        leak what it never contained, whatever later code does with it.
        """
        folder = os.path.join(self.mirror_dir, PRIVATE_DIR)
        os.makedirs(folder, exist_ok=True)
        with self._lock:
            _atomic_write(os.path.join(folder, VM_SECRETS_FILE), secrets)

    def vm_secrets(self, asset_id: str) -> dict | None:
        path = os.path.join(self.mirror_dir, PRIVATE_DIR, VM_SECRETS_FILE)
        return (_read(path, {}) or {}).get(asset_id)

    def facets(self, query: AssetQuery | None = None) -> Facets:
        """Every filter value with a real count, each scoped to its own slice.

        A facet is counted over the results of every filter EXCEPT its own.
        Counting a dimension by itself is what makes a filter panel a trap:
        choose Type=VDK and the Type dropdown reads "VDK (196), Video (0),
        LDK (0)" -- true, and useless, because it can be entered and never
        left. The question the control actually answers is "if I picked this
        instead, how many?", which is this slice. Every other dimension stays
        scoped by Type=VDK, so Product still narrows honestly.

        `total` excludes nothing: it is the real result count.
        """
        base = query or AssetQuery()
        # Deliberately the same _rows() the listing uses, so a facet count can
        # never disagree with the number of results clicking it produces.
        full = self._rows(base)
        cache: dict[str, list[dict]] = {}

        def rows_for(dimension: str) -> list[dict]:
            # An unfiltered dimension has nothing to exclude and shares `full`,
            # so a typical request re-filters once or twice, not eleven times.
            if not getattr(base, dimension):
                return full
            if dimension not in cache:
                cache[dimension] = self._rows(replace(base, **{dimension: []}))
            return cache[dimension]

        def scalar(field: str, dimension: str) -> list[FacetValue]:
            rows = rows_for(dimension)
            counts = Counter(r.get(field) for r in rows if r.get(field))
            return [FacetValue(value=v, count=n) for v, n in sorted(counts.items())]

        def multi(field: str, dimension: str) -> list[FacetValue]:
            rows = rows_for(dimension)
            counts = Counter(v for r in rows for v in (r.get(field) or []))
            return [FacetValue(value=v, count=n) for v, n in sorted(counts.items())]

        # Families are derived, not stored: the mapping is code, so a change to
        # it must take effect without a re-sync.
        family_counts = Counter(
            f for r in rows_for("product_families")
            for f in taxonomy.families_of(r.get("products")))
        umbrella_counts = Counter(
            f for r in rows_for("umbrella_families")
            for f in taxonomy.umbrellas_of(r.get("products")))

        # Every filterable type, in FILTER_TYPES' order, at its real count or
        # zero -- then anything scalar() found outside that list (there is
        # none today) tacked on after, so nothing real ever goes missing.
        type_counts = Counter(r.get("type") for r in rows_for("types") if r.get("type"))
        type_facets = [FacetValue(value=t.value, count=type_counts.pop(t.value, 0))
                       for t in FILTER_TYPES]
        type_facets += [FacetValue(value=v, count=n) for v, n in sorted(type_counts.items())]

        # Published: the four age bands in order (at zero too, so the control
        # never changes shape), then every year that has content, newest first.
        dated = [_as_date(r.get("uploaded_at")) for r in rows_for("published")]
        dated = [d for d in dated if d]
        band_counts = Counter(content_age.band(d) for d in dated)
        year_counts = Counter(str(d.year) for d in dated)
        published = [FacetValue(value=b, count=band_counts.get(b, 0))
                     for b, _ in content_age.BANDS]
        published += [FacetValue(value=y, count=n)
                      for y, n in sorted(year_counts.items(), reverse=True)]

        return Facets(
            types=type_facets,
            published=published,
            products=multi("products", "products"),
            funnel_stages=scalar("funnel_stage", "funnel_stages"),
            segments=scalar("segment", "segments"),
            industries=scalar("industry", "industries"),
            value_drivers=multi("value_drivers", "value_drivers"),
            languages=scalar("language", "languages"),
            content_depths=scalar("content_depth", "content_depths"),
            sources=scalar("source", "sources"),
            tags=multi("tags", "tags"),
            product_families=[FacetValue(value=v, count=n)
                              for v, n in sorted(family_counts.items())],
            # In the team's own order, and including the ones with nothing yet:
            # IPE is on the list because its demos are being made now, and a
            # family that silently vanished until content arrived would look
            # like a bug rather than a plan.
            umbrella_families=[
                FacetValue(value=f, count=umbrella_counts.get(f, 0))
                for f in taxonomy.PRODUCT_FAMILIES],
            total=len(full),
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

    # ------------------------------------------------------------- requests
    def _requests_path(self) -> str:
        return os.path.join(self.owned_dir, "requests.jsonl")

    def save_request(self, request: AssetRequest) -> None:
        """Append one submission, flushed to disk before returning.

        JSON Lines rather than a JSON array: an append cannot corrupt what is
        already there, and a truncated write costs the last line rather than
        the file. This is the one store here that cannot be rebuilt from
        anywhere, so it is written first and written plainly.
        """
        path = self._requests_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        line = json.dumps(request.model_dump(mode="json"), ensure_ascii=False)
        with self._lock:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
                fh.flush()
                os.fsync(fh.fileno())

    def mark_request_synced(self, request_id: str, item_id: str) -> None:
        """Rewrite the one line whose request reached SharePoint.

        A rewrite rather than another append, because two lines for one
        request would make "did this sync?" ambiguous, and that question is
        the only reason the flag exists.
        """
        path = self._requests_path()
        if not os.path.exists(path):
            return
        with self._lock:
            with open(path, encoding="utf-8") as fh:
                rows = [json.loads(line) for line in fh if line.strip()]
            for row in rows:
                if row.get("id") == request_id:
                    row["sharepoint_item_id"] = item_id
                    row["synced"] = True
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                for row in rows:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)

    def unsynced_requests(self) -> list[AssetRequest]:
        """Submissions that never reached SharePoint.

        Without a way to ask, an outage hides itself: the request is safe in a
        file nobody thinks to open.
        """
        path = self._requests_path()
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
        return [AssetRequest(**r) for r in rows if not r.get("synced")]

    #: A replacement may not silently discard most of a source.
    #:
    #: The mirror is replaced wholesale, which is right when the caller has
    #: enumerated everything and catastrophic when it has not. A Graph delta
    #: sync did exactly that on 2026-09-02: it passed the 316 changed items to
    #: this method, which dutifully rewrote 455 SharePoint assets as 308 and
    #: reported success. Nothing in the result said 147 assets had gone.
    #:
    #: So a shrink past this fraction is refused. It is not a data-integrity
    #: guarantee — the mirror is rebuildable — it is a tripwire on the one
    #: mistake that looks like a normal run.
    _SHRINK_FLOOR = 0.5

    def replace_source_rows(self, assets: list[Asset], source_system: str,
                            allow_shrink: bool = False) -> int:
        """The ONLY sanctioned writer of mirror data.

        Rewrites one source's mirror file and maintains identity. Everything
        under owned/ is left completely alone — that is the whole point.

        Raises `WouldShrinkMirror` when the replacement holds less than half of
        what is already there, unless `allow_shrink` says the caller means it.
        A source really can shrink — content gets deleted — so this is a
        question, not a prohibition.
        """
        previous = self.count_source_rows(source_system)
        if (not allow_shrink and previous
                and len(assets) < previous * self._SHRINK_FLOOR):
            raise WouldShrinkMirror(
                f"a sync of {source_system!r} would replace {previous} assets "
                f"with {len(assets)}, discarding "
                f"{previous - len(assets)}. That is what a partial page looks "
                f"like when it is mistaken for a full enumeration. Re-run with "
                f"allow_shrink=True if the source really did lose them.")
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

    # ------------------------------------------------------------ usage events
    #: Append-only, one JSON object per line, under `owned/` — Portal-authored
    #: data that no sync may rebuild (§1.1), same as share_events.jsonl.
    #:
    #: An event log rather than counters, and the difference is not stylistic:
    #: `stats.json` holds a running total per asset, which can answer "how many
    #: downloads ever" and nothing else. It cannot answer "how many in
    #: September", "did the people who opened this also download it", or "which
    #: file did they take" — those are questions about individual occurrences,
    #: and a counter has thrown the occurrences away. Counters cannot be
    #: back-filled into events either, so the log starts from the day it ships
    #: and the page says so rather than implying the catalogue was idle before.
    #:
    #: Deliberately anonymous: no IP, no user agent, no identity. Liwei's call,
    #: 2026-09-21. The cost is that "unique visitors" is not derivable, only
    #: "visits"; the gain is that this file is not personal data and needs no
    #: privacy review to exist. If SSO ever makes attribution possible, that is
    #: a decision to take deliberately, not to inherit by accident.
    USAGE_EVENTS = ("view", "preview", "download", "search")

    def record_usage_event(self, event: str, asset_id: str | None = None,
                           **fields) -> None:
        if event not in self.USAGE_EVENTS:
            raise ValueError(f"unknown usage event {event!r}")
        path = os.path.join(self.owned_dir, "usage_events.jsonl")
        os.makedirs(self.owned_dir, exist_ok=True)
        entry = {"at": utcnow().isoformat(timespec="seconds"), "event": event}
        if asset_id:
            entry["asset_id"] = asset_id
        entry.update({k: v for k, v in fields.items() if v is not None})
        with self._lock, open(path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def usage_events(self, since: str | None = None,
                     until: str | None = None) -> list[dict]:
        """Every event in a window, oldest first.

        Read and filtered in Python rather than indexed. At this catalogue's
        traffic that is a file of thousands of lines, and the only caller is
        one admin page: an index would be machinery to keep correct in
        exchange for milliseconds nobody is waiting on. Worth revisiting if
        the file ever reaches the millions, which would be a happy problem.

        A malformed line is skipped, not fatal: the log's whole point is that
        a truncated write costs one event, and a reader that refused to open
        the file would turn that into losing all of them.
        """
        out: list[dict] = []
        # Only the real log. A usage_events.demo.jsonl left on a share by the
        # sample activity (removed 2026-10-16) is never read.
        for name in ("usage_events.jsonl",):
            path = os.path.join(self.owned_dir, name)
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except ValueError:
                        continue
                    at = entry.get("at") or ""
                    if since and at < since:
                        continue
                    if until and at > until:
                        continue
                    out.append(entry)
        out.sort(key=lambda e: e.get("at") or "")
        return out

    def record_sync_run(self, source_system: str, ok: bool,
                        summary: dict | None = None, error: str | None = None) -> None:
        """One line per sync, so the Admin page can show a history rather than
        only the latest state. `sync_state` still holds "where we are"; this
        holds "how we got here"."""
        path = os.path.join(self.owned_dir, "sync_runs.jsonl")
        os.makedirs(self.owned_dir, exist_ok=True)
        entry = {"at": utcnow().isoformat(timespec="seconds"),
                 "source": source_system, "ok": bool(ok)}
        if summary:
            entry["summary"] = summary
        if error:
            entry["error"] = error[:300]
        with self._lock, open(path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def sync_runs(self, source_system: str | None = None, limit: int = 50) -> list[dict]:
        """Most recent first."""
        path = os.path.join(self.owned_dir, "sync_runs.jsonl")
        if not os.path.exists(path):
            return []
        rows: list[dict] = []
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if source_system and entry.get("source") != source_system:
                    continue
                rows.append(entry)
        return list(reversed(rows))[:limit]

    def source_rows(self, source_system: str) -> list[dict]:
        """One source's mirror rows as stored -- for a sync that keeps state
        on its own rows (demo_pages remembers which folder a page points at)."""
        return list(_read(self._mirror_path(source_system), []))

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

    def record_sync(self, source_system: str, fingerprint: str | None = None,
                    api: str | None = None) -> None:
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
            if api is not None:
                row["api"] = api
            self._save("sync_state", state)

    def record_sync_attempt(self, source_system: str, ok: bool,
                            summary: dict | None = None,
                            error: str | None = None) -> None:
        """Stamp an attempt, successful or not.

        `last_success_at` alone could not tell "nobody has synced for eleven
        days" apart from "it has been failing since Tuesday" — the two look
        identical from the outside and want opposite responses. Added
        2026-09-21 for the Admin page, which is the first thing that reads
        this rather than a person opening the file.

        The error is stored as a string, deliberately truncated: it is there
        to say what broke, and an upstream payload dumped whole into a file
        we serve to a browser is a good way to leak something.
        """
        with self._lock:
            state = self._load("sync_state")
            row = state.setdefault(source_system, {})
            row["last_attempt_at"] = utcnow().isoformat(timespec="seconds")
            row["last_attempt_ok"] = bool(ok)
            if summary is not None:
                row["last_result"] = summary
            row["last_error"] = (error or "")[:300] or None
            self._save("sync_state", state)

    def sync_state(self, source_system: str) -> dict:
        return self._load("sync_state").get(source_system) or {}

    def set_sync_field(self, source_system: str, key: str, value) -> None:
        """One more fact about a source's sync, e.g. which mapping built it."""
        with self._lock:
            state = self._load("sync_state")
            state.setdefault(source_system, {})[key] = value
            self._save("sync_state", state)

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
            page_url=record.get("page_url"),
            partner_restricted=bool(record.get("partner_restricted")),
            internal=bool(record.get("internal")),
            internal_source=record.get("internal_source"),
            age_band=content_age.band(_as_date(record.get("uploaded_at"))),
            still_current_until=record.get("still_current_until"),
            still_current_by=record.get("still_current_by"),
            archived=bool(record.get("archived")),
            upload_review=record.get("upload_review"),
            has_main_video=bool(record.get("main_video")),
            creator=record.get("creator"),
            demo_owner=record.get("demo_owner"),
            product_version=record.get("product_version"),
            archived_at=record.get("archived_at"),
            products=record.get("products") or [],
            product_families=taxonomy.families_of(record.get("products")),
            umbrella_families=taxonomy.umbrellas_of(record.get("products")),
            funnel_stage=record.get("funnel_stage"),
            content_depth=record.get("content_depth"),
            language=record.get("language") or "en",
            segment=record.get("segment"), industry=record.get("industry"),
            value_drivers=record.get("value_drivers") or [],
            tags=record.get("tags") or [],
            external_views=record.get("external_views"),
            customer_facing=bool(record.get("customer_facing", True)),
            has_narrated_audio=record.get("has_narrated_audio"),
            named_customer=record.get("named_customer"),
            uploaded_at=_as_date(record.get("uploaded_at")),
            date_stated=bool(record.get("date_stated")),
            duration_seconds=record.get("duration_seconds"),
            # A SharePoint picture goes through the Hub (services/thumbnails.py).
            thumbnail_url=thumbnails.public_url(record["id"], record.get("thumbnail_url")),
            source_item_id=record.get("source_item_id"),
            brightcove_id=record.get("brightcove_id"),
            consensus_uuid=record.get("consensus_uuid"),
            internal_title=record.get("internal_title"),
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
