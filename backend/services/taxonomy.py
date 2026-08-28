"""Vocabulary shared across source platforms.

The Portal indexes several systems that describe the same products in different
words, and a filter is useless if picking "Windchill" silently hides half the
catalogue. This module is the one place that reconciles them.

The product problem, measured 2026-08-26
----------------------------------------
SharePoint uses PTC's full product taxonomy — a managed-metadata field with 41
distinct values, naming the specific module. Consensus uses whatever the person
typed, which is the colloquial brand:

    SharePoint   Windchill PDMLink (96) · Windchill MPMLink · Windchill PartsLink
    Consensus    Windchill (62)

    SharePoint   ThingWorx Platform · ThingWorx Analytics · ThingWorx Navigate
    Consensus    ThingWorx (6) · Navigate (29)

Only 6 product names appear verbatim in both. That is not a vocabulary clash —
it is a granularity gap, and a **family** level bridges it. Filtering by family
reaches both platforms, which is also what most people mean when they search for
"Windchill". Filtering by the specific product still works, and naturally
returns SharePoint content only, because only SharePoint records it.
"""
from __future__ import annotations

#: Families whose members carry the family name as a prefix. Covers the large
#: majority and, unlike a fixed list, absorbs new products without an edit.
_FAMILY_PREFIXES = (
    "Creo", "Windchill", "ThingWorx", "Arbortext", "Mathcad", "Vuforia",
    "Kepware", "Codebeamer", "ServiceMax", "Onshape", "Integrity", "Servigistics",
    # Newer PTC brands, seen as Consensus tags 2026-08-27.
    "Orbit", "Jetstream",
)

#: Every family name we recognise — the prefixes plus whatever the aliases
#: resolve to. Used to decide whether a bare word is a product at all.
def known_families() -> set[str]:
    return set(_FAMILY_PREFIXES) | set(_ALIASES.values())

#: Names that do not contain their own family. Every entry below was checked
#: against the live tenant by looking at which segment its content sits in,
#: rather than inferred from the name.
_ALIASES = {
    # PLM segment, 29 demos. SharePoint calls the same product ThingWorx Navigate.
    "navigate": "ThingWorx",
    # IoT segment, 3 demos whose titles spell out "Connected Work Cell".
    "cwc": "Connected Work Cell",
    "kepserverex": "Kepware",
    "kepware+": "Kepware",
    # ALM segment, 11 demos titled "PTC Modeler ... MBSE / SysML". Deliberately
    # its own family: it descends from Atego, not from the Windchill line, and
    # folding it into Windchill would put unrelated content behind that filter.
    "modeler": "PTC Modeler",
    "ptc modeler": "PTC Modeler",
}

#: Values that appear where a product is expected but are not products. They
#: come from Consensus, where the naming convention's second slot is free text.
_NOT_PRODUCTS = {
    "customer success onboarding", "meeting recording", "consensus training",
    "training", "single demonstration", "role-based demonstration",
    "consensus meeting", "tips and techniques", "n/a", "none", "other",
}

#: The segment vocabulary. Both platforms already agree on these five — 96% of
#: Consensus's convention-following demos use one of them — so segment needs a
#: membership test rather than a mapping.
SEGMENTS = ("CAD", "PLM", "ALM", "SLM", "IoT")


def is_segment(value: str | None) -> bool:
    """Is this one of the five shared segment values?

    Consensus puts free text in the same slot ("Single Demonstration",
    "Consensus Training"), so the slot's contents cannot be trusted as a
    segment without checking.
    """
    return bool(value) and value.strip().upper() in {s.upper() for s in SEGMENTS}


def normalise_segment(value: str | None) -> str | None:
    """The canonical spelling, or None if this is not a segment at all."""
    if not is_segment(value):
        return None
    wanted = value.strip().upper()
    return next(s for s in SEGMENTS if s.upper() == wanted)


def is_product(value: str | None) -> bool:
    return bool(value) and value.strip().lower() not in _NOT_PRODUCTS


def family_of(product: str | None) -> str | None:
    """The family a product belongs to, or None if it is not a product.

    Falls back to the product's own name, so a product in no known family is
    still filterable rather than disappearing — a single-member family is a
    correct answer, not a failure.
    """
    if not is_product(product):
        return None
    name = product.strip()
    if alias := _ALIASES.get(name.lower()):
        return alias
    for prefix in _FAMILY_PREFIXES:
        if name.lower().startswith(prefix.lower()):
            return prefix
    return name


def families_of(products: list[str] | None) -> list[str]:
    """Families for a list of products, de-duplicated, order preserved."""
    out: list[str] = []
    for product in products or []:
        family = family_of(product)
        if family and family not in out:
            out.append(family)
    return out


# ─────────────────────────────────────────── Consensus tags, measured not guessed
# The full vocabulary of the live tenant, harvested 2026-08-27 from V2 across
# 1,005 demos: 40 distinct tags, 1,945 uses, on 42% of demos. They are a flat
# bag that spans five of our dimensions at once —
#
#     ['PTC NEXT', 'CAD', 'Creo', 'Prospecting', 'Qualifying']
#      campaign     segment product  funnel stage
#
# so each tag is classified independently and the raw list is kept as well.
# Anything unrecognised stays a tag and nothing more: inventing a meaning for
# it would put unrelated content behind a filter, and this project has already
# paid twice for guessing at someone else's vocabulary.

#: Consensus writes some of these differently from SharePoint. Matching is
#: case-insensitive to absorb IOT/IoT and Thingworx/ThingWorx, which are the
#: two that actually differ on the live data.
_TAG_SEGMENTS = {"cad": "CAD", "plm": "PLM", "alm": "ALM",
                 "slm": "SLM", "iot": "IoT"}

#: Consensus tags the *sales* stage; our FunnelStage names the buyer's. The
#: mapping is a judgement, so it is written down rather than inferred:
#: prospecting is first contact, qualifying is active evaluation, validating is
#: the proof before signature.
_TAG_FUNNEL = {
    "prospecting": "Awareness",
    "qualifying": "Consideration",
    "validating": "Decision",
}

#: Depth of treatment. "Technical Tour" is rare (9 uses) and sits alongside
#: walkthroughs in practice.
_TAG_DEPTH = {
    "teaser": "Teaser",
    "technical overview": "Overview",
    "technical walkthrough": "Walkthrough",
    "technical tour": "Walkthrough",
}

#: Industry, a field that is empty across the entire SharePoint catalogue.
_TAG_INDUSTRY = {
    "medical device": "Medical Device",
    "aerospace and defense": "Aerospace and Defense",
    "automotive": "Automotive",
}

#: Tags that name a language duplicate the structured `language` field, which
#: is 100% covered and authoritative. Recognised so they are not mistaken for
#: products, then discarded.
_TAG_LANGUAGES = {"french", "korean", "japanese", "italian", "german",
                  "chinese", "spanish", "english"}

#: Not a dimension we model — campaign or event names. Kept as plain tags.
_TAG_CAMPAIGNS = {"ptc next"}


def classify_tag(tag: str) -> tuple[str, str] | None:
    """Which of our fields a Consensus tag belongs to, and its canonical value.

    Returns (field, value), or None when the tag means nothing we model — in
    which case it survives untouched in `tags`.
    """
    key = (tag or "").strip().lower()
    if not key:
        return None
    for field, table in (("segment", _TAG_SEGMENTS),
                         ("funnel_stage", _TAG_FUNNEL),
                         ("content_depth", _TAG_DEPTH),
                         ("industry", _TAG_INDUSTRY)):
        if key in table:
            return field, table[key]
    if key in _TAG_LANGUAGES or key in _TAG_CAMPAIGNS:
        return None
    # A product only when it resolves to a family we actually know. Comparing
    # the family against the tag itself was wrong: a brand name IS its own
    # family, so "Creo", "Windchill" and "Codebeamer" — the three commonest
    # product tags on the tenant — excluded themselves.
    if is_product(tag) and family_of(tag) in known_families():
        return "product", tag.strip()
    return None


def classify_tags(tags: list[str] | None) -> dict:
    """Fold a demo's tags into our fields.

    First value wins per field, so a demo tagged both CAD and PLM keeps CAD
    rather than silently picking by dict order. Products accumulate, because a
    demo genuinely can cover several.
    """
    out: dict = {"segment": None, "funnel_stage": None, "content_depth": None,
                 "industry": None, "products": []}
    for tag in tags or []:
        found = classify_tag(tag)
        if not found:
            continue
        field, value = found
        if field == "product":
            if value not in out["products"]:
                out["products"].append(value)
        elif out[field] is None:
            out[field] = value
    return out
