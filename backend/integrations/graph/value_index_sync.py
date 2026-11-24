"""Read the demo folders' `*.index.json` files during the SharePoint sync.

`build_assets` sets these files aside (they are data for the Hub, not files
for people) and this step reads them: only the ones that changed since the
last run, by eTag, so a sync over ~400 indexed demos downloads a handful of
files, not 400. The result is a mirror file the repository merges into the
catalogue (services/value_index.py says what is in it and why).
"""
from __future__ import annotations

import logging

from backend.integrations.graph.client import GraphClient, GraphError
from backend.services import value_index as vi

log = logging.getLogger(__name__)


def refresh(client: GraphClient, drive_id: str, refs: list[dict], assets: list,
            previous: dict | None) -> tuple[dict, dict]:
    """The new store, and what this run did.

    `refs`: the index files build_assets found ({folder_id, subfolder, name,
    item_id, etag}). `assets`: the demos just built, to tie each index to its
    video. `previous`: the store as the last run left it.
    """
    old = (previous or {}).get("files") or {}
    resources = {a.source_item_id: [r.model_dump(mode="json") for r in a.resources]
                 for a in assets if a.source_item_id}
    files: dict[str, dict] = {}
    read = reused = 0
    errors: list[dict] = []
    for ref in refs:
        item_id = ref.get("item_id")
        if not item_id:
            continue
        cached = old.get(item_id)
        entry = {k: ref.get(k) for k in ("folder_id", "subfolder", "name", "item_id",
                                         "etag", "modified_at")}
        video = vi.match_video(ref["name"], ref.get("subfolder"),
                               resources.get(ref.get("folder_id")) or [])
        entry["video"] = (video or {}).get("name")
        entry["video_item_id"] = (video or {}).get("item_id")
        if cached and cached.get("etag") and cached.get("etag") == ref.get("etag"):
            entry["index"], entry["error"] = cached.get("index"), cached.get("error")
            reused += 1
        else:
            try:
                raw = client.download_bytes(drive_id, item_id, vi.MAX_BYTES)
                if raw is None:
                    raise vi.NotAnIndex("the file could not be found")
                entry["index"], entry["error"] = vi.parse(raw), None
                read += 1
            except (vi.NotAnIndex, GraphError) as exc:
                entry["index"], entry["error"] = None, str(exc)
        if entry["error"]:
            errors.append({"name": ref["name"], "folder": ref.get("folder"),
                           "error": entry["error"]})
        files[item_id] = entry
    if errors:
        log.warning("value index: %d file(s) could not be used", len(errors))
    stats = {"files": len(files), "downloaded": read, "unchanged": reused,
             "indexed_demos": len({e["folder_id"] for e in files.values() if e.get("index")}),
             "errors": errors}
    return {"files": files}, stats
