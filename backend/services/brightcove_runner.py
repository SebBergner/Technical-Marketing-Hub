"""The Brightcove Gallery migration: validate a manifest, plan it, run it, log it.

Driven by scripts/migrate_brightcove.py. The input is a MANIFEST -- a CSV in
the format below, defined by us. Seb's sheet (Phase 1) will be converted into
it by an adapter once its format is known; nothing here depends on that sheet.

    brightcove_id          required; the identity key (HLR-A2)
    title                  becomes the folder name, once; blank = Brightcove's name
    description            blank = Brightcove's description
    segments               ";"-separated, each one of the library's Segment choices
    hub_products           ";"-separated, each one of the library's Hub Products choices
    products               ";"-separated Product TERM labels; blank = every hub_products
                           value that is also a Product term (plan §13)
    customer_facing        required: yes / no  (HLR-A9 -- never left to a default)
    video_type             one of the library's Video Type choices
    video_subtype          one of the library's Video Subtype choices
    named_customer         free text (HLR-C2)
    gallery                one of the library's Gallery choices
    gallery_section        free text
    long_description       free text; `description` holds the short one
    contains_audio         optional: yes / no
    original_publish_date  YYYY-MM-DD (HLR-A8); blank = Brightcove's published_at
    gallery_url            optional
    source                 blank = fetch from Brightcove by ID (the normal case);
                           or a local path / http(s) URL, for tests
    filename               blank = "<title>_<video type>.mp4" (video_file_name)

So a sheet only has to supply the IDs and the classification a person
decides (segments, products, customer-facing); everything Brightcove already
knows is filled from it by `enrich`, and a value the sheet does give always
wins over Brightcove's.

Rules this module keeps, each for a reason written in the plan:

* Unknown values are reported, never forced to a near match (HLR-A7).
* An existing video (same Brightcove ID) is SKIPPED, never updated, so no
  value a person corrected can be overwritten (HLR-A6). Updating in place
  comes later, with the last-written values kept to compare against.
* Per video: create the folder, upload the file, and write the metadata
  LAST. The Brightcove ID is therefore only on complete folders; a folder
  left half-done by a failure has none, shows up as a conflict on the next
  plan, and is finished by --resume from the batch log.
* The batch log is rewritten after every step, so a crash leaves an exact
  record of what exists -- which is also the only way to undo a batch.
* Nothing is ever deleted.
"""
from __future__ import annotations

import csv
import json
import os
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Callable

from backend.integrations.graph import migration_writer as w
from backend.integrations.graph.client import GraphClient, GraphError
from backend.services import sharepoint_mapping as m
from backend.services.brightcove_migration import batches_dir

REQUIRED = ("brightcove_id", "customer_facing")
BRIGHTCOVE = "brightcove"          # `source` value meaning "download by ID"
#: Extra manifest column -> (library column, is it a choice column).
EXTRA = {"hub_products": ("HubProducts", True), "video_type": ("VideoType", True),
         "video_subtype": ("VideoSubtype", True), "named_customer": ("NamedCustomer", False),
         "gallery": ("Gallery", True), "gallery_section": ("GallerySection", False),
         "long_description": ("LongDescription", False)}
COLUMNS = ("brightcove_id", "title", "description", "segments", "products", "customer_facing",
           "hub_products", "video_type", "video_subtype", "named_customer", "gallery",
           "gallery_section", "long_description",
           "contains_audio", "original_publish_date", "gallery_url", "source", "filename")


# ───────────────────────────────────────────────────────────── the manifest
@dataclass
class VideoRecord:
    row: int
    brightcove_id: str
    title: str
    description: str | None
    segments: list[str]
    products: list[str]
    customer_facing: bool | None
    contains_audio: bool | None
    original_publish_date: date | None
    gallery_url: str | None
    source: str
    filename: str
    problems: list[str] = field(default_factory=list)
    #: The video's size, once known (Brightcove's rendition size, or the file).
    size_bytes: int | None = None
    hub_products: list[str] = field(default_factory=list)
    #: The single-value EXTRA columns, keyed by manifest name.
    extra: dict = field(default_factory=dict)
    #: Runtime in seconds, from Brightcove, once enriched.
    duration_s: float | None = None

    @property
    def from_brightcove(self) -> bool:
        return self.source == BRIGHTCOVE

    @property
    def folder_name(self) -> str:
        return w.safe_folder_name(self.title)


def _split(value: str | None) -> list[str]:
    return [p for p in (m.clean_text(x) for x in (value or "").split(";")) if p]


def load_manifest(path: str) -> list[VideoRecord]:
    """Read the CSV. Problems are attached to each record, not raised, so one
    bad row never hides the state of the other 475."""
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        unknown = set(reader.fieldnames or ()) - set(COLUMNS)
        missing = set(REQUIRED) - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"manifest lacks required column(s): {', '.join(sorted(missing))}")
        rows = list(reader)

    records = []
    for i, raw in enumerate(rows, start=2):                  # row 1 is the header
        get = lambda k: m.clean_text(raw.get(k))             # noqa: E731
        problems = [f"unknown column {c!r} ignored" for c in sorted(unknown)] if i == 2 else []
        for k in REQUIRED:
            if not get(k):
                problems.append(f"{k} is empty")
        published = None
        if get("original_publish_date"):
            try:
                published = date.fromisoformat(get("original_publish_date"))
            except ValueError:
                problems.append(f"original_publish_date {get('original_publish_date')!r} is not YYYY-MM-DD")
        cf = m.as_bool(get("customer_facing"))
        if get("customer_facing") and cf is None:
            problems.append(f"customer_facing {get('customer_facing')!r} is not yes/no")
        audio = m.as_bool(get("contains_audio"))
        if get("contains_audio") and audio is None:
            problems.append(f"contains_audio {get('contains_audio')!r} is not yes/no")
        source = get("source") or BRIGHTCOVE
        if source.lower() == BRIGHTCOVE:
            source = BRIGHTCOVE
        filename = get("filename") or (
            "" if source == BRIGHTCOVE else os.path.basename(source.split("?")[0]))
        records.append(VideoRecord(
            row=i, brightcove_id=get("brightcove_id") or "", title=get("title") or "",
            description=get("description"), segments=_split(raw.get("segments")),
            products=_split(raw.get("products")), customer_facing=cf, contains_audio=audio,
            original_publish_date=published, gallery_url=get("gallery_url"),
            source=source, filename=filename, problems=problems,
            hub_products=_split(raw.get("hub_products")),
            extra={k: get(k) for k in EXTRA if k != "hub_products" and get(k)}))

    seen: dict[str, int] = {}
    for r in records:
        if r.brightcove_id in seen:
            r.problems.append(f"Brightcove ID repeats row {seen[r.brightcove_id]}")
        seen.setdefault(r.brightcove_id, r.row)
    return records


def enrich(records: list[VideoRecord], bc) -> None:
    """Fill what the sheet left blank from Brightcove, and confirm each video
    can actually be fetched. Read-only on Brightcove. A value the sheet gives
    is never replaced."""
    for r in records:
        if not r.from_brightcove or not r.brightcove_id:
            continue
        video = bc.video(r.brightcove_id)
        if video is None:
            r.problems.append("not found in Brightcove")
            continue
        if video.get("state") != "ACTIVE":
            r.problems.append(f"Brightcove state is {video.get('state')}, not ACTIVE")
        if video.get("duration"):
            r.duration_s = video["duration"] / 1000
        r.title = r.title or m.clean_text(video.get("name")) or ""
        r.description = (r.description or m.clean_text(video.get("description"))
                         or m.clean_text(video.get("long_description")))
        if r.original_publish_date is None:
            stamp = video.get("published_at") or video.get("created_at")
            if stamp:
                r.original_publish_date = date.fromisoformat(stamp[:10])
        rendition = bc.best_mp4(r.brightcove_id)
        if rendition is None:
            r.problems.append("Brightcove has no downloadable MP4 rendition")
        else:
            r.size_bytes = rendition.get("size")


def video_file_name(r: VideoRecord) -> str:
    """The migrated file's name: "<demo name>_<Video Type>.mp4" (Liwei,
    2026-09-29) -- e.g. "Creo 10 Top Enhancements_Technical Overview.mp4".
    Without a Video Type, the demo name alone. The same cleaning as the
    folder name, so a title SharePoint accepts as a folder is accepted here.
    """
    video_type = r.extra.get("video_type")
    stem = f"{r.title}_{video_type}" if video_type else r.title
    return w.safe_folder_name(stem) + ".mp4"


def validate(records: list[VideoRecord], choices, terms: w.TermIndex) -> None:
    """Check values against the live library and term store (HLR-A7), and
    that every record ends up complete. Run after `enrich`.

    `choices` is LibraryTarget.choices (column -> options); a plain sequence
    is taken as the Segment options alone. Choice values must match the
    library's option exactly, case included: SharePoint stores what it is
    sent, and "creo" would sit beside "Creo" as a different value.
    """
    if not isinstance(choices, dict):
        choices = {"Segment": tuple(choices)}
    segment_choices = list(choices.get("Segment") or ())
    allowed = {s.lower(): s for s in segment_choices}

    # Two rows that would become the same folder: the second create fails,
    # and with parallel uploads the two race for it. SharePoint names are
    # case-insensitive. Both rows are flagged -- which one keeps the name is
    # the sheet owner's call. V29 had 3 such pairs (2026-09-29).
    by_name: dict[str, list[VideoRecord]] = {}
    for r in records:
        if r.title:
            by_name.setdefault(r.folder_name.lower(), []).append(r)
    for same in by_name.values():
        for r in same if len(same) > 1 else ():
            others = ", ".join(str(o.row) for o in same if o is not r)
            r.problems.append(f"title gives the same folder name as row {others}; "
                              f"titles must be unique")

    for r in records:
        for key, (column, is_choice) in EXTRA.items():
            values = r.hub_products if key == "hub_products" else (
                [r.extra[key]] if r.extra.get(key) else [])
            options = choices.get(column)
            if is_choice and values and options is not None:
                for v in values:
                    if v not in options:
                        r.problems.append(f"{key} {v!r} is not a {column} option")
        if not r.products and r.hub_products:
            # Managed-metadata Product only where a term matches exactly (§13).
            r.products = [p for p in r.hub_products
                          if (t := terms.get(p)) and t[0].lower() == p.lower()]
        if not r.title:
            r.problems.append("title is empty")
        if not r.filename and r.from_brightcove and r.title:
            r.filename = video_file_name(r)
        if r.filename and not r.filename.lower().endswith(tuple("." + e for e in m.VIDEO_EXT)):
            r.problems.append(f"filename {r.filename!r} is not a video file name")
        if not r.filename and not r.from_brightcove:
            r.problems.append("filename is empty")
        for s in r.segments:
            if s.lower() not in allowed:
                r.problems.append(f"segment {s!r} is not one of {', '.join(segment_choices)}")
        for p in r.products:
            if terms.get(p) is None:
                r.problems.append(f"product {p!r} is not a Product term")


# ───────────────────────────────────────────────────────────── the batch log
def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class BatchLog:
    """One JSON file per run under owned/migration/brightcove/batches/, the
    shape the /migration page reads. Rewritten atomically after every step.

    Thread-safe: parallel uploads (migration_jobs) update one log from
    several threads, and an unguarded update could be written out half-done
    or lost to another thread's save.
    """

    def __init__(self, data: dict):
        self.data = data
        self._lock = threading.RLock()

    @classmethod
    def new(cls, mode: str, library: str, manifest: str, planned: int) -> "BatchLog":
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return cls({"batch_id": f"{stamp}-{mode}", "mode": mode, "library": library,
                    "manifest": os.path.abspath(manifest), "started_at": _now(),
                    "finished_at": None, "planned": planned, "counts": {}, "items": []})

    @classmethod
    def load(cls, batch_id: str) -> "BatchLog":
        with open(os.path.join(batches_dir(), f"{batch_id}.json"), encoding="utf-8") as fh:
            return cls(json.load(fh))

    @property
    def path(self) -> str:
        return os.path.join(batches_dir(), f"{self.data['batch_id']}.json")

    def item(self, brightcove_id: str) -> dict | None:
        return next((i for i in self.data["items"] if i["brightcove_id"] == brightcove_id), None)

    def set_item(self, brightcove_id: str, **fields) -> dict:
        with self._lock:
            entry = self.item(brightcove_id)
            if entry is None:
                entry = {"brightcove_id": brightcove_id}
                self.data["items"].append(entry)
            entry.update(fields, updated_at=_now())
            self.save()
            return entry

    def recount(self) -> None:
        counts: dict[str, int] = {}
        for i in self.data["items"]:
            counts[i["status"]] = counts.get(i["status"], 0) + 1
        self.data["counts"] = counts

    def save(self) -> None:
        with self._lock:
            self.recount()
            os.makedirs(batches_dir(), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, indent=1, ensure_ascii=False)
            os.replace(tmp, self.path)

    def finish(self) -> None:
        with self._lock:
            self.data["finished_at"] = _now()
            self.save()


# ───────────────────────────────────────────────────────────── planning
def plan(records: list[VideoRecord], existing: dict[str, dict],
         names_in_use: set[str]) -> dict[str, str]:
    """Brightcove ID -> invalid | existing | conflict | new. Writes nothing.

    `conflict`: a folder of the same name exists without this Brightcove ID
    -- someone else's folder, or one of ours left half-done. Either way a
    person or --resume decides; the tool does not write into it.
    """
    status = {}
    for r in records:
        if r.problems:
            status[r.brightcove_id or f"row {r.row}"] = "invalid"
        elif r.brightcove_id in existing:
            status[r.brightcove_id] = "existing"
        elif r.folder_name.lower() in names_in_use:
            status[r.brightcove_id] = "conflict"
        else:
            status[r.brightcove_id] = "new"
    return status


def fields_for(r: VideoRecord) -> dict:
    """The columns written, LAST, once the video is in. Shapes as proven in §9."""
    fields = {
        "Demo_x0020_Type": "Video",
        "BrightcoveID": r.brightcove_id,
        "Customer_x0020_Facing": bool(r.customer_facing),
    }
    if r.segments:
        fields["Segment@odata.type"] = "Collection(Edm.String)"
        fields["Segment"] = r.segments
    if r.description:
        fields["DocumentSetDescription"] = r.description
    if r.original_publish_date:
        fields["OriginalPublishDate"] = r.original_publish_date.isoformat() + "T00:00:00Z"
    if r.gallery_url:
        fields["GalleryURL"] = r.gallery_url
    if r.contains_audio is not None:
        fields["Contains_x0020_Audio"] = r.contains_audio
    if r.hub_products:
        fields["HubProducts@odata.type"] = "Collection(Edm.String)"
        fields["HubProducts"] = r.hub_products
    for key, (column, _) in EXTRA.items():
        if key != "hub_products" and r.extra.get(key):
            fields[column] = r.extra[key]
    return fields


# ───────────────────────────────────────────────────────────── running
def migrate_one(client: GraphClient, target: w.LibraryTarget, terms: w.TermIndex,
                r: VideoRecord, log: BatchLog, *, bc=None, uploader=None, source_http=None,
                chunk_size: int = w.CHUNK_SIZE,
                say: Callable[[str], None] = print) -> None:
    """Carry one video from wherever the batch log says it got to, to done."""
    entry = log.item(r.brightcove_id) or {}
    folder_id = entry.get("folder_id")

    if not folder_id:
        folder = w.create_demo_folder(client, target, r.folder_name)
        folder_id = folder["id"]
        log.set_item(r.brightcove_id, status="folder_created", folder_id=folder_id,
                     folder_name=r.folder_name, web_url=folder.get("webUrl"))
        say(f"  created folder {r.folder_name!r}")

    if not entry.get("file_id"):
        if r.from_brightcove:
            if bc is None:
                raise GraphError("this video comes from Brightcove, but Brightcove is not configured")
            source = w.BrightcoveSource(bc, r.brightcove_id, http=source_http)
        else:
            source = w.ByteSource(r.source, http=source_http)
        size = source.size()
        url = entry.get("upload_url")
        if not url:
            url = w.start_upload(client, target, folder_id, r.filename)
            log.set_item(r.brightcove_id, status="uploading", upload_url=url, size=size)
        last = [0]

        def progress(done: int) -> None:
            # Record progress every ~5% so a resume knows roughly where it
            # stood; Graph's nextExpectedRanges remains the exact source.
            if done == size or done - last[0] >= max(size // 20, 1):
                last[0] = done
                log.set_item(r.brightcove_id, status="uploading", uploaded_bytes=done)
                say(f"  {done / size:6.1%}  {done / 1e9:.2f}/{size / 1e9:.2f} GB")

        try:
            item = w.upload(source, url, size=size, uploader=uploader,
                            chunk_size=chunk_size, on_progress=progress)
        except w.UploadSessionExpired:
            # A session left idle too long is gone, and with it the partial
            # upload; Graph never creates the file, so start over cleanly.
            say("  upload session expired; starting a new one")
            url = w.start_upload(client, target, folder_id, r.filename)
            log.set_item(r.brightcove_id, status="uploading", upload_url=url, uploaded_bytes=0)
            item = w.upload(source, url, size=size, uploader=uploader,
                            chunk_size=chunk_size, on_progress=progress)
        log.set_item(r.brightcove_id, status="uploaded", file_id=item.get("id"),
                     upload_url=None, uploaded_bytes=size)

    w.write_fields(client, target, folder_id, fields_for(r))
    if r.products:
        chosen = [terms.get(p) for p in r.products]
        w.write_fields(client, target, folder_id,
                       {target.product_note_field: w.note_value([t for t in chosen if t])})
    log.set_item(r.brightcove_id, status="done")
    say("  metadata written")
