"""Write demo requests into the SharePoint list that records them.

This is the second place the code modifies a system of record, and the only
one that *originates* data rather than correcting it. Everything else the
Portal reads from SharePoint is a rebuildable mirror; a submitted request
exists nowhere else, so SharePoint is its store of record and no sync may ever
rebuild this list.

Two consequences follow, and both are implemented rather than hoped for:

* **A submission is never lost to a Graph outage.** The local append happens
  first and independently. If SharePoint is unreachable the request is still
  recorded, flagged as unsynced, and the caller is told plainly -- rather than
  being shown a success screen for something that went nowhere, which is what
  the form did before it was wired up at all.

* **Column shapes are verified, not assumed.** Every field name and payload
  shape here was tried against the real list on 2026-09-01. The notes on the
  awkward ones record what failed, because three of them fail *silently* or
  with an unhelpful 500.
"""
from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any
from urllib.parse import quote

from backend.integrations.graph.client import GraphClient, GraphError

log = logging.getLogger(__name__)

#: The list as created on EXT-TDD. Addressed by display name rather than id so
#: the same code works if it is ever recreated; Graph resolves either.
LIST_NAME = "Demo Requests"

#: Multi-value choice columns. Graph needs the type as a SIBLING key --
#:
#:     "DistributionChannels@odata.type": "Collection(Edm.String)",
#:     "DistributionChannels": ["eStore"]
#:
#: Nesting it inside the value, which is the shape the docs suggest for other
#: collections, returns 400 invalidRequest, and so does a bare list.
MULTI_CHOICE = ("DistributionChannels", "StartingMaterials")

#: Free-text columns that were originally something richer and could not be
#: written through Graph at all:
#:
#:   Products        was `multiterm` (managed metadata) -> 500 on every shape
#:   DeliveredAsset  was `url`                          -> 400 on every shape
#:   Requester       was a Person column                -> needs a numeric
#:                   LookupId, and resolving a person needs User.Read.All,
#:                   which this app does not have. Worse, writing an email
#:                   string returned 200 OK and stored nothing.
#:
#: All three are single-line text now. Products and StartingMaterials carry
#: several values, so they are joined; the separator is recorded here rather
#: than at each call site.
LIST_SEPARATOR = "; "


class RequestWriteError(RuntimeError):
    """The request is safe locally but did not reach SharePoint."""


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return LIST_SEPARATOR.join(str(v) for v in value if v)
    return str(value)


def build_fields(request: Any, *, request_id: str) -> dict[str, Any]:
    """Map an AssetRequestCreate onto the list's columns.

    Kept apart from the writing so it can be asserted against without a tenant.
    """
    fields: dict[str, Any] = {
        # SharePoint requires Title and shows it as the item's name, so it has
        # to read as a summary rather than be left blank or filled with an id.
        "Title": " — ".join(
            p for p in (
                (request.asset_type.value.upper()
                 if hasattr(request.asset_type, "value") else str(request.asset_type)),
                _as_text(request.products) or None,
            ) if p
        ) or "Asset request",
        "RequestID": request_id,
        # Every request starts unclaimed. The team moves it from here.
        "Status": "New",
        "AssetType": ("Video" if str(getattr(request.asset_type, "value",
                                             request.asset_type)) == "video" else "LDK"),
        "Products": _as_text(request.products),
        "Brief": _as_text(request.brief),
        "NarrativeAngle": _as_text(request.narrative),
        "DesiredLength": _as_text(request.target_length),
        "NamedCustomer": _as_text(request.named_customer),
        "CompellingEvent": _as_text(getattr(request, "compelling_event", None)),
        "ContentDepth": _as_text(getattr(request, "content_depth", None)),
        "Requester": _as_text(request.requester_email or request.requester_name),
        "RequesterTeam": _as_text(request.requester_team),
        "Notes": _as_text(getattr(request, "notes", None)),
    }

    # A named customer only means something when one is involved; the form's
    # three-way answer is mapped rather than passed through, because "footage"
    # and "story" are its internal values and not what a reader should see.
    involvement = {"none": "None", "footage": "Customer footage",
                   "story": "Customer story"}
    if getattr(request, "customer_involvement", None):
        fields["CustomerInvolvement"] = involvement.get(
            request.customer_involvement, request.customer_involvement)

    if request.needed_by:
        # Date-only column; Graph still wants an ISO instant.
        needed = request.needed_by
        fields["NeededBy"] = (needed.isoformat() + "T00:00:00Z"
                              if isinstance(needed, date) else str(needed))

    for column, values in (("DistributionChannels", request.distribution_channels),
                           ("StartingMaterials", request.starting_materials)):
        if values:
            fields[f"{column}@odata.type"] = "Collection(Edm.String)"
            fields[column] = list(values)

    # An empty string is a written-down blank; leaving the key out lets the
    # column keep whatever default the list defines.
    return {k: v for k, v in fields.items() if v not in ("", None, [])}


def create_request_item(client: GraphClient, site_id: str,
                        fields: dict[str, Any]) -> dict:
    """POST one item, and turn a Graph failure into something actionable."""
    list_ref = LIST_NAME.replace(" ", "%20")
    try:
        created = client._request(
            "POST", f"/sites/{site_id}/lists/{list_ref}/items",
            json={"fields": fields})
    except GraphError as exc:
        raise RequestWriteError(
            f"The request was saved locally but SharePoint rejected it: {exc}"
        ) from exc

    if not created or "id" not in created:
        raise RequestWriteError(
            "SharePoint accepted the write but returned no item id, so the "
            "request cannot be confirmed as recorded.")
    return created

# ------------------------------------------------------------- attachments

#: Where a requester's files go. A document library, not the list item:
#: Graph v1.0 cannot write list-item attachments at all, and a library gives
#: the team a normal SharePoint link to open, share and version.
ATTACHMENT_LIBRARY = "Documents"
ATTACHMENT_FOLDER = "Demo Requests"

#: Graph's simple upload tops out at 4 MB; past that it needs a resumable
#: session. A brief, a slide, a screen grab all fit comfortably. Rejecting a
#: larger file with a clear reason beats a truncated upload nobody notices.
MAX_ATTACHMENT_BYTES = 4 * 1024 * 1024

#: Extensions we will not accept, whatever they claim to be. This is an
#: intake form open to the whole org writing into a shared library; a form
#: that will store anything is a distribution channel for anything.
BLOCKED_EXTENSIONS = frozenset({
    ".exe", ".dll", ".scr", ".com", ".bat", ".cmd", ".ps1", ".psm1", ".vbs",
    ".js", ".jse", ".wsf", ".wsh", ".msi", ".msp", ".hta", ".cpl", ".jar",
    ".reg", ".lnk", ".iso", ".img", ".sh",
})


def safe_attachment_name(name: str) -> str:
    """A filename that cannot escape its folder or break SharePoint.

    Path separators and `..` are stripped rather than escaped: a name is a
    name here, never a path, and the only reason one would contain a
    separator is to try to be one.
    """
    name = os.path.basename(str(name or "").replace("\\", "/"))
    for ch in '"*:<>?/|#%':                     # SharePoint rejects these
        name = name.replace(ch, "-")
    name = name.strip(" .") or "attachment"
    return name[:128]


def attachment_rejection(name: str, size: int) -> str | None:
    """Why this file will not be stored, or None if it will be."""
    clean = safe_attachment_name(name)
    ext = os.path.splitext(clean)[1].lower()
    if ext in BLOCKED_EXTENSIONS:
        return f"{clean}: {ext} files are not accepted here."
    if size > MAX_ATTACHMENT_BYTES:
        return (f"{clean}: {size / 1_048_576:.1f} MB is over the "
                f"{MAX_ATTACHMENT_BYTES // 1_048_576} MB limit. "
                f"Link it in the notes instead.")
    if size == 0:
        return f"{clean}: the file is empty."
    return None


def upload_attachment(client: GraphClient, site_id: str, request_id: str,
                      filename: str, content: bytes) -> dict:
    """Put one file under Documents/Demo Requests/<request id>/.

    A folder per request, so the library stays navigable and two people
    attaching `brief.docx` on the same day cannot overwrite each other —
    which `@microsoft.graph.conflictBehavior: rename` alone would only
    disguise by appending a number.
    """
    drive = _library(client, site_id, ATTACHMENT_LIBRARY)
    path = f"{ATTACHMENT_FOLDER}/{request_id}/{safe_attachment_name(filename)}"
    try:
        return client._request(
            "PUT",
            f"/drives/{drive}/root:/{quote(path)}:/content"
            "?@microsoft.graph.conflictBehavior=rename",
            content=content,
            headers={"Content-Type": "application/octet-stream"},
        )
    except GraphError as exc:
        raise RequestWriteError(
            f"{safe_attachment_name(filename)} could not be uploaded: {exc}"
        ) from exc


def _library(client: GraphClient, site_id: str, name: str) -> str:
    for drive in client.list_drives(site_id):
        if drive.name == name:
            return drive.drive_id
    raise RequestWriteError(
        f"The '{name}' document library was not found on this site, so there "
        f"is nowhere to put attachments.")
