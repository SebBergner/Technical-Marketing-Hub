"""Archiving a SharePoint demo: its folder moves into the library's _Archive
folder (A8, Liwei 2026-10-21/28).

_Archive is a folder in each library -- the same library, so the folder keeps
its item id and the Hub keeps knowing which demo it is -- whose permissions
leave out the Visitors group (partners and everyone outside the team).
Moving a folder in makes it take _Archive's permissions, PROVIDED it and
everything in it inherit their permissions. A folder or file with permissions
of its own keeps them wherever it goes, so it would stay open to whoever it
names. Graph cannot reset inheritance (only SharePoint's REST API can, and
the app has no certificate for it), so such a demo is refused, with the
items named, to be fixed in SharePoint ("Delete unique permissions") first.

How "of its own" is told: Graph reports every permission of an item but not
whether it is inherited (inheritedFrom is empty on SharePoint, measured
2026-10-28). An inheriting item has exactly its parent's permissions, so the
check compares sets: the folder against the library root, each item inside
against its own folder (measured 2026-10-28: 113 of 118 top-level folders
equal the root; the 5 that differ all have grants or sharing links of their
own). A folder whose own permissions happen to equal its parent's would pass
-- so after the move every item is compared again, now against _Archive, and
if any still differs the folder goes straight back and the archive is refused.

Restoring moves the folder back to the library's root, under the same name;
a folder of that name already there refuses it.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

from backend.integrations.graph.client import GraphClient, GraphError

ARCHIVE_FOLDER = "_Archive"
#: Permission reads in parallel: a kit can hold a hundred files or more.
WORKERS = 8


class ArchiveRefused(RuntimeError):
    """Why this demo cannot be archived or restored (said to the person)."""


def signature(client: GraphClient, drive_id: str, item_id: str) -> frozenset:
    """An item's permissions as a comparable set: (roles, who) per grant;
    a sharing link counts by its scope."""
    out = set()
    for p in (client._request("GET", f"/drives/{drive_id}/items/{item_id}/permissions")
              or {}).get("value", []):
        g = p.get("grantedToV2") or p.get("grantedTo") or {}
        who = g.get("siteGroup") or g.get("user") or g.get("group") or {}
        key = who.get("id") or who.get("displayName")
        if not key and p.get("link"):
            key = "link:" + str((p["link"] or {}).get("scope"))
        out.add((tuple(sorted(p.get("roles") or [])), key))
    return frozenset(out)


def _tree(client: GraphClient, drive_id: str, folder_id: str) -> list[tuple[dict, str]]:
    """Every item below a folder, each with its parent folder's id."""
    out, todo = [], [folder_id]
    while todo:
        parent = todo.pop()
        for child in client._paged(f"/drives/{drive_id}/items/{parent}/children",
                                   {"$select": "id,name,folder,parentReference", "$top": "200"}):
            out.append((child, parent))
            if "folder" in child:
                todo.append(child["id"])
    return out


def own_permissions(client: GraphClient, drive_id: str, folder_id: str,
                    parent_signature: frozenset) -> list[str]:
    """The folder and the items in it whose permissions are not their
    parent's: names, folder first, at most 20."""
    items = _tree(client, drive_id, folder_id)
    ids = [folder_id] + [i["id"] for i, _ in items] + [p for _, p in items]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        sigs = dict(zip(set(ids), pool.map(lambda i: signature(client, drive_id, i), set(ids))))
    odd = []
    if sigs[folder_id] != parent_signature:
        odd.append("the demo's folder itself")
    for item, parent in items:
        if sigs[item["id"]] != sigs[parent]:
            odd.append(item.get("name") or item["id"])
    return odd[:20]


def _archive_id(client: GraphClient, drive_id: str) -> str:
    item = client._request("GET", f"/drives/{drive_id}/root:/{ARCHIVE_FOLDER}",
                           params={"$select": "id,folder"})
    if not item or "folder" not in item:
        raise ArchiveRefused(f"This library has no {ARCHIVE_FOLDER} folder yet.")
    return item["id"]


def _move(client: GraphClient, drive_id: str, item_id: str, parent_id: str) -> dict:
    return client._request("PATCH", f"/drives/{drive_id}/items/{item_id}",
                           json={"parentReference": {"id": parent_id},
                                 "@microsoft.graph.conflictBehavior": "fail"})


def archive(client: GraphClient, drive_id: str, folder_id: str) -> dict:
    """Move a demo's folder into _Archive, or ArchiveRefused."""
    root = client._request("GET", f"/drives/{drive_id}/root", params={"$select": "id"})["id"]
    archive_id = _archive_id(client, drive_id)
    odd = own_permissions(client, drive_id, folder_id, signature(client, drive_id, root))
    if odd:
        raise ArchiveRefused(
            "Some of this demo has permissions of its own, which it would keep in "
            f"{ARCHIVE_FOLDER} (open to whoever they name): " + ", ".join(odd)
            + ". In SharePoint, open each one's Manage access and choose "
              "\"Delete unique permissions\", then archive again.")
    try:
        moved = _move(client, drive_id, folder_id, archive_id)
    except GraphError as exc:
        if "409" in str(exc):
            raise ArchiveRefused(f"{ARCHIVE_FOLDER} already holds a folder of this name.")
        raise
    # Checked again where it now is: anything that did not take _Archive's
    # permissions goes back, and the archive is refused.
    odd = own_permissions(client, drive_id, folder_id, signature(client, drive_id, archive_id))
    if odd:
        _move(client, drive_id, folder_id, root)
        raise ArchiveRefused(
            "Moved back: after the move these still had permissions of their own: "
            + ", ".join(odd) + ". Delete their unique permissions in SharePoint, then "
              "archive again.")
    return moved or {}


def restore(client: GraphClient, drive_id: str, folder_id: str) -> dict:
    """Move an archived folder back to the library's root, or ArchiveRefused."""
    name = (client._request("GET", f"/drives/{drive_id}/items/{folder_id}",
                            params={"$select": "name"}) or {}).get("name") or ""
    taken = client._request("GET", f"/drives/{drive_id}/root:/{quote(name)}",
                            params={"$select": "id"})
    if taken and taken.get("id") != folder_id:
        raise ArchiveRefused(f'The library already has a folder named "{name}"; '
                             "rename one of them in SharePoint first.")
    root = client._request("GET", f"/drives/{drive_id}/root", params={"$select": "id"})["id"]
    return _move(client, drive_id, folder_id, root) or {}
