"""Where the Hub may upload, and what each upload must say (2026-10-15).

Liwei: uploads go to the Demo Catalog (kits) and Demo Video (videos), with
"an interface for libraries added later". That interface is TARGETS: one
entry per SharePoint library, naming the kinds it takes and the metadata an
upload must carry. Adding a library is adding an entry -- the form, the
validation and the SharePoint write all follow from it. (For the Hub to
*list* what is uploaded there, its sync must index that library too: the
Demo Catalog and Demo Video are indexed today.)

Every upload states its metadata before a byte is sent: the form will not
start without the required fields, and the server checks them again.
Choice fields take their options live from the library's own columns
(upload_writer.resolve), so the form can never offer a value SharePoint
would refuse.

Rules for every target, whatever its entry says:
* uploads only ever create a NEW folder (a document set); a name already in
  the library is refused, never merged into or overwritten;
* existing content is never modified or deleted.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date

#: Field kinds the form knows how to draw.
TEXT, LONGTEXT, CHOICE, MULTI, YESNO, DATE = "text", "longtext", "choice", "multi", "yesno", "date"


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    kind: str
    required: bool = False
    #: The library column written (internal name). None: kept by the Hub.
    column: str | None = None
    #: Where a choice field's options come from: a column of this library,
    #: read live, or the curated Hub product list ("products").
    choices_from: str | None = None
    default: object = None
    help: str = ""
    max_length: int | None = None
    #: Required on the Hub's own form, a warning only through the API (A11,
    #: Liwei 2026-10-26: product version), so scripts keep working until
    #: their authors add it.
    form_required: bool = False


@dataclass(frozen=True)
class KindSpec:
    key: str           # the Hub's asset type: video, ldk, vdk
    label: str
    demo_type: str     # the library's Demo Type value


#: Where a new demo can be created (Liwei, 2026-10-15). Only SharePoint is
#: built; the others are listed so the choice is visible from the start.
PLATFORMS = (
    {"key": "sharepoint", "label": "SharePoint", "available": True,
     "description": "The TDD libraries: demo kits and videos. Listed in the Hub."},
    {"key": "consensus", "label": "Consensus", "available": False,
     "description": "Interactive demos. Not available yet."},
    {"key": "brightcove", "label": "Brightcove", "available": False,
     "description": "The video Gallery. Not available yet."},
)


@dataclass(frozen=True)
class TargetSpec:
    key: str
    library: str
    label: str
    kinds: tuple[KindSpec, ...]
    fields: tuple[FieldSpec, ...]
    #: Video uploads are one video file; kits are any files, any folders.
    single_video: bool = False
    #: Products as the library's managed-metadata "Product" column (note
    #: field), offered from the terms the library already uses.
    product_terms: bool = True
    #: Products also as a plain choice column (Demo Video's HubProducts).
    product_choice_column: str | None = None
    #: The column the stated publish date goes to; None: kept by the Hub
    #: (owned/publish_dates.json) because the library has none.
    publish_date_column: str | None = None
    #: The Hub's asset-id prefix for this library's sync (video_sync: "video-").
    id_prefix: str = ""
    #: The destination platform (PLATFORMS).
    platform: str = "sharepoint"


def _common(*, description_help: str) -> list[FieldSpec]:
    return [
        FieldSpec("title", "Title", TEXT, required=True, max_length=120,
                  help="The demo's name, and its link in the Hub: choose it carefully, "
                       "renaming later breaks shared links."),
        FieldSpec("description", "Description", LONGTEXT, required=True,
                  column="DocumentSetDescription", max_length=2000, help=description_help),
        FieldSpec("products", "Products", MULTI, required=True, choices_from="products",
                  help="Every product the demo shows."),
        FieldSpec("segment", "Segment", MULTI, required=True, column="Segment",
                  choices_from="Segment"),
        FieldSpec("customer_facing", "Customer facing", YESNO, required=True,
                  column="Customer_x0020_Facing",
                  help="Can it be shown to customers as it is?"),
        FieldSpec("contains_audio", "Narrated audio", YESNO, required=True,
                  column="Contains_x0020_Audio"),
        FieldSpec("original_publish_date", "Original publish date", DATE, required=True,
                  default="today",
                  help="When the content was made. Drives its age badge; for older material "
                       "being added now, the recording date."),
        # Every asset (A11, 2026-10-26); "N/A" where none applies, which the
        # Hub then does not show.
        FieldSpec("product_version", "Product version", TEXT, column="Product_x0020_Version",
                  max_length=100, form_required=True,
                  help="e.g. Creo 12, Windchill 13.1. N/A if it does not apply."),
    ]


DEMO_CATALOG = TargetSpec(
    key="demo_catalog", library="Demo Catalog", label="Demo Catalog — demo kits",
    kinds=(KindSpec("ldk", "Live Demo Kit (LDK)", "Live Demo Kit"),
           KindSpec("vdk", "Virtual Demo Kit (VDK)", "Virtual Demo Kit")),
    fields=tuple(_common(description_help="What the kit demonstrates and who it is for.") + [
        FieldSpec("language", "Language", CHOICE, required=True, column="Language",
                  choices_from="Language", default="English"),
        FieldSpec("owned_by", "Owned by", CHOICE, required=True, column="Owned_x0020_By",
                  choices_from="Owned_x0020_By", default="Technical Demonstration Development"),
    ]),
    # Added by Liwei 2026-10-15 (indexed); the sync reads it first.
    publish_date_column="OriginalPublishDate",
)

DEMO_VIDEO = TargetSpec(
    key="demo_video", library="Demo Video", label="Demo Video — single videos",
    kinds=(KindSpec("video", "Video", "Video"),),
    fields=tuple(_common(description_help="One or two sentences shown on the card.") + [
        FieldSpec("video_type", "Video type", CHOICE, required=True, column="VideoType",
                  choices_from="VideoType"),
        FieldSpec("video_subtype", "Video subtype", CHOICE, column="VideoSubtype",
                  choices_from="VideoSubtype"),
        FieldSpec("named_customer", "Named customer", TEXT, column="NamedCustomer",
                  max_length=100),
        FieldSpec("long_description", "Long description", LONGTEXT,
                  column="LongDescription", max_length=8000),
    ]),
    single_video=True,
    # The Hub reads Demo Video's products from HubProducts (video_sync.py);
    # the managed-metadata column is not needed there.
    product_terms=False,
    product_choice_column="HubProducts",
    publish_date_column="OriginalPublishDate",
    id_prefix="video-",
)

#: The libraries uploads may go to. Add a library here (see the module doc).
TARGETS: dict[str, TargetSpec] = {t.key: t for t in (DEMO_CATALOG, DEMO_VIDEO)}

#: GXC Video (2026-10-29): Demo Video's columns, restricted in SharePoint.
#: Its videos come from the migration and are filled in afterwards with
#: Edit metadata, so it is edited here but never offered as an upload target.
GXC_VIDEO = replace(DEMO_VIDEO, key="gxc_video", library="GXC Video",
                    label="GXC Video — restricted videos", id_prefix="gxc-")
EDIT_ONLY: dict[str, TargetSpec] = {GXC_VIDEO.key: GXC_VIDEO}

#: Never an upload target, whatever TARGETS says.
NEVER = frozenset({"documents", "wiki", "apps for sharepoint", "client side assets"})

VIDEO_EXT = {"mp4", "mov", "m4v", "webm", "wmv", "avi", "mkv"}
#: Characters SharePoint refuses in a file or folder name.
BAD_NAME_CHARS = set('"*:<>?\\|#%')


class UploadInvalid(ValueError):
    """What is wrong with an upload, for the person making it."""


def overrides() -> dict[str, str]:
    """UPLOAD_LIBRARY_OVERRIDES as {target key: library}: a test library to
    write to instead, while trying uploads out."""
    from backend.config import settings
    out = {}
    for pair in (settings.upload_library_overrides or "").split(";"):
        key, _, library = pair.partition("=")
        if key.strip() in TARGETS and library.strip():
            out[key.strip()] = library.strip()
    return out


def target(key: str) -> TargetSpec:
    spec = TARGETS.get(key) or EDIT_ONLY.get(key)
    if spec is None:
        raise UploadInvalid("Choose where it goes: " + ", ".join(t.label for t in TARGETS.values()))
    if key in overrides():
        spec = replace(spec, library=overrides()[key])
    if spec.library.strip().lower() in NEVER:
        raise UploadInvalid(f"{spec.library} is never an upload target.")
    return spec


def kind_of(spec: TargetSpec, key: str) -> KindSpec:
    found = next((k for k in spec.kinds if k.key == key), None)
    if found is None:
        raise UploadInvalid(f"{spec.library} takes: " + ", ".join(k.label for k in spec.kinds))
    return found


def clean_fields(spec: TargetSpec, raw: dict, choices: dict[str, list[str]], *,
                 form: bool = False, partial: bool = False) -> dict:
    """The metadata, checked against the target's spec and the library's live
    options. Raises UploadInvalid naming every problem at once.

    `form`: from the Hub's own page, where form_required fields are required
    too. `partial`: an edit of a demo that exists (A1), which says only what
    changes, so nothing is required -- only checked."""
    out, problems = {}, []
    for f in spec.fields:
        if partial and f.key not in raw:
            continue
        value = raw.get(f.key)
        if isinstance(value, str):
            value = value.strip()
        if f.kind == MULTI:
            value = [v.strip() for v in (value or []) if isinstance(v, str) and v.strip()]
            value = list(dict.fromkeys(value))
        empty = value in (None, "", []) or (f.kind == YESNO and value not in (True, False))
        if empty:
            if not partial and (f.required or (form and f.form_required)):
                problems.append(f"{f.label} is required.")
            elif partial and f.kind in (TEXT, LONGTEXT) and not f.required:
                out[f.key] = ""            # cleared on purpose
            elif partial and f.required:
                problems.append(f"{f.label} cannot be empty.")
            continue
        if f.kind in (TEXT, LONGTEXT) and f.max_length and len(value) > f.max_length:
            problems.append(f"{f.label}: at most {f.max_length} characters.")
        if f.kind in (CHOICE, MULTI) and f.choices_from:
            allowed = set(choices.get(f.choices_from) or [])
            bad = [v for v in (value if f.kind == MULTI else [value]) if v not in allowed]
            if bad:
                problems.append(f"{f.label}: not an option — {', '.join(bad)}.")
        if f.kind == DATE:
            try:
                when = date.fromisoformat(str(value)[:10])
            except ValueError:
                problems.append(f"{f.label}: a date as YYYY-MM-DD.")
                continue
            if when > date.today():
                problems.append(f"{f.label} cannot be in the future.")
            value = when.isoformat()
        if f.key == "title" and (set(value) & BAD_NAME_CHARS or value.strip(" .") != value):
            problems.append('Title cannot contain " * : < > ? \\ | # % or start/end with a '
                            "dot or space.")
        out[f.key] = value
    if problems:
        raise UploadInvalid(" ".join(problems))
    return out


#: Which subtypes a video type takes (A15, from Seb via Liwei, 2026-10-27).
#: The form offers only these; a type with none (Other) hides the subtype and
#: stores N/A, as the library's older "Other" videos already say.
VIDEO_SUBTYPES: dict[str, list[str]] = {
    "Technical Overview": ["Customer", "Feature", "Solution", "Product"],
    "Technical Teaser": ["Product", "Social"],
    "Technical Walkthrough": ["Customer", "Solution"],
    "Experience Asset": ["Attract Loop", "Presenter Support", "XDP Clip"],
    "Other": [],
}
NO_SUBTYPE = "N/A"
#: Kept on the videos that have them, never offered again (Liwei, 2026-10-27):
#: Release (3 videos) as a subtype; Presenter Support as a type.
RETIRED_SUBTYPES = {"Release"}
RETIRED_VIDEO_TYPES = {"Presenter Support"}
#: A customer video names its customer: these types, this subtype.
CUSTOMER_SUBTYPE = "Customer"
CUSTOMER_TYPES = {"Technical Overview", "Technical Walkthrough"}


def video_rules(values: dict, before: dict | None = None) -> tuple[dict, list[str]]:
    """A video's type, subtype and named customer made consistent (A15):
    (values to store, problems). `before`: the video as it is, for an edit --
    a retired subtype it already has may stay. A customer video without its
    customer is a problem; any other video's named customer is dropped
    (cleared, when it had one)."""
    values = dict(values)
    vtype = values.get("video_type")
    if not vtype:
        return values, []
    before = before or {}
    problems = []
    allowed = VIDEO_SUBTYPES.get(vtype)
    sub = values.get("video_subtype")
    if allowed is None:
        if not (vtype == before.get("video_type")):
            problems.append(f"Video type: choose one of {', '.join(VIDEO_SUBTYPES)}.")
    elif not allowed:
        values["video_subtype"] = NO_SUBTYPE
        sub = NO_SUBTYPE
    elif not sub or sub == NO_SUBTYPE:
        problems.append(f"Video subtype is required for {vtype}: {', '.join(allowed)}.")
    elif sub not in allowed and not (sub in RETIRED_SUBTYPES and sub == before.get("video_subtype")
                                     and vtype == before.get("video_type")):
        problems.append(f"Video subtype: {sub} is not one of {vtype}'s ({', '.join(allowed)}).")
    if sub == CUSTOMER_SUBTYPE and vtype in CUSTOMER_TYPES:
        if not (values.get("named_customer") or "").strip():
            problems.append("Named customer is required for a customer video.")
    elif values.get("named_customer") or before.get("named_customer"):
        values["named_customer"] = "" if before.get("named_customer") else None
        if values["named_customer"] is None:
            values.pop("named_customer")
    return values, problems


PREVIEW_COLUMN = "PreviewVideo"
#: Who submitted a demo made through the Hub (2026-10-21): a single line of
#: text on the demo's folder -- an email address, since Graph cannot write a
#: Person column. Written only where the library has it; read by the syncs
#: as the demo's creator.
SUBMITTED_COLUMN = "submitted_by"     # as Liwei created it in both libraries
#: Who to ask about a demo (A4, 2026-10-26): a single line of text holding an
#: email address, in both libraries. The uploader, on upload.
OWNER_COLUMN = "DemoOwner"
#: A picture chosen for the demo's tile (B5, 2026-10-26): a Yes/No column on
#: files, ticked on the one image the demo's card shows.
THUMBNAIL_COLUMN = "HubThumbnail"


def preview_of(files: list[dict], chosen: str | None) -> str | None:
    """The video ticked PreviewVideo (Liwei, 2026-10-15): the only video, or,
    with two or more, the one the person chose -- which is then required."""
    videos = [f["path"] for f in files if f["path"].rsplit(".", 1)[-1].lower() in VIDEO_EXT]
    if len(videos) == 1:
        return videos[0]
    if len(videos) > 1:
        chosen = (chosen or "").replace("\\", "/").strip("/")
        if chosen not in videos:
            raise UploadInvalid("There are several videos: choose the one to preview the "
                                "demo with.")
        return chosen
    return None


def clean_files(spec: TargetSpec, files: list) -> list[dict]:
    """The files to upload, as paths inside the new folder (sub-folders kept)."""
    if not files:
        raise UploadInvalid("Add at least one file.")
    out, seen, problems = [], set(), []
    for f in files:
        path = str((f or {}).get("path") or "").replace("\\", "/").strip("/")
        size = (f or {}).get("size")
        parts = [p for p in path.split("/") if p]
        if not parts or any(p in (".", "..") or set(p) & BAD_NAME_CHARS
                            or p != p.strip(" .") for p in parts):
            problems.append(f"Unusable file name: {path or '(empty)'}.")
            continue
        if not isinstance(size, int) or size <= 0:
            problems.append(f"{path}: empty or unreadable file.")
            continue
        key = "/".join(parts).lower()
        if key in seen:
            problems.append(f"{path} appears twice.")
            continue
        seen.add(key)
        out.append({"path": "/".join(parts), "size": size})
    if spec.single_video:
        videos = [f for f in out if f["path"].rsplit(".", 1)[-1].lower() in VIDEO_EXT]
        if len(out) != 1 or len(videos) != 1:
            problems.append("A video upload is exactly one video file "
                            f"({', '.join(sorted(VIDEO_EXT))}).")
        elif "/" in out[0]["path"]:
            out[0]["path"] = out[0]["path"].rsplit("/", 1)[-1]
    if problems:
        raise UploadInvalid(" ".join(problems))
    return out


def offered(f: FieldSpec, choices: dict[str, list[str]]) -> list[str] | None:
    """A choice field's options as a form offers them: the library's own,
    minus what is retired (A15)."""
    if not f.choices_from:
        return None
    options = choices.get(f.choices_from) or []
    if f.key == "video_type":
        options = [o for o in options if o not in RETIRED_VIDEO_TYPES]
    if f.key == "video_subtype":
        options = [o for o in options if o not in RETIRED_SUBTYPES and o != NO_SUBTYPE]
    return options


def subtype_rules(spec: TargetSpec, choices: dict[str, list[str]]) -> dict | None:
    """What the form needs to make the subtype follow the type (A15): each
    type's subtypes, which of them the library has as options yet (a new
    one is added in SharePoint first), and when a customer is named."""
    if not any(f.key == "video_subtype" for f in spec.fields):
        return None
    return {"subtypes": VIDEO_SUBTYPES,
            "available": [s for s in choices.get("VideoSubtype") or []
                          if s not in RETIRED_SUBTYPES and s != NO_SUBTYPE],
            "customer_subtype": CUSTOMER_SUBTYPE, "customer_types": sorted(CUSTOMER_TYPES),
            "no_subtype": NO_SUBTYPE}


def form(spec: TargetSpec, choices: dict[str, list[str]], skipped: tuple = ()) -> dict:
    """The target as the upload form draws it."""
    today = date.today().isoformat()
    return {
        "video_rules": subtype_rules(spec, choices),
        "key": spec.key, "library": spec.library, "label": spec.label,
        "platform": spec.platform,
        "test_library": spec.key in overrides(),
        "single_video": spec.single_video,
        "kinds": [{"key": k.key, "label": k.label} for k in spec.kinds],
        "fields": [{"key": f.key, "label": f.label, "kind": f.kind,
                    "required": f.required or f.form_required,
                    "help": f.help, "max_length": f.max_length,
                    "default": today if f.default == "today" else f.default,
                    "not_stored": bool(f.column and f.column in skipped),
                    "choices": offered(f, choices)}
                   for f in spec.fields],
    }
