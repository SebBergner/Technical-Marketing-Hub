"""Field logic shared by the xlsx importer and the live Graph sync.

Both paths must produce byte-identical assets from the same SharePoint content.
They started as one script; keeping the mapping here is what stops the seed and
the live catalogue drifting apart as the rules evolve.

Every rule below was derived by measuring the real Demo Catalog (452 assets,
9,166 items) rather than assumed — see docs/ARCHITECTURE.md section 2a.
"""
from __future__ import annotations

import re
from datetime import date, datetime

#: Demo Type -> our AssetType. The catalogue contains only these two.
TYPE_MAP = {"Live Demo Kit": "ldk", "Virtual Demo Kit": "vdk"}

LANG_MAP = {
    "English": "en",
    "Chinese (People’s Republic of China)": "zh",
    "Chinese (People's Republic of China)": "zh",
    "German (Germany)": "de",
    "French (France)": "fr",
    "Spanish (Spain)": "es",
    "Italian (Italy)": "it",
    "Japanese (Japan)": "ja",
    "Korean (Korea)": "ko",
}

VIDEO_EXT = {"mp4", "mov", "wmv", "avi", "m4v", "mkv", "webm"}
DOC_EXT = {"docx", "doc", "pptx", "ppt", "pdf", "xlsx", "xls", "txt", "aspx"}
DATA_EXT = {"zip", "rar", "7z", "gz", "tar"}
IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "bmp", "svg"}
CAD_EXT = {"creo", "xpr", "asm", "prt", "drw", "neu", "sec", "mcdx", "sdpc", "frm"}

#: Creo saves versioned files as `part.prt.1`, `asm.asm.2`. ~3,400 in the
#: catalogue, 42% of all files — a plain extension lookup misclassifies them.
CAD_VERSIONED = re.compile(r"\.(prt|asm|drw|neu|sec|frm|xpr)\.\d+$", re.I)

#: PTC's own naming carries the audience. 54% of the 1,204 catalogue videos are
#: marked one way or the other, and it is a property of the FILE, not the asset:
#: one kit routinely ships both a customer cut and a training cut.
CF_RE = re.compile(r"(customer[ _-]?facing|[_\- ]CF[_\- .]|[_\- ]CF$)", re.I)
INT_RE = re.compile(r"(internal[ _-]?only|[_\- ]training[_\- .]|[_\- ]training$)", re.I)

#: Applied only when the name states it outright. 137/452 do.
DEPTH_RULES = [
    (re.compile(r"quick overview", re.I), "Overview"),
    (re.compile(r"\boverview\b", re.I), "Overview"),
    (re.compile(r"what.s new", re.I), "Overview"),
    (re.compile(r"\bwalkthrough\b", re.I), "Walkthrough"),
    (re.compile(r"\bintroduction\b", re.I), "Teaser"),
]

#: Kinds a person would pick from a list. CAD is counted but never listed.
BROWSABLE = {"video", "document", "dataset", "image"}


def clean_text(value) -> str | None:
    if value in (None, ""):
        return None
    # Three product names use a FULL-WIDTH ampersand (U+FF06), which breaks
    # exact matching and renders wrong in the UI.
    text = str(value).replace("＆", "&").replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", text).strip() or None


def parse_lookup(value) -> list[str]:
    """SharePoint serialises lookup columns as `30;#Creo Parametric`.

    Graph returns the same column as a list of dicts, so both shapes are
    accepted here rather than in two places.
    """
    if not value:
        return []
    if isinstance(value, list):
        raw = [v.get("LookupValue", v) if isinstance(v, dict) else v for v in value]
    else:
        raw = re.findall(r"\d+;#([^;]+)", str(value)) or [str(value)]
    out: list[str] = []
    for item in raw:
        cleaned = clean_text(item)
        if cleaned and cleaned not in out:
            out.append(cleaned)
    return out


def parse_segment(value) -> tuple[str | None, list[str]]:
    """Segment mixes two delimiters in one column: `IoT,PLM` and `CAD;#SLM`."""
    if not value:
        return None, []
    if isinstance(value, list):
        parts = [clean_text(v) for v in value]
    else:
        parts = [p.strip() for p in re.split(r";#|,", str(value))]
    parts = [p for p in parts if p]
    return (parts[0] if parts else None), parts


def parse_language(value) -> str:
    return LANG_MAP.get(str(value or "").strip(), "en")


def content_depth(name: str) -> str | None:
    return next((d for rx, d in DEPTH_RULES if rx.search(name or "")), None)


def slugify(text: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (clean_text(text) or "").lower())
    base = base.strip("-")[:70].rstrip("-") or "asset"
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    taken.add(slug)
    return slug


def display_title(name: str) -> str:
    """The SharePoint name as-is, only normalising characters.

    An earlier version stripped the `v.N` suffix and a trailing LDK/VDK as
    noise. Measured against the real catalogue that collapsed 126 assets (28%)
    onto 60 duplicate titles — five distinct kits all became "Navigate
    Overview". The version and the format are what distinguish them, and they
    are what the team searches by.
    """
    return clean_text(name) or ""


def classify(filename: str) -> tuple[str, str | None]:
    if match := CAD_VERSIONED.search(filename):
        return "cad", match.group(1).lower()
    match = re.search(r"\.([A-Za-z0-9]{1,6})$", filename)
    ext = match.group(1).lower() if match else None
    if ext is None:
        return "other", None
    if ext in VIDEO_EXT:
        return "video", ext
    if ext in DOC_EXT:
        return "document", ext
    if ext in DATA_EXT:
        return "dataset", ext
    if ext in IMAGE_EXT:
        return "image", ext
    if ext in CAD_EXT or ext.isdigit():
        return "cad", ext
    return "other", ext


def audience_of(filename: str) -> str:
    stem = re.sub(r"\.[A-Za-z0-9]{1,6}$", "", filename)
    if CF_RE.search(stem):
        return "customer_facing"
    if INT_RE.search(stem):
        return "internal"
    return "unknown"


def audio_of(filename: str) -> bool | None:
    low = filename.lower()
    if "no audio" in low:
        return False
    if "with audio" in low:
        return True
    return None


def pick_main_video(videos: list[dict]) -> str | None:
    """One video, or exactly one Customer Facing. Otherwise leave it to a human.

    Covers 281 of the 396 assets that have any video. Guessing at the other 122
    is how false confidence gets shipped.
    """
    if len(videos) == 1:
        return videos[0]["name"]
    customer_facing = [v for v in videos if v["audience"] == "customer_facing"]
    return customer_facing[0]["name"] if len(customer_facing) == 1 else None


def build_resource(filename: str, subfolder: str | None = None) -> dict:
    kind, ext = classify(filename)
    return {
        "name": filename,
        "kind": kind,
        "audience": audience_of(filename),
        "subfolder": subfolder or None,
        "extension": ext,
        "has_audio": audio_of(filename),
    }


def derive_video_facts(asset: dict) -> None:
    """Fill resource counts, main_video, customer_facing and audio in place.

    Split resources into 'counted' and 'listed': CAD is 42% of the catalogue
    and nobody picks a `part.prt.1` from a list, so it is counted only.
    Every derived value comes from what the filenames actually state.
    """
    import collections

    all_resources = asset.get("resources") or []
    asset["resource_counts"] = dict(collections.Counter(r["kind"] for r in all_resources))
    asset["resources"] = [r for r in all_resources if r["kind"] in BROWSABLE]

    videos = [r for r in asset["resources"] if r["kind"] == "video"]
    asset["resource_count"] = len(all_resources)
    asset["video_count"] = len(videos)
    asset["main_video"] = pick_main_video(videos)

    if videos:
        if any(v["audience"] == "customer_facing" for v in videos):
            asset["customer_facing"] = True
        elif all(v["audience"] == "internal" for v in videos):
            asset["customer_facing"] = False

    stated = [v["has_audio"] for v in videos if v["has_audio"] is not None]
    if stated:
        asset["has_narrated_audio"] = any(stated)


def blank_asset(asset_id: str, title: str, asset_type: str = "ldk") -> dict:
    return {
        "id": asset_id, "type": asset_type, "title": display_title(title),
        "description": None, "products": [], "funnel_stage": None,
        "content_depth": None, "language": "en", "segment": None, "industry": None,
        "value_drivers": [], "customer_facing": True, "has_narrated_audio": None,
        "named_customer": None, "uploaded_at": None, "duration_seconds": None,
        "thumbnail_url": None, "source_item_id": None, "brightcove_id": None,
        "consensus_uuid": None, "web_url": None, "rails": [], "is_editor_pick": False,
        "value_roadmap": None,
        "stats": {"views": 0, "downloads": 0, "launches": 0, "shares": 0},
        "resources": [], "main_video": None, "resource_count": 0, "video_count": 0,
        "resource_counts": {},
    }


def as_date(value) -> str | None:
    """Normalise whatever SharePoint or Graph hands back to YYYY-MM-DD."""
    if not value:
        return None
    if isinstance(value, (date, datetime)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    text = str(value)
    return text[:10] if len(text) >= 10 else None
