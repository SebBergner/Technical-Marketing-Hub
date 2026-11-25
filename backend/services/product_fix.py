"""Content health -> Fix products: many demos' Product (and Segment) at once,
with a suggestion for each (Liwei, 2026-11-25).

Why. On 2026-11-25 production listed 161 demos with no product that a PTC
person can see -- 87 in SharePoint (81 of them Demo Video videos: customer
stories and attract loops) and 74 from Consensus -- besides the GXC videos,
whose IoT/AR rows keep Product empty on purpose (2026-11-02) and are not
offered here. A demo with no product is under no product in the navigation
and never a related demo by product; one demo at a time through Edit is slow.

Suggestions use only what the demo already says. A product name in the title
is a strong hint and comes ticked; one only in the description is a weaker
hint, shown but not ticked. Measured on the 161: the title names a product
for 56, title or description for 101 (63%). Nothing is written until a person
confirms it, and every save goes to the Admin log like an ordinary edit.

A segment is suggested from the product, by what the catalogue already does:
the segment that at least SEGMENT_SHARE of the demos of that product family
carry (Creo -> CAD, Codebeamer -> ALM...), never a fixed table of our own.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from functools import lru_cache

from backend.services import taxonomy

#: A family's segment is suggested when this share of its demos carry it...
SEGMENT_SHARE = 0.8
#: ...out of at least this many demos.
SEGMENT_MIN_DEMOS = 5
#: At most this many products are suggested from a description.
MAX_FROM_DESCRIPTION = 3


#: Words that join two names rather than belong to one.
_JOINING = r"(?:and|or|with|to|for|from|in|on|of|the|a|an|vs|via|into|plus|&)"


@lru_cache(maxsize=512)
def _pattern(product: str) -> re.Pattern:
    return re.compile(r"(?<![\w])" + re.escape(product) + r"(?![\w])", re.IGNORECASE)


def _found(text: str, choices: list[str]) -> list[str]:
    """The choices named in the text, the most specific of each family:
    "Creo Parametric" and not also "Creo"; one spelling of a family
    ("PTC Jetstream", not also "Jetstream")."""
    hits = [p for p in sorted(choices, key=len, reverse=True) if _pattern(p).search(text)]
    hits = [h for h in hits
            if not any(o != h and o.lower().startswith(h.lower() + " ") for o in hits)]
    # A word right after another product's name, one word between at most,
    # belongs to that name: "Creo Option Modeler" is a Creo module, not PTC
    # Modeler (2026-11-25, on production's titles).
    # "Windchill and Creo" names two products: a joining word ends a name.
    hits = [h for h in hits
            if not any(o != h and taxonomy.family_of(o) != taxonomy.family_of(h)
                       and re.search(r"(?<![\w])" + re.escape(o) + r"\s+(?:(?!" + _JOINING
                                     + r"\b)[A-Za-z][\w+-]*\s+)?" + re.escape(h) + r"(?![\w])",
                                     text, re.IGNORECASE)
                       for o in hits)]
    out, families = [], set()
    for h in hits:
        fam = taxonomy.family_of(h)
        same = fam in families and not any(o.lower().startswith(h.lower() + " ") for o in out)
        if same and not h.lower().startswith(fam.lower() + " "):
            continue                      # "Jetstream" after "PTC Jetstream"
        families.add(fam)
        out.append(h)
    return out


def suggestion(record: dict, choices: list[str]) -> dict | None:
    """{"products": [...], "from": "title" | "description"}, or None."""
    choices = [c for c in choices if taxonomy.is_product(c) and not taxonomy.is_excluded([c])]
    if not choices:
        return None
    title = _found(record.get("title") or "", choices)
    if title:
        return {"products": title, "from": "title"}
    described = _found(record.get("description") or "", choices)
    if described:
        return {"products": described[:MAX_FROM_DESCRIPTION], "from": "description"}
    return None


def family_segments(rows: list[dict]) -> dict[str, str]:
    """{product family: the segment its demos carry}, where they agree."""
    seen: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        segment = taxonomy.normalise_segment(r.get("segment"))
        if not segment:
            continue
        for fam in taxonomy.families_of(r.get("products")):
            seen[fam][segment] += 1
    out = {}
    for fam, counts in seen.items():
        total = sum(counts.values())
        segment, n = counts.most_common(1)[0]
        if total >= SEGMENT_MIN_DEMOS and n / total >= SEGMENT_SHARE:
            out[fam] = segment
    return out


def segment_for(products: list[str], by_family: dict[str, str]) -> str | None:
    """The one segment the products' families agree on, or None."""
    found = {by_family.get(f) for f in taxonomy.families_of(products)} - {None}
    return found.pop() if len(found) == 1 else None


def needs_product(record: dict) -> str | None:
    """Where a demo with no product is fixed: "sharepoint" (written to its
    folder), "consensus" (set on the Hub), or None when it is not offered."""
    if record.get("products"):
        return None
    rid = record.get("id") or ""
    if record.get("source") == "consensus":
        return "consensus" if record.get("consensus_uuid") else None
    if record.get("source") != "sharepoint" or rid.startswith(("gxc-", "page-", "vm-")):
        return None
    if record.get("type") not in ("video", "ldk", "vdk") or not record.get("source_item_id"):
        return None
    return "sharepoint"
