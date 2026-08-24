import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.config import settings
from backend.db import SessionLocal, create_all
from backend.routers import assets, consensus, curation, debug, graph, taxonomy

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Seed an empty catalogue so a fresh clone just runs.

    Seeding only happens when the catalogue is empty, so it never overwrites
    real data once Graph sync is populating it.
    """
    from backend.deps import build_repo
    from backend.repositories.base import AssetQuery
    from backend.seed import load_seed

    if settings.storage_backend == "sql":
        create_all()

    repo = build_repo()
    if repo.list(AssetQuery(limit=1)).total == 0 and os.path.exists(settings.seed_path):
        result = load_seed(repo)
        print(f"[startup] seeded {result['assets']} assets "
              f"({result['roadmaps']} roadmaps, {result['curation']} curated) "
              f"via {settings.storage_backend} backend")
    yield


app = FastAPI(
    title="TDD Portal",
    description="Unified catalogue for PTC Technical Demo Development content.",
    version="0.2.0",
    lifespan=lifespan,
)

app.include_router(assets.router)
app.include_router(taxonomy.router)
app.include_router(consensus.router)
app.include_router(curation.router)
app.include_router(graph.router)
app.include_router(debug.router)


@app.get("/debug", include_in_schema=False)
async def debug_page():
    """Plain data inspector. Separate from index.html on purpose — that file is
    Elio's, and the two must not collide."""
    return FileResponse(os.path.join(BASE_DIR, "static", "debug.html"))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def index():
    return FileResponse(os.path.join(BASE_DIR, "index.html"))
