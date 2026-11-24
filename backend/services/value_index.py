"""The Value Roadmap index: AMP-shaped JSON files read from the demo folders.

Decided 2026-11-19/24 (Liwei, Seb): each video is indexed outside the Hub --
by AMP, or by a Copilot / Azure pipeline producing the same format -- and the
result is saved NEXT TO THE VIDEO in its SharePoint folder as
`<video name>.index.json`. The Hub never runs AI itself; it only reads these.

The format is AMP's own (`GET /videos/{id}` on amp.ptcxc.com, read
2026-11-19): an `analysis` object (description, products, primary_area,
confidence, tags[{type: process|capability, id, name}], scenes[{start_s,
end_s, description, tags}]) and a `value_roadmap` object (summary,
value_drivers, initiatives / challenges / metrics as [{term, evidence}]).
Both may also sit at the top level, and the rest of AMP's record is ignored.

Being SharePoint content, the index is MIRROR data: rebuilt from the files,
never edited on the Hub (tags are corrected where they were made). It is
also AI output nobody has reviewed yet, so the Hub shows it only to people
with "Preview the Value Roadmap" (access.Perm.VIEW_ROADMAP).
"""
from __future__ import annotations

import json
import re
from typing import Any

#: The suffix that marks an index file. `Demo.mp4` -> `Demo.index.json`
#: (or `Demo.mp4.index.json`); matching is case-insensitive.
SUFFIX = ".index.json"
#: A real index is a few kB; anything far larger is not one.
MAX_BYTES = 2 * 1024 * 1024
#: Generous caps, so one malformed file cannot swell the catalogue.
_MAX_TAGS, _MAX_SCENES, _MAX_TERMS, _MAX_TEXT = 300, 200, 60, 4000


def is_index_file(name: str | None) -> bool:
    return bool(name) and name.lower().endswith(SUFFIX) and len(name) > len(SUFFIX)


def _stem(name: str) -> str:
    return name[:-len(SUFFIX)]


def match_video(index_name: str, subfolder: str | None,
                resources: list[dict]) -> dict | None:
    """The video an index file describes: same folder, and its name is the
    index's name without `.index.json`, with or without the video's own
    extension. None when no video matches -- the index still counts for the
    demo, it just is not tied to one file."""
    stem = _stem(index_name).lower()
    where = (subfolder or None)
    for r in resources:
        if r.get("kind") != "video" or (r.get("subfolder") or None) != where:
            continue
        name = (r.get("name") or "").lower()
        if name == stem or name.rsplit(".", 1)[0] == stem:
            return r
    return None


# ------------------------------------------------------------------ parsing
class NotAnIndex(ValueError):
    """The file is not a usable index; the message says why, for the sync
    report."""


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:_MAX_TEXT] or None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _number(value: Any) -> float | None:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def _terms(value: Any) -> list[dict]:
    out = []
    for item in (value or [])[:_MAX_TERMS]:
        if isinstance(item, dict):
            term = _text(item.get("term") or item.get("name"))
            if term:
                out.append({"term": term, "evidence": _text(item.get("evidence"))})
        elif _text(item):
            out.append({"term": _text(item), "evidence": None})
    return out


def _tag(item: Any, known: dict[str, dict]) -> dict | None:
    """One tag as {type, id, name}. A bare string is looked up among the
    file's own tags (by id, then name) so a scene can name a tag either way."""
    if isinstance(item, dict):
        name = _text(item.get("name"))
        tag_id = _text(item.get("id")) or (_slug(name) if name else None)
        if not tag_id:
            return None
        found = known.get(tag_id.lower()) or (known.get(name.lower()) if name else None)
        kind = _text(item.get("type")) or (found or {}).get("type") or "capability"
        return {"type": kind.lower(), "id": tag_id, "name": name or (found or {}).get("name") or tag_id}
    text = _text(item)
    if not text:
        return None
    found = known.get(text.lower())
    return dict(found) if found else {"type": "capability", "id": _slug(text), "name": text}


def parse(raw: bytes | str | dict) -> dict:
    """An AMP-shaped index as the Hub keeps it. Raises NotAnIndex with a
    reason a person can act on when the file is not one."""
    if isinstance(raw, (bytes, str)):
        if len(raw) > MAX_BYTES:
            raise NotAnIndex(f"larger than {MAX_BYTES // 1024} kB")
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise NotAnIndex(f"not valid JSON ({exc})") from exc
    else:
        data = raw
    if not isinstance(data, dict):
        raise NotAnIndex("not a JSON object")

    analysis = data.get("analysis") if isinstance(data.get("analysis"), dict) else None
    roadmap = data.get("value_roadmap") if isinstance(data.get("value_roadmap"), dict) else None
    if analysis is None and roadmap is None:
        # The two parts written straight at the top level.
        if any(k in data for k in ("tags", "scenes", "description")):
            analysis = data
        if any(k in data for k in ("value_drivers", "initiatives", "metrics", "summary")):
            roadmap = data
    if analysis is None and roadmap is None:
        raise NotAnIndex("no `analysis` or `value_roadmap` in it")
    analysis, roadmap = analysis or {}, roadmap or {}

    tags: list[dict] = []
    known: dict[str, dict] = {}
    for item in (analysis.get("tags") or [])[:_MAX_TAGS]:
        tag = _tag(item, known)
        if tag and tag["id"].lower() not in known:
            tags.append(tag)
            known[tag["id"].lower()] = tag
            known.setdefault(tag["name"].lower(), tag)
    processes = [t for t in tags if t["type"] == "process"]
    capabilities = [{**t, "process_id": t["id"].split("--", 1)[0] if "--" in t["id"] else None}
                    for t in tags if t["type"] != "process"]

    scenes = []
    for item in (analysis.get("scenes") or [])[:_MAX_SCENES]:
        if not isinstance(item, dict):
            continue
        start = _number(item.get("start_s"))
        if start is None:
            continue
        end = _number(item.get("end_s"))
        scene_tags = [t for t in (_tag(x, known) for x in (item.get("tags") or [])[:_MAX_TAGS]) if t]
        scenes.append({"start_s": start, "end_s": end if end is None or end >= start else None,
                       "description": _text(item.get("description")), "tags": scene_tags})
    scenes.sort(key=lambda s: s["start_s"])

    products = [p for p in (_text(x) for x in (analysis.get("products") or [])[:_MAX_TERMS]) if p]
    drivers = [d for d in (_text(x) for x in (roadmap.get("value_drivers") or [])[:_MAX_TERMS]) if d]
    index = {
        "description": _text(analysis.get("description")),
        "primary_area": _text(analysis.get("primary_area")),
        "products": list(dict.fromkeys(products)),
        "confidence": _text(analysis.get("confidence")),
        "processes": processes,
        "capabilities": capabilities,
        "scenes": scenes,
        "summary": _text(roadmap.get("summary")),
        "value_drivers": list(dict.fromkeys(drivers)),
        "initiatives": _terms(roadmap.get("initiatives")),
        "challenges": _terms(roadmap.get("challenges")),
        "metrics": _terms(roadmap.get("metrics")),
        "used_audio": analysis.get("used_audio") if isinstance(analysis.get("used_audio"), bool) else None,
        "used_visuals": (analysis.get("used_visuals")
                         if isinstance(analysis.get("used_visuals"), bool) else None),
        "source": _text(data.get("source") or roadmap.get("source")),
        "generated_at": _text(roadmap.get("generated_at") or analysis.get("generated_at")
                              or data.get("generated_at")),
        "model": _text(data.get("model") or roadmap.get("model")),
    }
    if not (index["processes"] or index["capabilities"] or index["value_drivers"]
            or index["summary"] or index["description"]):
        raise NotAnIndex("it holds no tags, value drivers, summary or description")
    return index


# ------------------------------------------------------------- per demo
def for_asset(entries: list[dict]) -> dict | None:
    """One demo's index from its files' entries (the store's rows for its
    folder): every indexed video, the main ones first, plus the unions the
    filters and facets use. None when nothing parsed."""
    videos = [e for e in entries if e.get("index")]
    if not videos:
        return None
    videos.sort(key=lambda e: (e.get("video") is None, (e.get("video") or e.get("name") or "").lower()))

    def union(key: str, field: str | None = None) -> list[str]:
        seen: dict[str, None] = {}
        for e in videos:
            for v in e["index"].get(key) or []:
                seen.setdefault(v[field] if field else v, None)
        return list(seen)

    return {
        "videos": [{**e["index"], "video": e.get("video"), "video_item_id": e.get("video_item_id"),
                    "subfolder": e.get("subfolder"), "file": e.get("name")} for e in videos],
        "processes": union("processes", "name"),
        "capabilities": union("capabilities", "name"),
        "value_drivers": union("value_drivers"),
    }


def by_folder(store: dict) -> dict[str, list[dict]]:
    """The store's file entries grouped by their demo folder's item id."""
    out: dict[str, list[dict]] = {}
    for entry in (store.get("files") or {}).values():
        if entry.get("folder_id"):
            out.setdefault(entry["folder_id"], []).append(entry)
    return out
