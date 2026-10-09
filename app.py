import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from backend.config import settings
from backend.version import app_version
from backend.db import SessionLocal, create_all
from backend import oidc
from backend.routers import (
    admin, assets, auth, consensus, curation, debug, graph, migration, requests,
    segments, taxonomy, vms,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Seed an empty catalogue ONLY when there is no way to fetch a real one.

    The seed is a 452-asset snapshot of an xlsx export, so a fresh clone with
    no credentials still runs and shows something. Once credentials exist it is
    the wrong answer, and it used to be loaded whenever the catalogue happened
    to be empty -- which meant deleting data/runtime silently resurrected stale
    data, and left both the seed and the live sync present at once. That cost
    two real bugs: 907 rows for 455 assets, then 288 assets retired by mistake.

    So it is now conditional on the sources being unreachable rather than on
    the catalogue being empty. Configured credentials means sync is the answer,
    and an empty catalogue that says so is more honest than a stale full one.
    """
    from backend.auth import log_security_warnings
    from backend.deps import build_repo

    log_security_warnings()
    # Partners are anonymous in the activity records (2026-10-09); this drops
    # identity written before that, and does nothing once the files are clean.
    from backend import activity
    try:
        activity.scrub_partners()
    except Exception:                                      # noqa: BLE001
        logging.getLogger(__name__).exception("could not scrub partner identity")
    from backend.repositories.base import AssetQuery
    from backend.seed import load_seed

    if settings.storage_backend == "sql":
        create_all()

    repo = build_repo()
    empty = repo.list(AssetQuery(limit=1)).total == 0
    can_fetch = settings.graph_configured or settings.consensus_configured

    if empty and can_fetch:
        print("[startup] catalogue is empty and credentials are set — "
              "POST /api/graph/sync and /api/consensus/sync to populate it "
              "(buttons on /admin)")
    elif empty and os.path.exists(settings.seed_path):
        result = load_seed(repo)
        print(f"[startup] no source credentials — seeded {result['assets']} assets "
              f"from the xlsx snapshot. This data is STALE; it exists so a fresh "
              f"clone runs. Configure GRAPH_* / CONSENSUS_* and sync for real data.")

    # The daily sync's loop. It only syncs when switched on from the Admin
    # page -- see backend/auto_sync.py.
    task = None
    if settings.auto_sync_scheduler:
        import asyncio
        from backend import auto_sync
        task = asyncio.create_task(auto_sync.scheduler())
    # A migration run started from /migration and interrupted by a restart
    # carries on from its batch log (backend/services/migration_jobs.py).
    # Only where runs are enabled; it returns at once and runs in a thread.
    if settings.migration_runner_enabled:
        from backend.services import migration_jobs
        migration_jobs.auto_resume()
    yield
    if task:
        task.cancel()


app = FastAPI(
    title="TDD Portal",
    description="Unified catalogue for PTC Technical Demo Development content.",
    version="0.2.0",
    lifespan=lifespan,
)

app.include_router(auth.router)
app.include_router(assets.router)
app.include_router(taxonomy.router)
app.include_router(segments.router)
app.include_router(requests.router)
app.include_router(consensus.router)
app.include_router(curation.router)
app.include_router(graph.router)
app.include_router(debug.router)
app.include_router(admin.router)
app.include_router(migration.router)
app.include_router(oidc.router)
app.include_router(vms.router)

# Middleware, innermost first. Starlette wraps each new one around the ones
# already added, so the order below is the reverse of the order a request
# meets them in: canonical_host, then the session, then the sign-in gate.
# The gate must sit inside SessionMiddleware because it reads the session;
# the host redirect sits outside everything, so a request on the wrong host
# never touches a cookie at all.
#
# All three are installed in every AUTH_MODE and decide per request whether
# to act, so switching mode is a setting and a restart, never a code change.
# Outside oidc mode the session is never written, so no cookie is ever set.
app.middleware("http")(oidc.require_sign_in)
app.add_middleware(
    SessionMiddleware,
    secret_key=oidc.session_secret(),
    session_cookie=oidc.SESSION_COOKIE,
    max_age=settings.session_timeout_hours * 3600,
    # lax, not strict: the return from Microsoft is a top-level navigation
    # from another site, and strict would withhold the very cookie that
    # holds the sign-in being completed.
    same_site="lax",
    https_only=settings.https_only,
)
app.middleware("http")(oidc.canonical_host)


@app.get("/admin", include_in_schema=False)
async def admin_page():
    """The Admin page. Its own file because it is ours, index.html is
    Elio's, and the two must not collide.

    Served to anyone — the page itself decides what to show, and every figure
    on it comes from /api/admin/overview, which does not."""
    return FileResponse(os.path.join(BASE_DIR, "static", "admin.html"))


@app.get("/migration", include_in_schema=False)
async def migration_page():
    """Content migrations into SharePoint, one section per source
    (Brightcove Gallery first). Its own page, like /admin, and not linked
    from index.html or /admin (Liwei, 2026-09-28).

    Served to anyone for the same reason as /admin: the page decides what to
    show, and every figure on it comes from /api/migration/..., which is
    behind the admin sign-in.

    `no-cache` for the reason RevalidatingStatic gives below: without it the
    browser kept serving a superseded copy of this page after it changed
    (seen 2026-09-28, a new element missing from the DOM while the server
    was already returning it)."""
    return FileResponse(os.path.join(BASE_DIR, "static", "migration.html"),
                        headers={"Cache-Control": "no-cache"})


# /debug, the plain data inspector, was removed 2026-09-28 for security at
# Liwei's request: it was served to anyone, with buttons for sync and
# SharePoint write-back. Its duties live on /admin, behind the admin sign-in.
# /api/debug/backend (the read-only diagnostics) is unchanged.
class RevalidatingStatic(StaticFiles):
    """Static files that must be revalidated on every request.

    Without this the browser applies its own heuristic freshness and happily
    serves a stale script for minutes. That cost real time here -- the page
    kept running a superseded hub-api.js while the file on disk and the one the
    server returned were both current -- and it would cost Elio the same every
    time he edits and reloads.

    `no-cache` is not `no-store`: the response is still cached and still
    revalidated with an ETag, so an unchanged file is a 304 and costs nothing.
    """

    def is_not_modified(self, response_headers, request_headers) -> bool:
        return super().is_not_modified(response_headers, request_headers)

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/static", RevalidatingStatic(directory=os.path.join(BASE_DIR, "static")),
          name="static")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/version")
async def version():
    """What the sidebar prints, bottom-left beside the PTC mark.

    Public, and deliberately so: it is the first thing to ask for when
    somebody reports a problem, and requiring a sign-in to find out which
    build you are on would defeat the reason it is on screen at all.
    """
    return {"version": app_version()}


@app.get("/")
async def index():
    """Elio's UI, fed from the live API by static/hub-api.js.

    The file itself is his and arrives from the Elio-UI-Development branch
    essentially unchanged; the integration is one script tag at the bottom, so
    merging his next revision stays trivial.
    """
    return FileResponse(os.path.join(BASE_DIR, "index.html"))
