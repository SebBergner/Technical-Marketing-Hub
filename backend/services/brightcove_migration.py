"""What the Brightcove Gallery migration has put into SharePoint, summarised.

The "Demo Video" library is the permanent home of the migrated videos (Liwei,
2026-09-28; first named Gallery_Brightcove, renamed 2026-09-29 because it
will also hold demo videos from other sources). The Hub will index it
alongside the Demo Catalog. This module reads it READ-ONLY and
summarises it for the /migration page -- for a manager, not a developer:
how many demos, when they arrived, how far the plan has got, and how they
split by Segment and Product.

The library is read through the Hub's own sync mapping (build_assets), so a
count here is the count the Hub will show once it indexes the library -- the
page cannot describe the content one way and the catalogue another.
"""
from __future__ import annotations

import collections
import json
import os
from datetime import date, timedelta

from backend.config import settings
from backend.integrations.graph import sync
from backend.integrations.graph.client import DriveRef, GraphClient

#: Product bars beyond this fold into "Other" -- a long tail of one-offs is
#: noise in a chart and still complete in the Hub's own filters.
TOP_PRODUCTS = 10
RECENT = 10


# ─────────────────────────────────────────────────────────────── reading
def read_library(client: GraphClient, site_id: str, name: str) -> list[dict] | None:
    """Every item in the library with the columns the sync needs, or None
    when the library does not exist. GET requests only."""
    drive = client.find_drive(site_id, name)
    if drive is None:
        return None
    page = client.delta(drive.drive_id)
    return sync._with_fields(client, DriveRef(drive.drive_id, drive.name), page.items)


# ─────────────────────────────────────────────────────────── summarising
def _week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _share(counter: collections.Counter, total: int, top: int | None = None) -> list[dict]:
    rows = counter.most_common()
    if top is not None and len(rows) > top:
        other = sum(n for _, n in rows[top:])
        rows = rows[:top] + [("Other", other)]
    return [{"name": k, "count": n, "percent": round(n * 100 / total, 1) if total else 0}
            for k, n in rows]


def summarize(items: list[dict]) -> dict:
    """The manager's view of one library. Pure: items in, figures out."""
    assets, result = sync.build_assets([dict(i) for i in items])
    folders = {i["id"]: i for i in items
               if "folder" in i and not sync._relative_path(i) and not i.get("deleted")
               and (i.get("parentReference") or {}).get("path") is not None}

    migrated_on: dict[str, date] = {}
    published_year: dict[str, int | None] = {}
    hub_products: dict[str, list[str]] = {}
    for a in assets:
        folder = folders.get(a.source_item_id) or {}
        created = (folder.get("createdDateTime") or "")[:10]
        if created:
            migrated_on[a.id] = date.fromisoformat(created)
        # The publish year from the column itself, never from uploaded_at:
        # uploaded_at falls back to the folder date when the column is empty,
        # and that fallback would pass the migration day off as a publish year.
        fields = ((folder.get("listItem") or {}).get("fields") or {})
        raw = sync._field(fields, "original_publish_date")
        published_year[a.id] = int(str(raw)[:4]) if raw else None
        # This library's products live in Hub Products (a choice column), not
        # in the managed-metadata Product, which has no term for "Windchill"
        # or "Creo" (plan §13). Measured 2026-09-29: counting Product showed
        # only "Codebeamer" for a video tagged Windchill, Codebeamer and Creo.
        hub = fields.get("HubProducts")
        hub_products[a.id] = [str(p) for p in hub] if isinstance(hub, list) and hub else a.products

    total = len(assets)
    segments = collections.Counter()
    products = collections.Counter()
    for a in assets:
        for s in dict.fromkeys([a.segment, *a.rails]):
            if s:
                segments[s] += 1
        for p in dict.fromkeys(hub_products[a.id]):
            products[p] += 1
        if not a.segment:
            segments["Not set"] += 1
        if not hub_products[a.id]:
            products["Not set"] += 1

    weeks = collections.Counter(_week_start(d) for d in migrated_on.values())
    years = collections.Counter(published_year.values())

    size_bytes = sum(i.get("size") or 0 for i in items
                     if "file" in i and not i.get("deleted"))
    runtime = sum(a.duration_seconds or 0 for a in assets)

    recent = sorted(assets, key=lambda a: migrated_on.get(a.id) or date.min, reverse=True)
    return {
        "demos": total,
        # Top-level folders that are not (yet) demos: no Demo Type set. On a
        # healthy library this is zero; anything else needs a person.
        "incomplete_folders": result.skipped_no_demo_type,
        "internal_only": sum(1 for a in assets if a.customer_facing is False),
        "runtime_seconds": runtime,
        "size_bytes": size_bytes,
        "first_migrated": min(migrated_on.values()).isoformat() if migrated_on else None,
        "last_migrated": max(migrated_on.values()).isoformat() if migrated_on else None,
        "by_week": [{"week_start": w.isoformat(), "count": n} for w, n in sorted(weeks.items())],
        "by_publish_year": [{"year": y, "count": n} for y, n in
                            sorted(years.items(), key=lambda kv: (kv[0] is None, kv[0] or 0))],
        # A demo can carry several segments and products, so each list's
        # percentages are "share of demos" and can add up past 100.
        "segments": _share(segments, total),
        "products": _share(products, total, TOP_PRODUCTS),
        "recent": [{
            "title": a.title,
            "segment": a.segment,
            "products": hub_products[a.id],
            "published": (str(published_year[a.id]) if published_year.get(a.id) else None),
            "migrated": migrated_on[a.id].isoformat() if a.id in migrated_on else None,
            "customer_facing": a.customer_facing,
            "web_url": a.web_url,
        } for a in recent[:RECENT]],
    }


# ─────────────────────────────────────────────────────────────── batch logs
def batches_dir() -> str:
    """Batch logs are irreplaceable -- they are the only record of which
    folders a run created, and so the only way to undo one -- hence owned/,
    which no sync ever touches."""
    return os.path.join(settings.data_dir, "owned", "migration", "brightcove", "batches")


def list_batches(limit: int = 50, library: str | None = None) -> list[dict]:
    """Summaries of the batch logs the CLI writes, newest first.

    `library` keeps runs against the test library off the production
    dashboard: a test manifest's "planned" would otherwise become the
    progress bar's denominator.

    A file that cannot be read is listed as unreadable rather than skipped:
    a batch that silently disappears from this list is a batch nobody can
    find to undo.
    """
    folder = batches_dir()
    if not os.path.isdir(folder):
        return []
    out = []
    for fname in sorted(os.listdir(folder)):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(folder, fname), encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            out.append({"batch_id": fname[:-5], "unreadable": str(exc)[:200]})
            continue
        if library and (data.get("library") or "").lower() != library.lower():
            continue
        out.append({
            "batch_id": data.get("batch_id") or fname[:-5],
            "mode": data.get("mode"),
            "started_at": data.get("started_at"),
            "finished_at": data.get("finished_at"),
            "planned": data.get("planned"),
            "counts": data.get("counts") or {},
        })
    out.sort(key=lambda b: b.get("started_at") or "", reverse=True)
    return out[:limit]


def plan_total(batches: list[dict]) -> int | None:
    """How many demos the migration intends to move, as the newest batch
    that states it says. None until a sheet has been loaded -- the page then
    shows no progress bar rather than one measured against a guess."""
    for b in batches:
        if isinstance(b.get("planned"), int):
            return b["planned"]
    return None
