"""Microsoft Graph client — app-only, scoped to one SharePoint site.

This is the ONLY module that reads Graph credentials. Nothing else in the
codebase should touch them.

Permission model, and its one trap
----------------------------------
`Sites.Selected` is a **two-step** grant:

  1. An admin consents to the `Sites.Selected` application permission.
     **On its own this grants access to nothing.**
  2. An admin grants the app a role on one specific site, via
     `POST /v1.0/sites/{siteId}/permissions`.

Step 2 is very easy for IT to miss, because in the Azure portal step 1 looks
like the whole job. The symptom is a perfectly valid token followed by `403` on
every site call — which reads exactly like a bug in our code and can burn a day.
`verify_access()` exists to distinguish the two in one call, and it is the first
thing to run when credentials arrive.

Throttling and delta
--------------------
Graph throttles with `429` and a `Retry-After` header, and delta tokens expire
with `410 Gone`. Both are normal operating conditions rather than errors, and
both are handled here so callers never have to think about them.
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Iterator
from urllib.parse import quote, urlparse

import httpx

from backend.config import settings

log = logging.getLogger(__name__)

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
SCOPE = "https://graph.microsoft.com/.default"

#: Graph caps page size; 999 is the practical maximum for list/drive children.
PAGE_SIZE = 200


class GraphError(RuntimeError):
    """Upstream failed. Callers should degrade, not crash the page."""


class GraphNotConfigured(GraphError):
    pass


class GraphAuthError(GraphError):
    """Token acquisition failed — wrong tenant, client id or secret."""


class GraphPermissionError(GraphError):
    """Authenticated, but not authorised for this site.

    Almost always means step 2 of the Sites.Selected grant is missing.
    """


class DeltaTokenExpired(GraphError):
    """Graph returned 410 Gone. Discard the token and do a full pass."""


class GraphFieldUnknown(GraphError):
    """SharePoint does not have the column we tried to write.

    A setup problem, not a data problem — it fails identically for every item,
    so a caller writing in bulk should abort rather than repeat it 450 times.
    """


class GraphConcurrentEdit(GraphError):
    """412: the item changed in SharePoint since we read it.

    Its own class because it is the one write failure that is a legitimate
    outcome rather than a fault — someone edited the item first, and their
    value must not be silently overwritten.
    """


@dataclass(frozen=True)
class SiteRef:
    site_id: str
    display_name: str | None = None
    web_url: str | None = None


@dataclass(frozen=True)
class DriveRef:
    drive_id: str
    name: str | None = None


#: Phrases SharePoint uses when a column name is not recognised. It has no
#: dedicated error code for this, so the message is all there is to go on.
_UNKNOWN_COLUMN_HINTS = (
    "is not recognized", "is not recognised", "does not exist",
    "invalid field name", "column does not exist", "unknown field",
)


def _looks_like_unknown_column(detail: str) -> bool:
    lowered = (detail or "").lower()
    return any(hint in lowered for hint in _UNKNOWN_COLUMN_HINTS)


@dataclass
class DeltaPage:
    items: list[dict] = field(default_factory=list)
    delta_token: str | None = None


class GraphClient:
    def __init__(self, tenant_id: str, client_id: str, client_secret: str,
                 site_url: str | None = None, timeout: float = 30.0,
                 transport: httpx.BaseTransport | None = None,
                 token_provider=None):
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret
        self.site_url = site_url
        #: Injected by tests so the whole client can be exercised without MSAL
        #: or a real tenant.
        self._token_provider = token_provider
        self._msal_app = None
        self._client = httpx.Client(
            base_url=GRAPH_ROOT, timeout=timeout,
            headers={"Accept": "application/json"},
            transport=transport,
        )

    # ------------------------------------------------------------------ auth
    def _token(self) -> str:
        if self._token_provider is not None:
            return self._token_provider()

        import msal

        if self._msal_app is None:
            self._msal_app = msal.ConfidentialClientApplication(
                client_id=self._client_id,
                client_credential=self._client_secret,
                authority=f"https://login.microsoftonline.com/{self._tenant_id}",
            )
        # MSAL caches and refreshes internally; asking every call is correct.
        result = self._msal_app.acquire_token_for_client(scopes=[SCOPE])
        if "access_token" not in result:
            raise GraphAuthError(
                f"{result.get('error', 'unknown')}: "
                f"{result.get('error_description', 'no token returned')}")
        return result["access_token"]

    def granted_roles(self) -> list[str]:
        """Application permissions actually present in our own token.

        Read straight off the `roles` claim. No signature check — this is not
        authentication, it is introspection of a token we just acquired.

        Worth the trouble because an app with NO consented permission still
        receives a perfectly valid token, and every Graph call then fails with
        401. That looks like a bad secret and is not; the empty roles claim is
        the only thing that says so plainly. Measured on the real tenant
        2026-08-26, where it was exactly this.
        """
        try:
            payload = self._token().split(".")[1]
            payload += "=" * (-len(payload) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload))
        except (GraphError, ValueError, IndexError, binascii.Error):
            return []
        return list(claims.get("roles") or [])

    # -------------------------------------------------------------- plumbing
    def _request(self, method: str, url: str, **kwargs) -> Any:
        """One Graph call, with throttling and transient-failure retries.

        429 and 5xx are retried honouring Retry-After. 403 and 410 are NOT
        retried — they are meaningful states, not transient faults.
        """
        last: Exception | None = None
        for attempt in range(4):
            headers = {"Authorization": f"Bearer {self._token()}"}
            headers.update(kwargs.pop("headers", {}) or {})
            try:
                response = self._client.request(method, url, headers=headers, **kwargs)
            except httpx.HTTPError as exc:
                last = exc
                log.warning("graph %s %s failed: %s", method, url, exc)
                time.sleep(min(2 ** attempt, 8))
                continue

            if response.status_code in (429,) or response.status_code >= 500:
                wait = float(response.headers.get("Retry-After", 2 ** attempt))
                log.warning("graph %s %s -> %s, retrying in %.1fs",
                            method, url, response.status_code, wait)
                time.sleep(min(wait, 30))
                last = GraphError(f"HTTP {response.status_code} from Graph")
                continue

            return self._interpret(response, url)

        raise GraphError(f"Graph request to {url} failed: {last}") from last

    @staticmethod
    def _interpret(response: httpx.Response, url: str) -> Any:
        if response.status_code == 410:
            raise DeltaTokenExpired(
                "delta token expired (410 Gone) — discard it and resync in full")
        if response.status_code in (401,):
            raise GraphAuthError(f"401 from Graph for {url}: token rejected")
        if response.status_code == 403:
            raise GraphPermissionError(
                f"403 from Graph for {url}. The token is valid but the app is not "
                f"authorised for this site. This is almost always the missing "
                f"second step of the Sites.Selected grant — ask IT to run "
                f"POST /v1.0/sites/{{siteId}}/permissions. Check with verify_access().")
        if response.status_code == 412:
            raise GraphConcurrentEdit(
                f"412 precondition failed for {url}: it changed in SharePoint since we "
                f"read it. Re-read and confirm before overwriting.")
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            detail = ""
            try:
                detail = (response.json().get("error") or {}).get("message", "")
            except ValueError:
                detail = response.text[:200]
            if response.status_code == 400 and _looks_like_unknown_column(detail):
                raise GraphFieldUnknown(
                    f"SharePoint rejected a column name: {detail}. The column does not "
                    f"exist in the library, so this will fail for every item — create "
                    f"it in SharePoint, then re-run "
                    f"`python scripts/check_graph.py --columns` to confirm its internal "
                    f"name.")
            raise GraphError(f"HTTP {response.status_code} from Graph for {url}: {detail}")
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise GraphError(f"non-JSON response from Graph for {url}") from exc

    def _paged(self, url: str, params: dict | None = None) -> Iterator[dict]:
        """Follow @odata.nextLink until exhausted."""
        payload = self._request("GET", url, params=params)
        while payload:
            yield from payload.get("value", [])
            next_link = payload.get("@odata.nextLink")
            if not next_link:
                return
            # nextLink is absolute and already carries every parameter.
            payload = self._request("GET", next_link)

    # ----------------------------------------------------------- diagnostics
    def verify_access(self, site_url: str | None = None) -> dict[str, Any]:
        """Separate 'bad credentials' from 'missing site grant'.

        Run this FIRST when credentials arrive. Distinguishing the two failures
        is the difference between a five-minute fix and a day of debugging a
        403 that looks like a code bug.
        """
        result: dict[str, Any] = {"configured": True}

        try:
            self._token()
            result["token"] = {"ok": True}
        except GraphError as exc:
            result["token"] = {"ok": False, "error": str(exc)}
            result["diagnosis"] = ("Could not get a token. Check tenant id, client id "
                                   "and secret — this is step 0, before any permission.")
            return result

        # Check what the token actually carries before making a call whose
        # failure we would otherwise misread. An app with no consented
        # permission gets a valid token and a 401 on everything, which is
        # indistinguishable from a bad site URL from the outside.
        roles = self.granted_roles()
        result["granted_permissions"] = roles
        if not roles:
            result["site"] = {"ok": False, "error": "not attempted"}
            result["diagnosis"] = (
                "The token is valid but carries NO application permissions — its "
                "'roles' claim is empty. The app registration exists, but step 1 of "
                "the Sites.Selected grant was never done. Ask IT to add the "
                "Sites.Selected APPLICATION permission under API permissions > "
                "Microsoft Graph, then click 'Grant admin consent'. Step 2, the "
                "per-site grant, is still needed after that.")
            return result

        try:
            site = self.resolve_site(site_url or self.site_url)
            result["site"] = {"ok": True, "site_id": site.site_id,
                              "name": site.display_name, "web_url": site.web_url}
        except GraphPermissionError as exc:
            result["site"] = {"ok": False, "error": str(exc)}
            result["diagnosis"] = ("Token is valid but the site is forbidden. Step 1 of "
                                   "Sites.Selected was done; step 2 (the per-site grant) "
                                   "was not.")
            return result
        except GraphError as exc:
            result["site"] = {"ok": False, "error": str(exc)}
            result["diagnosis"] = "Could not resolve the site. Check the site URL."
            return result

        try:
            grants = self.site_permissions(site.site_id)
            result["permissions"] = {"ok": True, "count": len(grants),
                                     "roles": sorted({r for g in grants
                                                      for r in g.get("roles", [])})}
            if not grants:
                result["diagnosis"] = (
                    "Site resolved but reports NO permission grants. If calls start "
                    "failing with 403, the per-site grant is missing.")
            elif "write" not in result["permissions"]["roles"]:
                result["diagnosis"] = (
                    f"Granted {result['permissions']['roles']} but not 'write'. "
                    f"Read-only: sync will work, metadata write-back will not.")
            else:
                result["diagnosis"] = "Fully configured — read and write."
        except GraphError as exc:
            # Reading the permission list itself needs elevated rights, so this
            # failing is not conclusive.
            result["permissions"] = {"ok": False, "error": str(exc),
                                     "note": "listing grants needs Sites.FullControl.All; "
                                             "inconclusive, not necessarily a problem"}
            result["diagnosis"] = "Site is reachable, so the grant exists."
        return result

    def site_permissions(self, site_id: str) -> list[dict]:
        payload = self._request("GET", f"/sites/{site_id}/permissions")
        return (payload or {}).get("value", [])

    # ------------------------------------------------------------ resolution
    def resolve_site(self, site_url: str | None = None) -> SiteRef:
        """`https://host/sites/x` -> a Graph site id."""
        url = site_url or self.site_url
        if not url:
            raise GraphNotConfigured("no SharePoint site URL configured")
        parsed = urlparse(url if "://" in url else f"https://{url}")
        host = parsed.netloc
        path = parsed.path.strip("/")
        if not host or not path:
            raise GraphNotConfigured(f"cannot parse a site out of {url!r}")

        payload = self._request("GET", f"/sites/{host}:/{quote(path)}")
        if not payload:
            raise GraphError(f"site not found: {url}")
        return SiteRef(site_id=payload["id"],
                       display_name=payload.get("displayName"),
                       web_url=payload.get("webUrl"))

    def list_drives(self, site_id: str) -> list[DriveRef]:
        return [DriveRef(drive_id=d["id"], name=d.get("name"))
                for d in self._paged(f"/sites/{site_id}/drives")]

    def find_drive(self, site_id: str, name: str) -> DriveRef | None:
        wanted = name.strip().lower()
        return next((d for d in self.list_drives(site_id)
                     if (d.name or "").strip().lower() == wanted), None)

    # ------------------------------------------------------------------ read
    def list_children(self, drive_id: str, item_id: str = "root",
                      expand_fields: bool = True) -> list[dict]:
        """Immediate children of a drive item.

        `listItem($expand=fields)` is what carries the SharePoint columns —
        Demo Type, Segment, Product and the rest live there, not on the
        driveItem.
        """
        path = (f"/drives/{drive_id}/root/children" if item_id == "root"
                else f"/drives/{drive_id}/items/{item_id}/children")
        params = {"$top": PAGE_SIZE}
        if expand_fields:
            params["$expand"] = "listItem($expand=fields)"
        return list(self._paged(path, params))

    def delta(self, drive_id: str, token: str | None = None) -> DeltaPage:
        """Whole-drive delta.

        With no token this enumerates everything; with one it returns only what
        changed, including removals (marked with a `deleted` facet). The token
        for next time comes back in `delta_token`.

        Raises DeltaTokenExpired on 410 so the caller resyncs in full — without
        that, sync silently stops working.
        """
        url = (f"/drives/{drive_id}/root/delta"
               if not token else f"/drives/{drive_id}/root/delta?token={quote(token)}")

        items: list[dict] = []
        payload = self._request("GET", url, params={"$top": PAGE_SIZE} if not token else None)
        while payload:
            items.extend(payload.get("value", []))
            if link := payload.get("@odata.nextLink"):
                payload = self._request("GET", link)
                continue
            delta_link = payload.get("@odata.deltaLink") or ""
            new_token = None
            if "token=" in delta_link:
                new_token = delta_link.split("token=", 1)[1]
            return DeltaPage(items=items, delta_token=new_token)
        return DeltaPage(items=items)

    def get_item(self, drive_id: str, item_id: str) -> dict | None:
        return self._request("GET", f"/drives/{drive_id}/items/{item_id}")

    def download_url(self, drive_id: str, item_id: str) -> str | None:
        """Short-lived pre-authenticated URL.

        Lets a browser play a video without the viewer holding any SharePoint
        permission. Expires in about an hour, so resolve it at play time, never
        at list time — and note SharePoint is not a CDN: no adaptive bitrate, no
        transcoding, and it throttles under load.
        """
        item = self.get_item(drive_id, item_id)
        return (item or {}).get("@microsoft.graph.downloadUrl")

    def thumbnails(self, drive_id: str, item_id: str) -> list[dict]:
        payload = self._request("GET", f"/drives/{drive_id}/items/{item_id}/thumbnails")
        return (payload or {}).get("value", [])

    def list_columns(self, drive_id: str) -> list[dict]:
        """Column definitions of the list behind a document library.

        Needed because reading and writing are not symmetric. Reading can
        accept any of several plausible internal names; writing has to pick
        exactly one, and picking wrong fails on every item. So the write path
        asks SharePoint what the column is actually called instead of guessing.
        """
        payload = self._request("GET", f"/drives/{drive_id}/list",
                                params={"$expand": "columns"})
        return (payload or {}).get("columns", [])

    def get_list_item(self, drive_id: str, item_id: str) -> dict | None:
        """The listItem behind a driveItem, with its columns and ETag.

        Addressing through the drive matters: sync records the *driveItem* id,
        so going via `/sites/{id}/lists/{id}/items/{id}` would need a second
        identifier we never stored.
        """
        return self._request("GET", f"/drives/{drive_id}/items/{item_id}/listItem",
                             params={"$expand": "fields"})

    # ----------------------------------------------------------------- write
    def update_list_item_fields(self, drive_id: str, item_id: str,
                                fields: dict[str, Any],
                                etag: str | None = None) -> dict:
        """Write columns back on the item sync already identified.

        `If-Match` is not optional. SharePoint's own UI is a second writer, and
        without the ETag a stale Portal value would silently overwrite an edit
        someone made a minute ago — raising GraphConcurrentEdit instead.
        """
        url = f"/drives/{drive_id}/items/{item_id}/listItem/fields"
        result = self._request("PATCH", url, json=fields,
                               headers=self._write_headers(etag))
        if result is None:
            raise GraphError(
                f"item {item_id} was not found when writing fields — it was probably "
                f"deleted or moved in SharePoint. Re-sync and try again.")
        return result

    def update_fields(self, site_id: str, list_id: str, item_id: str,
                      fields: dict[str, Any], etag: str | None = None) -> dict:
        """Same write, addressed by site and list rather than by drive.

        Kept for callers that hold list coordinates instead of a driveItem id.
        """
        url = f"/sites/{site_id}/lists/{list_id}/items/{item_id}/fields"
        return self._request("PATCH", url, json=fields,
                             headers=self._write_headers(etag)) or {}

    @staticmethod
    def _write_headers(etag: str | None) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if etag:
            headers["If-Match"] = etag
        return headers


# ------------------------------------------------------------------ factory
def get_graph_client() -> GraphClient | None:
    """Configured client, or None while the IT request is outstanding.

    Returning None rather than a stub is deliberate: unlike Consensus, there is
    nothing useful to fake here. A caller must decide what to do without Graph,
    and a silent stub would hide that Graph is simply not available yet.
    """
    if not settings.graph_configured:
        return None
    return GraphClient(
        tenant_id=settings.graph_tenant_id,
        client_id=settings.graph_client_id,
        client_secret=settings.graph_client_secret,
        site_url=settings.graph_site_url,
    )
