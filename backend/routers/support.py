"""Reports about content and requests for help (A2; services/support_reports.py).

`/api/support` is for everyone who can view the Hub, partners included:
make a report, see your own and where they stand. `/api/admin/report-owners`
is Admin -> Report owners: who is told about each segment's reports, and how
many each has had.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.access import Perm
from backend.admin_auth import require_perm
from backend.auth import CurrentUser, get_current_user
from backend.deps import get_repo
from backend.repositories.base import AssetRepository
from backend.services import support_reports as sr

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/support", tags=["support"])
admin_router = APIRouter(prefix="/api/admin/report-owners", tags=["admin"])
VIEW_ADMIN = Depends(require_perm(Perm.VIEW_ADMIN))


class ReportIn(BaseModel):
    category: str
    details: str
    asset_id: str | None = None


@router.get("/options", dependencies=[Depends(require_perm(Perm.VIEW_HUB))])
def options():
    return {"categories": sr.CATEGORIES}


@router.post("/reports")
def submit(body: ReportIn, repo: AssetRepository = Depends(get_repo),
           actor: str = Depends(require_perm(Perm.VIEW_HUB)),
           user: CurrentUser = Depends(get_current_user)):
    asset = None
    if body.asset_id:
        asset = repo.get(body.asset_id)
        if asset is None:
            raise HTTPException(status_code=404, detail=f"no asset with id '{body.asset_id}'")
    try:
        record = sr.submit(repo, user, category=body.category, details=body.details, asset=asset)
    except sr.ReportError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    # The log says who for staff only: a partner stays "partner".
    log.info("report %s (%s) on %s by %s", record["id"], record["category"],
             record["asset_id"] or "-", record["reported_by"])
    return {"id": record["id"], "segment": record["segment"], "status": "Open"}


@router.get("/reports/mine", dependencies=[Depends(require_perm(Perm.VIEW_HUB))])
def mine(repo: AssetRepository = Depends(get_repo),
         user: CurrentUser = Depends(get_current_user)):
    return {"items": sr.mine(repo, user)}


# ─────────────────────────────────────────────── Admin -> Report owners
class Owner(BaseModel):
    name: str = ""
    email: str
    notify: bool = True


class OwnersIn(BaseModel):
    owners: list[Owner]


@admin_router.get("", dependencies=[VIEW_ADMIN])
def report_owners(repo: AssetRepository = Depends(get_repo)):
    lists, counts = sr.owners(repo), sr.counts(repo)
    return {"segments": [{"segment": s, "owners": lists[s], **counts[s]}
                         for s in sr.SEGMENTS + [sr.GENERAL]],
            "general": sr.GENERAL}


@admin_router.put("/{segment}")
def set_report_owners(segment: str, body: OwnersIn, repo: AssetRepository = Depends(get_repo),
                      actor: str = Depends(require_perm(Perm.MANAGE_USERS))):
    try:
        saved = sr.set_owners(repo, segment, [o.model_dump() for o in body.owners])
    except sr.ReportError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    log.info("report owners of %s set by %s: %d", segment, actor, len(saved))
    return {"segment": segment, "owners": saved}


@admin_router.get("/{segment}/reports", dependencies=[VIEW_ADMIN])
def segment_reports(segment: str, repo: AssetRepository = Depends(get_repo)):
    if segment not in sr.SEGMENTS + [sr.GENERAL]:
        raise HTTPException(status_code=404, detail=f"no segment {segment!r}")
    return {"segment": segment, "items": sr.by_segment(repo, segment)}
