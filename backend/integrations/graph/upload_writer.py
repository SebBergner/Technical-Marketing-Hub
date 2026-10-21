"""SharePoint writes for uploads through the Hub (2026-10-15).

Built from the calls the Brightcove migration proved (migration_writer.py),
but for uploads: any library in services/upload_targets.TARGETS, the Demo
Catalog included (Liwei, 2026-10-15: new folders only -- the migration itself
still refuses the Demo Catalog).

What it never does: rename into, merge with, overwrite, modify or delete
anything that was already there. Every create is `conflictBehavior: fail`;
metadata is written only to the folder this upload created, with If-Match.

The bytes do not pass through the Hub: the browser PUTs them straight to
the pre-authorised upload-session URL this hands out (CORS verified
2026-10-15 from a browser page), in chunks, resumable.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from urllib.parse import quote

from backend.config import settings
from backend.integrations.graph import migration_writer as w
from backend.integrations.graph.client import GraphClient, GraphError
from backend.services import upload_targets as ut

#: Options and ids change rarely; a form opened a hundred times reads them once.
CACHE_SECONDS = 15 * 60
_cache: dict[str, tuple[float, "Target"]] = {}
_lock = threading.Lock()


class TargetUnavailable(GraphError):
    """The library is missing something an upload needs."""


@dataclass
class Target:
    spec: ut.TargetSpec
    site_id: str
    drive_id: str
    list_id: str
    demo_content_type_id: str
    product_note_field: str | None
    #: choices_from key -> options, read live.
    choices: dict = field(default_factory=dict)
    terms: w.TermIndex | None = None
    #: Columns a TEST library lacks (UPLOAD_LIBRARY_OVERRIDES): asked for and
    #: checked as usual, not written. Always empty for a real library.
    skipped: tuple = ()
    #: The library has submitted_by (optional: written only where it exists).
    has_submitted_by: bool = False


def resolve(client: GraphClient, spec: ut.TargetSpec, *, fresh: bool = False) -> Target:
    """The library behind a target, its ids and its live options. Read-only."""
    now = time.time()
    with _lock:
        hit = _cache.get(spec.key)
        if hit and not fresh and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    site_id = client.resolve_site().site_id
    drive = client.find_drive(site_id, spec.library)
    if drive is None:
        raise TargetUnavailable(f"No library named {spec.library!r} on the site.")
    list_id = (client._request("GET", f"/drives/{drive.drive_id}/list",
                               params={"$select": "id"}) or {})["id"]
    columns = {c["name"]: c for c in client._paged(
        f"/sites/{site_id}/lists/{list_id}/columns",
        {"$select": "name,displayName,hidden,choice"})}
    types = (client._request("GET", f"/sites/{site_id}/lists/{list_id}/contentTypes")
             or {}).get("value", [])
    demo = next((t for t in types if t.get("name") == "Demo" and t.get("documentSet")), None)
    if demo is None:
        raise TargetUnavailable(f'{spec.library!r} has no "Demo" document set content type.')
    note = next((c["name"] for c in columns.values() if c.get("displayName") == "Product_0"), None)

    def options(column: str) -> list[str]:
        return list(((columns.get(column) or {}).get("choice") or {}).get("choices") or [])

    missing = [f.column for f in spec.fields if f.column and f.column not in columns]
    if spec.publish_date_column and spec.publish_date_column not in columns:
        missing.append(spec.publish_date_column)
    if spec.product_choice_column and spec.product_choice_column not in columns:
        missing.append(spec.product_choice_column)
    if spec.product_terms and note is None:
        missing.append("Product's note field (Product_0)")
    if ut.PREVIEW_COLUMN not in columns:
        missing.append(ut.PREVIEW_COLUMN)
    if "Demo_x0020_Type" not in columns:
        missing.append("Demo_x0020_Type")
    skipped: tuple = ()
    if missing and spec.key in ut.overrides() and "Demo_x0020_Type" in columns:
        # A test library: the form is tried out whole, these are not stored.
        skipped = tuple(c for c in missing if c in {f.column for f in spec.fields}
                        | {spec.publish_date_column, spec.product_choice_column,
                           ut.PREVIEW_COLUMN})
        missing = [c for c in missing if c not in skipped]
    if missing:
        raise TargetUnavailable(f"{spec.library!r} is missing: {', '.join(missing)}")
    if skipped:
        # Options for the skipped columns come from the real library (read-only),
        # so the form is the one people will see.
        real = client.find_drive(site_id, ut.TARGETS[spec.key].library)
        if real is not None:
            real_list = (client._request("GET", f"/drives/{real.drive_id}/list",
                                         params={"$select": "id"}) or {})["id"]
            for c in client._paged(f"/sites/{site_id}/lists/{real_list}/columns",
                                   {"$select": "name,choice"}):
                if c["name"] in skipped:
                    columns[c["name"]] = c

    choices = {f.choices_from: options(f.choices_from) for f in spec.fields
               if f.choices_from and f.choices_from != "products"}
    demo_types = options("Demo_x0020_Type")
    absent = [k.demo_type for k in spec.kinds if k.demo_type not in demo_types]
    if absent:
        raise TargetUnavailable(f"{spec.library!r} Demo Type has no {', '.join(absent)}")
    terms = None
    if spec.product_terms:
        # The term store is closed to this app (Sites.Selected: 404, measured
        # 2026-10-15), so the products on offer are the terms the library's
        # demos already carry, each with its GUID.
        terms = w.TermIndex.load(client, site_id, settings.migration_product_term_set)
        if not len(terms):
            terms = harvest_terms(client, drive.drive_id)
        choices["products"] = terms.labels()
    else:
        # The library's own list, or -- a test library with an empty column --
        # the Hub's product list from Demo Video.
        choices["products"] = (options(spec.product_choice_column)
                               if spec.product_choice_column else [])             or _hub_products(client, site_id)
    # Never a product PTC no longer sells: the Hub lists no demo touching one
    # (taxonomy.DIVESTED_PRODUCTS), so offering it would create a demo nobody
    # can find. The Demo Catalog's old folders still carry such terms.
    from backend.services import taxonomy
    choices["products"] = [p for p in choices["products"] if not taxonomy.is_excluded([p])]
    if "Segment" in choices:
        choices["Segment"] = [s for s in choices["Segment"] if s not in taxonomy.RETIRED_SEGMENTS]
    target = Target(spec=spec, site_id=site_id, drive_id=drive.drive_id, list_id=list_id,
                    demo_content_type_id=demo["id"], product_note_field=note,
                    choices=choices, terms=terms, skipped=skipped,
                    has_submitted_by=ut.SUBMITTED_COLUMN in columns)
    with _lock:
        _cache[spec.key] = (now, target)
    return target


def _hub_products(client: GraphClient, site_id: str) -> list[str]:
    """The curated product list every upload picks from: Demo Video's
    HubProducts options -- the same list the Hub's Product filter uses."""
    drive = client.find_drive(site_id, settings.graph_video_library)
    if drive is None:
        return []
    list_id = (client._request("GET", f"/drives/{drive.drive_id}/list",
                               params={"$select": "id"}) or {})["id"]
    for c in client._paged(f"/sites/{site_id}/lists/{list_id}/columns",
                           {"$select": "name,choice"}):
        if c.get("name") == "HubProducts":
            return list((c.get("choice") or {}).get("choices") or [])
    return []


def harvest_terms(client: GraphClient, drive_id: str) -> w.TermIndex:
    """Product label -> (label, TermGuid) from the managed-metadata values on
    the library's top-level folders -- one read of ~750 folders."""
    found: dict[str, tuple[str, str]] = {}
    for item in client._paged(f"/drives/{drive_id}/root/children",
                              {"$select": "id,name,folder",
                               "$expand": "listItem($expand=fields($select=Product))",
                               "$top": "200"}):
        values = ((item.get("listItem") or {}).get("fields") or {}).get("Product") or []
        for v in values if isinstance(values, list) else []:
            label, guid = v.get("Label"), v.get("TermGuid")
            if label and guid:
                found.setdefault(w.TermIndex.key(label), (label, guid))
    return w.TermIndex(found)


def name_taken(client: GraphClient, target: Target, name: str) -> bool:
    # The client answers a 404 with None.
    return client._request("GET", f"/drives/{target.drive_id}/root:/{quote(name)}",
                           params={"$select": "id"}) is not None


def create_folder(client: GraphClient, target: Target, name: str) -> dict:
    """A new top-level Demo document set; an existing name is an error."""
    return w.create_demo_folder(client, target, name)


def ensure_subfolders(client: GraphClient, target: Target, folder_id: str,
                      path: str) -> str:
    """The id of `path`'s parent inside this upload's own folder, creating
    the sub-folders on the way. Only ever inside the folder this upload
    created, so finding one already there means this upload made it."""
    parent = folder_id
    for part in path.split("/")[:-1]:
        try:
            item = client._request("POST", f"/drives/{target.drive_id}/items/{parent}/children",
                                   json={"name": part, "folder": {},
                                         "@microsoft.graph.conflictBehavior": "fail"})
        except GraphError as exc:
            if "HTTP 409" not in str(exc):
                raise
            item = client._request("GET",
                                   f"/drives/{target.drive_id}/items/{parent}:/{quote(part)}",
                                   params={"$select": "id"})
        parent = item["id"]
    return parent


def upload_session(client: GraphClient, target: Target, parent_id: str, filename: str) -> dict:
    session = client._request(
        "POST", f"/drives/{target.drive_id}/items/{parent_id}:/{quote(filename)}:/createUploadSession",
        json={"item": {"@microsoft.graph.conflictBehavior": "fail"}})
    if not session or "uploadUrl" not in session:
        raise GraphError(f"no upload session for {filename!r}")
    return {"upload_url": session["uploadUrl"], "expires": session.get("expirationDateTime")}


def file_item(client: GraphClient, target: Target, item_id: str) -> dict:
    return client._request("GET", f"/drives/{target.drive_id}/items/{item_id}",
                           params={"$select": "id,name,size,parentReference"}) or {}


def metadata_fields(target: Target, kind: ut.KindSpec, values: dict) -> tuple[dict, dict]:
    """(fields, product note) to write, from cleaned values."""
    spec = target.spec
    fields: dict = {"Demo_x0020_Type": kind.demo_type}
    for f in spec.fields:
        if not f.column or f.key not in values or f.column in target.skipped:
            continue
        value = values[f.key]
        if f.kind == ut.MULTI:
            fields[f"{f.column}@odata.type"] = "Collection(Edm.String)"
        fields[f.column] = value
    if (spec.publish_date_column and values.get("original_publish_date")
            and spec.publish_date_column not in target.skipped):
        fields[spec.publish_date_column] = values["original_publish_date"] + "T00:00:00Z"
    products = values.get("products") or []
    if spec.product_choice_column and products             and spec.product_choice_column not in target.skipped:
        fields[f"{spec.product_choice_column}@odata.type"] = "Collection(Edm.String)"
        fields[spec.product_choice_column] = products
    note = {}
    if spec.product_terms and target.product_note_field and products and target.terms:
        found = [target.terms.get(p) for p in products]
        note = {target.product_note_field: w.note_value([t for t in found if t])}
    return fields, note


def unknown_products(target: Target, products: list[str]) -> list[str]:
    """Products the managed-metadata column could not store."""
    if not target.spec.product_terms or target.terms is None:
        return []
    return [p for p in products if target.terms.get(p) is None]


def mark_preview(client: GraphClient, target: Target, item_id: str) -> None:
    """Tick PreviewVideo on the chosen video (a file this upload created)."""
    if ut.PREVIEW_COLUMN in target.skipped:
        return
    w.write_fields(client, target, item_id, {ut.PREVIEW_COLUMN: True})


def write_metadata(client: GraphClient, target: Target, folder_id: str,
                   fields: dict, note: dict) -> None:
    w.write_fields(client, target, folder_id, fields)
    if note:
        w.write_fields(client, target, folder_id, note)
