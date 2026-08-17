#!/usr/bin/env python
"""One-off: lift the mockup's hand-written catalogue into data/seed/assets.json.

Three sources inside the mockup, merged by title:
  * 18 gallery cards  — taxonomy lives in data-* attributes
  * 9  home cards     — type chip, meta row, stats line
  * 6  videoData      — the only records carrying a Value Roadmap

Pre-formatted display strings are decomposed here, because an API cannot drive
a UI from prose:
    '214 views · Uploaded Jul 21'  ->  views=214, uploaded_at=2025-07-21
    'Consideration · EN'           ->  funnel_stage, language
    '4:12'                         ->  duration_seconds=252

Deliberately does NOT invent data. The gallery videos with no videoData entry
get value_roadmap=null and the UI shows an honest "not indexed yet" state.
Fabricating value drivers would violate the project's own rule against
invented content.

Requires beautifulsoup4 (dev only — the cards are nested divs, which regex
cannot match reliably).

Run from the repo root:  python scripts/extract_seed.py
"""
from __future__ import annotations

import json
import os
import re
from datetime import date

from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "index.mockup.original.html")
if not os.path.exists(SRC):
    SRC = os.path.join(ROOT, "index.html")
OUT = os.path.join(ROOT, "data", "seed", "assets.json")

#: The mockup's cards carry month/day only. It was built mid-2025.
ASSUMED_YEAR = 2025
MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}

TYPE_MAP = {"video": "video", "ldk": "ldk", "vdk": "vdk", "wiki": "wiki",
            "virtual machine": "vm", "vm": "vm"}
LANG_MAP = {"EN": "en", "DE": "de", "FR": "fr", "JA": "ja", "ZH": "zh", "ES": "es", "IT": "it"}
PRODUCT_MAP = {"windchill": "Windchill", "creo": "Creo",
               "servicemax": "ServiceMax", "codebeamer": "Codebeamer"}
STAGES = {"Awareness", "Consideration", "Decision", "Post-Sale"}


def collapse(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "")).replace("\xa0", " ").strip()


def slugify(text: str) -> str:
    s = collapse(text).lower().replace("&", "and")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:60].rstrip("-")


def norm(title: str) -> str:
    """Merge key — punctuation and case insensitive."""
    return re.sub(r"[^a-z0-9]+", "", collapse(title).lower())


def parse_date(text: str) -> str | None:
    m = re.search(r"\b([A-Z][a-z]{2})\s+(\d{1,2})\b", text)
    if m and m.group(1) in MONTHS:
        return date(ASSUMED_YEAR, MONTHS[m.group(1)], int(m.group(2))).isoformat()
    return None


def parse_int(text: str, keyword: str) -> int | None:
    m = re.search(r"([\d,]+)\s*" + keyword, text, re.I)
    return int(m.group(1).replace(",", "")) if m else None


def parse_duration(text: str) -> int | None:
    m = re.match(r"^\s*(\d+):(\d{2})\s*$", text or "")
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def parse_meta(text: str) -> tuple[str | None, str | None]:
    stage = language = None
    for p in (x.strip() for x in re.split(r"[·|]", collapse(text)) if x.strip()):
        if p in STAGES:
            stage = p
        elif p.upper() in LANG_MAP:
            language = LANG_MAP[p.upper()]
        elif p.lower() == "chinese":
            language = "zh"
    return stage, language


def audio_from_title(title: str) -> bool | None:
    """The library's own naming already states this — 'No Audio' / 'Audio'."""
    t = title.lower()
    if "no audio" in t:
        return False
    if re.search(r"\baudio\b", t):
        return True
    return None


def product_from(node) -> str | None:
    use = node.select_one('use[href^="#logo-"]')
    if not use:
        return None
    name = use["href"].removeprefix("#logo-").removesuffix("-mark")
    return PRODUCT_MAP.get(name)


def blank(slug: str, title: str, atype: str = "video") -> dict:
    return {
        "id": slug, "type": atype, "title": title, "description": None,
        "products": [], "funnel_stage": None, "content_depth": None, "language": "en",
        "segment": None, "industry": None, "value_drivers": [],
        "customer_facing": True, "has_narrated_audio": audio_from_title(title),
        "named_customer": None, "uploaded_at": None, "duration_seconds": None,
        "thumbnail_url": None, "source_item_id": None, "brightcove_id": None,
        "consensus_uuid": None, "web_url": None, "rails": [], "is_editor_pick": False,
        "value_roadmap": None,
        "stats": {"views": 0, "downloads": 0, "launches": 0, "shares": 0},
    }


def main() -> None:
    raw = open(SRC, encoding="utf-8").read()
    soup = BeautifulSoup(raw, "html.parser")

    assets: dict[str, dict] = {}
    by_title: dict[str, str] = {}

    # ---------------------------------------------------------- gallery cards
    gallery = 0
    for card in soup.select(".dvg-card"):
        title_el = card.select_one(".dvg-card__title")
        if not title_el:
            continue
        title = collapse(title_el.get_text())
        slug = slugify(title)

        rail_el = card.find_parent(class_="dvg-rail")
        rail_title = rail_el.select_one(".dvg-rail__title") if rail_el else None
        share = card.select_one(".js-dvg-share")

        product = card.get("data-product")
        driver = card.get("data-driver")

        a = blank(slug, title)
        a.update(
            description=card.get("data-desc") or None,
            products=[product] if product and product != "Cross-Portfolio" else
                     (["Cross-Portfolio"] if product else []),
            funnel_stage=card.get("data-funnel") or None,
            segment=card.get("data-segment") or None,
            industry=card.get("data-industry") or None,
            value_drivers=[driver] if driver else [],
            customer_facing=(card.get("data-cf") or "yes").lower() == "yes",
            thumbnail_url=f"/static/img/thumbs/{slug}.jpg",
            consensus_uuid=(share.get("data-share-uuid") if share else None) or None,
            rails=[collapse(rail_title.get_text())] if rail_title else [],
        )
        assets[slug] = a
        by_title[norm(title)] = slug
        gallery += 1

    # ------------------------------------------------------------- home cards
    home_new = home_merged = 0
    for card in soup.select(".asset-card"):
        title_el = card.select_one(".asset-card__title")
        if not title_el:
            continue
        title = collapse(title_el.get_text())
        k = norm(title)

        chip = card.select_one(".type-chip")
        atype = TYPE_MAP.get(collapse(chip.get_text()).lower(), "video") if chip else "video"

        meta_el = card.select_one(".asset-card__meta")
        stage, language = parse_meta(meta_el.get_text()) if meta_el else (None, None)

        stats_el = card.select_one(".asset-card__stats")
        stats_text = collapse(stats_el.get_text()) if stats_el else ""

        dur_el = card.select_one(".duration-chip")
        share = card.select_one("[data-share-uuid]")
        product = product_from(card)

        stats = {"views": parse_int(stats_text, "views") or 0,
                 "downloads": parse_int(stats_text, "downloads") or 0,
                 "launches": parse_int(stats_text, "launches") or 0,
                 "shares": parse_int(stats_text, "shares") or 0}

        target = assets.get(by_title.get(k, ""))
        if target is None:
            slug = slugify(title)
            target = assets[slug] = blank(slug, title, atype)
            by_title[k] = slug
            home_new += 1
        else:
            home_merged += 1

        target["type"] = atype
        target["funnel_stage"] = target["funnel_stage"] or stage
        target["language"] = language or target["language"]
        target["uploaded_at"] = target["uploaded_at"] or parse_date(stats_text)
        target["duration_seconds"] = target["duration_seconds"] or parse_duration(
            collapse(dur_el.get_text()) if dur_el else "")
        target["consensus_uuid"] = target["consensus_uuid"] or (
            share.get("data-share-uuid") if share else None) or None
        if any(stats.values()):
            target["stats"] = stats
        if product and product not in target["products"]:
            target["products"].append(product)

    # --------------------------------------------------- videoData / roadmaps
    roadmaps = 0
    block = re.search(r"var videoData = \{(.*?)\n\};", raw, re.S)
    if block:
        for entry in re.finditer(r"'([a-z0-9-]+)':\s*\{(.*?)\n  \}(?:,|\s*$)",
                                 block.group(1), re.S):
            payload = entry.group(2)

            def field(name):
                g = re.search(rf"\b{name}:\s*'((?:[^'\\]|\\.)*)'", payload, re.S)
                return g.group(1).replace("\\'", "'") if g else None

            title = collapse(field("title") or "")
            if not title:
                continue
            k = norm(title)
            slug = by_title.get(k)
            if slug is None:
                slug = slugify(title) or entry.group(1)
                assets[slug] = blank(slug, title)
                by_title[k] = slug
            a = assets[slug]

            stage, language = parse_meta(field("metaText") or "")
            stats_text = field("stats") or ""
            a["funnel_stage"] = a["funnel_stage"] or stage
            a["language"] = language or a["language"]
            a["duration_seconds"] = a["duration_seconds"] or parse_duration(field("duration") or "")
            a["consensus_uuid"] = a["consensus_uuid"] or (field("uuid") or None)
            a["description"] = a["description"] or field("desc")
            a["uploaded_at"] = a["uploaded_at"] or parse_date(stats_text)
            for name in ("views", "shares", "downloads", "launches"):
                if (n := parse_int(stats_text, name)) is not None:
                    a["stats"][name] = n
            if (pretty := PRODUCT_MAP.get(field("logo") or "")) and pretty not in a["products"]:
                a["products"].append(pretty)

            drivers = re.search(r"drivers:\s*\[(.*?)\]", payload, re.S)
            caps = [{
                "phase": c.group(1),
                "title": c.group(2).replace("\\'", "'"),
                "chips": re.findall(r"'([^']+)'", c.group(3)),
                "narration": c.group(4).replace("\\'", "'"),
            } for c in re.finditer(
                r"\{\s*phase:\s*'([^']+)',\s*title:\s*'((?:[^'\\]|\\.)*)',\s*"
                r"chips:\s*\[(.*?)\],\s*narration:\s*'((?:[^'\\]|\\.)*)'\s*\}", payload, re.S)]

            a["value_roadmap"] = {
                "description": field("desc"),
                "value_drivers": re.findall(r"'([^']+)'", drivers.group(1)) if drivers else [],
                "capabilities": caps,
                "indexed_at": None,
                "model": None,
            }
            roadmaps += 1

    # ------------------------------------------------------------ editor picks
    # Some featured cards reference assets that appear nowhere else — e.g. "The
    # Intelligent Product Lifecycle Presentation", which is distinct from the
    # "… — Executive Overview" video. They are real catalogue items, so create
    # them rather than silently dropping the pick.
    picks = picks_created = 0
    for card in soup.select(".featured-card"):
        t = card.select_one(".featured-card__title")
        if not t:
            continue
        title = collapse(t.get_text())
        slug = by_title.get(norm(title))
        if slug is None:
            slug = slugify(title)
            a = assets[slug] = blank(slug, title)
            by_title[norm(title)] = slug
            body = card.select_one(".featured-card__body")
            foot = collapse(card.select_one(".featured-card__foot").get_text()) \
                if card.select_one(".featured-card__foot") else ""
            _, language = parse_meta(foot)
            a["description"] = collapse(body.get_text()) if body else None
            a["language"] = language or "en"
            a["stats"]["views"] = parse_int(foot, "views") or 0
            a["stats"]["downloads"] = parse_int(foot, "downloads") or 0
            if "all products" in foot.lower():
                a["products"] = ["Cross-Portfolio"]
            elif (p := product_from(card)):
                a["products"] = [p]
            picks_created += 1
        assets[slug]["is_editor_pick"] = True
        picks += 1

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    records = sorted(assets.values(), key=lambda a: a["title"].lower())
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(records, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    # ----------------------------------------------------------------- report
    by_type: dict[str, int] = {}
    for a in records:
        by_type[a["type"]] = by_type.get(a["type"], 0) + 1

    print(f"source        {os.path.basename(SRC)}")
    print(f"gallery cards {gallery}")
    print(f"home cards    {home_new} new, {home_merged} merged")
    print(f"roadmaps      {roadmaps}")
    print(f"editor picks  {picks} ({picks_created} referenced nothing else, created)")
    print(f"\nwrote {len(records)} assets -> {os.path.relpath(OUT, ROOT)}")
    print(f"  by type: {by_type}")
    print(f"  no Value Roadmap : {sum(1 for a in records if not a['value_roadmap'])} (null on purpose)")
    print(f"  no Consensus UUID: {sum(1 for a in records if not a['consensus_uuid'])} (cannot share externally)")
    print(f"  no thumbnail     : {sum(1 for a in records if not a['thumbnail_url'])}")
    print("\n  R=roadmap  U=uuid  P=pick  T=thumb")
    for a in records:
        flags = "".join(["R" if a["value_roadmap"] else "·",
                         "U" if a["consensus_uuid"] else "·",
                         "P" if a["is_editor_pick"] else "·",
                         "T" if a["thumbnail_url"] else "·"])
        print(f"  [{a['type']:>5}] {flags}  {a['title'][:60]}")


if __name__ == "__main__":
    main()
