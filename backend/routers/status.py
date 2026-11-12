"""Release status: what a smoke test after a swap needs to see (Liwei, 2026-11-11).

The Admin page shows the same facts, but an API token can never hold View
Admin, so scripts/smoke_test.py could not read them. This one page gives any
signed-in person or token the facts that say whether a slot is healthy --
the build, when each source last synced and whether that worked, the daily
schedule, and the Hub's three display switches -- and nothing else: no
names, no error texts, no counts of hidden or PTC Only content.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from backend import auto_sync
from backend.auth import CurrentUser, require_authenticated
from backend.deps import get_repo
from backend.repositories.base import AssetRepository
from backend.version import app_version

router = APIRouter(prefix="/api/status", tags=["status"])

#: The sources a sync writes, in the order the report lists them.
SOURCES = ("sharepoint", "demo_video", "gxc_video", "consensus", "demo_pages", "vm_pages")


def _source(repo: AssetRepository, name: str) -> dict:
    state = repo.sync_state(name) if hasattr(repo, "sync_state") else {}
    return {"last_success_at": state.get("last_success_at"),
            "last_attempt_at": state.get("last_attempt_at"),
            "last_attempt_ok": state.get("last_attempt_ok")}


def _auto_sync() -> dict:
    state = auto_sync.load_state()
    upcoming = auto_sync.next_slot(state)
    last = state.get("last_run") or {}
    results = last.get("results") or {}
    return {"enabled": state["enabled"],
            "hours_utc": state["hours_utc"],
            "next_run_at": upcoming.isoformat(timespec="seconds") if upcoming else None,
            "last_run": {"started_at": last.get("started_at"),
                         "finished_at": last.get("finished_at"),
                         "ok": last.get("ok"),
                         "sources": {k: (v or {}).get("ok") for k, v in results.items()}}
            if last else None}


def _settings(repo: AssetRepository) -> dict | None:
    try:
        s = repo.hub_settings()
    except (AttributeError, NotImplementedError):
        return None
    return {k: s.get(k) for k in ("show_page_only_demos", "show_demo_page_links",
                                  "gxc_downloads")}


@router.get("")
def status(_: CurrentUser = Depends(require_authenticated),
           repo: AssetRepository = Depends(get_repo)):
    return {"version": app_version(),
            "sync": {name: _source(repo, name) for name in SOURCES},
            "auto_sync": _auto_sync(),
            "hub_settings": _settings(repo)}
