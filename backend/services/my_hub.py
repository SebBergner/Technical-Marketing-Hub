"""My Hub: each person's favourites and recently viewed (A3; Liwei, 2026-11-12).

One small file per person, `owned/me/<digest>.json`, never one file for
everyone: a star or a view writes only its owner's file, so two people
never wait on each other, and nothing here can list what anyone else saved.

* **Who** is the Entra object id when there is one, else the address -- a
  partner has an object id and no usable address, and is never named here
  or in any report (Liwei, 2026-10-23). The file name is a digest of it, so
  the directory listing names nobody either.
* **Only the person** reads their file: there is no endpoint, Admin's
  included, that opens anyone else's.
* **Recently viewed** is kept here rather than read from the usage events:
  those record a partner only as "external", and partners have My Hub too.
  The last RECENT_KEEP demos, newest first, each once.
* Data stays with the slot, like everything under `owned/` (production's
  share stays production's across swaps).
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone

from backend.config import settings

RECENT_KEEP = 20            # Liwei, 2026-10-28
FAVORITES_MAX = 500
_lock = threading.Lock()


def user_key(user) -> str | None:
    """Whose file: the Entra object id, else the address; None for nobody
    (anonymous)."""
    if user is None or not (user.is_authenticated or user.is_dev_principal):
        return None
    if getattr(user, "object_id", None):
        return f"oid:{user.object_id}"
    who = (user.email or user.username or "").strip().lower()
    return f"email:{who}" if who else None


def _path(key: str, data_dir: str | None = None) -> str:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:40]
    return os.path.join(data_dir or settings.data_dir, "owned", "me", f"{digest}.json")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load(key: str, data_dir: str | None = None) -> dict:
    try:
        with open(_path(key, data_dir), encoding="utf-8") as fh:
            state = json.load(fh)
        return state if isinstance(state, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}


def _save(key: str, state: dict, data_dir: str | None = None) -> None:
    from backend.repositories.json_repo import _atomic_write
    path = _path(key, data_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _atomic_write(path, state)


def favorites(key: str, data_dir: str | None = None) -> list[str]:
    """Asset ids, most recently starred first."""
    return [f["id"] for f in load(key, data_dir).get("favorites") or []]


def set_favorite(key: str, asset_id: str, on: bool, data_dir: str | None = None) -> list[str]:
    with _lock:
        state = load(key, data_dir)
        kept = [f for f in state.get("favorites") or [] if f.get("id") != asset_id]
        if on:
            kept.insert(0, {"id": asset_id, "at": _now()})
        state["favorites"] = kept[:FAVORITES_MAX]
        _save(key, state, data_dir)
    return [f["id"] for f in state["favorites"]]


def note_view(key: str, asset_id: str, data_dir: str | None = None) -> None:
    """Put a demo at the front of recently viewed."""
    with _lock:
        state = load(key, data_dir)
        recent = [r for r in state.get("recent") or [] if r.get("id") != asset_id]
        recent.insert(0, {"id": asset_id, "at": _now()})
        state["recent"] = recent[:RECENT_KEEP]
        _save(key, state, data_dir)


def recent(key: str, data_dir: str | None = None) -> list[dict]:
    """[{id, at}], newest first."""
    return list(load(key, data_dir).get("recent") or [])
