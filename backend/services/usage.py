"""The Hub's own usage events, as every report reads them (2026-11-11; the
Admin router's `_events` until then): views, previews, downloads, searches,
minus a GXC video opened through a personal link by someone outside the GXC
group -- not Hub usage (B10); GXC personal links shows it.
"""
from __future__ import annotations


def events(repo, since: str | None = None, until: str | None = None) -> list[dict]:
    from backend import gxc_shares
    reader = getattr(repo, "usage_events", None)
    return gxc_shares.without_link_views(reader(since=since, until=until)) if reader else []
