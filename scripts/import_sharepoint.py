#!/usr/bin/env python
"""Turn a SharePoint export into data/seed/assets.json.

Replaces the 28 hand-extracted mockup rows with the real Demo Catalog.

The structural rule, established by measuring the site rather than guessing:

    An asset is a TOP-LEVEL folder in Demo Catalog that carries a Demo Type.
    Everything beneath it is a resource.

All 452 such folders sit at depth 0, so resolving a file's owner is just its
first path segment — no heuristics, no prefix search.

Deliberately NOT imported: the Virtual Machine Catalog. Its 49 VMs are all 2024
or older and were judged out of scope. Its field mapping is recorded in
docs/ARCHITECTURE.md so the analysis is not lost, and this module's shape is the
seam to add it behind — a second source_system, nothing else changes.

Usage, from the repo root:
    python scripts/import_sharepoint.py            # writes data/seed/assets.json
    python scripts/import_sharepoint.py --dry-run  # report only
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = r"C:\Users\liwchen\OneDrive - PTC\Desktop\Sharepoint Raw Data.xlsx"
CATALOG = r"C:\Work\TDD Hub\SharepoinDemoCatalog.xlsx"
OUT = os.path.join(ROOT, "data", "seed", "assets.json")
LIBRARY = "sites/EXT-TDD/Demo Catalog"

# ------------------------------------------------------------------ mappings
TYPE_MAP = {"Live Demo Kit": "ldk", "Virtual Demo Kit": "vdk"}

LANG_MAP = {
    "English": "en",
    "Chinese (People\u2019s Republic of China)": "zh",
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

#: Creo saves versioned files as `part.prt.1`, `asm.asm.2`. ~3,400 of them.
CAD_VERSIONED = re.compile(r"\.(prt|asm|drw|neu|sec|frm|xpr)\.\d+$", re.I)

CF_RE = re.compile(r"(customer[ _-]?facing|[_\- ]CF[_\- .]|[_\- ]CF$)", re.I)
INT_RE = re.compile(r"(internal[ _-]?only|[_\- ]training[_\- .]|[_\- ]training$)", re.I)

#: Only applied when the name states it outright. 137/452 names do.
DEPTH_RULES = [
    (re.compile(r"quick overview", re.I), "Overview"),
    (re.compile(r"\boverview\b", re.I), "Overview"),
    (re.compile(r"what.s new", re.I), "Overview"),
    (re.compile(r"\bwalkthrough\b", re.I), "Walkthrough"),
    (re.compile(r"\bintroduction\b", re.I), "Teaser"),
]


def clean_text(value) -> str | None:
    if value in (None, ""):
        return None
    # Three product names use a FULL-WIDTH ampersand (U+FF06), which breaks
    # exact matching and renders wrong in the UI.
    text = str(value).replace("\uff06", "&").replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text).strip()
    return text or None


def parse_lookup(value) -> list[str]:
    """SharePoint serialises lookup columns as `30;#Creo Parametric`."""
    if not value:
        return []
    found = re.findall(r"\d+;#([^;]+)", str(value)) or [str(value)]
    out: list[str] = []
    for item in found:
        cleaned = clean_text(item)
        if cleaned and cleaned not in out:
            out.append(cleaned)
    return out


def parse_segment(value) -> tuple[str | None, list[str]]:
    """Segment mixes two delimiters in one column: `IoT,PLM` and `CAD;#SLM`."""
    if not value:
        return None, []
    parts = [p.strip() for p in re.split(r";#|,", str(value)) if p.strip()]
    return (parts[0] if parts else None), parts


def slugify(text: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (clean_text(text) or "").lower())
    base = base.strip("-")[:70].rstrip("-") or "asset"
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    taken.add(slug)
    return slug


def display_title(name: str) -> str:
    """Use the SharePoint name as-is, only normalising characters.

    An earlier version stripped the `v.N` suffix and a trailing LDK/VDK on the
    grounds that they were noise. Measured against the real catalogue that was
    wrong: it collapsed 126 assets (28%) onto 60 duplicate titles — five
    distinct kits all became "Navigate Overview". The version and the format
    are what distinguish them, and these are the names the team already
    searches by.
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


def load_sheet(path: str):
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=True)
    sheet = workbook[workbook.sheetnames[0]]
    rows = list(sheet.iter_rows(values_only=True))
    header = [str(h) if h is not None else "" for h in rows[0]]
    return header, [r for r in rows[1:] if any(r)]


def build_assets(rows, col, descriptions) -> dict[str, dict]:
    assets: dict[str, dict] = {}
    taken: set[str] = set()

    def get(row, name):
        return row[col[name]] if name in col else None

    for row in rows:
        if str(get(row, "Item Type")) != "Folder":
            continue
        if str(get(row, "Path")) != LIBRARY or not get(row, "Demo Type"):
            continue

        name = clean_text(get(row, "Name"))
        demo_type = clean_text(get(row, "Demo Type"))
        if not name or demo_type not in TYPE_MAP:
            continue

        segment, all_segments = parse_segment(get(row, "Segment"))
        modified = get(row, "Modified")
        depth = next((d for rx, d in DEPTH_RULES if rx.search(name)), None)

        assets[name] = {
            "id": slugify(name, taken),
            "type": TYPE_MAP[demo_type],
            "title": display_title(name),
            "description": descriptions.get(name) or clean_text(get(row, "Description")),
            "products": parse_lookup(get(row, "Product")),
            "funnel_stage": None,
            "content_depth": depth,
            "language": LANG_MAP.get(str(get(row, "Language") or "").strip(), "en"),
            "segment": segment,
            "industry": None,
            "value_drivers": [],
            "customer_facing": True,
            "has_narrated_audio": None,
            "named_customer": None,
            "uploaded_at": str(modified)[:10] if modified else None,
            "duration_seconds": None,
            "thumbnail_url": None,
            "source_item_id": f"{LIBRARY}/{name}",
            "brightcove_id": None,
            "consensus_uuid": None,
            "web_url": None,
            "rails": all_segments[1:],       # extra segments become rail membership
            "is_editor_pick": False,
            "value_roadmap": None,
            "stats": {"views": 0, "downloads": 0, "launches": 0, "shares": 0},
            "resources": [],
            "main_video": None,
            "resource_count": 0,
            "video_count": 0,
            "resource_counts": {},
        }
    return assets


def attach_resources(rows, col, assets) -> int:
    """Attribute every file to its top-level folder. Returns the orphan count."""
    def get(row, name):
        return row[col[name]] if name in col else None

    orphans = 0
    for row in rows:
        if str(get(row, "Item Type")) == "Folder":
            continue
        path = str(get(row, "Path") or "")
        if not path.startswith(LIBRARY):
            continue
        rest = path[len(LIBRARY):].strip("/")
        if not rest:
            continue
        folder, _, subfolder = rest.partition("/")
        owner = assets.get(folder)
        if owner is None:
            orphans += 1          # lives under a folder carrying no Demo Type
            continue
        filename = clean_text(get(row, "Name")) or ""
        kind, ext = classify(filename)
        owner["resources"].append({
            "name": filename,
            "kind": kind,
            "audience": audience_of(filename),
            "subfolder": subfolder or None,
            "extension": ext,
            "has_audio": audio_of(filename),
        })
    return orphans


#: Kinds a person would actually pick from a list. CAD is excluded because 42%
#: of the catalogue is Creo version files (`part.prt.1`, `asm.asm.2`) — listing
#: them individually is noise, and it tripled the seed file.
BROWSABLE = {"video", "document", "dataset", "image"}


def derive_video_facts(assets) -> None:
    for asset in assets.values():
        all_resources = asset["resources"]
        asset["resource_counts"] = dict(
            collections.Counter(r["kind"] for r in all_resources))
        asset["resources"] = [r for r in all_resources if r["kind"] in BROWSABLE]

        videos = [r for r in asset["resources"] if r["kind"] == "video"]
        asset["resource_count"] = len(all_resources)
        asset["video_count"] = len(videos)
        asset["main_video"] = pick_main_video(videos)

        # Only ever derived from what the filenames actually state.
        if videos:
            if any(v["audience"] == "customer_facing" for v in videos):
                asset["customer_facing"] = True
            elif all(v["audience"] == "internal" for v in videos):
                asset["customer_facing"] = False
        stated = [v["has_audio"] for v in videos if v["has_audio"] is not None]
        if stated:
            asset["has_narrated_audio"] = any(stated)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--raw", default=RAW)
    parser.add_argument("--catalog", default=CATALOG)
    args = parser.parse_args()

    for path in (args.raw, args.catalog):
        if not os.path.exists(path):
            print(f"missing export: {path}")
            return 1

    header, rows = load_sheet(args.raw)
    col = {h: i for i, h in enumerate(header)}

    # The folder-level export carries a better Description: `Description2`
    # preserves newlines and has the highest coverage (93% vs 81%).
    cat_header, cat_rows = load_sheet(args.catalog)
    cat_col = {h: i for i, h in enumerate(cat_header)}
    desc_field = "Description2" if "Description2" in cat_col else "Description"
    descriptions = {}
    for row in cat_rows:
        name = clean_text(row[cat_col["Name"]])
        if name:
            descriptions[name] = clean_text(row[cat_col[desc_field]])

    assets = build_assets(rows, col, descriptions)
    orphans = attach_resources(rows, col, assets)
    derive_video_facts(assets)

    records = sorted(assets.values(), key=lambda a: a["title"].lower())

    by_type = collections.Counter(a["type"] for a in records)
    with_video = sum(1 for a in records if a["video_count"])
    with_main = sum(1 for a in records if a["main_video"])
    total_res = sum(a["resource_count"] for a in records)

    print(f"assets              {len(records)}   {dict(by_type)}")
    print(f"resources           {total_res}")
    print(f"  videos            {sum(a['video_count'] for a in records)}")
    print(f"  orphan files      {orphans}  (under folders carrying no Demo Type)")
    print()
    print(f"with >=1 video      {with_video}/{len(records)}")
    print(f"main video resolved {with_main}/{with_video}"
          f"  ({100 * with_main // max(1, with_video)}%) — the rest need a human")
    print(f"customer_facing     {sum(1 for a in records if a['customer_facing'])}")
    print(f"internal only       {sum(1 for a in records if not a['customer_facing'])}")
    print(f"audio stated        {sum(1 for a in records if a['has_narrated_audio'] is not None)}")
    print(f"content_depth set   {sum(1 for a in records if a['content_depth'])}"
          f"  (only where the name states it)")
    print(f"consensus_uuid      0  — absent from SharePoint entirely")
    print()
    for field in ("segment", "language", "products", "description"):
        print(f"  {field:<14} {sum(1 for a in records if a[field])}/{len(records)}")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(records, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(f"\nwrote {len(records)} assets -> {os.path.relpath(OUT, ROOT)}"
          f"  ({os.path.getsize(OUT) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
