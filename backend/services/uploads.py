"""Uploads through the Hub: one record per upload, and what the Hub shows of
it (2026-10-15).

A record follows one upload from the form to publication:

    uploading  -> the folder exists, files are going in (the browser sends
                  them straight to SharePoint; each file is confirmed here)
    pending    -> files and metadata are in; waiting for a reviewer
    sent_back  -> a reviewer asked for changes (note); the uploader fixes the
                  metadata and resubmits, or fixes files in SharePoint
    published  -> listed in the Hub
    cancelled  -> stopped by the uploader before finishing

From the moment its folder exists until it is published, the demo is out of
every Hub list (owned/upload_review.json, keyed by the SharePoint folder id,
read by the repository), so a sync can never list a half-made or unreviewed
upload. Its uploader and reviewers open it by id.

The Hub never deletes anything in SharePoint: a cancelled or abandoned
upload's folder stays there for a person to remove.

Files kept (owned/): uploads.json (the records), upload_review.json (what
the Hub hides), publish_dates.json (dates stated for libraries with no
column for them -- the Demo Catalog).
"""
from __future__ import annotations

import json
import os
import secrets
import threading
from datetime import datetime, timezone

RECORDS, REVIEW, DATES = "uploads", "upload_review", "publish_dates"
#: Internal, asked for when it was created: by folder, so it holds before the
#: Hub has indexed the demo (2026-10-15). Read by the repository.
INTERNAL = "upload_internal"
_lock = threading.Lock()

OPEN = ("uploading",)
WAITING = ("pending", "sent_back")


class UploadStateError(ValueError):
    """An action the record's state does not allow; the message is for people."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _path(repo, name: str) -> str:
    return os.path.join(repo.owned_dir, f"{name}.json")


def _load(repo, name: str, empty):
    try:
        with open(_path(repo, name), encoding="utf-8") as fh:
            value = json.load(fh)
        return value if isinstance(value, type(empty)) else empty
    except (FileNotFoundError, ValueError):
        return empty


def _save(repo, name: str, value) -> None:
    from backend.repositories.json_repo import _atomic_write
    _atomic_write(_path(repo, name), value)
    if hasattr(repo, "_invalidate"):
        repo._invalidate()


def _set_review(repo, folder_id: str, status: str | None, upload_id: str) -> None:
    state = _load(repo, REVIEW, {})
    if status:
        state[folder_id] = {"status": status, "upload": upload_id}
    else:
        state.pop(folder_id, None)
    _save(repo, REVIEW, state)


# ───────────────────────────────────────────────────────────── reading
def all_records(repo) -> list[dict]:
    return sorted(_load(repo, RECORDS, []), key=lambda r: r["created_at"], reverse=True)


def get(repo, upload_id: str) -> dict:
    record = next((r for r in _load(repo, RECORDS, []) if r["id"] == upload_id), None)
    if record is None:
        raise LookupError(upload_id)
    return record


def by_folder(repo, folder_id: str) -> dict | None:
    return next((r for r in _load(repo, RECORDS, []) if r.get("folder_id") == folder_id), None)


def _update(repo, upload_id: str, change) -> dict:
    with _lock:
        records = _load(repo, RECORDS, [])
        record = next((r for r in records if r["id"] == upload_id), None)
        if record is None:
            raise LookupError(upload_id)
        change(record)
        record["updated_at"] = _now()
        _save(repo, RECORDS, records)
    return record


# ───────────────────────────────────────────────────────────── the steps
def create(repo, *, target: str, kind: str, values: dict, files: list[dict],
           internal: bool, folder_id: str, folder_name: str, web_url: str | None,
           actor: str, preview: str | None = None) -> dict:
    """Recorded the moment the folder exists, and hidden from the Hub then."""
    record = {"id": secrets.token_hex(6), "target": target, "kind": kind,
              "title": values.get("title"), "values": values, "internal": bool(internal),
              "preview": preview,
              "folder_id": folder_id, "folder_name": folder_name, "web_url": web_url,
              "files": [{**f, "done": False, "item_id": None} for f in files],
              "status": "uploading", "uploaded_by": actor,
              "created_at": _now(), "updated_at": _now(),
              "submitted_at": None, "reviewed_by": None, "reviewed_at": None,
              "note": None, "error": None, "history": [{"at": _now(), "by": actor,
                                                         "what": "started"}]}
    with _lock:
        records = _load(repo, RECORDS, [])
        records.append(record)
        _save(repo, RECORDS, records)
        _set_review(repo, folder_id, "pending", record["id"])
    return record


def file_done(repo, upload_id: str, index: int, item_id: str, actor: str) -> dict:
    def change(r):
        if r["status"] not in OPEN:
            raise UploadStateError(f"This upload is {r['status']}.")
        if not 0 <= index < len(r["files"]):
            raise UploadStateError("No such file in this upload.")
        r["files"][index].update(done=True, item_id=item_id)
    return _update(repo, upload_id, change)


def submit(repo, upload_id: str, actor: str, values: dict | None = None) -> dict:
    """Files and metadata are in: waiting for review."""
    def change(r):
        if r["status"] not in OPEN + ("sent_back",):
            raise UploadStateError(f"This upload is {r['status']}.")
        if any(not f["done"] for f in r["files"]):
            raise UploadStateError("Some files have not finished uploading.")
        if values is not None:
            r["values"] = values
            r["title"] = values.get("title", r["title"])
        was = r["status"]
        r.update(status="pending", submitted_at=_now(), error=None)
        r["history"].append({"at": _now(), "by": actor,
                             "what": "resubmitted" if was == "sent_back" else "submitted"})
    record = _update(repo, upload_id, change)
    _set_review(repo, record["folder_id"], "pending", upload_id)
    if record["target"] == "demo_catalog":       # no date column there
        dates = _load(repo, DATES, {})
        dates[record["folder_id"]] = record["values"].get("original_publish_date")
        _save(repo, DATES, dates)
    if record.get("internal"):
        marks = _load(repo, INTERNAL, {})
        marks.setdefault(record["folder_id"], {"by": record["uploaded_by"], "at": _now(),
                                               "reason": "Marked Internal when created"})
        _save(repo, INTERNAL, marks)
    return record


def failed(repo, upload_id: str, error: str) -> dict:
    def change(r):
        r["error"] = error[:500]
    return _update(repo, upload_id, change)


def publish(repo, upload_id: str, actor: str, note: str | None = None) -> dict:
    def change(r):
        if r["status"] != "pending":
            raise UploadStateError(f"Only an upload waiting for review can be published "
                                   f"(this one is {r['status']}).")
        r.update(status="published", reviewed_by=actor, reviewed_at=_now(),
                 note=(note or "").strip()[:1000] or None)
        r["history"].append({"at": _now(), "by": actor, "what": "published"})
    record = _update(repo, upload_id, change)
    _set_review(repo, record["folder_id"], None, upload_id)
    return record


def send_back(repo, upload_id: str, actor: str, note: str) -> dict:
    note = (note or "").strip()
    if not note:
        raise UploadStateError("Say what needs changing.")
    def change(r):
        if r["status"] != "pending":
            raise UploadStateError(f"This upload is {r['status']}.")
        r.update(status="sent_back", reviewed_by=actor, reviewed_at=_now(), note=note[:1000])
        r["history"].append({"at": _now(), "by": actor, "what": "sent back", "note": note[:1000]})
    record = _update(repo, upload_id, change)
    _set_review(repo, record["folder_id"], "sent_back", upload_id)
    return record


def cancel(repo, upload_id: str, actor: str) -> dict:
    def change(r):
        if r["status"] not in OPEN + ("sent_back",):
            raise UploadStateError(f"This upload is {r['status']}.")
        if r["uploaded_by"] != actor:
            raise UploadStateError("Only the person who started it can cancel an upload.")
        r.update(status="cancelled")
        r["history"].append({"at": _now(), "by": actor, "what": "cancelled"})
    # Stays hidden: its folder is still in SharePoint for a person to remove.
    record = _update(repo, upload_id, change)
    _set_review(repo, record["folder_id"], "cancelled", upload_id)
    return record
