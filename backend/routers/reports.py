"""The Hub activity page's data, for every PTC employee (2026-10-14).

Serge (2026-10-13): reporting for all users, "top users vs laggers ...
healthy competition". Liwei (2026-10-14): the top N and team totals only --
no laggards -- and no partner data beyond a count of what was left out of
the ranking. Gated on "View Hub activity", a PTC-employees default.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from backend import access, activity
from backend.access import Perm
from backend.admin_auth import require_perm
from backend.auth import CurrentUser, principal_from_request
from backend.config import settings
from backend.deps import get_repo
from backend.repositories.base import AssetQuery, AssetRepository

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/library", dependencies=[Depends(require_perm(Perm.VIEW_REPORTS))])
def library(repo: AssetRepository = Depends(get_repo)):
    """What the Hub holds, for the Dashboard (Serge, 2026-10-23): how much of
    each kind, by product, segment, language and age, and month by month.
    Not how complete the metadata is -- that stays on the Admin page."""
    from backend.services import content_dashboard
    return content_dashboard.library(repo)


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
    creators = {k: a.creator for k, a in listed.items() if a.creator}
    out = activity.leaderboard(events, since=since, until=until, top=top,
                               titles=titles, teams=teams, creators=creators)
    # Creators come from SharePoint, written by a full sync (MAPPING_VERSION
    # 3). With none at all, the page says to sync rather than "nobody's demos
    # were used" (2026-10-14).
    out["creators_known"] = bool(creators)
    # Only content the Hub still lists, so a link never leads to a 404; with
    # its picture and type for the page's cards.
    # Usage by asset type (the Dashboard, Serge 2026-10-23): what each kind
    # of content was used for, so videos and kits can be compared.
    by_type: dict[str, dict] = {}
    for aid, c in out.pop("used").items():
        if aid not in listed:
            continue
        kind = getattr(listed[aid].type, "value", listed[aid].type)
        row = by_type.setdefault(kind, {"type": kind, "views": 0, "downloads": 0, "demos": 0})
        row["views"] += c["views"]
        row["downloads"] += c["downloads"]
        row["demos"] += 1
    out["by_type"] = sorted(by_type.values(), key=lambda r: -(r["views"] + r["downloads"]))
    out["content"] = [{**c, "thumbnail_url": listed[c["asset_id"]].thumbnail_url,
                       "type": listed[c["asset_id"]].type,
                       "products": listed[c["asset_id"]].products,
                       "age_band": listed[c["asset_id"]].age_band}
                      for c in out["content"] if c["asset_id"] in listed]
    # When PTC people were first counted by name (2026-10-16): production's log
    # before that day names nobody, so a period reaching further back shows
    # fewer people than used the Hub, and the page says from when it counts.
    named = [e.get("at") for e in events if e.get("user") and not e.get("external")]
    first = min(named) if named else None
    out["named_since"] = first[:10] if first and (not since or first > since) else None
    # The same span just before, for the "+12% vs previous 30 days" on tiles.
    out["previous"] = None
    lo, hi = activity._parse(since), activity._parse(until) or activity._now()
    if lo:
        before = activity.leaderboard(events, since=(lo - (hi - lo)).isoformat(),
                                      until=lo.isoformat(), top=1)
        out["previous"] = before["totals"]
    return out


# ──────────────────────────────────────────────────── content to review
_USE_EVENTS = ("view", "preview", "download")


async def _reviewer(request: Request) -> CurrentUser:
    """Review content or Archive content: the two things done from the list."""
    user = principal_from_request(request)
    if user.can(Perm.REVIEW_CONTENT.value) or user.can(Perm.ARCHIVE.value):
        return user
    if user.is_authenticated:
        raise HTTPException(status_code=403, detail="Content to review needs Review "
                            "content or Archive content.")
    raise HTTPException(status_code=401, detail="Sign-in required.")


def _is_mine(asset, user: CurrentUser) -> bool:
    """Who made it, as the Hub credits it (A4): the DemoOwner column, the
    person a Hub upload was submitted for, else the files' creator, which
    SharePoint writes "Last, First"."""
    mine = {e for e in (user.email, user.username) if e}
    mine = {e.lower() for e in mine}
    owner = asset.demo_owner or asset.submitted_by
    if owner:
        return owner.lower() in mine
    if not asset.creator or not user.name:
        return False
    last, _, first = asset.creator.partition(",")
    as_written = f"{first.strip()} {last.strip()}".strip().lower()
    return user.name.strip().lower() in (as_written, asset.creator.strip().lower())


@router.get("/content-to-review")
def content_to_review(user: CurrentUser = Depends(_reviewer),
                      repo: AssetRepository = Depends(get_repo)):
    """Every demo the Hub lists, least recently used first (A6, Liwei
    2026-10-23/28): its age and when anyone last opened, previewed or
    downloaded it -- no threshold, the team decides -- and no figures about
    who used it. `mine` marks the demos credited to the person asking."""
    from backend.repositories.base import AssetQuery as _Q
    reader = getattr(repo, "usage_events", None)
    events = reader() if reader else []
    last_used: dict[str, str] = {}
    for e in events:
        aid = e.get("asset_id")
        if aid and e.get("event") in _USE_EVENTS:
            last_used[aid] = max(last_used.get(aid, ""), e.get("at") or "")
    rows = []
    for a in repo.list(_Q(limit=10 ** 6, include_older_vms=True)).items:
        rows.append({
            "asset_id": a.id, "title": a.title, "type": a.type,
            "products": a.products, "segment": a.segment,
            "uploaded_at": str(a.uploaded_at) if a.uploaded_at else None,
            "date_stated": a.date_stated,
            "age_band": a.age_band,
            "last_used": (last_used.get(a.id) or "")[:10] or None,
            "owner": a.demo_owner or a.submitted_by or a.creator,
            "mine": _is_mine(a, user),
            "in_sharepoint": a.source == "sharepoint",
            "still_current_until": str(a.still_current_until) if a.still_current_until
                                   else None})
    # Never used first, then the longest unused; within those, the oldest.
    rows.sort(key=lambda r: (r["last_used"] or "", r["uploaded_at"] or ""))
    return {"items": rows, "usage_since": (events[0].get("at") or "")[:10] if events else None,
            "still_current_months": settings.still_current_months}
