"""Seb's "Gallery Consolidation" workbook -> the migration manifest.

Shape measured on V29 (2026-09-29, plan §13): one worksheet per gallery
section, titled "<section> (<gallery>)"; a header row with `Id`; a totals row
at the bottom; a `Delete?` (or `Archive?`) column. The rich sheets add
Proposed Title, Proposed Tags, Published Date, Video Type and Subtype.
Segment and Customer Facing columns arrive in the final version and are
found by name when present.

Rules, each from a decision recorded in the plan:

* A row ticked Delete?/Archive? is left out; every other row is migrated
  (Liwei, 2026-09-29).
* Proposed Tags mixes products and customers. A tag is a PRODUCT when it
  starts with a PTC product-family name the Hub knows (taxonomy) or is one of
  the few products named otherwise; anything else is a CUSTOMER and goes to
  named_customer. Spelling differences between the sheet and the library's
  choices are mapped here, explicitly -- never by fuzzy matching (HLR-A7).
* Divested products are passed through unchanged, so validation reports them
  rather than the video quietly losing its product and slipping past the
  Hub's divestment rule.
* Titles: the Proposed Title when there is one, else the gallery title.
  Description: the Short one; the Long one goes to long_description.
* Audio: stated only when the title says "Audio" or "No Audio".
* The "XDP VDKs" sheet is skipped: those videos are loaded another way
  (Seb, via Elio, 2026-09-30).
* Current? ("this video shows the current software version") is carried
  into the library as a column of its own; the Hub neither searches nor
  shows it (Liwei, 2026-09-30).

Nothing here touches SharePoint or Brightcove.
"""
from __future__ import annotations

import collections
import csv
import re
from datetime import date, datetime

from backend.services import taxonomy
from backend.services.brightcove_runner import COLUMNS

GALLERIES = ("PTC Gallery", "GXC Gallery")

#: Sheet spelling -> the library's Hub Products option (keys lower-case).
PRODUCT_SPELLING = {"pure variants": "pure::variants", "jetstream": "PTC Jetstream",
                    "orbit": "PTC Orbit",
                    # Unambiguous typos in V29 (2), 2026-09-30.
                    "creo creo simulation live": "Creo Simulation Live",
                    "creo ai": "Creo AI"}
#: Products whose names do not start with a family prefix.
OTHER_PRODUCTS = ("PTC Illustrate", "pure::variants", "PTC Jetstream", "PTC Orbit", "PTC Modeler",
                  "IPE", "Mathcad")
VIDEO_TYPE_SPELLING = {"other/unclear": "Other"}
#: Sheets that are not part of this migration.
SKIP_SHEETS = ("XDP VDKs",)

_SEGMENT = re.compile(r"^segments?$", re.I)
_CUSTOMER_FACING = re.compile(r"^customer[\s_-]*facing\??$", re.I)


def _is_product(tag: str) -> bool:
    low = tag.lower()
    prefixes = [f.lower() for f in taxonomy.known_families()] + [p.lower() for p in OTHER_PRODUCTS]
    return any(low == p or low.startswith(p + " ") or low.startswith(p + "+") for p in prefixes)


def split_tags(value) -> tuple[list[str], list[str]]:
    """Proposed Tags -> (hub products, customers)."""
    products, customers = [], []
    for raw in re.split(r"[;,]", str(value or "")):
        tag = raw.strip().replace("_", " ")
        if not tag:
            continue
        tag = PRODUCT_SPELLING.get(tag.lower(), tag)
        (products if _is_product(tag) else customers).append(tag)
    return list(dict.fromkeys(products)), list(dict.fromkeys(customers))


def _yes_no(value) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    text = str(value or "").strip().lower()
    return {"y": "yes", "yes": "yes", "true": "yes", "1": "yes",
            "n": "no", "no": "no", "false": "no", "0": "no"}.get(text, text)


def _audio(title: str) -> str:
    if re.search(r"\bno[\s-]*audio\b", title, re.I):
        return "no"
    if re.search(r"\baudio\b", title, re.I):
        return "yes"
    return ""


def _date(value) -> str:
    if isinstance(value, (datetime, date)):
        return (value.date() if isinstance(value, datetime) else value).isoformat()
    return str(value or "").strip()[:10]


def read(path: str) -> tuple[list[dict], dict]:
    """The workbook -> manifest rows, plus a report of what was decided how."""
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    rows: list[dict] = []
    report = {"sheets": {}, "customers": collections.Counter(), "no_gallery": [],
              "has_segment_column": False, "has_customer_facing_column": False,
              "skipped_sheets": []}
    for ws in wb.worksheets:
        data = list(ws.iter_rows(values_only=True))
        if not data:
            continue
        head = [str(h).strip() if h is not None else "" for h in data[0]]
        if "Id" not in head:
            continue
        if ws.title.strip() in SKIP_SHEETS:
            report["skipped_sheets"].append(ws.title)
            continue
        col = {h: i for i, h in enumerate(head) if h}
        seg_col = next((h for h in col if _SEGMENT.match(h)), None)
        cf_col = next((h for h in col if _CUSTOMER_FACING.match(h)), None)
        report["has_segment_column"] |= bool(seg_col)
        report["has_customer_facing_column"] |= bool(cf_col)
        suffix = (re.search(r"\(([^)]*)\)\s*$", ws.title) or [None, ""])[1]
        gallery = suffix if suffix in GALLERIES else ""
        kept = dropped = 0
        for r in data[1:]:
            g = lambda h: (r[col[h]] if h and h in col and col[h] < len(r) else None)   # noqa: E731
            bcid = str(g("Id") or "").strip().removesuffix(".0")
            if not re.fullmatch(r"\d{10,19}", bcid):
                continue                                   # blank, or the totals row
            if (g("Delete?") if "Delete?" in col else g("Archive?")) is True:
                dropped += 1
                continue
            kept += 1
            if not gallery and ws.title not in report["no_gallery"]:
                report["no_gallery"].append(ws.title)
            title = str(g("Video Title") or "").strip()
            products, customers = split_tags(g("Proposed Tags"))
            report["customers"].update(customers)
            vtype = str(g("Video Type") or "").strip()
            rows.append({
                "brightcove_id": bcid,
                "title": str(g("Proposed Title") or "").strip() or title,
                "description": str(g("Short Description") or "").strip(),
                "long_description": str(g("Long Description") or "").strip(),
                "segments": ";".join(s.strip() for s in re.split(r"[;,/]", str(g(seg_col) or "")) if s.strip()),
                "hub_products": ";".join(products),
                "products": "",
                "named_customer": ", ".join(customers),
                "customer_facing": _yes_no(g(cf_col)) if cf_col else "",
                "current": _yes_no(g("Current?")) if "Current?" in col else "",
                "contains_audio": _audio(title),
                "original_publish_date": _date(g("Published Date")),
                "video_type": VIDEO_TYPE_SPELLING.get(vtype.lower(), vtype),
                "video_subtype": str(g("Subtype") or "").strip(),
                "gallery": gallery,
                "gallery_section": str(g("Section") or "").strip(),
                "gallery_url": "", "source": "", "filename": "",
                "_sheet": ws.title,
            })
        if kept or dropped:
            report["sheets"][ws.title] = {"kept": kept, "deleted": dropped}
    return rows, report


def write_manifest(rows: list[dict], path: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        out = csv.DictWriter(fh, fieldnames=list(COLUMNS), extrasaction="ignore")
        out.writeheader()
        out.writerows(rows)
