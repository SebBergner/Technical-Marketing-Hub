"""Graph / SharePoint endpoints: diagnose access, then sync the catalogue."""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.config import settings
from backend.access import Perm
from backend.admin_auth import require_perm
from backend.deps import CurrentUser, get_repo, require_authenticated, require_curator
from backend.integrations.graph.client import (
    GraphClient, GraphError, GraphPermissionError, get_graph_client,
)
from backend.integrations.graph.sync import SOURCE_SYSTEM, sync_catalogue
from backend.integrations.graph.writeback import DEFAULT_LIMIT, backlog, write_back
from backend.repositories.base import AssetRepository

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/graph", tags=["graph"])

#: Who may look at or test the SharePoint integration (access audit,
#: 2026-10-30: these were open to anyone signed in, partners included).
RUN_SYNC = Depends(require_perm(Perm.RUN_SYNC))


def require_client() -> GraphClient:
    client = get_graph_client()
    if client is None:
        raise HTTPException(
            status_code=503,
            detail=("Microsoft Graph is not configured. Set GRAPH_TENANT_ID, "
                    "GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET and GRAPH_SITE_URL. "
                    "Pending the Entra ID app registration request to IT."),
        )
    return client


@router.get("/status", dependencies=[RUN_SYNC])
def status(repo: AssetRepository = Depends(get_repo)):
    """Cheap, credential-free: is Graph wired up, and how old is the mirror?

    `last_sync` matters because nothing refreshes it automatically yet -- the
    catalogue can be arbitrarily stale and look perfectly healthy.
    """
    state = getattr(repo, "sync_state", None)
    return {
        "configured": settings.graph_configured,
        "site_url": settings.graph_site_url,
        "library": settings.graph_list_name,
        "source_system": SOURCE_SYSTEM,
        "indexed": repo.count_source_rows(SOURCE_SYSTEM)
                   if hasattr(repo, "count_source_rows") else None,
        "last_sync": (state(SOURCE_SYSTEM) or {}).get("last_success_at") if state else None,
    }


@router.get("/verify", dependencies=[RUN_SYNC])
def verify(user: CurrentUser = Depends(require_authenticated),
           client: GraphClient = Depends(require_client)):
    """Run this FIRST when IT delivers credentials.

    Separates "bad credentials" from "missing per-site grant". Those two fail
    identically from the outside — a valid token plus 403 on everything — and
    telling them apart is the difference between a five-minute fix and a day
    spent debugging code that is not broken.
    """
    try:
        return client.verify_access()
    except GraphError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/sync", status_code=202)
def sync(full: bool = False, repo: AssetRepository = Depends(get_repo),
         actor: str = Depends(require_perm(Perm.RUN_SYNC)),
         client: GraphClient = Depends(require_client)):
    """Pull the Demo Catalog and replace the mirror -- in the background.

    Needs the curator role, or an Admin sign-in (2026-09-21 — see
    backend/admin_auth.py for why a shared credential is allowed to refresh a
    rebuildable mirror and nothing else). Portal-owned data — stable slugs,
    curation, the Value Roadmap index, counters — is untouched either way.

    Returns at once (D17, 2026-11-05). Reading three libraries and the
    Brightcove posters outlasts Azure's front end, which dropped the request
    (HTTP 499) while the sync went on to succeed, so the page said "failed"
    and invited a second click. The Admin page now polls /sync/state; the
    outcome is the Last attempt it already shows.
    """
    already = sync_running()
    sync_soon(repo, actor, full=full)
    return {"queued": True, "was_running": already}


@router.get("/sync/state", dependencies=[RUN_SYNC])
def sync_state(repo: AssetRepository = Depends(get_repo)):
    """For the Admin page while it waits: running yet, and the last attempt."""
    state = repo.sync_state(SOURCE_SYSTEM) if hasattr(repo, "sync_state") else {}
    return {"running": sync_running(repo),
            "last_attempt_at": state.get("last_attempt_at"),
            "last_attempt_ok": state.get("last_attempt_ok"),
            "last_error": state.get("last_error")}


#: One SharePoint sync at a time, whoever starts it -- the button, the daily
#: schedule, a new demo (2026-10-15). Two at once each replace the mirror
#: with what they read, and the later finisher's view wins.
#:
#: Across workers too (2026-11-05): the threading lock covers one gunicorn
#: worker, and the button, the schedule and a new demo can land in different
#: ones. So the run also holds a lock file on the shared data directory, the
#: way auto_sync does. A sync takes minutes, so the file counts as left by a
#: dead worker only after SYNC_STALE_SECONDS, and a second sync waits for
#: the first rather than giving up.
_run_lock = threading.Lock()
_queue = {"requested": False, "worker": False, "actor": None, "full": False}
_queue_lock = threading.Lock()
LOCK_NAME = "sharepoint_sync"
SYNC_STALE_SECONDS = 3 * 3600
SYNC_WAIT_SECONDS = 3 * 3600


def _lock_path(repo: AssetRepository | None) -> str:
    import os
    owned = getattr(repo, "owned_dir", None) or os.path.join(settings.data_dir, "owned")
    return os.path.join(owned, LOCK_NAME)


@contextmanager
def _exclusive(repo: AssetRepository):
    """This worker's turn, then every worker's."""
    from backend.file_safety import locked
    with _run_lock, locked(_lock_path(repo), wait=SYNC_WAIT_SECONDS,
                           stale=SYNC_STALE_SECONDS):
        yield


def sync_running(repo: AssetRepository | None = None) -> bool:
    """A sync is running or waiting to run, in this worker or another
    (for "indexing…" on the page)."""
    from backend.file_safety import held
    with _queue_lock:
        if _run_lock.locked() or _queue["worker"]:
            return True
    return held(_lock_path(repo), SYNC_STALE_SECONDS)


def sync_soon(repo: AssetRepository, actor: str, full: bool = False) -> None:
    """Index soon, in the background, and never drop the request.

    Started at once when nothing is running. When a sync is running -- which
    began before whatever the caller just created, so cannot see it -- one
    more follows it. Requests made meanwhile share that one follow-up, which
    is a full sync if any of them asked for one."""
    with _queue_lock:
        _queue["requested"], _queue["actor"] = True, actor
        _queue["full"] = _queue["full"] or full
        if _queue["worker"]:
            return
        _queue["worker"] = True

    def worker():
        while True:
            # The turn first, then the request: whatever was asked while the
            # running sync went on is answered by this one run.
            ran = False
            try:
                with _exclusive(repo):
                    with _queue_lock:
                        if not _queue["requested"]:
                            _queue["worker"] = False
                            return
                        _queue["requested"] = False
                        who, everything = _queue["actor"], _queue["full"]
                        _queue["full"] = False
                    client = get_graph_client()
                    if client is not None:
                        _run_sync(client, repo, f"queued for {who}", everything)
                        ran = True
            except Exception:                                # noqa: BLE001
                log.exception("queued sync failed; the next one picks the change up")
                with _queue_lock:
                    if not _queue["requested"]:
                        _queue["worker"] = False
                        return
            if ran:
                _after(repo)

    threading.Thread(target=worker, daemon=True, name="hub-sync-soon").start()


def run_sync(client: GraphClient, repo: AssetRepository, actor: str,
             full: bool = False) -> dict:
    """The sync itself, shared by the queue and the daily schedule
    (backend/auto_sync.py), so the two can never drift apart. Records the
    attempt either way and re-raises a failure for the caller to report.
    One at a time (_exclusive): a second caller waits for the first."""
    with _exclusive(repo):
        result = _run_sync(client, repo, actor, full)
    _after(repo)
    return result


def _after(repo: AssetRepository) -> None:
    """What follows a successful sync, outside the lock."""
    # Rows the Hub Tasks list missed (Graph was down) go again now.
    from backend.integrations.graph import hub_tasks
    hub_tasks.flush_soon(repo)
    # SharePoint-hosted pictures fetched ahead of the first viewer.
    from backend.services import thumbnails
    thumbnails.warm_soon(repo)
    # And Create New Demo's options, ahead of the next person opening it.
    from backend.integrations.graph import upload_writer
    upload_writer.warm_soon()


def _run_sync(client: GraphClient, repo: AssetRepository, actor: str,
              full: bool = False) -> dict:
    from backend.integrations.graph.sync import MAPPING_VERSION
    state = repo.sync_state(SOURCE_SYSTEM) if hasattr(repo, "sync_state") else {}
    # A mirror built by an older mapping is rebuilt in full once, whatever
    # delta says (sync.MAPPING_VERSION).
    stale = state.get("mapping_version") != MAPPING_VERSION
    token = None if (full or stale) else _load_token(repo)
    try:
        result = sync_catalogue(client, repo, delta_token=token)
    except (GraphPermissionError, GraphError, ValueError) as exc:
        _record_attempt(repo, ok=False, error=str(exc))
        raise

    _save_token(repo, result.delta_token)
    if hasattr(repo, "set_sync_field"):
        repo.set_sync_field(SOURCE_SYSTEM, "mapping_version", MAPPING_VERSION)
    summary = result.as_dict()
    summary["vm_pages"] = _sync_vm_pages(client, repo)
    summary["demo_video"] = _sync_demo_video(client, repo)
    summary["gxc_video"] = _sync_gxc_video(client, repo)
    summary["demo_pages"] = _sync_demo_pages(client, repo)
    summary["partner_access"] = _sync_partner_access(client, repo)
    _record_attempt(repo, ok=True, summary=summary)
    log.info("graph sync by %s: %s", actor, summary)
    return summary


def _sync_vm_pages(client: GraphClient, repo: AssetRepository) -> dict:
    """The VM pages ride along with the catalogue sync, and fail alone.

    Same site, same credentials, same button on the Admin page -- but a
    different source, so a problem reading pages must not undo a catalogue
    sync that has already succeeded. The outcome is reported inside the
    summary either way, so a failure is visible rather than silent.
    """
    from backend.integrations.graph.vm_pages import sync_vm_pages
    try:
        site = client.resolve_site(settings.graph_site_url)
        return {"ok": True, **sync_vm_pages(client, repo, site).as_dict()}
    except Exception as exc:                                 # noqa: BLE001
        log.exception("vm page sync failed")
        return {"ok": False, "error": str(exc)[:300]}


def _sync_partner_access(client: GraphClient, repo: AssetRepository) -> dict:
    """Which demo folders the partner group may download from: read after
    the libraries, failing alone (partner_access.py)."""
    from backend.integrations.graph.partner_access import sync_partner_access
    if not hasattr(repo, "replace_partner_access"):
        return {"ok": None, "skipped": "repository has no partner access store"}
    try:
        site = client.resolve_site(settings.graph_site_url)
        return {"ok": True, **sync_partner_access(client, repo, site).as_dict()}
    except Exception as exc:                                 # noqa: BLE001
        log.exception("partner access sync failed")
        return {"ok": False, "error": str(exc)[:300]}


def _sync_demo_pages(client: GraphClient, repo: AssetRepository) -> dict:
    """The Demo Catalog's pages (SitePages/Demo Catalog/), the same way: their
    own source, failing alone. A page adds its thumbnail and link to its
    folder's demo, or is a page-only demo (demo_pages.py)."""
    from backend.integrations.graph.demo_pages import sync_demo_pages
    try:
        site = client.resolve_site(settings.graph_site_url)
        return {"ok": True, **sync_demo_pages(client, repo, site).as_dict()}
    except Exception as exc:                                 # noqa: BLE001
        log.exception("demo pages sync failed")
        return {"ok": False, "error": str(exc)[:300]}


def _sync_demo_video(client: GraphClient, repo: AssetRepository) -> dict:
    """The "Demo Video" library, the same way: its own source, failing alone.

    Blank `graph_video_library` switches it off (reported as skipped).
    """
    from backend.integrations.graph.video_sync import sync_videos
    if not settings.graph_video_library:
        return {"ok": None, "skipped": "not configured"}
    try:
        site = client.resolve_site(settings.graph_site_url)
        return {"ok": True, **sync_videos(client, repo, site).as_dict()}
    except Exception as exc:                                 # noqa: BLE001
        log.exception("demo video sync failed")
        return {"ok": False, "error": str(exc)[:300]}


def _sync_gxc_video(client: GraphClient, repo: AssetRepository) -> dict:
    """"GXC Video" (2026-10-29): the same as Demo Video, into its own mirror,
    failing alone. Blank `graph_gxc_library` switches it off."""
    from backend.integrations.graph.video_sync import GXC_VIDEO, sync_videos
    if not GXC_VIDEO.name:
        return {"ok": None, "skipped": "not configured"}
    try:
        site = client.resolve_site(settings.graph_site_url)
        return {"ok": True, **sync_videos(client, repo, site, which=GXC_VIDEO).as_dict()}
    except Exception as exc:                                 # noqa: BLE001
        log.exception("gxc video sync failed")
        return {"ok": False, "error": str(exc)[:300]}


def _record_attempt(repo: AssetRepository, ok: bool, summary: dict | None = None,
                    error: str | None = None) -> None:
    """Best-effort: a repository without the method (SQL) must not turn a
    successful sync into a 500 over a status line nobody has read yet."""
    recorder = getattr(repo, "record_sync_attempt", None)
    if recorder is None:
        return
    try:
        recorder("sharepoint", ok=ok, summary=summary, error=error)
        # And one line in the history, so the Admin page can show how the last
        # thirty runs went rather than only how the last one did.
        historian = getattr(repo, "record_sync_run", None)
        if historian:
            historian("sharepoint", ok=ok, summary=summary, error=error)
    except Exception:                                    # noqa: BLE001
        log.warning("could not record the sync attempt", exc_info=True)


@router.get("/writeback/backlog", dependencies=[RUN_SYNC])
def writeback_backlog(repo: AssetRepository = Depends(get_repo)):
    """What write-back would push, without calling Graph. Credential-free."""
    return backlog(repo)


@router.post("/writeback")
def writeback(dry_run: bool = True,
              limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=500),
              repo: AssetRepository = Depends(get_repo),
              # Authorisation BEFORE the configuration gate, and the order is
              # load-bearing: FastAPI resolves these in the order they are
              # declared, so with require_client first an unconfigured
              # deployment answered 503 to everyone -- telling an anonymous
              # caller about our Graph setup, and leaving the curator check
              # unproven on any environment without credentials. CI has none,
              # which is how this was caught (2026-09-22).
              user: CurrentUser = Depends(require_curator),
              client: GraphClient = Depends(require_client)):
    """Push accepted proposals into SharePoint columns. Requires curator.

    **Dry run by default.** Pass `dry_run=false` to actually write. This is the
    only endpoint that modifies a system of record, and the values it writes
    come from a matcher that produced confident false positives before it was
    tightened — so seeing the plan first is worth one extra call per item.

    Never overwrites an existing value: an item whose column already holds
    something different is reported as a conflict and left alone.
    """
    try:
        result = write_back(client, repo, changed_by=user.email,
                            dry_run=dry_run, limit=limit)
    except GraphPermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail=(f"{exc} If reads work and only writes fail, the per-site grant "
                    f"is read-only and IT must raise it to 'write'.")) from exc
    except GraphError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if result.aborted:
        # A missing column is a setup problem that would fail identically for
        # every item, so it is an error rather than a run with 50 failures.
        raise HTTPException(status_code=409, detail=result.aborted)

    if not dry_run and result.items:
        log.info("write-back by %s: %s", user.email, result.counts())
    return result.as_dict()


# The delta cursor is Portal-owned state. It lives beside the other owned data
# rather than in the mirror, which sync is entitled to wipe.
def _load_token(repo: AssetRepository) -> str | None:
    getter = getattr(repo, "get_sync_token", None)
    return getter(SOURCE_SYSTEM) if getter else None


def _save_token(repo: AssetRepository, token: str | None) -> None:
    setter = getattr(repo, "set_sync_token", None)
    if setter and token:
        setter(SOURCE_SYSTEM, token)
