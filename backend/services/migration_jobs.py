"""The /migration page's jobs: an uploaded sheet, its preview, and a run.

Decided by Liwei, 2026-09-29 (plan §14):

* A migration can be STARTED from the page, by an SSO curator or by the
  shared admin sign-in. The admin sign-in must type an operator name, which
  the batch log keeps. This is a deliberate, temporary exception to
  backend/admin_auth.py's rule that the shared credential never writes to
  SharePoint; once production has SSO, only curators may start a run.
* A run executes INSIDE the Hub server, in a background thread -- on exactly
  one deployment (MIGRATION_RUNNER_ENABLED; staging).

What makes that safe on App Service, where a run takes hours:

* One run at a time across every gunicorn worker: an O_EXCL lock file on the
  shared data directory (the auto_sync pattern), kept fresh by a heartbeat and
  taken over only once it has gone stale -- so a crashed worker cannot block
  the next run forever, and a live one is never doubled.
* Everything a run knows is in its batch log, written after every step; a
  restarted server picks an unfinished, un-paused run up again on startup
  (`auto_resume`), through the same resume path the CLI uses.
* Pausing is a separate marker file, not a field of the batch log: the click
  may reach a different worker than the one running, and two processes
  rewriting one log would lose each other's writes.

Nothing here writes to SharePoint except through brightcove_runner.migrate_one,
the path the CLI and its tests already exercise.
"""
from __future__ import annotations

import collections
import csv
import io
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone

from backend.config import settings
from backend.services import brightcove_runner as run
from backend.services import gallery_sheet
from backend.services.brightcove_migration import batches_dir

log = logging.getLogger(__name__)

#: End-to-end Brightcove -> SharePoint rate measured from a workstation
#: (2026-09-29: 212.9 MB in 97 s). Only labels an estimate; the Azure rate
#: is unmeasured and likely higher.
MEASURED_MB_PER_S = 2.2
#: A run's lock is refreshed on every progress step; one this old belonged
#: to a process that died.
STALE_LOCK_SECONDS = 15 * 60
LOCK_FILE = "run.lock"


def _root() -> str:
    return os.path.join(settings.data_dir, "owned", "migration", "brightcove")


def _sheets_dir() -> str:
    return os.path.join(_root(), "sheets")


def _control_dir() -> str:
    return os.path.join(_root(), "control")


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False, default=str)
    os.replace(tmp, path)


def _read_json(path: str, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def clients():
    """(graph, brightcove) -- a function so tests can hand in fakes."""
    from backend.integrations.brightcove import get_brightcove_client
    from backend.integrations.graph.client import get_graph_client
    return get_graph_client(), get_brightcove_client()


def http_clients():
    """(uploader, source_http) for the transfer itself -- None means the
    defaults in migration_writer. A function so tests can hand in fakes."""
    return None, None


def _prepare(manifest: str, *, progress=None):
    """Target, terms, Brightcove client and validated records. Read-only."""
    from backend.integrations.graph import migration_writer as w
    graph, bc = clients()
    if graph is None:
        raise RuntimeError("SharePoint (Graph) is not configured on this deployment.")
    target = w.LibraryTarget.resolve(graph, settings.migration_brightcove_library,
                                     allow_production=True)    # resolve only reads
    terms = w.TermIndex.load(graph, target.site_id, settings.migration_product_term_set)
    records = run.load_manifest(manifest)
    if any(r.from_brightcove for r in records):
        if bc is None:
            raise RuntimeError("Brightcove is not configured on this deployment "
                               "(BRIGHTCOVE_ACCOUNT_ID / CLIENT_ID / CLIENT_SECRET).")
        todo = [r for r in records if r.from_brightcove]
        for i in range(0, len(todo), 20):          # in slices, so progress can show
            run.enrich(todo[i:i + 20], bc)
            if progress:
                progress(min(i + 20, len(todo)), len(todo))
    run.validate(records, target.choices, terms)
    status = run.plan(records, w.existing_by_brightcove_id(graph, target),
                      w.folder_names(graph, target))
    return graph, bc, target, terms, records, status


# ─────────────────────────────────────────────────────────────── sheets
def save_sheet(filename: str, content: bytes, *, uploaded_by: str) -> str:
    """Keep the upload, convert it to a manifest, start its preview."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = re.sub(r"[^A-Za-z0-9._ -]", "_", os.path.basename(filename or "sheet.xlsx"))[:80]
    sheet_id = f"{stamp}"
    folder = os.path.join(_sheets_dir(), sheet_id)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "source.xlsx"), "wb") as fh:
        fh.write(content)
    rows, report = gallery_sheet.read(os.path.join(folder, "source.xlsx"))
    gallery_sheet.write_manifest(rows, os.path.join(folder, "manifest.csv"))
    _write_json(os.path.join(folder, "preview.json"), {
        "sheet_id": sheet_id, "filename": safe, "uploaded_at": _now(), "uploaded_by": uploaded_by,
        "status": "running", "progress": {"done": 0, "total": len(rows)},
        "sheet": {"to_migrate": len(rows),
                  "left_out": sum(s["deleted"] for s in report["sheets"].values()),
                  "sheets": len(report["sheets"]),
                  "has_segment_column": report["has_segment_column"],
                  "has_customer_facing_column": report["has_customer_facing_column"],
                  "no_gallery": report["no_gallery"],
                  "customers_from_tags": dict(report["customers"])},
    })
    threading.Thread(target=compute_preview, args=(sheet_id,), daemon=True,
                     name=f"preview-{sheet_id}").start()
    return sheet_id


def _problem_key(text: str) -> str:
    return re.sub(r"'[^']*'", "'…'", text)


def compute_preview(sheet_id: str) -> dict:
    """What this sheet would do, from live SharePoint and Brightcove. Read-only."""
    folder = os.path.join(_sheets_dir(), sheet_id)
    path = os.path.join(folder, "preview.json")
    preview = _read_json(path, {})

    def progress(done, total):
        preview["progress"] = {"done": done, "total": total}
        _write_json(path, preview)

    try:
        _, _, target, _, records, status = _prepare(os.path.join(folder, "manifest.csv"),
                                                    progress=progress)
    except Exception as exc:                                   # noqa: BLE001
        log.exception("migration preview %s failed", sheet_id)
        preview.update(status="error", error=str(exc)[:500], computed_at=_now())
        _write_json(path, preview)
        return preview

    new = [r for r in records if status.get(r.brightcove_id) == "new"]
    counts = collections.Counter(status.values())
    problems: dict[str, list] = collections.defaultdict(list)
    for r in records:
        for p in r.problems:
            problems[_problem_key(p)].append({"row": r.row, "brightcove_id": r.brightcove_id,
                                             "title": r.title, "detail": p})

    def share(values_per_record):
        c = collections.Counter(v for vs in values_per_record for v in dict.fromkeys(vs))
        total = len(values_per_record)
        return [{"name": k, "count": n, "percent": round(n * 100 / total, 1) if total else 0}
                for k, n in c.most_common()]

    # The migration's scope: every kept row not already in the library, valid
    # or not. Charting only the rows that can go NOW left every chart empty
    # while one column was missing from the whole sheet (V29, 2026-09-29).
    scope = [r for r in records
             if status.get(r.brightcove_id or f"row {r.row}") != "existing"]
    volume = sum(r.size_bytes or 0 for r in scope)
    preview.update(
        status="ready", computed_at=_now(), library=target.name,
        counts={"rows": len(records), "new": counts.get("new", 0),
                "existing": counts.get("existing", 0), "conflict": counts.get("conflict", 0),
                "invalid": counts.get("invalid", 0), "scope": len(scope)},
        volume_bytes=volume,
        volume_ready_bytes=sum(r.size_bytes or 0 for r in new),
        runtime_seconds=round(sum(r.duration_s or 0 for r in scope)),
        estimate_hours=round(volume / (MEASURED_MB_PER_S * 1e6) / 3600, 1) if volume else 0,
        estimate_rate_mb_s=MEASURED_MB_PER_S,
        segments=share([r.segments or ["Not set"] for r in scope]),
        hub_products=share([r.hub_products or ["Not set"] for r in scope]),
        video_types=share([[r.extra.get("video_type") or "Not set"] for r in scope]),
        galleries=share([[r.extra.get("gallery") or "Not set"] for r in scope]),
        customers=share([[r.extra["named_customer"]] for r in scope if r.extra.get("named_customer")]),
        audience=share([["Customer-facing" if r.customer_facing is True
                         else "Internal" if r.customer_facing is False else "Not set"]
                        for r in scope]),
        problems=[{"reason": k, "count": len(v), "rows": v}
                  for k, v in sorted(problems.items(), key=lambda kv: -len(kv[1]))],
        rows=[{"row": r.row, "brightcove_id": r.brightcove_id, "title": r.title,
               "status": status.get(r.brightcove_id) or status.get(f"row {r.row}"),
               "size_bytes": r.size_bytes} for r in records],
    )
    _write_json(path, preview)
    return preview


#: A preview still "running" with no progress for this long lost its thread
#: to a restart (seen 2026-09-29 when the dev server reloaded mid-preview).
STALE_PREVIEW_SECONDS = 120


def load_preview(sheet_id: str) -> dict | None:
    if not re.fullmatch(r"\d{8}-\d{6}", sheet_id or ""):
        return None
    path = os.path.join(_sheets_dir(), sheet_id, "preview.json")
    preview = _read_json(path)
    if preview and preview.get("status") == "running":
        try:
            stale = time.time() - os.path.getmtime(path) > STALE_PREVIEW_SECONDS
        except OSError:
            stale = False
        if stale:
            log.warning("migration preview %s was interrupted; computing it again", sheet_id)
            preview["progress"] = {"done": 0, "total": (preview.get("progress") or {}).get("total")}
            _write_json(path, preview)                 # fresh mtime: only one restart
            threading.Thread(target=compute_preview, args=(sheet_id,), daemon=True,
                             name=f"preview-{sheet_id}").start()
    return preview


def list_sheets(limit: int = 10) -> list[dict]:
    if not os.path.isdir(_sheets_dir()):
        return []
    out = []
    for sid in sorted(os.listdir(_sheets_dir()), reverse=True)[:limit]:
        p = load_preview(sid) or {}
        out.append({k: p.get(k) for k in ("sheet_id", "filename", "uploaded_at", "uploaded_by",
                                           "status")} | {"counts": p.get("counts")})
    return out


def planned_total() -> int | None:
    """How many videos the migration intends to move: the kept rows of the
    newest workbook whose preview finished. Better than a batch log's count,
    which describes only that run -- a one-video test run said "of 1
    planned" (2026-09-29)."""
    for s in list_sheets(limit=20):
        if s.get("status") == "ready" and s.get("counts"):
            return s["counts"].get("rows")
    return None


def problems_csv(sheet_id: str) -> str | None:
    p = load_preview(sheet_id)
    if not p or p.get("status") != "ready":
        return None
    buf = io.StringIO()
    out = csv.writer(buf)
    out.writerow(["row", "brightcove_id", "title", "problem"])
    for group in p.get("problems") or []:
        for row in group["rows"]:
            out.writerow([row["row"], row["brightcove_id"], row["title"], row["detail"]])
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────── the lock
def _lock_path() -> str:
    return os.path.join(_control_dir(), LOCK_FILE)


def _claim(batch_id: str) -> bool:
    path = _lock_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                age = time.time() - os.path.getmtime(path)
            except OSError:
                continue
            if age < STALE_LOCK_SECONDS:
                return False
            log.warning("migration: taking over a lock %.0f min old", age / 60)
            try:
                os.remove(path)
            except OSError:
                return False
            continue
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps({"batch_id": batch_id, "pid": os.getpid(), "since": _now()}))
        return True
    return False


def _heartbeat() -> None:
    try:
        os.utime(_lock_path(), None)
    except OSError:
        pass


def _release() -> None:
    try:
        os.remove(_lock_path())
    except OSError:
        pass


def active_run() -> str | None:
    """The batch holding a live lock, if any."""
    path = _lock_path()
    try:
        if time.time() - os.path.getmtime(path) >= STALE_LOCK_SECONDS:
            return None
    except OSError:
        return None
    return (_read_json(path, {}) or {}).get("batch_id")


# ─────────────────────────────────────────────────────────────── runs
class RunRefused(RuntimeError):
    """A run cannot start; the message says why, for the page to show."""


def _pause_path(batch_id: str) -> str:
    return os.path.join(_control_dir(), f"{batch_id}.pause")


#: Parallel uploads a run may use (Liwei, 2026-09-29: 3 to 5). Each holds
#: one 10 MiB chunk in memory; SharePoint's 429s are retried per chunk.
MAX_PARALLEL = 5
DEFAULT_PARALLEL = 3


def start_run(sheet_id: str, *, limit: int | None, operator: str, via: str,
              confirm_library: str | None = None, parallel: int = DEFAULT_PARALLEL) -> str:
    """The library is fixed -- MIGRATION_BRIGHTCOVE_LIBRARY, never chosen on
    the page -- so typing its name is no longer asked (Liwei, 2026-09-29).
    A name that IS sent must still be that library."""
    if not settings.migration_runner_enabled:
        raise RunRefused("Runs are not enabled on this deployment (MIGRATION_RUNNER_ENABLED).")
    if confirm_library and confirm_library.strip() != settings.migration_brightcove_library:
        raise RunRefused(f"Runs only write to {settings.migration_brightcove_library}.")
    if not (operator or "").strip():
        raise RunRefused("An operator name is required.")
    if active_run():
        raise RunRefused(f"Run {active_run()} is still going; wait for it or pause it first.")
    preview = load_preview(sheet_id)
    if not preview or preview.get("status") != "ready":
        raise RunRefused("That sheet has no finished preview.")
    # Taken from the preview, not recomputed here: checking every video
    # against Brightcove takes minutes, longer than App Service lets a request
    # live. The run itself re-checks everything live before each video.
    manifest = os.path.join(_sheets_dir(), sheet_id, "manifest.csv")
    todo = [r for r in preview.get("rows") or [] if r.get("status") == "new"][: limit or None]
    if not todo:
        raise RunRefused("Nothing new to migrate in that sheet.")
    blog = run.BatchLog.new("upload", preview.get("library") or settings.migration_brightcove_library,
                            manifest, planned=(preview.get("counts") or {}).get("rows"))
    blog.data.update(sheet_id=sheet_id, operator=operator.strip(), via=via, limit=limit,
                     parallel=max(1, min(MAX_PARALLEL, int(parallel or 1))),
                     started_from="page")
    for r in todo:
        blog.data["items"].append({"brightcove_id": r["brightcove_id"], "row": r["row"],
                                   "title": r["title"], "status": "pending",
                                   "size": r.get("size_bytes"), "problems": []})
    blog.save()
    batch_id = blog.data["batch_id"]
    _spawn(batch_id)
    return batch_id


def _spawn(batch_id: str) -> None:
    threading.Thread(target=execute, args=(batch_id,), daemon=True,
                     name=f"migration-{batch_id}").start()


def execute(batch_id: str) -> None:
    """Carry every unfinished item of a batch to done, `parallel` at a time.

    Workers take the next unfinished video from one shared queue. A pause
    stops them from TAKING another; what is already uploading finishes, so
    no upload is abandoned half-way.
    """
    if not _claim(batch_id):
        log.info("migration %s: another process holds the run lock", batch_id)
        return
    try:
        blog = run.BatchLog.load(batch_id)
        graph, bc, target, terms, records, status = _prepare(blog.data["manifest"])
        by_id = {r.brightcove_id: r for r in records}
        queue = [i["brightcove_id"] for i in blog.data["items"]
                 if i.get("status") in ("pending", "folder_created", "uploading", "uploaded")]
        parallel = max(1, min(MAX_PARALLEL, int(blog.data.get("parallel") or 1)))
        blog.data.pop("paused_at", None)
        blog.data["finished_at"] = None
        blog.save()
        take = threading.Lock()
        paused = threading.Event()

        def next_video() -> str | None:
            with take:
                if os.path.exists(_pause_path(batch_id)):
                    paused.set()
                    return None
                return queue.pop(0) if queue else None

        def one(bcid: str) -> None:
            record = by_id.get(bcid)
            if blog.item(bcid).get("status") == "pending" and status.get(bcid) == "existing":
                # Arrived in the library since the preview (another run, or
                # by hand): the ID is the key, so it is not uploaded twice.
                blog.set_item(bcid, status="existing", note="already in the library")
                return
            if record is None or record.problems:
                blog.set_item(bcid, status="failed",
                              error="no longer valid in the sheet: " + "; ".join(
                                  (record.problems if record else ["row missing"]))[:400])
                return
            blog.set_item(bcid, started_at=blog.item(bcid).get("started_at") or _now())
            try:
                uploader, source_http = http_clients()
                run.migrate_one(graph, target, terms, record, blog, bc=bc, uploader=uploader,
                                source_http=source_http, say=lambda _msg: _heartbeat())
                blog.set_item(bcid, finished_at=_now())
            except Exception as exc:                       # noqa: BLE001
                log.exception("migration %s: %s failed", batch_id, bcid)
                blog.set_item(bcid, status="failed", error=str(exc)[:500])

        def worker() -> None:
            while (bcid := next_video()) is not None:
                one(bcid)
                _heartbeat()

        workers = [threading.Thread(target=worker, daemon=True, name=f"migration-{batch_id}-{n}")
                   for n in range(min(parallel, max(1, len(queue))))]
        for t in workers:
            t.start()
        for t in workers:
            t.join()
        if paused.is_set() and any(i.get("status") in ("pending", "folder_created", "uploading",
                                                       "uploaded") for i in blog.data["items"]):
            blog.data["paused_at"] = _now()
            blog.save()
            log.info("migration %s paused", batch_id)
            return
        blog.finish()
    except Exception as exc:                               # noqa: BLE001
        log.exception("migration %s stopped", batch_id)
        try:
            blog = run.BatchLog.load(batch_id)
            blog.data["stopped_error"] = str(exc)[:500]
            blog.save()
        except Exception:                                  # noqa: BLE001
            pass
    finally:
        _release()


def pause(batch_id: str) -> None:
    os.makedirs(_control_dir(), exist_ok=True)
    with open(_pause_path(batch_id), "w", encoding="utf-8") as fh:
        fh.write(_now())


def resume(batch_id: str, *, operator: str, via: str) -> None:
    if not settings.migration_runner_enabled:
        raise RunRefused("Runs are not enabled on this deployment (MIGRATION_RUNNER_ENABLED).")
    if active_run():
        raise RunRefused(f"Run {active_run()} is still going.")
    try:
        os.remove(_pause_path(batch_id))
    except OSError:
        pass
    blog = run.BatchLog.load(batch_id)
    blog.data.setdefault("resumed", []).append({"at": _now(), "operator": operator, "via": via})
    blog.save()
    _spawn(batch_id)


def run_status(batch_id: str) -> dict | None:
    try:
        blog = run.BatchLog.load(batch_id)
    except OSError:
        return None
    d = blog.data
    items = d.get("items") or []
    total_bytes = sum(i.get("size") or 0 for i in items)
    done_bytes = sum((i.get("size") or 0) if i.get("status") == "done"
                     else (i.get("uploaded_bytes") or 0) for i in items)
    running = active_run() == batch_id
    state = ("running" if running else "paused" if d.get("paused_at")
             else "finished" if d.get("finished_at") else "stopped")
    current = [i for i in items if i.get("status") in ("folder_created", "uploading", "uploaded")]
    return {
        "batch_id": batch_id, "state": state, "operator": d.get("operator"), "via": d.get("via"),
        "started_at": d.get("started_at"), "finished_at": d.get("finished_at"),
        "paused_at": d.get("paused_at"), "pause_requested": os.path.exists(_pause_path(batch_id)),
        "stopped_error": d.get("stopped_error"), "counts": d.get("counts") or {},
        "parallel": d.get("parallel") or 1,
        "total": len(items), "bytes_total": total_bytes, "bytes_done": done_bytes,
        # Every video in flight -- several at once with parallel uploads.
        "current": [{k: c.get(k) for k in ("brightcove_id", "title", "status", "size",
                                           "uploaded_bytes")} for c in current],
        "items": [{k: i.get(k) for k in ("brightcove_id", "title", "status", "size",
                                         "uploaded_bytes", "error", "web_url")} for i in items],
    }


def latest_page_run() -> str | None:
    """The newest batch started from the page, for the page to show."""
    folder = batches_dir()
    if not os.path.isdir(folder):
        return None
    for fname in sorted(os.listdir(folder), reverse=True):
        if fname.endswith("-upload.json"):
            d = _read_json(os.path.join(folder, fname), {}) or {}
            if d.get("started_from") == "page":
                return d.get("batch_id")
    return None


def auto_resume() -> str | None:
    """On startup: pick up a page-started run that a restart interrupted."""
    if not settings.migration_runner_enabled or active_run():
        return None
    folder = batches_dir()
    if not os.path.isdir(folder):
        return None
    for fname in sorted(os.listdir(folder), reverse=True):
        if not fname.endswith("-upload.json"):
            continue
        d = _read_json(os.path.join(folder, fname), {}) or {}
        bid = d.get("batch_id")
        if (d.get("started_from") == "page" and not d.get("finished_at")
                and not d.get("paused_at") and not os.path.exists(_pause_path(bid))):
            log.info("migration: resuming %s after a restart", bid)
            _spawn(bid)
            return bid
    return None
