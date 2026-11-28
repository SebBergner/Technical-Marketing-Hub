"""The Hub's own usage: the events every report reads, and the Admin usage
figures built from them.

`events` (2026-11-11; the Admin router's `_events` until then): views,
previews, downloads, searches, minus a GXC video opened through a personal
link by someone outside the GXC group -- not Hub usage (B10); GXC personal
links shows it.

The figures (summary, one demo, breakdown, untouched) moved here from
`routers/admin.py` on 2026-11-28 (optimisation plan WS-F): the router reads
the request and checks permissions; what the numbers mean lives here. They
are also what the PostgreSQL plan turns into SQL views.
"""
from __future__ import annotations

from datetime import datetime

from backend.repositories.base import AssetQuery


class UnknownDimension(ValueError):
    """A breakdown or scope dimension not in BREAKDOWNS."""


def events(repo, since: str | None = None, until: str | None = None) -> list[dict]:
    from backend import gxc_shares
    reader = getattr(repo, "usage_events", None)
    return gxc_shares.without_link_views(reader(since=since, until=until)) if reader else []


def tally(rows: list[dict], key: str = "event") -> dict:
    out: dict = {}
    for e in rows:
        out[e.get(key)] = out.get(e.get(key), 0) + 1
    return out


# ───────────────────────────────────────────────────────────── the summary
def summary(repo, since: str | None, until: str | None, data_dir: str) -> dict:
    """What the Hub itself was used for, in a window.

    The window is passed in as ISO bounds rather than a named period, because
    "this week" depends on where the reader is sitting and the browser already
    knows — resolving it here would quietly give everyone Redmond's week.

    Consensus's own play counts are deliberately NOT here (Liwei, 2026-09-21):
    they measure a different platform's audience, and standing them beside our
    figures invited exactly the comparison that §7.3 warns against. They live
    on the Consensus source page, where the population they describe is the
    page's subject.
    """
    rows = events(repo, since, until)
    by_type = tally(rows)

    touched = {e["asset_id"] for e in rows if e.get("asset_id")}

    searches = [e for e in rows if e.get("event") == "search"]
    search_tally: dict[str, dict] = {}
    for e in searches:
        row = search_tally.setdefault(e.get("q", ""), {"q": e.get("q", ""), "times": 0,
                                                       "zero_results": 0})
        row["times"] += 1
        if not e.get("results"):
            row["zero_results"] += 1

    from backend.services import feature_usage
    features = feature_usage.summarise(rows, since, until)
    features.update(feature_usage.starred_and_listed(data_dir, since, until))

    return {
        "window": {"since": since, "until": until},
        "totals": {
            "views": by_type.get("view", 0),
            "previews": by_type.get("preview", 0),
            "downloads": by_type.get("download", 0),
            "searches": by_type.get("search", 0),
            "assets_touched": len(touched),
        },
        "features": features,
        "daily": daily(rows),
        # Against the window immediately before this one, same length. A count
        # on its own says nothing about whether it is good -- "95 downloads"
        # only means something beside "68 last month". Absent when there is no
        # earlier window to compare with (the "all time" range).
        "previous": previous_totals(repo, since, until),
        "searches": {
            "top": sorted(search_tally.values(), key=lambda r: -r["times"])[:15],
            "zero_result": sorted(
                [r for r in search_tally.values() if r["zero_results"]],
                key=lambda r: -r["zero_results"])[:15],
        },
    }


def daily(rows: list[dict]) -> list[dict]:
    """Per-day counts, for the chart. Days with nothing are omitted rather
    than zero-filled here — the page knows the window and can draw the gaps,
    and inventing rows is how a quiet week starts looking like a busy one."""
    days: dict[str, dict] = {}
    for e in rows:
        day = (e.get("at") or "")[:10]
        if not day:
            continue
        row = days.setdefault(day, {"day": day, "view": 0, "preview": 0,
                                    "download": 0, "search": 0})
        if e["event"] in row:
            row[e["event"]] += 1
    return [days[d] for d in sorted(days)]


def previous_totals(repo, since: str | None, until: str | None) -> dict | None:
    """The same-length window ending where this one starts.

    Returns None for an unbounded range: "all time" has nothing before it, and
    inventing a comparison there would be arithmetic pretending to be insight.
    """
    if not since:
        return None
    try:
        start = datetime.fromisoformat(since)
        end = datetime.fromisoformat(until) if until else datetime.now()
    except ValueError:
        return None
    span = end - start
    if span.total_seconds() <= 0:
        return None
    rows = events(repo, (start - span).isoformat(timespec="seconds"),
                  start.isoformat(timespec="seconds"))
    by_type = tally(rows)
    return {
        "since": (start - span).isoformat(timespec="seconds"),
        "until": start.isoformat(timespec="seconds"),
        "views": by_type.get("view", 0),
        "previews": by_type.get("preview", 0),
        "downloads": by_type.get("download", 0),
        "searches": by_type.get("search", 0),
    }


# ───────────────────────────────────────────────────────────── one demo
def for_asset(repo, asset_id: str, since: str | None, until: str | None) -> dict:
    """One demo's own history, including which files people actually took."""
    rows = [e for e in events(repo, since, until) if e.get("asset_id") == asset_id]
    by_type = tally(rows)

    files: dict[str, dict] = {}
    for e in rows:
        if e["event"] not in ("download", "preview"):
            continue
        name = e.get("file") or e.get("item_id") or "—"
        row = files.setdefault(name, {"file": name, "kind": e.get("kind"),
                                      "download": 0, "preview": 0})
        row[e["event"]] += 1

    asset = repo.get(asset_id)
    return {
        "asset": {"id": asset_id,
                  "title": asset.title if asset else asset_id,
                  "type": asset.type if asset else None,
                  "source": asset.source if asset else None},
        "window": {"since": since, "until": until},
        "totals": {
            "views": by_type.get("view", 0),
            "previews": by_type.get("preview", 0),
            "downloads": by_type.get("download", 0),
        },
        "daily": daily(rows),
        "files": sorted(files.values(),
                        key=lambda r: (-r["download"], -r["preview"])),
    }


# ───────────────────────────────────────────────────────────── breakdown
#: What a row can be grouped by. Anything with thousands of demos behind it
#: needs to be readable before it is complete, and a roll-up answers "where is
#: the attention going" in a screenful where a list of every demo cannot.
BREAKDOWNS = {
    "demo": lambda a: [a.id] if a else [],
    "product": lambda a: (a.product_families or ["(no product)"]) if a else [],
    "segment": lambda a: [a.segment or "(no segment)"] if a else [],
    "source": lambda a: [getattr(a.source, "value", a.source) or "(unknown)"] if a else [],
    "type": lambda a: [getattr(a.type, "value", a.type) or "(unknown)"] if a else [],
}
#: Words for the keys above, where the key is a code ("cad_model" read as
#: "AssetType.CAD_MODEL" until 2026-10-14).
_BREAKDOWN_LABEL = {"type": {"video": "Videos", "ldk": "LDKs", "vdk": "VDKs",
                             "cad_model": "CAD datasets", "vm": "Virtual machines"},
                    "source": {"sharepoint": "SharePoint", "consensus": "Consensus"}}


def breakdown(repo, dimension: str, since: str | None, until: str | None,
              q: str | None, sort: str, limit: int, offset: int,
              scope_dim: str | None, scope_key: str | None) -> dict:
    """Usage grouped by one dimension, searchable, sortable and paged.

    Paged on the server rather than sliced in the browser: at a thousand demos
    the honest answer to "show me the table" is a page of it plus a count, and
    a page that quietly dropped the other 975 rows would be the kind of number
    that misleads precisely because it looks complete.

    Raises UnknownDimension for a `dimension` or `scope_dim` it does not know.
    """
    if dimension not in BREAKDOWNS:
        raise UnknownDimension(f"unknown dimension {dimension!r}")
    if sort not in ("view", "preview", "download"):
        sort = "view"

    key_of = BREAKDOWNS[dimension]
    rows_in = [e for e in events(repo, since, until) if e.get("asset_id")]

    # One listing, not a get() per demo touched: each get() rebuilds the
    # catalogue view, and with a few hundred demos used the tab took 15 s
    # (2026-10-14). Archived demos and older VM versions included, as get()
    # returned them; hidden ones stay out, as before.
    # The few a listing leaves out but get() still opens (a kit's subfolder
    # such as "release-notes") are looked up one by one.
    touched = {e["asset_id"] for e in rows_in}
    assets = {a.id: a for a in repo.list(AssetQuery(
        limit=10 ** 6, include_older_vms=True, include_archived=True)).items
        if a.id in touched}
    assets.update({aid: repo.get(aid) for aid in touched - assets.keys()})

    # Drilling in: "by product" -> click Windchill -> the demos inside it.
    # Narrowing the events rather than the finished rows keeps every number
    # below -- including the share column -- relative to the scope on screen.
    if scope_dim and scope_key:
        if scope_dim not in BREAKDOWNS:
            raise UnknownDimension(f"unknown scope {scope_dim!r}")
        scope_of = BREAKDOWNS[scope_dim]
        rows_in = [e for e in rows_in
                   if scope_key in [str(k) for k in scope_of(assets.get(e["asset_id"]))]]

    groups: dict[str, dict] = {}
    for e in rows_in:
        asset = assets.get(e["asset_id"])
        for key in (key_of(asset) or ["(no longer in the catalogue)"]):
            row = groups.setdefault(str(key), {
                "key": str(key), "view": 0, "preview": 0, "download": 0})
            if e["event"] in row:
                row[e["event"]] += 1

    rows = list(groups.values())
    if dimension == "demo":
        for row in rows:
            asset = assets.get(row["key"])
            row["label"] = asset.title if asset else (
                row["key"] + " (no longer in the catalogue)")
            row["source"] = asset.source if asset else None
            row["type"] = asset.type if asset else None
    else:
        words = _BREAKDOWN_LABEL.get(dimension, {})
        for row in rows:
            row["label"] = words.get(row["key"], row["key"])

    if q:
        needle = q.strip().lower()
        rows = [r for r in rows if needle in r["label"].lower()]

    grand = sum(r[sort] for r in rows) or 1
    for row in rows:
        row["share"] = round(row[sort] * 100 / grand, 1)

    rows.sort(key=lambda r: (-r[sort], r["label"].lower()))
    return {
        "dimension": dimension,
        "scope": {"dimension": scope_dim, "key": scope_key} if scope_key else None,
        "sort": sort,
        "total_rows": len(rows),
        "rows": rows[offset:offset + limit],
        "offset": offset,
        "limit": limit,
    }


# ───────────────────────────────────────────────────────────── untouched
def untouched(repo, since: str | None, until: str | None, q: str | None,
              limit: int, offset: int) -> dict:
    """Demos nobody opened in this window.

    Its own view rather than a tail of zeroes on the main table: at this
    catalogue's size most demos are untouched in any given week, so mixing
    them in would bury the ones that were used under hundreds of rows that
    say nothing. Separated, the same fact becomes the more useful question —
    which content is not earning its place.
    """
    touched = {e["asset_id"] for e in events(repo, since, until) if e.get("asset_id")}
    rows = []
    for asset in repo.list(AssetQuery(limit=10 ** 6, include_older_vms=True)).items:
        if asset.id in touched:
            continue
        if q and q.strip().lower() not in (asset.title or "").lower():
            continue
        rows.append({"asset_id": asset.id, "label": asset.title,
                     "source": asset.source, "type": asset.type,
                     "uploaded_at": str(asset.uploaded_at) if asset.uploaded_at else None})
    rows.sort(key=lambda r: (r["label"] or "").lower())
    return {"total_rows": len(rows), "rows": rows[offset:offset + limit],
            "offset": offset, "limit": limit, "touched": len(touched)}
