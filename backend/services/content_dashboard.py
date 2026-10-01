"""The content dashboard (HLR-F1): what the Hub holds, at a glance.

Serge asked for it (2026-09-25 email, "Idea for TMH: content dashboard and age
flags"): counts by type, product, segment, stage, customer, industry and age,
where every chart drills into the matching assets. Built 2026-10-01 as a tab on
the Admin page; who else may see it is still open (HLR-F2).

Counted over exactly what the Hub lists -- `repo.list()`, so divested products
and superseded VMs are out, as they are for every user -- and recomputed on
every request: the catalogue is a few thousand rows at most.

"Not set" is a bucket of its own on purpose. A dashboard that silently drops
the assets without a segment overstates how well the catalogue is classified;
the gap is part of the picture.

Age is for videos only. A video's date is when it was published; a SharePoint
kit's is its folder's last edit (381 kits read 2024-05 from one bulk edit,
measured 2026-10-01), so ageing kits would be measuring edits, not content.
"""
from __future__ import annotations

from datetime import date

from backend.models import AssetSummary
from backend.repositories.base import AssetQuery, AssetRepository

NOT_SET = "Not set"

TYPE_ORDER = ["video", "ldk", "vdk", "cad_model", "vm"]
TYPE_LABEL = {"video": "Videos", "ldk": "LDKs", "vdk": "VDKs",
              "cad_model": "CAD datasets", "vm": "Virtual machines"}

#: Same renames the Hub's own pages show (hub-api.js UMBRELLA_DISPLAY).
PRODUCT_LABEL = {"IPE": "PTC Ignite"}

#: HLR-D4's tiers (New under 1 year, 1-2, 2-4, older), with 7+ split out:
#: HLR-D5's "collecting dust" threshold.
AGE_TIERS = ["Under 1 year", "1–2 years", "2–4 years", "4–7 years", "7+ years"]

WHERE_LABEL = {"catalog": "SharePoint · Demo Catalog",
               "demo_video": "SharePoint · Demo Video",
               "consensus": "Consensus"}


def _years(published: date | None, today: date) -> float | None:
    if published is None:
        return None
    return (today - published).days / 365.25


def _age_tier(a: AssetSummary, today: date) -> list[str]:
    years = _years(a.uploaded_at, today)
    if years is None:
        return [NOT_SET]
    for limit, tier in zip((1, 2, 4, 7), AGE_TIERS):
        if years < limit:
            return [tier]
    return [AGE_TIERS[-1]]


def _where(a: AssetSummary) -> list[str]:
    if a.source == "consensus":
        return ["consensus"]
    # Demo Video assets carry the "video-" id prefix (video_sync.py).
    return ["demo_video" if a.id.startswith("video-") else "catalog"]


def _type_value(a: AssetSummary) -> str:
    return getattr(a.type, "value", a.type)


#: key -> (title, values of one asset, label of a value, fixed order or None,
#:         applies to this asset?)
DIMENSIONS = {
    "type": ("Asset type", lambda a, t: [_type_value(a)],
             lambda v: TYPE_LABEL.get(v, v), TYPE_ORDER, None),
    "product": ("Product", lambda a, t: list(a.umbrella_families) or [NOT_SET],
                lambda v: PRODUCT_LABEL.get(v, v), None, None),
    "segment": ("Segment", lambda a, t: [a.segment or NOT_SET], None, None, None),
    "stage": ("Funnel stage", lambda a, t: [a.funnel_stage or NOT_SET], None,
              ["Awareness", "Consideration", "Decision", "Post-Sale"], None),
    "customer": ("Named customer", lambda a, t: [a.named_customer or NOT_SET],
                 None, None, None),
    "industry": ("Industry", lambda a, t: [a.industry or NOT_SET], None, None, None),
    "age": ("Age of videos", _age_tier, None, AGE_TIERS,
            lambda a: _type_value(a) == "video"),
    "where": ("Where it lives", lambda a, t: _where(a),
              lambda v: WHERE_LABEL.get(v, v), list(WHERE_LABEL), None),
}

NOTES = {
    "age": "Videos only, by publish date. A kit's date is its folder's last "
           "edit, so it would measure edits, not content.",
    "product": "A demo covering two products counts under both.",
}


def listed(repo: AssetRepository) -> list[AssetSummary]:
    """Everything the Hub lists, in one page."""
    first = repo.list(AssetQuery(sort="title", limit=1))
    return repo.list(AssetQuery(sort="title", limit=max(first.total, 1))).items


def summary(repo: AssetRepository, today: date | None = None) -> dict:
    today = today or date.today()
    assets = listed(repo)
    out = []
    for key, (title, values_of, label_of, order, applies) in DIMENSIONS.items():
        pool = [a for a in assets if applies is None or applies(a)]
        counts: dict[str, int] = {}
        for a in pool:
            for v in values_of(a, today):
                counts[v] = counts.get(v, 0) + 1
        if order:
            keys = [v for v in order if v in counts] + sorted(
                v for v in counts if v not in order and v != NOT_SET)
        else:
            keys = sorted((v for v in counts if v != NOT_SET),
                          key=lambda v: (-counts[v], v.lower()))
        if NOT_SET in counts:
            keys.append(NOT_SET)
        out.append({
            "key": key, "title": title, "of": len(pool), "note": NOTES.get(key),
            "buckets": [{"value": v, "label": (label_of or (lambda x: x))(v)
                         if v != NOT_SET else NOT_SET, "count": counts[v]}
                        for v in keys],
        })
    return {"total": len(assets), "as_of": today.isoformat(), "dimensions": out}


def assets_in(repo: AssetRepository, dim: str, value: str,
              today: date | None = None) -> list[dict]:
    """The assets behind one bar, newest first."""
    if dim not in DIMENSIONS:
        raise KeyError(dim)
    today = today or date.today()
    _, values_of, _, _, applies = DIMENSIONS[dim]
    hits = [a for a in listed(repo)
            if (applies is None or applies(a)) and value in values_of(a, today)]
    hits.sort(key=lambda a: a.uploaded_at or date.min, reverse=True)
    return [{"id": a.id, "title": a.title, "type": _type_value(a),
             "uploaded_at": a.uploaded_at.isoformat() if a.uploaded_at else None}
            for a in hits]
