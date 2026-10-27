"""Editing a demo's metadata on its Details card (A1, Liwei 2026-10-26).

People with "Edit metadata" (Administrators and TDD Team) change a demo's
columns in place on its page; the Hub writes them to the demo's folder in
SharePoint at once -- no review (Liwei, 2026-10-26: "改完不用审核") -- and
every change lands in the Admin log (the route is watched, admin_log.py).

What can change is the library's own upload form (upload_targets.TARGETS),
so an edit can never put a value in a column that an upload could not, plus
the Demo Owner (A4). Not the title: it is the folder's name, and the Hub's
id and every shared link are made from it (Liwei: leave it for now). Not a
Consensus demo: the Hub never writes to Consensus.

Writing: the folder's columns are re-read first; the form sends back the
ETag it was opened with, and a folder changed in SharePoint since then is
refused rather than overwritten (409). Only the columns whose value
actually changes are written.

Seeing it at once: a write is in SharePoint immediately, in the Hub's mirror
only after the next sync, which the edit starts straight away (a minute or
so). Until that sync has run, the values written are laid over the mirror
(owned/metadata_edits.json, apply_edits) so the demo's page, its card and
search show them now. A sync that finishes after the edit makes the overlay
moot, and it is dropped.

The preview video (PreviewVideo) and the card's picture (HubThumbnail, B5)
are Yes/No columns on files: one ticked per demo.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from backend.integrations.graph import migration_writer as w
from backend.integrations.graph import upload_writer as uw
from backend.integrations.graph.client import GraphClient, GraphError
from backend.services import sharepoint_mapping as m
from backend.services import upload_targets as ut

#: Fields of the upload form an edit never offers.
NOT_EDITED = {"title"}
#: The Demo Owner, edited with the rest though no upload form asks for it.
OWNER = ut.FieldSpec("demo_owner", "Demo owner", ut.TEXT, column=ut.OWNER_COLUMN,
                     max_length=200, help="The PTC email address of the person to ask "
                                          "about this demo.")
#: Pictures a card may show (B5): what a browser can draw.
IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
#: The picture's file in the demo's folder; a new one replaces it.
THUMBNAIL_NAME = "Hub thumbnail"

EDITS_FILE = "metadata_edits"


class NotEditable(ValueError):
    """This demo is not one the Hub edits; says why."""


class EditConflict(RuntimeError):
    """The folder changed in SharePoint since the editor was opened."""


def target_key(record: dict) -> str:
    """Which library a demo lives in, or NotEditable."""
    if (record.get("source") or "sharepoint") != "sharepoint":
        raise NotEditable("This demo lives in Consensus; the Hub does not edit it.")
    if record["id"].startswith("page-"):
        raise NotEditable("This demo is a SharePoint page only; edit the page in SharePoint.")
    if record.get("type") not in ("video", "ldk", "vdk"):
        raise NotEditable("Only demo kits and videos are edited here.")
    if not record.get("source_item_id"):
        raise NotEditable("The Hub does not know this demo's SharePoint folder yet.")
    return "demo_video" if record["id"].startswith("video-") else "demo_catalog"


def edit_fields(spec: ut.TargetSpec) -> list[ut.FieldSpec]:
    return [f for f in spec.fields if f.key not in NOT_EDITED] + [OWNER]


def _spec_with_owner(spec: ut.TargetSpec) -> ut.TargetSpec:
    from dataclasses import replace
    return replace(spec, fields=tuple(edit_fields(spec)))


# ─────────────────────────────────────────────────────────────── reading
def values_of(spec: ut.TargetSpec, fields: dict) -> dict:
    """The folder's columns as the form's values."""
    out: dict = {}
    for f in edit_fields(spec):
        if f.key == "products":
            if spec.product_choice_column:
                raw = fields.get(spec.product_choice_column) or []
                out["products"] = [p for p in raw if isinstance(p, str)]
            else:
                raw = fields.get("Product") or []
                out["products"] = [v.get("Label") for v in raw
                                   if isinstance(v, dict) and v.get("Label")]
            continue
        if f.key == "original_publish_date":
            when = fields.get(spec.publish_date_column or "") or ""
            out[f.key] = str(when)[:10] or None
            continue
        value = fields.get(f.column) if f.column else None
        if f.kind == ut.MULTI:
            value = value if isinstance(value, list) else ([value] if value else [])
        elif f.kind == ut.YESNO:
            value = value if isinstance(value, bool) else None
        elif isinstance(value, str):
            value = value.strip()
        out[f.key] = value if value not in ("",) else None
    return out


def form(spec: ut.TargetSpec, target: uw.Target) -> list[dict]:
    """The editor's fields, as the upload form draws them, minus the title."""
    full = ut.form(_spec_with_owner(spec), target.choices, target.skipped)
    return full["fields"]


# ─────────────────────────────────────────────────────────────── writing
def changes(spec: ut.TargetSpec, target: uw.Target, sent: dict, current: dict) -> dict:
    """The values that differ from SharePoint's, checked. Raises
    ut.UploadInvalid naming every problem."""
    sent = {k: v for k, v in (sent or {}).items() if k in {f.key for f in edit_fields(spec)}}
    cleaned = ut.clean_fields(_spec_with_owner(spec), sent, target.choices, partial=True)
    owner = cleaned.get("demo_owner")
    if owner:
        from backend.access import _is_internal_address
        owner = owner.lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", owner) or not _is_internal_address(owner):
            raise ut.UploadInvalid("Demo owner: a PTC email address.")
        cleaned["demo_owner"] = owner
    # A video's subtype follows its type (A15), judged on the whole video as
    # it will be; a retired subtype it already has may stay, a customer
    # video missing its customer must now name it (Liwei, 2026-10-27).
    if any(f.key == "video_subtype" for f in spec.fields):
        merged, problems = ut.video_rules({**current, **cleaned}, before=current)
        if problems:
            raise ut.UploadInvalid(" ".join(problems))
        for key in ("video_subtype", "named_customer"):
            if key in merged and merged.get(key) != current.get(key):
                cleaned[key] = merged[key]
    out = {}
    for key, value in cleaned.items():
        before = current.get(key)
        if isinstance(value, list) and isinstance(before, list):
            if sorted(value) == sorted(before):
                continue
        elif (value or None) == (before or None):
            continue
        out[key] = value
    if "original_publish_date" in out and not out["original_publish_date"]:
        # Graph cannot clear a date column (null is ignored).
        raise ut.UploadInvalid("Original publish date cannot be removed, only changed.")
    unknown = uw.unknown_products(target, out.get("products") or [])
    if unknown:
        raise ut.UploadInvalid("Not in SharePoint's Product list: " + ", ".join(unknown)
                               + ". Ask an administrator to add the term.")
    return out


def write(client: GraphClient, target: uw.Target, folder_id: str, changed: dict,
          etag: str | None) -> None:
    """Write the changed columns to the folder, refusing a stale form."""
    item = client.get_list_item(target.drive_id, folder_id) or {}
    now_etag = item.get("@odata.etag") or item.get("eTag")
    if etag and now_etag and etag != now_etag:
        raise EditConflict("Someone changed this demo in SharePoint since you opened the "
                           "editor. Reload it and make your change again.")
    values = {k: v for k, v in changed.items() if k != "demo_owner"}
    fields, note = uw.metadata_fields(target, target.spec.kinds[0], values)
    fields.pop("Demo_x0020_Type", None)        # an edit never changes the type
    if "demo_owner" in changed and target.has_demo_owner:
        fields[ut.OWNER_COLUMN] = changed["demo_owner"] or ""
    if fields:
        client.update_list_item_fields(target.drive_id, folder_id, fields, etag=now_etag)
    if note:
        w.write_fields(client, target, folder_id, note)


def tick(client: GraphClient, target: uw.Target, column: str, chosen: str | None,
         others: list[str]) -> None:
    """One file ticked in a Yes/No column, the others cleared."""
    for item_id in others:
        if item_id != chosen:
            w.write_fields(client, target, item_id, {column: False})
    if chosen:
        w.write_fields(client, target, chosen, {column: True})


def put_thumbnail(client: GraphClient, target: uw.Target, folder_id: str,
                  content: bytes, content_type: str) -> dict:
    """The picture into the demo's folder (replacing the Hub's last one)."""
    ext = IMAGE_TYPES[content_type]
    name = f"{THUMBNAIL_NAME}.{ext}"
    item = client._request(
        "PUT", f"/drives/{target.drive_id}/items/{folder_id}:/{name}:/content",
        params={"@microsoft.graph.conflictBehavior": "replace"},
        content=content, headers={"Content-Type": content_type})
    if not item or "id" not in item:
        raise GraphError("SharePoint did not store the picture.")
    return item


# ─────────────────────────────────────────────── seeing the change at once
def hub_values(key: str, changed: dict) -> dict:
    """What an edit means for the Hub's own record of the demo."""
    out: dict = {}
    for k, v in changed.items():
        if k == "description":
            out["description"] = v or None
        elif k == "products":
            out["products"] = v
        elif k == "segment":
            out["segment"] = (v or [None])[0]
            out["rails"] = (v or [])[1:]
        elif k == "language":
            out["language"] = m.parse_language(v) if v else "en"
        elif k == "customer_facing":
            out["customer_facing"] = v
        elif k == "contains_audio":
            out["has_narrated_audio"] = v
        elif k == "original_publish_date":
            out["uploaded_at"], out["date_stated"] = v, True
        elif k in ("product_version", "named_customer", "long_description"):
            out[k] = v or None
        elif k == "demo_owner":
            out["demo_owner"] = v or None
        elif k == "video_type":
            from backend.models import video_type
            out["content_depth"] = video_type(v)
    return out


def remember(repo, asset_id: str, values: dict) -> None:
    """Lay these values over the mirror until the next sync has them."""
    if not values:
        return
    with repo._lock:
        edits = repo._load(EDITS_FILE) or {}
        row = edits.setdefault(asset_id, {"values": {}})
        row["values"].update(values)
        # Naive UTC, like the sync's own stamps (record_sync), so the two compare.
        row["at"] = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
        repo._save(EDITS_FILE, edits)


def apply_edits(rows: list[dict], edits: dict, synced: dict[str, str | None]) -> list[dict]:
    """The mirror with recent edits laid over it. `synced`: source -> when
    its last sync finished; an edit older than that is already in the mirror."""
    if not edits:
        return rows
    out = []
    for r in rows:
        e = edits.get(r["id"])
        source = "demo_video" if r["id"].startswith("video-") else "sharepoint"
        if e and (not synced.get(source) or e.get("at", "") > synced[source]):
            r = {**r, **e.get("values", {})}
        out.append(r)
    return out
