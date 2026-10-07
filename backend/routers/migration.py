"""The Migration page's own endpoints: /api/migration/<source>/...

One page, /migration, for every content migration, so that each new one is a
section there rather than another top-level name (Liwei, 2026-09-28).
Brightcove Gallery is the first; its plan is docs/brightcove-migration-plan.md.

Who may use it: the "Run Brightcove migration" permission (backend/access.py,
2026-10-06; Administrators by default), or the shared admin sign-in while it
still exists. That includes STARTING a run, which writes to SharePoint. The
shared sign-in must therefore type an operator name, kept in the batch log; a
signed-in person is recorded by their own identity.
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from backend.access import Perm
from backend.admin_auth import require_perm
from backend.config import settings
from backend.integrations.graph.client import GraphClient, GraphError, get_graph_client
from backend.services import brightcove_migration as bc
from backend.services import migration_jobs as jobs

log = logging.getLogger(__name__)

#: Its own permission (Liwei, 2026-10-06): a run uploads to SharePoint.
RUN_MIGRATION = require_perm(Perm.RUN_MIGRATION)

router = APIRouter(prefix="/api/migration", tags=["migration"],
                   dependencies=[Depends(RUN_MIGRATION)])

#: Seb's V29 was 0.2 MB; this leaves room without inviting anything else.
MAX_SHEET_BYTES = 20 * 1024 * 1024


def graph_client_or_none() -> GraphClient | None:
    """A dependency so tests can hand in a MockTransport client."""
    return get_graph_client()


def _operator(actor: str, typed: str | None) -> str:
    """Who is starting this. A curator is who they signed in as; the shared
    admin sign-in has no identity of its own, so a name must be typed."""
    if actor.startswith(("user:", "dev:")):
        return actor.split(":", 1)[1]
    name = (typed or "").strip()
    if len(name) < 2:
        raise HTTPException(status_code=422,
                            detail="Signed in with the shared admin account: type your name "
                                   "as the operator, so this run can be traced to a person.")
    return name


@router.get("/brightcove/status")
def brightcove_status(client: GraphClient | None = Depends(graph_client_or_none),
                      actor: str = Depends(RUN_MIGRATION)):
    """Everything the Brightcove section shows, in one read-only call.

    Reads the whole library on every call. At the planned size (~260 demos,
    a few Graph pages) that is seconds; cache it only if measured slow.
    """
    name = settings.migration_brightcove_library
    library: dict = {"name": name, "found": None}
    summary = None
    error = None
    if client is not None:
        try:
            site_id = client.resolve_site().site_id
            items = bc.read_library(client, site_id, name)
            library["found"] = items is not None
            if items is not None:
                summary = bc.summarize(items)
        except GraphError as exc:
            error = str(exc)[:300]

    batches = bc.list_batches(library=name)
    latest = jobs.latest_page_run()
    return {
        "environment": {
            "site_name": os.getenv("WEBSITE_SITE_NAME") or "local",
            "slot": os.getenv("WEBSITE_SLOT_NAME") or "local",
        },
        "actor": {"kind": "admin-session" if actor == "admin-session" else "curator",
                  "name": actor.split(":", 1)[1] if ":" in actor else None},
        "runner_enabled": settings.migration_runner_enabled,
        "graph": {"configured": client is not None, "error": error},
        "library": library,
        "summary": summary,
        "plan": {"total": jobs.planned_total() or bc.plan_total(batches)},
        "batches": batches,
        "sheets": jobs.list_sheets(),
        "active_run": jobs.active_run(),
        "latest_run": jobs.run_status(latest) if latest else None,
    }


# ─────────────────────────────────────────────────────────────── sheets
@router.post("/brightcove/sheets")
async def upload_sheet(file: UploadFile = File(...), actor: str = Depends(RUN_MIGRATION)):
    """Keep the workbook, convert it, and start its preview. Writes nothing
    to SharePoint or Brightcove."""
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(status_code=415, detail="Upload the gallery workbook as .xlsx.")
    content = await file.read(MAX_SHEET_BYTES + 1)
    if len(content) > MAX_SHEET_BYTES:
        raise HTTPException(status_code=413, detail="That workbook is over 20 MB.")
    try:
        sheet_id = jobs.save_sheet(file.filename, content, uploaded_by=actor)
    except Exception as exc:                                # noqa: BLE001
        log.exception("sheet upload failed")
        raise HTTPException(status_code=422,
                            detail=f"The workbook could not be read: {str(exc)[:200]}") from exc
    return {"sheet_id": sheet_id}


@router.get("/brightcove/sheets/{sheet_id}")
def sheet_preview(sheet_id: str):
    preview = jobs.load_preview(sheet_id)
    if preview is None:
        raise HTTPException(status_code=404, detail="No such sheet.")
    return preview


@router.get("/brightcove/sheets/{sheet_id}/problems.csv", response_class=PlainTextResponse)
def sheet_problems(sheet_id: str):
    text = jobs.problems_csv(sheet_id)
    if text is None:
        raise HTTPException(status_code=404, detail="No finished preview for that sheet.")
    return PlainTextResponse(text, media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="migration-problems-{sheet_id}.csv"'})


# ─────────────────────────────────────────────────────────────── runs
class RunIn(BaseModel):
    sheet_id: str
    limit: int | None = None
    #: Optional since 2026-09-29: the library is fixed, so the page no
    #: longer asks for it to be typed. A name that is sent must still match.
    confirm_library: str | None = None
    operator: str | None = None
    #: Parallel uploads, 1-5 (Liwei: 3 to 5); the server clamps it.
    parallel: int = jobs.DEFAULT_PARALLEL


class ResumeIn(BaseModel):
    operator: str | None = None


@router.post("/brightcove/runs")
def start_run(body: RunIn, actor: str = Depends(RUN_MIGRATION)):
    operator = _operator(actor, body.operator)
    if body.limit is not None and body.limit < 1:
        raise HTTPException(status_code=422, detail="The limit must be at least 1.")
    try:
        batch_id = jobs.start_run(body.sheet_id, limit=body.limit, operator=operator, via=actor,
                                  confirm_library=body.confirm_library, parallel=body.parallel)
    except jobs.RunRefused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    log.info("migration run %s started by %s (%s)", batch_id, operator, actor)
    return {"batch_id": batch_id}


@router.get("/brightcove/runs/{batch_id}")
def run_progress(batch_id: str):
    status = jobs.run_status(batch_id)
    if status is None:
        raise HTTPException(status_code=404, detail="No such run.")
    return status


@router.post("/brightcove/runs/{batch_id}/pause")
def pause_run(batch_id: str, actor: str = Depends(RUN_MIGRATION)):
    if jobs.run_status(batch_id) is None:
        raise HTTPException(status_code=404, detail="No such run.")
    jobs.pause(batch_id)
    log.info("migration run %s pause requested (%s)", batch_id, actor)
    return {"pause_requested": True}


@router.post("/brightcove/runs/{batch_id}/resume")
def resume_run(batch_id: str, body: ResumeIn, actor: str = Depends(RUN_MIGRATION)):
    if jobs.run_status(batch_id) is None:
        raise HTTPException(status_code=404, detail="No such run.")
    operator = _operator(actor, body.operator)
    try:
        jobs.resume(batch_id, operator=operator, via=actor)
    except jobs.RunRefused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"resumed": True}
