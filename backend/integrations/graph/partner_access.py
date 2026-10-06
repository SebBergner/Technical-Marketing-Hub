"""Which demo folders partners may download from, read from SharePoint.

The Hub fetches files with its own app identity, which has the whole site, so
a folder that SharePoint closes to partners stayed open to them through the
Hub (found 2026-10-06: the Lamborghini IPL folder has the Visitors group
removed, and the Hub still served its 6 files to anyone signed in). Liwei's
rule, the same day: partners -- guest accounts, who reach SharePoint through
the "GPX TDD Scalable Demo Catalog Visitors" group -- may download what that
group may read, and nothing else. So this reads each demo folder's
permissions during the SharePoint sync and records whether the partner group
holds Read there; the file endpoints then refuse partners on the rest.

An approximation, chosen over checking each user's own SharePoint access
(which needs a delegated Graph permission from IT): it follows the partner
group, not individual grants.

Read-only towards SharePoint. A folder whose permissions cannot be read this
time keeps what was recorded for it last time, so a failing scan never
reopens a folder that was closed.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from backend.config import settings
from backend.integrations.graph.client import GraphClient, SiteRef

log = logging.getLogger(__name__)

GRAPH = "https://graph.microsoft.com/v1.0"
#: A role that lets a member download. "restrictedView" (View Only) does not.
DOWNLOAD_ROLES = {"read", "write", "owner"}


def _norm(name: str | None) -> str:
    return " ".join((name or "").lower().split())


def partner_can_download(permissions: list[dict], group: str | None = None) -> bool:
    """Whether the partner group holds a downloading role in these permissions."""
    wanted = _norm(group or settings.partner_group_name)
    for p in permissions:
        holders = [p.get("grantedToV2") or {}] + list(p.get("grantedToIdentitiesV2") or [])
        names = {_norm(v.get("displayName")) for h in holders for v in h.values()
                 if isinstance(v, dict)}
        if wanted in names and DOWNLOAD_ROLES & set(p.get("roles") or []):
            return True
    return False


@dataclass
class PartnerAccessResult:
    folders: int = 0
    restricted: int = 0
    kept_from_last_time: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"folders": self.folders, "restricted": self.restricted,
                "kept_from_last_time": self.kept_from_last_time,
                "errors": self.errors[:10]}


def sync_partner_access(client: GraphClient, repo, site: SiteRef | None = None) -> PartnerAccessResult:
    """Read the permissions of every Demo Catalog and Demo Video folder the
    Hub lists, and store {folder item id: restricted} for the read path."""
    site = site or client.resolve_site()
    previous = repo.partner_access() if hasattr(repo, "partner_access") else {}
    jobs = []
    for library, source in ((settings.graph_list_name, "sharepoint"),
                            (settings.graph_video_library, "demo_video")):
        if not library:
            continue
        drive = client.find_drive(site.site_id, library)
        if drive is None:
            continue
        for row in repo.source_rows(source):
            if row.get("source_item_id"):
                jobs.append((drive.drive_id, row["source_item_id"]))

    def check(job):
        drive_id, item_id = job
        try:
            perms = (client._request(
                "GET", f"{GRAPH}/drives/{drive_id}/items/{item_id}/permissions") or {}).get("value", [])
            return item_id, not partner_can_download(perms), None
        except Exception as exc:                                  # noqa: BLE001
            return item_id, None, str(exc)[:120]

    result = PartnerAccessResult()
    access: dict[str, bool] = {}
    # Four at a time: the site throttles (429) a wider fan-out.
    with ThreadPoolExecutor(max_workers=4) as pool:
        for item_id, restricted, error in pool.map(check, jobs):
            result.folders += 1
            if error is not None:
                result.errors.append(f"{item_id}: {error}")
                if item_id in previous:
                    access[item_id] = previous[item_id]
                    result.kept_from_last_time += 1
                continue
            access[item_id] = restricted
    result.restricted = sum(1 for v in access.values() if v)
    repo.replace_partner_access(access)
    log.info("partner access: %d folders, %d closed to partners", result.folders, result.restricted)
    return result
