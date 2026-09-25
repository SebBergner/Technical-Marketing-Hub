"""What stays reachable by its id but is not listed.

Divested products (taxonomy.is_excluded) are gone entirely -- not listed, not
reachable. The rules here are softer: the record is real and something may
link to it, but nobody browsing should meet it.

* A folder titled "Release Notes" is documentation filed in the Demo Catalog,
  not a demo (Paul and Scott, who own the VM pages, 2026-09-25). The VM pages link
  its PDFs, so its files must still preview -- hence unlisted, not removed.

* An older version of a VM. Sellers should find the VM to use today, not
  choose between five Windchill images (same meeting). The older ones stay
  one click away from the newest, and a listing can ask for them.
"""
from __future__ import annotations

#: Compared after trimming and lower-casing. Exact titles only: "Windchill 13
#: Release Notes" would be a real asset about release notes.
UNLISTED_TITLES = frozenset({"release notes"})


def is_unlisted_title(title: str | None) -> bool:
    return " ".join((title or "").split()).lower() in UNLISTED_TITLES


def is_superseded_vm(record: dict) -> bool:
    return bool((record.get("vm") or {}).get("superseded_by"))


def is_listed(record: dict, include_older_vms: bool = False) -> bool:
    if is_unlisted_title(record.get("title")):
        return False
    if not include_older_vms and is_superseded_vm(record):
        return False
    return True
