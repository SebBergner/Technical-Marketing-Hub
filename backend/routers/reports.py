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
from backend.services import support_reports as sr

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
    # A GXC video unlisted for this person would still show its id, which
    # is its title (2026-10-29): its use is left out for them altogether.
    if not getattr(repo, "gxc", True):
        events = [e for e in events if not (e.get("asset_id") or "").startswith("gxc-")]
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
    def with_cards(items):
        return [{**c, "thumbnail_url": listed[c["asset_id"]].thumbnail_url,
                 "type": listed[c["asset_id"]].type,
                 "products": listed[c["asset_id"]].products,
                 "age_band": listed[c["asset_id"]].age_band}
                for c in items if c["asset_id"] in listed]
    out["content"] = with_cards(out["content"])
    for row in out["creators"]:
        row["content"] = with_cards(row["content"])
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
#: Columns a SharePoint demo should have filled, as the Data Clean list
#: counts them (2026-10-28): (key, words). Consensus demos are read-only
#: here, so they are never asked for these.
_MISSING = [("demo_owner", "Demo owner"), ("publish_date", "Publish date"),
            ("customer_facing", "Customer facing"), ("has_narrated_audio", "Narrated audio"),
            ("language", "Language"), ("product_version", "Product version"),
            ("named_customer", "Named customer")]


async def _reviewer(request: Request) -> CurrentUser:
    """Maintain content (Review and Archive content until 2026-10-30)."""
    user = principal_from_request(request)
    if user.can(Perm.MAINTAIN.value):
        return user
    if user.is_authenticated:
        raise HTTPException(status_code=403,
                            detail="Content to review needs Maintain content.")
    raise HTTPException(status_code=401, detail="Sign-in required.")


def _is_mine(asset, user: CurrentUser, my_segments: frozenset = frozenset()) -> bool:
    """Who made it, as the Hub credits it (A4): the DemoOwner column, the
    person a Hub upload was submitted for, else the files' creator, which
    SharePoint writes "Last, First". With no owner, also the owners of its
    segment on Admin -> Report owners (`my_segments`; Liwei, 2026-10-29),
    the segment counted as a report about it would be."""
    mine = {e for e in (user.email, user.username) if e}
    mine = {e.lower() for e in mine}
    owner = asset.demo_owner or asset.submitted_by
    if owner:
        return owner.lower() in mine
    if my_segments and sr.route_segment(asset.segment) in my_segments:
        return True
    if not asset.creator or not user.name:
        return False
    last, _, first = asset.creator.partition(",")
    as_written = f"{first.strip()} {last.strip()}".strip().lower()
    return user.name.strip().lower() in (as_written, asset.creator.strip().lower())


def _missing(record: dict) -> list[str]:
    """What a SharePoint demo leaves empty (the Data Clean list's checks)."""
    if record.get("source") != "sharepoint":
        return []
    assumed = set(record.get("assumed") or [])
    video = str(record.get("id") or "").startswith("video-")    # the Demo Video library
    gaps = {"demo_owner": not record.get("demo_owner"),
            "publish_date": not record.get("date_stated"),
            "customer_facing": "customer_facing" in assumed
                               or bool(record.get("customer_facing_stated_yes")),
            "has_narrated_audio": "has_narrated_audio" in assumed,
            "language": "language" in assumed,
            "product_version": video and not record.get("product_version"),
            "named_customer": video and record.get("video_subtype") == "Customer"
                              and not record.get("named_customer")}
    return [key for key, _ in _MISSING if gaps[key]]


@router.get("/content-to-review")
def content_to_review(user: CurrentUser = Depends(_reviewer),
                      repo: AssetRepository = Depends(get_repo)):
    """Every demo the Hub lists (A6, Liwei 2026-10-23/28), with its age, when
    anyone last opened, previewed or downloaded it -- no figures about who --
    and why it may need a look (2026-10-28):

    * `reasons`: Admin -> Content review's own rules -- collecting dust,
      little used, Still current running out -- so the two pages agree;
    * `missing`: the columns the Data Clean list counts as empty.

    Every demo is listed, with or without a reason; `mine` marks the ones
    credited to the person asking. `archived` lists what is archived, to
    restore from here (Liwei 2026-10-30: the team archives here, and may not
    open Admin)."""
    from datetime import date as _date, timedelta as _td
    from backend.repositories.base import AssetQuery as _Q
    from backend.routers.admin import (REVIEW_EXPIRING_DAYS, REVIEW_IDLE_DAYS,
                                       REVIEW_MIN_AGE_DAYS)
    from backend.services import content_age
    from backend.services.metadata_edit import NotEditable, target_key

    reader = getattr(repo, "usage_events", None)
    events = reader() if reader else []
    last_used: dict[str, str] = {}
    for e in events:
        aid = e.get("asset_id")
        if aid and e.get("event") in _USE_EVENTS:
            last_used[aid] = max(last_used.get(aid, ""), e.get("at") or "")
    records = repo.listed_records() if hasattr(repo, "listed_records") else {}
    today = _date.today()
    me = {e.lower() for e in (user.email, user.username) if e}
    my_segments = frozenset(s for s, people in sr.owners(repo).items()
                            if any((p.get("email") or "").lower() in me for p in people))
    idle_from = (today - _td(days=REVIEW_IDLE_DAYS)).isoformat()
    soon = (today + _td(days=REVIEW_EXPIRING_DAYS)).isoformat()
    lately = (today - _td(days=REVIEW_EXPIRING_DAYS)).isoformat()

    def reasons(a) -> list[dict]:
        out = []
        until = str(a.still_current_until) if a.still_current_until else None
        if until and lately <= until <= soon:
            out.append({"key": "still_current", "until": until,
                        "label": "Still current " + ("ended" if until < today.isoformat()
                                                     else "ends soon")})
        if until:
            return out
        if content_age.collecting_dust(a.uploaded_at, today):
            out.append({"key": "dust", "label": "Collecting dust",
                        "why": f"{content_age.DUST_YEARS}+ years old, not confirmed Still current"})
        elif a.uploaded_at and (today - a.uploaded_at).days >= REVIEW_MIN_AGE_DAYS                 and (last_used.get(a.id) or "") < idle_from:
            out.append({"key": "idle", "label": "Little used",
                        "why": f"Over a year old; not used in the last "
                               f"{REVIEW_IDLE_DAYS // 30} months"})
        return out

    def moves(a) -> bool:
        """Whether archiving moves its folder: a SharePoint demo the Hub can
        edit (Demo Catalog, Demo Video, GXC Video), as the archive route."""
        try:
            return bool(target_key(a.model_dump(mode="json")))
        except NotEditable:
            return False

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
            "mine": _is_mine(a, user, my_segments),
            "in_sharepoint": moves(a),
            "still_current_until": str(a.still_current_until) if a.still_current_until
                                   else None,
            "reasons": reasons(a),
            "missing": _missing(records.get(a.id) or {})})
    # Never used first, then the longest unused; within those, the oldest.
    rows.sort(key=lambda r: (r["last_used"] or "", r["uploaded_at"] or ""))
    try:
        archived = repo.archived()
    except NotImplementedError:
        archived = []
    return {"items": rows, "archived": archived,
            "usage_since": (events[0].get("at") or "")[:10] if events else None,
            "still_current_months": settings.still_current_months,
            "missing_labels": dict(_MISSING),
            "idle_days": REVIEW_IDLE_DAYS, "dust_years": content_age.DUST_YEARS}
