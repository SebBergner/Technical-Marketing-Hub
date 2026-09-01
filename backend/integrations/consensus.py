"""Consensus integration.

Written against the official reference at
https://app.goconsensus.com/api-documentation/

Consensus is the external-share mechanism. The domain constraint that shapes
this module:

    The API can only send content ALREADY REGISTERED in Consensus. It cannot
    create or upload demos.

So this client reads and shares. There is deliberately no `create_demo` — its
absence is the design. An asset with no `consensus_uuid` genuinely cannot be
shared externally, and the UI must say so rather than fabricate a link.

Three things about this API are unusual enough to be worth stating up front:

1. **Auth is a body object, not a header.** Every call carries an `auth` block
   with `api_key`, `api_secret`, `user_email` and `source_name`. There is no
   token endpoint and no Authorization header.
2. **Everything is POST**, including searches.
3. **Responses wrap twice**: `{"data": {"items": [...], "paging": {...}},
   "status": 200}`. The `status` inside the body is the authoritative one; the
   docs do not state whether the HTTP status always agrees, so both are checked.

Known documentation gaps, handled explicitly rather than guessed at:

* The **base URL** is blank in the docs. Defaults to `https://app.goconsensus.com`
  and is overridable via `CONSENSUS_BASE_URL`.
* The **`createsenddemo` and `createlink` request/response schemas are truncated**
  on the documentation page. Trackable DemoBoard sharing is therefore marked
  unverified and fails loudly instead of silently producing a wrong link.
  Non-trackable sharing uses `previewLink`, which *is* documented.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

import httpx

from backend.config import settings

log = logging.getLogger(__name__)

#: Documented paths. Auth travels in the body, so these are all POST.
PATHS = {
    "user_info": "/api/integr/v1.0/info/userInfo",
    "demo_search": "/api/integr/v1.0/demo/search",
    "demo_by_hash": "/api/integr/v1.0/demo/getDemoByLinkHash",
    # ⚠ Documented by name only — the schema sections are truncated.
    "send_demo": "/api/integr/v1.0/sales/createsenddemo",
    "create_link": "/api/integr/v1.0/marketing/createlink",
    # Reports. Engagement metrics live here, NOT on the demo object.
    "demos_details": "/api/reports/v1.0/demosDetails",
    "track_demoboards": "/api/reports/v1.0/trackDemoBoards",
}

#: The API caps page size at 500.
MAX_PAGE_SIZE = 500


# ------------------------------------------------------------------- models
@dataclass(frozen=True)
class ConsensusDemo:
    """A demo record as Consensus returns it from `demo/search`.

    Note what is *absent*: view counts, watch time, duration and tags are not
    on this object. Engagement lives behind the `/api/reports/` endpoints, so
    `view_count` stays None unless populated from there.
    """
    uuid: str
    title: str
    description: str | None = None
    internal_title: str | None = None
    demo_type: str | None = None            # single | standard | advanced
    created_at: datetime | None = None
    preview_link: str | None = None
    thumbnails: tuple[str, ...] = ()
    is_published: bool | None = None
    is_archived: bool | None = None
    is_public: bool | None = None
    owner_email: str | None = None
    folder: str | None = None
    language: str | None = None
    view_count: int | None = None           # reports endpoints only
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)


@dataclass(frozen=True)
class ShareRecipient:
    email: str
    first_name: str | None = None
    last_name: str | None = None
    invite_hash: str | None = None
    invite_uuid: str | None = None
    contact_uuid: str | None = None

    def to_payload(self) -> dict[str, Any]:
        """Verified against the live API on 2026-08-31, not inferred.

        The spec declares `share_to` items as a bare `type: object` with no
        properties, so this was originally guessed from the *response* shape --
        `email` / `first_name` / `last_name` -- and the guess was wrong. The
        address field is **`contact_email`**; sending `email` fails with
        "contact_email: This value is required."

        The two name fields are not symmetric with it. `first_name` and
        `last_name` are correct and come back populated; `contact_first_name`
        and `contact_last_name` are accepted and silently ignored, as are
        `firstName` / `lastName` and a combined `contact_name`. All four were
        tried against the live endpoint and returned empty names.
        """
        payload: dict[str, Any] = {"contact_email": self.email}
        if self.first_name:
            payload["first_name"] = self.first_name
        if self.last_name:
            payload["last_name"] = self.last_name
        return payload


def _describe_fields(errors: Any) -> str | None:
    """Flatten Consensus's `errors` map into one readable line.

    It arrives as `{"auth": {"source_name": "..."},
                   "share_to": [{"contact_email": "..."}]}` -- nested, and
    sometimes a list because the offending item is one of several.
    """
    if not isinstance(errors, (dict, list)):
        return None

    parts: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")
        elif node:
            parts.append(f"{path}: {node}" if path else str(node))

    walk(errors, "")
    return "; ".join(parts) or None


@dataclass(frozen=True)
class ShareLink:
    url: str
    demo_uuid: str
    created_at: datetime
    #: demoboard  = trackable DemoBoard (createsenddemo), per-recipient
    #: marketing  = generated link (marketing/createlink)
    #: preview    = the demo's own previewLink, no generation step
    kind: str = "preview"
    send_demo_uuid: str | None = None
    send_demo_hash: str | None = None
    is_test: bool = False
    recipients: tuple[ShareRecipient, ...] = ()


class ConsensusError(RuntimeError):
    """Upstream failed. Callers should degrade, not crash the page."""


class ConsensusSchemaUnknown(ConsensusError):
    """We are missing a documented contract and refuse to guess."""


class ConsensusAPIError(ConsensusError):
    def __init__(self, status: int, code: str | None, message: str):
        super().__init__(f"Consensus {status} {code or ''}: {message}".strip())
        self.status, self.code, self.message = status, code, message


# ------------------------------------------------------------------ protocol
class ConsensusClient(Protocol):
    def is_configured(self) -> bool: ...
    def probe(self) -> dict[str, Any]: ...
    def list_demos(self, limit: int = 500) -> list[ConsensusDemo]: ...
    def get_demo(self, uuid: str) -> ConsensusDemo | None: ...
    def search(self, text: str, limit: int = 10) -> list[ConsensusDemo]: ...
    def create_share_link(self, uuid: str, recipient: str | None = None,
                          trackable: bool = True, *,
                          organization: str | None = None,
                          recipients: list[ShareRecipient] | None = None,
                          opportunity: str | None = None,
                          title: str | None = None,
                          is_test: bool = False) -> ShareLink: ...
    # No create_demo / upload — Consensus cannot do it.


# ---------------------------------------------------------------- stub impl
_STUB_EXTRA = [
    # Registered in Consensus with no Portal counterpart — exercises the
    # "orphaned externally" side of the reconciliation report.
    ConsensusDemo(uuid="c0de-1111", title="Windchill Quality Management Overview",
                  description="Registered in Consensus only.", is_published=True),
    ConsensusDemo(uuid="c0de-2222", title="ServiceMax Field Service Walkthrough",
                  description="Registered in Consensus only.", is_published=True),
]


class StubConsensusClient:
    """Offline stand-in used until credentials are configured.

    Its demos derive from the seed catalogue's UUIDs plus two that exist only
    here, so the reconciliation report shows gaps in *both* directions and the
    UI can be built against realistic output.
    """

    def __init__(self, demos: list[ConsensusDemo] | None = None):
        self._demos = demos if demos is not None else self._from_seed()

    @staticmethod
    def _from_seed() -> list[ConsensusDemo]:
        """Synthesise demos from the seed catalogue.

        SharePoint holds no Consensus UUID, so there is nothing real to mirror.
        Instead a slice of seed titles is given synthetic UUIDs, a few are
        deliberately reworded, and two exist only here. That produces gaps in
        BOTH directions plus some near-misses, which is what the reconciliation
        UI has to be built against — an empty stub would prove nothing.
        """
        import json
        import os

        demos: list[ConsensusDemo] = []
        if not os.path.exists(settings.seed_path):
            return list(_STUB_EXTRA)

        with open(settings.seed_path, encoding="utf-8") as fh:
            records = json.load(fh)

        # Every 5th asset, so roughly a fifth of the catalogue is "registered".
        for i, record in enumerate(records[::5]):
            title = record["title"]
            if i % 7 == 3:
                title = f"{title} Demo"        # near-miss, should still match
            uuid = f"stub-{record['id'][:28]}"
            demos.append(ConsensusDemo(
                uuid=uuid,
                title=title,
                description=record.get("description"),
                is_published=True,
                preview_link=f"https://play.goconsensus.com/{uuid}",
            ))
        return demos + _STUB_EXTRA

    def is_configured(self) -> bool:
        return False

    def probe(self) -> dict[str, Any]:
        return {"mode": "stub", "configured": False, "demo_count": len(self._demos),
                "note": "Set CONSENSUS_API_KEY, CONSENSUS_API_SECRET and "
                        "CONSENSUS_USER_EMAIL to use the real API."}

    def list_demos(self, limit: int = 500) -> list[ConsensusDemo]:
        return self._demos[:limit]

    def get_demo(self, uuid: str) -> ConsensusDemo | None:
        return next((d for d in self._demos if d.uuid == uuid), None)

    def search(self, text: str, limit: int = 10) -> list[ConsensusDemo]:
        needle = (text or "").lower().strip()
        if not needle:
            return []
        return [d for d in self._demos
                if needle in d.title.lower()
                or needle in (d.description or "").lower()][:limit]

    def create_share_link(self, uuid: str, recipient: str | None = None,
                          trackable: bool = True, *,
                          organization: str | None = None,
                          recipients: list[ShareRecipient] | None = None,
                          opportunity: str | None = None,
                          title: str | None = None,
                          is_test: bool = False) -> ShareLink:
        demo = self.get_demo(uuid)
        if demo is None:
            raise ConsensusError(f"demo {uuid} is not registered in Consensus")
        from backend.tables import utcnow

        if not trackable:
            return ShareLink(url=demo.preview_link or f"https://play.goconsensus.com/{uuid}",
                             demo_uuid=uuid, created_at=utcnow(), kind="marketing",
                             send_demo_hash=f"stub{uuid}")

        # Mirror the real API's requirement so the stub cannot mask a bug that
        # would only appear against production.
        if not organization:
            raise ConsensusError(
                "Consensus requires an 'organization' — the customer or prospect this "
                "DemoBoard is for — before it will create a trackable share.")

        people = list(recipients or ([ShareRecipient(email=recipient)] if recipient else []))
        return ShareLink(
            url=f"https://play.goconsensus.com/stub{uuid}",
            demo_uuid=uuid, created_at=utcnow(), kind="demoboard",
            send_demo_uuid=f"stub-send-{uuid}", send_demo_hash=f"stub{uuid}",
            is_test=is_test,
            recipients=tuple(
                ShareRecipient(email=p.email, first_name=p.first_name,
                               last_name=p.last_name,
                               invite_hash=f"inv{i}", invite_uuid=f"stub-invite-{i}")
                for i, p in enumerate(people)
            ),
        )


# ---------------------------------------------------------------- http impl
class HttpConsensusClient:
    """Real client. See module docstring for the three API quirks."""

    def __init__(self, base_url: str, api_key: str, api_secret: str,
                 user_email: str, source_name: str = "TDD Portal",
                 viewer_url_template: str = "https://play.goconsensus.com/{hash}",
                 timeout: float = 20.0,
                 transport: httpx.BaseTransport | None = None):
        self._base = base_url.rstrip("/")
        self._viewer_template = viewer_url_template
        self._auth = {
            "api_key": api_key,
            "api_secret": api_secret,
            "user_email": user_email,
            "source_name": source_name,
            "user_activity": False,
        }
        self._client = httpx.Client(
            base_url=self._base, timeout=timeout,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            transport=transport,   # tests inject httpx.MockTransport here
        )

    def is_configured(self) -> bool:
        return True

    # -------------------------------------------------------------- plumbing
    def _post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        """POST with the auth block injected, retrying 429 and 5xx."""
        payload = {"auth": self._auth, **(body or {})}
        last: Exception | None = None

        for attempt in range(3):
            try:
                response = self._client.post(path, json=payload)
            except httpx.HTTPError as exc:
                last = exc
                log.warning("consensus POST %s failed: %s", path, exc)
                time.sleep(2 ** attempt)
                continue

            if response.status_code == 429 or response.status_code >= 500:
                wait = float(response.headers.get("Retry-After", 2 ** attempt))
                log.warning("consensus POST %s -> %s, retrying in %.1fs",
                            path, response.status_code, wait)
                time.sleep(min(wait, 10))
                last = ConsensusError(f"HTTP {response.status_code} from Consensus")
                continue

            try:
                data = response.json()
            except ValueError as exc:
                raise ConsensusError(
                    f"Consensus returned non-JSON from {path} "
                    f"(HTTP {response.status_code})"
                ) from exc

            return self._check(data, response.status_code, path)

        raise ConsensusError(f"Consensus request to {path} failed: {last}") from last

    @staticmethod
    def _check(payload: Any, http_status: int, path: str) -> Any:  # noqa: D401
        """The docs put the authoritative status inside the body.

        They do not say whether the HTTP status always agrees, so an error in
        either position is treated as an error.
        """
        if isinstance(payload, dict):
            body_status = payload.get("status")
            error = (payload.get("data") or {}).get("error") if isinstance(
                payload.get("data"), dict) else None
            # A validation failure does not use data.error at all: it returns a
            # top-level `errors` map naming the offending fields. Dropping it
            # turned "share_to[0].contact_email: This value is required" into a
            # bare "error from /sales/createsenddemo", which says nothing about
            # what to fix.
            fields = payload.get("errors")

            if error or fields or (isinstance(body_status, int) and body_status >= 400):
                raise ConsensusAPIError(
                    status=body_status if isinstance(body_status, int) else http_status,
                    code=(error or {}).get("code"),
                    message=((error or {}).get("message")
                             or _describe_fields(fields)
                             or f"error from {path}"),
                )

        if http_status >= 400:
            raise ConsensusAPIError(http_status, None, f"HTTP {http_status} from {path}")
        return payload

    @staticmethod
    def _items(payload: Any) -> list[dict]:
        """Unwrap `{"data": {"items": [...]}}`, tolerating the simpler shapes."""
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, dict):
                if isinstance(data.get("items"), list):
                    return data["items"]
                return [data]
            if isinstance(data, list):
                return data
        if isinstance(payload, list):
            return payload
        return []

    @staticmethod
    def _item(payload: Any) -> dict:
        """Unwrap `{"data": {"item": {...}}}` — the singular form used by the
        create endpoints, as opposed to `items` on the search endpoints."""
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, dict):
            item = data.get("item")
            if isinstance(item, dict):
                return item
            return data
        return {}

    @staticmethod
    def _paging(payload: Any) -> dict:
        data = payload.get("data") if isinstance(payload, dict) else None
        return (data or {}).get("paging") or {} if isinstance(data, dict) else {}

    @staticmethod
    def _parse_dt(value: Any) -> datetime | None:
        """Consensus returns e.g. '2018-08-22T08:22:55+0000' — note no colon
        in the UTC offset, which older parsers reject."""
        if not isinstance(value, str) or not value.strip():
            return None
        text = value.strip().replace("Z", "+00:00")
        for candidate in (text, text[:-5] + text[-5:-2] + ":" + text[-2:]):
            try:
                return datetime.fromisoformat(candidate)
            except ValueError:
                continue
        return None

    @classmethod
    def _to_demo(cls, payload: dict[str, Any]) -> ConsensusDemo:
        """Map a documented `demo/search` item onto our model."""
        language = payload.get("language")
        folder = payload.get("folderInfo") or {}
        thumbs = payload.get("previewThumbs") or []
        # The spec documents `ownerData`, but the live tenant returns only
        # `creatorData` — verified against production, where every record
        # omitted ownerData entirely. Fall back rather than losing the field.
        owner = payload.get("ownerData") or payload.get("creatorData") or {}

        return ConsensusDemo(
            uuid=str(payload.get("uuid") or ""),
            title=payload.get("title") or payload.get("internalTitle") or "",
            description=payload.get("description"),
            internal_title=payload.get("internalTitle"),
            demo_type=payload.get("type"),
            created_at=cls._parse_dt(payload.get("createdAt")),
            preview_link=payload.get("previewLink"),
            thumbnails=tuple(t for t in thumbs if isinstance(t, str)),
            is_published=payload.get("isPublished"),
            is_archived=payload.get("isArchived"),
            is_public=payload.get("isPublic"),
            owner_email=owner.get("email"),
            folder=folder.get("name"),
            language=(language or {}).get("code") if isinstance(language, dict) else language,
            raw=payload,
        )

    # ----------------------------------------------------------------- api
    def probe(self) -> dict[str, Any]:
        """Connectivity check plus a sample of the real response shape.

        `userInfo` is the lightest authenticated call, so it verifies
        credentials without touching the catalogue.
        """
        result: dict[str, Any] = {"mode": "http", "configured": True, "base_url": self._base}
        try:
            info = self._post(PATHS["user_info"])
            user = ((info or {}).get("data") or {}).get("user") or {}
            group = ((info or {}).get("data") or {}).get("group") or {}
            result["auth"] = {"ok": True, "user_email": user.get("email"),
                              "display_name": user.get("displayName"),
                              "group": group.get("name")}
        except ConsensusError as exc:
            result["auth"] = {"ok": False, "error": str(exc)}
            return result

        try:
            payload = self._post(PATHS["demo_search"],
                                 {"paging": {"limit": 1, "page": 1},
                                  "include_thumbs": True, "responseType": "full"})
            items = self._items(payload)
            result["demo_search"] = {
                "ok": True,
                "paging": self._paging(payload),
                "record_keys": sorted(items[0].keys()) if items else None,
                "sample": items[0] if items else None,
                "mapped": self._to_demo(items[0]).__dict__ if items else None,
            }
        except ConsensusError as exc:
            result["demo_search"] = {"ok": False, "error": str(exc)}
        return result

    def list_demos(self, limit: int = 500, include_archived: bool = False,
                   published_only: bool = True) -> list[ConsensusDemo]:
        """Page through `demo/search` until the API says there is no next page."""
        collected: list[ConsensusDemo] = []
        page = 1

        while len(collected) < limit:
            body: dict[str, Any] = {
                "paging": {"limit": min(MAX_PAGE_SIZE, limit - len(collected)),
                           "page": page, "sortBy": "createdAt", "order": "desc"},
                "include_thumbs": True,
                "responseType": "full",
            }
            if published_only:
                body["isPublished"] = True

            payload = self._post(PATHS["demo_search"], body)
            items = self._items(payload)
            if not items:
                break

            for item in items:
                demo = self._to_demo(item)
                if demo.is_archived and not include_archived:
                    continue
                if demo.uuid:
                    collected.append(demo)

            next_page = self._paging(payload).get("nextPage") or 0
            if not next_page or next_page == page:
                break
            page = next_page

        return collected[:limit]

    def get_demo(self, uuid: str) -> ConsensusDemo | None:
        payload = self._post(PATHS["demo_search"],
                             {"uuid": [uuid], "paging": {"limit": 1, "page": 1},
                              "include_thumbs": True, "responseType": "full"})
        items = self._items(payload)
        return self._to_demo(items[0]) if items else None

    def search(self, text: str, limit: int = 10) -> list[ConsensusDemo]:
        payload = self._post(PATHS["demo_search"], {
            "query": text,
            "paging": {"limit": min(limit, MAX_PAGE_SIZE), "page": 1},
            "include_thumbs": True,
            "responseType": "full",
        })
        return [self._to_demo(item) for item in self._items(payload)][:limit]

    def _share_url(self, hash_value: str) -> str:
        """Where a *recipient* opens a DemoBoard.

        Not the same URL as browsing the demo ourselves. `?preview=sales` puts
        the viewer in internal preview mode, which is right for a card in our
        own catalogue and wrong for something sent to a customer, so the query
        is stripped here. Verified: the bare hash URL resolves 200.
        """
        return self._viewer_url(hash_value).split("?")[0]

    def _viewer_url(self, hash_value: str) -> str:
        return self._viewer_template.format(hash=hash_value)

    def create_share_link(self, uuid: str, recipient: str | None = None,
                          trackable: bool = True, *,
                          organization: str | None = None,
                          recipients: list[ShareRecipient] | None = None,
                          opportunity: str | None = None,
                          title: str | None = None,
                          is_test: bool = False) -> ShareLink:
        """Produce a link for a demo.

        `trackable=True` creates a DemoBoard via `sales/createsenddemo`, which
        the spec marks `organization` as **required** for — it is the customer
        or prospect the board is for.

        `trackable=False` falls back to `marketing/createlink`, or to the demo's
        own `previewLink` if link generation is unavailable. Neither carries
        per-recipient tracking.
        """
        from backend.tables import utcnow

        demo = self.get_demo(uuid)
        if demo is None:
            raise ConsensusError(
                f"demo {uuid} is not registered in Consensus, so it cannot be shared")

        if trackable:
            people = list(recipients or [])
            if not people and recipient:
                people = [ShareRecipient(email=recipient)]
            return self._create_send_demo(
                demo, organization=organization, recipients=people,
                opportunity=opportunity, title=title, is_test=is_test)

        try:
            return self.create_marketing_link(uuid)
        except ConsensusError:
            if not demo.preview_link:
                raise
            log.info("createlink unavailable for %s, falling back to previewLink", uuid)
            return ShareLink(url=demo.preview_link, demo_uuid=uuid,
                             created_at=utcnow(), kind="preview")

    def create_marketing_link(self, uuid: str) -> ShareLink:
        """`marketing/createlink` -> `data.item.{uuid, hash}`."""
        from backend.tables import utcnow

        payload = self._post(PATHS["create_link"],
                             {"demo_uuid": uuid, "creationSource": "api"})
        item = self._item(payload)
        hash_value = item.get("hash")
        if not hash_value:
            raise ConsensusError(f"no hash in createlink response for demo {uuid}")
        return ShareLink(url=self._share_url(hash_value), demo_uuid=uuid,
                         created_at=utcnow(), kind="marketing",
                         send_demo_uuid=item.get("uuid"), send_demo_hash=hash_value)

    def _create_send_demo(self, demo: ConsensusDemo, *, organization: str | None,
                          recipients: list[ShareRecipient], opportunity: str | None,
                          title: str | None, is_test: bool) -> ShareLink:
        """`sales/createsenddemo` -> a trackable DemoBoard.

        The spec lists `auth` and `organization` as the only required fields;
        `organization` is enforced here rather than letting Consensus reject the
        call, so the caller gets a useful message.
        """
        from backend.tables import utcnow

        if not organization:
            raise ConsensusError(
                "Consensus requires an 'organization' — the customer or prospect this "
                "DemoBoard is for — before it will create a trackable share.")

        body: dict[str, Any] = {
            "demo_uuid": demo.uuid,
            "organization": organization,
            "creationSource": "api",
            "isTest": is_test,
        }
        if opportunity:
            body["opportunity"] = opportunity
        if title:
            body["title"] = title
        if recipients:
            body["share_to"] = [r.to_payload() for r in recipients]

        payload = self._post(PATHS["send_demo"], body)
        item = self._item(payload)

        send_hash = item.get("senddemo_hash")
        if not send_hash:
            raise ConsensusError(
                f"no senddemo_hash in createsenddemo response for demo {demo.uuid}")

        returned = tuple(
            ShareRecipient(
                email=r.get("email", ""),
                first_name=r.get("first_name"), last_name=r.get("last_name"),
                invite_hash=r.get("invite_hash"), invite_uuid=r.get("invite_uuid"),
                contact_uuid=r.get("contact_uuid"),
            )
            for r in (item.get("recipients") or []) if isinstance(r, dict)
        )

        return ShareLink(
            url=self._share_url(send_hash), demo_uuid=demo.uuid, created_at=utcnow(),
            kind="demoboard", send_demo_uuid=item.get("senddemo_uuid"),
            send_demo_hash=send_hash, is_test=bool(item.get("isTest", is_test)),
            recipients=returned,
        )


# ------------------------------------------------------------------ factory
def get_consensus_client() -> ConsensusClient:
    """Real client when credentials exist, stub otherwise.

    Swapping one for the other is a config change, never a code change.
    """
    if settings.consensus_configured:
        return HttpConsensusClient(
            base_url=settings.consensus_base_url,
            api_key=settings.consensus_api_key,
            api_secret=settings.consensus_api_secret,
            user_email=settings.consensus_user_email,
            source_name=settings.consensus_source_name,
            viewer_url_template=settings.consensus_viewer_url_template,
        )
    return StubConsensusClient()
