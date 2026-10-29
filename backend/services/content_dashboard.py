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

#: LANGUAGE_LABEL in static/js/hub/util.js.
LANGUAGE_LABEL = {"en": "English", "zh": "Chinese", "de": "German", "fr": "French",
                  "es": "Spanish", "it": "Italian", "ja": "Japanese", "ko": "Korean"}

#: Same renames the Hub's own pages show (UMBRELLA_DISPLAY in static/js/hub/nav.js).
PRODUCT_LABEL = {"IPE": "PTC Ignition"}

#: HLR-D4's tiers (New under 1 year, 1-2, 2-4, older), with 7+ split out:
#: HLR-D5's "collecting dust" threshold.
AGE_TIERS = ["Under 1 year", "1–2 years", "2–4 years", "4–7 years", "7+ years"]

WHERE_LABEL = {"catalog": "SharePoint · Demo Catalog",
               "demo_video": "SharePoint · Demo Video",
               "gxc_video": "SharePoint · GXC Video",
               "page": "SharePoint · Demo page only",
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
    # Demo Video assets carry the "video-" id prefix, GXC Video's "gxc-"
    # (video_sync.py), demos known only from their page "page-" (demo_pages.py).
    if a.id.startswith("page-"):
        return ["page"]
    if a.id.startswith("gxc-"):
        return ["gxc_video"]
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
    "language": ("Language", lambda a, t: [a.language or "en"],
                 lambda v: LANGUAGE_LABEL.get(v, v.upper()), None, None),
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

#: Data completeness (2026-10-14; was "Catalogue health" on the Overview,
#: which counted every type against every field and older VM versions too).
#: Each field is measured only over the types it applies to -- a funnel
#: stage exists only on videos, a CAD dataset has no segment -- so a gap is
#: a real gap, and over the same demos as the charts. Drilling in lists the
#: demos missing it, like any bar.
#: key -> (label, is it set?, types it applies to (None: all), note)
COMPLETENESS = {
    "product": ("Product", lambda a: bool(a.umbrella_families), None,
                "A product family the Hub recognises."),
    "segment": ("Segment", lambda a: bool(a.segment),
                ("video", "ldk", "vdk", "vm"), "Not asked of CAD datasets."),
    "stage": ("Funnel stage", lambda a: bool(a.funnel_stage), ("video",),
              "Videos only: kits have no such column."),
    "depth": ("Content depth", lambda a: bool(a.content_depth), ("video", "ldk", "vdk"),
              "Videos and demo kits."),
    "description": ("Description", lambda a: bool(a.description), None, None),
    # Kits with two or more videos and none the Hub can play first: tick
    # PreviewVideo on one in SharePoint (2026-10-15).
    "preview": ("Preview video", lambda a: (a.video_count or 0) < 2 or a.has_main_video,
                ("ldk", "vdk"), "Kits with several videos: tick PreviewVideo on one in "
                "SharePoint."),
    "thumbnail": ("Thumbnail", lambda a: bool(a.thumbnail_url),
                  ("video", "ldk", "vdk", "cad_model"),
                  "Without one the Hub draws a product cover."),
}


def _completeness_dim(key: str):
    """A completeness field in DIMENSIONS' shape, so drilling in is the same
    call as for a bar: its values are "Set" or "Not set"."""
    label, is_set, types, _ = COMPLETENESS[key]
    return (label, lambda a, t: ["Set" if is_set(a) else NOT_SET], None, None,
            (lambda a: _type_value(a) in types) if types else None)


def completeness(assets: list[AssetSummary]) -> list[dict]:
    out = []
    for key, (label, is_set, types, note) in COMPLETENESS.items():
        pool = [a for a in assets if not types or _type_value(a) in types]
        missing = sum(1 for a in pool if not is_set(a))
        out.append({"key": "missing:" + key, "title": label, "of": len(pool),
                    "missing": missing, "note": note,
                    "types": [TYPE_LABEL[t] for t in types] if types else None,
                    "percent_missing": round(missing * 100 / len(pool), 1) if pool else 0})
    return sorted(out, key=lambda r: -r["percent_missing"])


NOTES = {
    "age": "Videos only, by publish date. A kit's date is its folder's last "
           "edit, so it would measure edits, not content.",
    "product": "A demo covering two products counts under both.",
}


def listed(repo: AssetRepository) -> list[AssetSummary]:
    """Everything the Hub lists, in one page."""
    first = repo.list(AssetQuery(sort="title", limit=1))
    return repo.list(AssetQuery(sort="title", limit=max(first.total, 1))).items


def _dimensions(assets: list[AssetSummary], today: date, only=None) -> list[dict]:
    out = []
    for key, (title, values_of, label_of, order, applies) in DIMENSIONS.items():
        if only is not None and key not in only:
            continue
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
    return out


def summary(repo: AssetRepository, today: date | None = None) -> dict:
    today = today or date.today()
    assets = listed(repo)
    return {"total": len(assets), "as_of": today.isoformat(),
            "dimensions": _dimensions(assets, today), "completeness": completeness(assets)}


#: What the Dashboard shows of the library (Serge, 2026-10-23), in order.
LIBRARY_DIMENSIONS = ("type", "product", "segment", "language", "age")


def library(repo: AssetRepository, today: date | None = None, months: int = 24) -> dict:
    """The Dashboard's library half, for every PTC employee: the same counts
    as the Admin content dashboard minus the completeness gaps, plus the
    content by month for the last `months` months, per type.

    A month is the item's own date: its publication date where one is stated
    (date_stated), otherwise its files' last update -- the same date the
    tiles show."""
    today = today or date.today()
    assets = listed(repo)
    first = date(today.year, today.month, 1)
    keys = []
    y, m = first.year, first.month
    for _ in range(months):
        keys.append(f"{y:04d}-{m:02d}")
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    keys.reverse()
    by_month = {k: {t: 0 for t in TYPE_ORDER} for k in keys}
    for a in assets:
        if a.uploaded_at:
            k = a.uploaded_at.strftime("%Y-%m")
            if k in by_month:
                by_month[k][_type_value(a)] = by_month[k].get(_type_value(a), 0) + 1
    return {"total": len(assets), "as_of": today.isoformat(),
            "types": [{"type": t, "label": TYPE_LABEL[t], "count": sum(
                1 for a in assets if _type_value(a) == t)} for t in TYPE_ORDER],
            "dimensions": _dimensions(assets, today, LIBRARY_DIMENSIONS),
            "by_month": [{"month": k, **by_month[k]} for k in keys]}


def assets_in(repo: AssetRepository, dim: str, value: str,
              today: date | None = None) -> list[dict]:
    """The assets behind one bar, newest first."""
    if dim.startswith("missing:") and dim[8:] in COMPLETENESS:
        _, values_of, _, _, applies = _completeness_dim(dim[8:])
    elif dim in DIMENSIONS:
        _, values_of, _, _, applies = DIMENSIONS[dim]
    else:
        raise KeyError(dim)
    today = today or date.today()
    hits = [a for a in listed(repo)
            if (applies is None or applies(a)) and value in values_of(a, today)]
    hits.sort(key=lambda a: a.uploaded_at or date.min, reverse=True)
    return [{"id": a.id, "title": a.title, "type": _type_value(a),
             "uploaded_at": a.uploaded_at.isoformat() if a.uploaded_at else None}
            for a in hits]
