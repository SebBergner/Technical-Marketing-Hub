import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.config import settings
from backend.db import SessionLocal, create_all
from backend.routers import (
    assets, auth, consensus, curation, debug, graph, requests, segments,
    taxonomy,
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
              "(buttons on /debug)")
    elif empty and os.path.exists(settings.seed_path):
        result = load_seed(repo)
        print(f"[startup] no source credentials — seeded {result['assets']} assets "
              f"from the xlsx snapshot. This data is STALE; it exists so a fresh "
              f"clone runs. Configure GRAPH_* / CONSENSUS_* and sync for real data.")
    yield


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


@app.get("/debug", include_in_schema=False)
async def debug_page():
    """Plain data inspector. Separate from index.html on purpose — that file is
    Elio's, and the two must not collide."""
    return FileResponse(os.path.join(BASE_DIR, "static", "debug.html"))
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


@app.get("/")
async def index():
    """Elio's UI, fed from the live API by static/hub-api.js.

    The file itself is his and arrives from the Elio-UI-Development branch
    essentially unchanged; the integration is one script tag at the bottom, so
    merging his next revision stays trivial.
    """
    return FileResponse(os.path.join(BASE_DIR, "index.html"))
