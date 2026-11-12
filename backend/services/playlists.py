"""My Hub playlists (A3 phase 2; Liwei, 2026-10-23 and 2026-11-12).

Each playlist is one file, `owned/playlists/<id>.json`, apart from its
owner's My Hub file, because a shared link has to find it by its id alone.

* **Owner** is the owner's My Hub key (services/my_hub.user_key), kept only
  as a digest: no object id, no address. A PTC owner's display name is kept
  for the playlist page ("by Ann Lee"); a partner's never is (2026-10-23).
* **Only the owner** renames, reorders, adds, removes or deletes.
* **Anyone signed in** may open a shared link; they see only the demos they
  may open themselves, told how many others there are, and may "Save a
  copy" -- which copies only those.
* It is a list inside the Hub, not something to hand a customer: that is
  Consensus's DemoBoard (C2).
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
from datetime import datetime, timezone

from backend.config import settings

MAX_PER_PERSON = 100
MAX_ITEMS = 200
MAX_NAME = 80
_lock = threading.Lock()


class PlaylistError(ValueError):
    """Refused; the message is for the page."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def owner_digest(key: str) -> str:
    return hashlib.sha256(("playlist-owner:" + key).encode("utf-8")).hexdigest()[:32]


def _dir(data_dir: str | None = None) -> str:
    return os.path.join(data_dir or settings.data_dir, "owned", "playlists")


def _path(playlist_id: str, data_dir: str | None = None) -> str:
    if not playlist_id or not playlist_id.replace("-", "").isalnum():
        raise KeyError(playlist_id)
    return os.path.join(_dir(data_dir), f"{playlist_id}.json")


def get(playlist_id: str, data_dir: str | None = None) -> dict | None:
    try:
        with open(_path(playlist_id, data_dir), encoding="utf-8") as fh:
            return json.load(fh)
    except (KeyError, FileNotFoundError, ValueError):
        return None


def _save(record: dict, data_dir: str | None = None) -> None:
    from backend.repositories.json_repo import _atomic_write
    os.makedirs(_dir(data_dir), exist_ok=True)
    _atomic_write(_path(record["id"], data_dir), record)


def _clean_name(name: str | None) -> str:
    name = " ".join((name or "").split())[:MAX_NAME]
    if not name:
        raise PlaylistError("Give the playlist a name.")
    return name


def mine(key: str, data_dir: str | None = None) -> list[dict]:
    """The owner's playlists, most recently changed first."""
    digest = owner_digest(key)
    out = []
    if os.path.isdir(_dir(data_dir)):
        for name in os.listdir(_dir(data_dir)):
            if not name.endswith(".json"):
                continue
            record = get(name[:-5], data_dir)
            if record and record.get("owner") == digest:
                out.append(record)
    out.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
    return out


def create(key: str, name: str, owner_name: str | None, items: list[str] | None = None,
           data_dir: str | None = None) -> dict:
    with _lock:
        if len(mine(key, data_dir)) >= MAX_PER_PERSON:
            raise PlaylistError(f"You have {MAX_PER_PERSON} playlists, the most there can be.")
        now = _now()
        record = {"id": secrets.token_urlsafe(9).replace("_", "x").replace("-", "y"),
                  "name": _clean_name(name), "owner": owner_digest(key),
                  "owner_name": owner_name, "items": list(dict.fromkeys(items or []))[:MAX_ITEMS],
                  "created_at": now, "updated_at": now}
        _save(record, data_dir)
    return record


def _owned(key: str, playlist_id: str, data_dir: str | None) -> dict:
    record = get(playlist_id, data_dir)
    if record is None:
        raise KeyError(playlist_id)
    if record.get("owner") != owner_digest(key):
        raise PermissionError("Only its owner can change a playlist.")
    return record


def update(key: str, playlist_id: str, name: str | None = None,
           items: list[str] | None = None, data_dir: str | None = None) -> dict:
    """Rename, or set the order: `items` must be the same demos, reordered
    (the page sends what it showed; demos the owner can no longer see keep
    their place at the end)."""
    with _lock:
        record = _owned(key, playlist_id, data_dir)
        if name is not None:
            record["name"] = _clean_name(name)
        if items is not None:
            present = list(record["items"])
            wanted = [i for i in dict.fromkeys(items) if i in present]
            record["items"] = wanted + [i for i in present if i not in wanted]
        record["updated_at"] = _now()
        _save(record, data_dir)
    return record


def set_item(key: str, playlist_id: str, asset_id: str, on: bool,
             data_dir: str | None = None) -> dict:
    with _lock:
        record = _owned(key, playlist_id, data_dir)
        items = [i for i in record["items"] if i != asset_id]
        if on:
            if len(items) >= MAX_ITEMS:
                raise PlaylistError(f"A playlist holds at most {MAX_ITEMS} demos.")
            items.append(asset_id)
        record["items"] = items
        record["updated_at"] = _now()
        _save(record, data_dir)
    return record


def delete(key: str, playlist_id: str, data_dir: str | None = None) -> None:
    with _lock:
        _owned(key, playlist_id, data_dir)
        os.remove(_path(playlist_id, data_dir))
