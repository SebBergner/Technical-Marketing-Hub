"""Graph writes for the Brightcove Gallery migration -- only the calls Phase 0 proved.

Every call here was tried against the test library on 2026-09-28, and the
ones that do NOT work are recorded next to the ones that do, because three of
them fail silently with a 200 (docs/brightcove-migration-plan.md §9):

    create a Demo document set   POST folder, then PATCH listItem {"contentType": {"id"}}
                                 (fields.ContentTypeId -> 403 read-only;
                                  fields.ContentType by name -> 200, NO change)
    write managed metadata       PATCH the hidden note field with "Label|Guid;Label|Guid"
                                 (the column itself -> 400; "-1;#Label|Guid" -> 200,
                                  NOTHING written, or a mangled note)
    upload a large file          createUploadSession + 10 MiB chunks, no auth header
                                 on the upload URL, resume from nextExpectedRanges

Which library it writes to is decided by `LibraryTarget.resolve`, which refuses
the Demo Catalog outright and the production Brightcove library unless the
caller says so explicitly. Nothing in this module deletes anything.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Callable, Iterator
from urllib.parse import quote

import httpx

from backend.config import settings
from backend.integrations.graph.client import GraphClient, GraphError
from backend.integrations.tls import system_trust
from backend.services import sharepoint_mapping as m

log = logging.getLogger(__name__)

#: 32 x 320 KiB. Graph requires chunks in multiples of 320 KiB, under 60 MiB.
CHUNK_SIZE = 32 * 320 * 1024

#: Never a migration target, whatever the command line says.
FORBIDDEN_LIBRARIES = frozenset({"demo catalog"})

#: Columns the migration writes (internal names, measured 2026-09-28; the
#: second line added 2026-09-29 for Seb's sheet, plan §13).
REQUIRED_COLUMNS = ("Demo_x0020_Type", "Segment", "Product", "BrightcoveID",
                    "OriginalPublishDate", "GalleryURL", "Customer_x0020_Facing",
                    "Contains_x0020_Audio", "DocumentSetDescription",
                    "HubProducts", "VideoType", "VideoSubtype", "NamedCustomer", "Gallery",
                    "GallerySection", "LongDescription")

#: Choice columns whose values a manifest is validated against -- the
#: library's own options, read live, never a copy kept in code.
CHOICE_COLUMNS = ("Segment", "HubProducts", "VideoType", "VideoSubtype", "Gallery")


class MigrationTargetError(GraphError):
    """The library cannot be written to, or must not be."""


class UploadSessionExpired(GraphError):
    """The upload URL no longer exists; a new session has to start from 0."""


@dataclass(frozen=True)
class LibraryTarget:
    site_id: str
    name: str
    drive_id: str
    list_id: str
    demo_content_type_id: str
    #: Internal name of Product's hidden note field; differs per list.
    product_note_field: str
    #: The library's own options for each of CHOICE_COLUMNS.
    choices: dict

    @property
    def segment_choices(self) -> tuple[str, ...]:
        return tuple(self.choices.get("Segment") or ())

    @classmethod
    def resolve(cls, client: GraphClient, name: str, *,
                allow_production: bool = False) -> "LibraryTarget":
        """Find the library and check it is fit to write to. Read-only.

        Refuses, before any write can happen:
          * the Demo Catalog, always -- the migration never writes there
            (Liwei, 2026-09-28);
          * the production Brightcove library, unless `allow_production`;
          * any library missing what the migration writes.
        """
        if name.strip().lower() in FORBIDDEN_LIBRARIES:
            raise MigrationTargetError(f"{name!r} is never a migration target.")
        if (name.strip().lower() == settings.migration_brightcove_library.strip().lower()
                and not allow_production):
            raise MigrationTargetError(
                f"{name!r} is the production Brightcove library. Test on the test library, "
                f"or pass --allow-production for the reviewed pilot and batches.")

        site_id = client.resolve_site().site_id
        drive = client.find_drive(site_id, name)
        if drive is None:
            raise MigrationTargetError(f"No library named {name!r} on the site.")
        list_id = (client._request("GET", f"/drives/{drive.drive_id}/list",
                                   params={"$select": "id"}) or {})["id"]
        # `hidden` must be in $select: Graph omits hidden columns -- Product's
        # note field among them -- unless it is (measured 2026-09-28: 52
        # columns without it, 163 with).
        columns = {c["name"]: c for c in client._paged(
            f"/sites/{site_id}/lists/{list_id}/columns",
            {"$select": "name,displayName,hidden,choice"})}
        types = (client._request("GET", f"/sites/{site_id}/lists/{list_id}/contentTypes")
                 or {}).get("value", [])
        demo = next((t for t in types if t.get("name") == "Demo"), None)
        note = next((c["name"] for c in columns.values()
                     if c.get("displayName") == "Product_0"), None)
        def options(column: str) -> tuple[str, ...]:
            return tuple(((columns.get(column) or {}).get("choice") or {}).get("choices") or ())

        choices = options("Demo_x0020_Type")

        missing = [c for c in REQUIRED_COLUMNS if c not in columns]
        if demo is None or not demo.get("documentSet"):
            missing.append('the "Demo" document set content type')
        if note is None:
            missing.append("Product's note field (Product_0)")
        if "Video" not in choices:
            missing.append('the "Video" choice in Demo Type')
        if missing:
            raise MigrationTargetError(f"{name!r} is not ready: missing " + ", ".join(missing))

        return cls(site_id=site_id, name=drive.name or name, drive_id=drive.drive_id,
                   list_id=list_id, demo_content_type_id=demo["id"],
                   product_note_field=note,
                   choices={c: options(c) for c in CHOICE_COLUMNS})


# ───────────────────────────────────────────────────────────── reading
def existing_by_brightcove_id(client: GraphClient, target: LibraryTarget) -> dict[str, dict]:
    """Top-level folders already in the library, keyed by Brightcove ID.

    This is what makes a re-run idempotent (HLR-A2): the key is the ID, never
    the title, which people correct.
    """
    found: dict[str, dict] = {}
    for item in client.list_children(target.drive_id, "root"):
        fields = ((item.get("listItem") or {}).get("fields") or {})
        bcid = m.clean_text(fields.get("BrightcoveID"))
        if "folder" in item and bcid:
            found[bcid] = item
    return found


def folder_names(client: GraphClient, target: LibraryTarget) -> set[str]:
    return {(i.get("name") or "").lower()
            for i in client.list_children(target.drive_id, "root", expand_fields=False)}


class TermIndex:
    """Product label -> (stored label, TermGuid), from the term store.

    Guards against a measured Graph fault: `/termStore/sets/{id}/terms` returns
    the whole set on page 1 and then an endless nextLink that repeats the same
    terms (2026-09-28: a plain paging loop hung for 23 minutes). Paging stops
    as soon as a page adds nothing new, and after `max_pages` regardless.

    Lookup is by normalised label (clean_text, case-insensitive), but the
    value written is the term's own stored label -- some carry a full-width
    ampersand that clean_text folds on read.
    """

    def __init__(self, terms: dict[str, tuple[str, str]]):
        self._terms = terms

    @classmethod
    def load(cls, client: GraphClient, site_id: str, term_set_id: str,
             max_pages: int = 20) -> "TermIndex":
        terms: dict[str, tuple[str, str]] = {}
        seen: set[str] = set()
        url = f"/sites/{site_id}/termStore/sets/{term_set_id}/terms"
        payload = client._request("GET", url, params={"$select": "id,labels"})
        pages = 0
        while payload and pages < max_pages:
            pages += 1
            fresh = [t for t in payload.get("value", []) if t["id"] not in seen]
            if not fresh:
                break
            for t in fresh:
                seen.add(t["id"])
                for label in t.get("labels") or []:
                    stored = label.get("name") or ""
                    terms.setdefault(cls.key(stored), (stored, t["id"]))
            link = payload.get("@odata.nextLink")
            if not link:
                break
            payload = client._request("GET", link)
        return cls(terms)

    @staticmethod
    def key(label: str) -> str:
        return (m.clean_text(label) or "").lower()

    def get(self, label: str) -> tuple[str, str] | None:
        return self._terms.get(self.key(label))

    def __len__(self) -> int:
        return len(self._terms)


def note_value(terms: list[tuple[str, str]]) -> str:
    """The note-field format that works: "Label|Guid;Label|Guid".

    NOT "-1;#Label|Guid" -- measured 2026-09-28, that returns 200 and writes
    nothing (single value) or mangles the note (multiple values).
    """
    return ";".join(f"{label}|{guid}" for label, guid in terms)


# ───────────────────────────────────────────────────────────── writing
#: Characters SharePoint rejects in a name, plus `#` and `%`, which it accepts
#: but some clients mishandle in URLs. `&` is fine and stays.
_BAD_NAME = re.compile(r'["*:<>?/\\|#%]')


def safe_folder_name(title: str) -> str:
    """A SharePoint-safe, stable folder name from a human title.

    The folder name becomes the Hub's asset id (slugify), and a rename later
    breaks shared links -- so it is derived from the title once, with no
    dates or version noise added here. A rejected character becomes a
    spaced dash ("A: B" -> "A - B"); hyphens inside words are left alone.
    """
    name = _BAD_NAME.sub(" - ", m.clean_text(title) or "Untitled")
    name = re.sub(r"\s+-(?:\s+-)*\s+", " - ", name)
    name = re.sub(r"\s{2,}", " ", name).strip(" .-")
    return name[:120].rstrip(" .-") or "Untitled"


def create_demo_folder(client: GraphClient, target: LibraryTarget, name: str) -> dict:
    """A top-level folder, then turned into a Demo document set.

    `conflictBehavior: fail`: an existing folder of the same name is a
    conflict for a person to look at, never something to rename around or
    write into.
    """
    item = client._request("POST", f"/drives/{target.drive_id}/root/children",
                           json={"name": name, "folder": {},
                                 "@microsoft.graph.conflictBehavior": "fail"})
    if not item or "id" not in item:
        raise GraphError(f"creating folder {name!r} returned no item")
    client._request("PATCH", f"/drives/{target.drive_id}/items/{item['id']}/listItem",
                    json={"contentType": {"id": target.demo_content_type_id}})
    return item


def write_fields(client: GraphClient, target: LibraryTarget, item_id: str,
                 fields: dict) -> dict:
    """PATCH columns with If-Match, so a concurrent human edit raises rather
    than being overwritten (GraphConcurrentEdit)."""
    current = client._request("GET", f"/drives/{target.drive_id}/items/{item_id}/listItem") or {}
    etag = current.get("@odata.etag") or current.get("eTag")
    return client.update_list_item_fields(target.drive_id, item_id, fields, etag=etag)


# ───────────────────────────────────────────────────────────── uploading
class ByteSource:
    """Where a video's bytes come from: a local file or an HTTP(S) URL.

    `open(offset)` yields the bytes from `offset` on, so an interrupted upload
    resumes without re-sending what Graph already has. Never reads a whole
    file into memory.
    """

    def __init__(self, location: str, *, http: httpx.Client | None = None):
        self.location = location
        self._http = http

    @property
    def is_url(self) -> bool:
        return self.location.lower().startswith(("http://", "https://"))

    def size(self) -> int:
        if not self.is_url:
            import os
            return os.path.getsize(self.location)
        http = self._http or httpx.Client(follow_redirects=True, timeout=60,
                                          verify=system_trust())
        r = http.head(self.location)
        r.raise_for_status()
        length = r.headers.get("content-length")
        if not length:
            raise GraphError(f"{self.location} did not say how large it is (no Content-Length)")
        return int(length)

    def open(self, offset: int = 0, block: int = 1024 * 1024) -> Iterator[bytes]:
        if not self.is_url:
            with open(self.location, "rb") as fh:
                fh.seek(offset)
                while chunk := fh.read(block):
                    yield chunk
            return
        http = self._http or httpx.Client(follow_redirects=True, timeout=120,
                                          verify=system_trust())
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        with http.stream("GET", self.location, headers=headers) as r:
            r.raise_for_status()
            skip = offset if (offset and r.status_code != 206) else 0   # no Range support
            for chunk in r.iter_bytes(block):
                if skip:
                    drop = min(skip, len(chunk))
                    chunk, skip = chunk[drop:], skip - drop
                if chunk:
                    yield chunk


class BrightcoveSource:
    """A Brightcove video's best MP4 rendition as a ByteSource.

    The signed URL is asked for afresh on every `open`: it expires, and a
    resume hours later must not reuse one that died in the meantime. The
    URL is never stored or logged.
    """

    def __init__(self, bc, video_id: str, *, http: httpx.Client | None = None):
        self._bc, self.video_id, self._http = bc, video_id, http

    def _rendition(self) -> dict:
        rendition = self._bc.best_mp4(self.video_id)
        if not rendition:
            raise GraphError(f"Brightcove video {self.video_id} has no MP4 rendition")
        return rendition

    def size(self) -> int:
        size = self._rendition().get("size")
        if not size:
            raise GraphError(f"Brightcove did not give a size for video {self.video_id}")
        return int(size)

    def open(self, offset: int = 0, block: int = 1024 * 1024) -> Iterator[bytes]:
        yield from ByteSource(self._rendition()["url"], http=self._http).open(offset, block)


def _chunks(stream: Iterator[bytes], size: int) -> Iterator[bytes]:
    """Re-cut an arbitrary byte stream into exactly `size`-byte chunks."""
    buf = bytearray()
    for piece in stream:
        buf.extend(piece)
        while len(buf) >= size:
            yield bytes(buf[:size])
            del buf[:size]
    if buf:
        yield bytes(buf)


def start_upload(client: GraphClient, target: LibraryTarget, folder_id: str,
                 filename: str) -> str:
    session = client._request(
        "POST",
        f"/drives/{target.drive_id}/items/{folder_id}:/{quote(filename)}:/createUploadSession",
        json={"item": {"@microsoft.graph.conflictBehavior": "fail"}})
    if not session or "uploadUrl" not in session:
        raise GraphError(f"no upload session for {filename!r}")
    return session["uploadUrl"]


def upload(source: ByteSource, upload_url: str, *, size: int,
           uploader: httpx.Client | None = None, chunk_size: int = CHUNK_SIZE,
           on_progress: Callable[[int], None] | None = None) -> dict:
    """Stream `source` into an upload session, resuming where Graph left off.

    The upload URL is pre-authorised: sending our bearer token to it is both
    unnecessary and, per Graph's guidance, wrong. Returns the driveItem.
    """
    up = uploader or httpx.Client(timeout=httpx.Timeout(120.0, connect=30.0))
    status = up.get(upload_url)
    if status.status_code in (404, 410):
        raise UploadSessionExpired(f"upload session gone (HTTP {status.status_code})")
    offset = 0
    if status.status_code == 200:
        ranges = status.json().get("nextExpectedRanges") or ["0-"]
        offset = int(ranges[0].split("-")[0])

    for data in _chunks(source.open(offset), chunk_size):
        end = offset + len(data) - 1
        for attempt in range(6):
            try:
                r = up.put(upload_url, content=data, headers={
                    "Content-Length": str(len(data)),
                    "Content-Range": f"bytes {offset}-{end}/{size}"})
            except httpx.HTTPError as exc:
                log.warning("upload chunk at %d failed: %s", offset, exc)
                time.sleep(min(2 ** attempt, 30))
                continue
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(min(float(r.headers.get("Retry-After", 2 ** attempt)), 60))
                continue
            break
        else:
            raise GraphError(f"upload chunk at byte {offset} kept failing")

        if r.status_code == 202:
            offset = end + 1
            if on_progress:
                on_progress(offset)
            continue
        if r.status_code in (200, 201):
            if on_progress:
                on_progress(size)
            return r.json()
        raise GraphError(f"upload chunk at byte {offset}: HTTP {r.status_code} {r.text[:200]}")
    raise GraphError("the source ended before the upload completed")
