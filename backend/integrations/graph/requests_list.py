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
from datetime import date
from typing import Any

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
