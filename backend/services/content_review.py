"""Content review: what to look at again (2026-10-14), shared by Content
health -> Content review (routers/content_health.py) and the rules of the
Hub's own Content to review (routers/reports.py). On the Admin page, in
routers/admin.py, until 2026-11-11.
"""
from __future__ import annotations

from backend.config import settings
from backend.repositories.base import AssetQuery
from backend.services.usage import events as _events_of

#: Defaults agreed 2026-10-07/14: Elio, "about a year old"; Seb, "not on age
#: alone -- recent views and downloads too"; Serge, 7 years = collecting dust.
REVIEW_MIN_AGE_DAYS = 365
REVIEW_IDLE_DAYS = 180
REVIEW_EXPIRING_DAYS = 30
_USE_EVENTS = ("view", "preview", "download")


def content_review(repo, min_age_days: int = REVIEW_MIN_AGE_DAYS,
                   idle_days: int = REVIEW_IDLE_DAYS) -> dict:
    """What to look at again (2026-10-14), in four lists:

    * collecting dust -- 7+ years old and not confirmed Still current;
    * little used -- at least `min_age_days` old, not confirmed, and nobody
      opened, previewed or downloaded it in the last `idle_days`;
    * Still current running out within REVIEW_EXPIRING_DAYS, or just ran out;
    * archived;
    * no longer sold (2026-11-03): demo kits and videos the Hub hides for a
      divested product, still in their library, to archive in SharePoint.

    Usage is only as long as the Hub has recorded it (`usage_since`): until
    that reaches `idle_days`, "little used" means "unused since recording
    began" and the page says so.
    """
    from datetime import date as _date, timedelta as _td
    from backend.services import content_age

    today = _date.today()
    events = _events_of(repo)
    usage_since = events[0].get("at") if events else None
    idle_from = (today - _td(days=idle_days)).isoformat()
    year_ago = (today - _td(days=365)).isoformat()
    last_used: dict[str, str] = {}
    counts: dict[str, dict] = {}
    for e in events:
        aid = e.get("asset_id")
        if not aid or e.get("event") not in _USE_EVENTS:
            continue
        at = e.get("at") or ""
        last_used[aid] = max(last_used.get(aid, ""), at)
        if at >= year_ago:
            c = counts.setdefault(aid, {"views": 0, "downloads": 0, "people": set()})
            c["views" if e["event"] != "download" else "downloads"] += 1
            if e.get("user"):
                c["people"].add(e["user"])

    reviews = repo.content_reviews() if hasattr(repo, "content_reviews") else {}
    everything = repo.list(AssetQuery(limit=10 ** 6, include_older_vms=True,
                                      include_archived=True)).items

    def row(a) -> dict:
        c = counts.get(a.id) or {}
        review = reviews.get(a.id) or {}
        return {"asset_id": a.id, "title": a.title, "type": a.type,
                "uploaded_at": str(a.uploaded_at) if a.uploaded_at else None,
                "age_band": a.age_band, "internal": a.internal,
                "last_used": (last_used.get(a.id) or "")[:10] or None,
                "views_12m": c.get("views", 0), "downloads_12m": c.get("downloads", 0),
                "people_12m": len(c.get("people") or ()),
                "still_current_until": review.get("until"),
                "still_current_by": review.get("by")}

    dust, idle, expiring = [], [], []
    soon = (today + _td(days=REVIEW_EXPIRING_DAYS)).isoformat()
    lately = (today - _td(days=REVIEW_EXPIRING_DAYS)).isoformat()
    for a in everything:
        if a.archived:
            continue
        until = (reviews.get(a.id) or {}).get("until")
        if until and lately <= until <= soon:
            expiring.append(row(a))
        if a.still_current_until:
            continue
        if content_age.collecting_dust(a.uploaded_at, today):
            dust.append(row(a))
        elif a.uploaded_at and (today - a.uploaded_at).days >= min_age_days \
                and (last_used.get(a.id) or "") < idle_from:
            idle.append(row(a))
    dust.sort(key=lambda r: r["uploaded_at"] or "")
    idle.sort(key=lambda r: (r["last_used"] or "", r["uploaded_at"] or ""))
    expiring.sort(key=lambda r: r["still_current_until"] or "")
    try:
        archived = repo.archived()
        divested = repo.divested()
    except NotImplementedError:
        archived, divested = [], []
    return {"dust": dust, "idle": idle, "expiring": expiring, "archived": archived,
            "divested": divested,
            "usage_since": usage_since, "min_age_days": min_age_days,
            "idle_days": idle_days, "dust_years": content_age.DUST_YEARS,
            "still_current_months": settings.still_current_months}
