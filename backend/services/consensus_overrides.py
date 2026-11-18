"""The Hub's own values for a Consensus demo (Liwei, 2026-11-18).

A Consensus demo's product, segment and the rest come only from its Consensus
tags or its internal title's pipe convention (consensus_sync.py). Many have
neither -- "PTC Ignition" on production has no tags and a one-word internal
title -- and the Hub never writes to Consensus, nor may we change another
team's titles. So people with Edit metadata set these values on the Hub.

How it differs from editing a SharePoint demo (metadata_edit.py):

* Kept, not passed through. A SharePoint edit is written to the folder and
  laid over the mirror only until the next sync reads it back. Nothing reads
  these back, so they live in `owned/consensus_overrides.json` for good and are
  laid over every Consensus sync (`apply`).
* Keyed by the Consensus uuid, not the Hub's id: the id is made from the
  title, so a title changed in Consensus would orphan an override keyed by it.
* Classification only: products, segment, stage, video type, industry, each
  from a fixed list (`fields`), so no new spelling makes a family of its own.
  Title, description and links stay Consensus's.
* The Hub's value wins, said openly: the demo's page marks it "set on the
  Hub", and where Consensus later says something else, Content health lists
  it (`differences`). A value the same as Consensus's is not kept at all, so
  saving Consensus's own values clears an override.

The Consensus owners do not see these, and need not (Liwei, 2026-11-18).
"""
from __future__ import annotations

from datetime import datetime, timezone

from backend.models import FunnelStage, VideoType
from backend.services import taxonomy

FILE = "consensus_overrides"

#: What may be set, in the order the form shows it: key -> (label, multi).
FIELDS = {
    "products": ("Products", True),
    "segment": ("Segment", False),
    "funnel_stage": ("Stage", False),
    "content_depth": ("Video type", False),
    "industry": ("Industry", False),
}


class OverrideInvalid(ValueError):
    """A value outside its field's list; says which."""


class NotConsensus(ValueError):
    """Not a Consensus demo: edited in SharePoint, or not at all."""


def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def _empty(value) -> bool:
    return value is None or value == "" or value == []


def _same(a, b) -> bool:
    if _empty(a) and _empty(b):
        return True
    if isinstance(a, list) or isinstance(b, list):
        return sorted(a or []) == sorted(b or [])
    return a == b


def choices(rows: list[dict]) -> dict[str, list[str]]:
    """Each field's list. Products: every product a listed demo carries,
    plus each umbrella's and rolled-up product's own name, so a product no
    demo carries yet (PTC Ignition) can still be chosen."""
    products = {p.strip() for r in rows for p in (r.get("products") or [])
                if p and p.strip() and not taxonomy.is_excluded([p])}
    products |= set(taxonomy.PRODUCT_FAMILIES) | set(taxonomy.FAMILY_ROLLUP)
    industries = {r.get("industry") for r in rows if r.get("industry")}
    industries |= {"Automotive", "Aerospace and Defense", "Medical Device"}
    return {
        "products": sorted(products, key=str.lower),
        "segment": list(taxonomy.SEGMENTS),
        "funnel_stage": [s.value for s in FunnelStage],
        "content_depth": [v.value for v in VideoType if v is not VideoType.PRESENTER_SUPPORT],
        "industry": sorted(industries, key=str.lower),
    }


def fields(rows: list[dict]) -> list[dict]:
    lists = choices(rows)
    return [{"key": k, "label": label, "kind": "multi" if multi else "choice",
             "choices": lists[k]} for k, (label, multi) in FIELDS.items()]


def clean(values: dict, rows: list[dict]) -> dict:
    """The sent values checked against the lists; unknown keys ignored."""
    lists = choices(rows)
    out: dict = {}
    for key, (label, multi) in FIELDS.items():
        if key not in values:
            continue
        value = values[key]
        if multi:
            items = value if isinstance(value, list) else [] if _empty(value) else [value]
            items = [str(i).strip() for i in items if str(i).strip()]
            bad = [i for i in items if i not in lists[key]]
            if bad:
                raise OverrideInvalid(f"{label}: not on the list: {', '.join(bad)}.")
            out[key] = list(dict.fromkeys(items))
        else:
            value = None if _empty(value) else str(value).strip()
            if value is not None and value not in lists[key]:
                raise OverrideInvalid(f"{label}: “{value}” is not on the list.")
            out[key] = value
    return out


def consensus_values(record: dict) -> dict:
    """What Consensus itself says, before any override."""
    own = record.get("consensus_values")
    if own is None:
        own = {k: record.get(k) for k in FIELDS}
    return {k: own.get(k) for k in FIELDS}


def save(repo, record: dict, values: dict, actor: str, rows: list[dict]) -> list[str]:
    """Keep the values that differ from Consensus's own; drop the rest.
    Returns the fields whose shown value changed."""
    if record.get("source") != "consensus" or not record.get("consensus_uuid"):
        raise NotConsensus("Only a Consensus demo is set on the Hub; "
                           "a SharePoint demo is edited in its folder.")
    sent = clean(values, rows)
    theirs = consensus_values(record)
    shown = {k: record.get(k) for k in FIELDS}
    uuid = record["consensus_uuid"]
    with repo._lock:
        store = repo._load(FILE) or {}
        entry = store.get(uuid) or {"values": {}}
        kept = dict(entry.get("values") or {})
        for key, value in sent.items():
            if _same(value, theirs.get(key)):
                kept.pop(key, None)
            else:
                kept[key] = value
        changed = [k for k in FIELDS if k in sent and not _same(sent[k], shown.get(k))]
        if kept:
            store[uuid] = {"values": kept, "title": record.get("title"),
                           "by": actor, "at": _now()}
        else:
            store.pop(uuid, None)
        repo._save(FILE, store)
        invalidate = getattr(repo, "_invalidate", None)
        if invalidate:
            invalidate()
    return changed


def apply(rows: list[dict], store: dict) -> list[dict]:
    """Consensus rows with the Hub's values laid over them. Each keeps
    Consensus's own values (`consensus_values`) and which fields the Hub set
    (`hub_set`), for the page's mark and Content health."""
    if not store:
        return rows
    out = []
    for r in rows:
        entry = store.get(r.get("consensus_uuid") or "") if r.get("source") == "consensus" else None
        values = (entry or {}).get("values") or {}
        if values:
            r = {**r, "consensus_values": {k: r.get(k) for k in FIELDS},
                 "hub_set": [k for k in FIELDS if k in values],
                 **{k: v for k, v in values.items() if k in FIELDS}}
        out.append(r)
    return out


def differences(record: dict) -> list[dict]:
    """Fields the Hub set where Consensus now says something else, not
    nothing: worth a look, since one of the two is likely out of date."""
    theirs = record.get("consensus_values") or {}
    return [{"field": FIELDS[k][0], "hub": record.get(k), "consensus": theirs.get(k)}
            for k in record.get("hub_set") or []
            if not _empty(theirs.get(k)) and not _same(theirs.get(k), record.get(k))]
