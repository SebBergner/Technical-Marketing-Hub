"""The Hub activity page's data, for every PTC employee (2026-10-14).

Serge (2026-10-13): reporting for all users, "top users vs laggers ...
healthy competition". Liwei (2026-10-14): the top N and team totals only --
no laggards -- and no partner data beyond a count of what was left out of
the ranking. Gated on "View Hub activity", a PTC-employees default.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from backend import access, activity
from backend.access import Perm
from backend.admin_auth import require_perm
from backend.deps import get_repo
from backend.repositories.base import AssetQuery, AssetRepository

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/activity", dependencies=[Depends(require_perm(Perm.VIEW_REPORTS))])
def hub_activity(since: str | None = None, until: str | None = None,
                 top: int = Query(10, ge=3, le=25),
                 repo: AssetRepository = Depends(get_repo)):
    reader = getattr(repo, "usage_events", None)
    events = reader() if reader else []
    # One listing, not a get() per demo: each get() rebuilds the catalogue
    # view, and hundreds of them took the page past a minute (2026-10-14).
    # A listing also leaves archived and hidden demos out by itself.
    listed = {a.id: a for a in repo.list(
        AssetQuery(limit=10 ** 6, include_older_vms=True)).items}
    titles = {k: a.title for k, a in listed.items()}
    # Teams are the Hub's own groups; the built-in ones (everyone, partners,
    # administrators) say nothing about a team.
    teams = [g for g in access.load_state()["groups"] if not g["builtin"]]
    out = activity.leaderboard(events, since=since, until=until, top=top,
                               titles=titles, teams=teams)
    # Only content the Hub still lists, so a link never leads to a 404; with
    # its picture and type for the page's cards.
    out["content"] = [{**c, "thumbnail_url": listed[c["asset_id"]].thumbnail_url,
                       "type": listed[c["asset_id"]].type,
                       "products": listed[c["asset_id"]].products,
                       "age_band": listed[c["asset_id"]].age_band}
                      for c in out["content"] if c["asset_id"] in listed]
    # The same span just before, for the "+12% vs previous 30 days" on tiles.
    out["previous"] = None
    lo, hi = activity._parse(since), activity._parse(until) or activity._now()
    if lo:
        before = activity.leaderboard(events, since=(lo - (hi - lo)).isoformat(),
                                      until=lo.isoformat(), top=1)
        out["previous"] = before["totals"]
    return out
