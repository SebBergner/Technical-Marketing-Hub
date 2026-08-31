"""Consensus V2 — the read API that actually has tags.

V1 exposes tags from none of its 21 endpoints, and tags are the whole reason
this exists: they carry segment, product, funnel stage and industry, four
dimensions V1 cannot supply at all.

The header nobody documents
---------------------------
`platform: developer-platform` is **required**. It appears in neither the
OpenAPI spec nor the OAuth guide; it was found in the JavaScript of Consensus's
own docs portal, which sets it on every request. Without it a perfectly valid
bearer token is rejected:

    Bearer <token>                     -> 401 "Token header is invalid"
    Bearer <token> + platform header   -> 200

That error names the token, so the missing header is invisible from the message
alone. Measured on the live tenant 2026-08-27.

Two further traps, both from the spec and both worth knowing before debugging a
400: `pageSize` has a **minimum of 5** (asking for 3 is a Bad Request), and
paging is by opaque cursor, not page number.

What V2 sees that V1 does not
-----------------------------
1,005 demos against V1's 637. The extra ones are drafts and unpublished work,
so the indexing boundary tightens rather than loosens — see `is_indexable`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime

import httpx

from backend.config import settings

log = logging.getLogger(__name__)

V2_ROOT = "/api/v2"

#: Undocumented and mandatory. See the module docstring.
PLATFORM_HEADER = "developer-platform"

#: The API rejects anything below 5, and caps at 100.
MIN_PAGE_SIZE, MAX_PAGE_SIZE = 5, 100


class ConsensusV2Error(RuntimeError):
    pass


class ConsensusV2Unauthorised(ConsensusV2Error):
    """No usable bearer token. Either OAuth has not been completed, or the
    manually supplied token has expired."""


@dataclass
class V2Page:
    items: list[dict] = field(default_factory=list)
    next_cursor: str | None = None


class ConsensusV2Client:
    def __init__(self, token: str | None = None, token_provider=None,
                 base_url: str | None = None,
                 transport: httpx.BaseTransport | None = None):
        #: A fixed token, for the interactive-docs token that unblocks work
        #: while OAuth is broken. `token_provider` is the real path: it is
        #: called per request so an expiring token refreshes itself.
        self._token = token
        self._token_provider = token_provider
        self.base_url = (base_url or settings.consensus_base_url).rstrip("/")
        self._transport = transport

    def _bearer(self) -> str:
        if self._token_provider is not None:
            return self._token_provider()
        if self._token:
            return self._token
        raise ConsensusV2Unauthorised(
            "No Consensus V2 token. Authorise at /api/consensus/oauth/start, "
            "or set CONSENSUS_V2_TOKEN to a token from "
            "https://app.goconsensus.com/api/v2/docs/portal/ for a temporary "
            "one.")

    def _get(self, path: str, params: dict) -> dict:
        headers = {
            "Authorization": f"Bearer {self._bearer()}",
            "platform": PLATFORM_HEADER,      # without this, every call 401s
            "Accept": "application/json",
        }
        with httpx.Client(timeout=60, transport=self._transport) as client:
            response = client.get(f"{self.base_url}{V2_ROOT}{path}",
                                  params=params, headers=headers)

        if response.status_code in (401, 403):
            raise ConsensusV2Unauthorised(
                f"HTTP {response.status_code} from V2: {response.text[:160]}. "
                f"If the token looks valid, check the `platform` header — its "
                f"absence is reported as an invalid token.")
        if response.status_code >= 400:
            raise ConsensusV2Error(
                f"HTTP {response.status_code} from V2 {path}: "
                f"{response.text[:200]}")
        payload = response.json()
        if not payload.get("success", True):
            raise ConsensusV2Error(f"V2 reported failure: {payload.get('error')}")
        return payload.get("data") or {}

    def search_page(self, cursor: str | None = None,
                    page_size: int = MAX_PAGE_SIZE, **filters) -> V2Page:
        params = {"pageSize": max(MIN_PAGE_SIZE, min(page_size, MAX_PAGE_SIZE))}
        if cursor:
            params["cursor"] = cursor
        params.update({k: v for k, v in filters.items() if v is not None})
        data = self._get("/demos/search", params)
        return V2Page(items=data.get("items") or [], next_cursor=data.get("next"))

    def all_demos(self, page_size: int = MAX_PAGE_SIZE,
                  max_pages: int = 40, **filters) -> list[dict]:
        """Every demo, following cursors.

        `max_pages` is a runaway guard, not a limit anyone should hit — the
        tenant holds ~1,005 demos, or eleven pages. If it ever trips, the
        catalogue has grown a lot or the cursor stopped advancing.
        """
        out: list[dict] = []
        cursor = None
        for page_number in range(max_pages):
            page = self.search_page(cursor=cursor, page_size=page_size, **filters)
            out.extend(page.items)
            cursor = page.next_cursor
            if not page.items or not cursor:
                return out
        log.warning("consensus v2: stopped at the %d-page guard with a cursor "
                    "still outstanding; the catalogue may be truncated", max_pages)
        return out


def _as_date(value) -> date | None:
    """V2 mixes two timestamp shapes: '2026-07-16T11:28:07' on updateDate and
    '2026-06-06 11:09:33' on creationDate."""
    if not value:
        return None
    text = str(value).strip().replace(" ", "T")[:19]
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def is_indexable(demo: dict) -> bool:
    """Whether a demo belongs in a catalogue everyone can search.

    V2 returns 1,005 where V1 returned 637 — the surplus is drafts, archived
    and unpublished work. Both flags are required, and for different reasons:
    `isPublished` keeps unfinished material out, and `isPublic` keeps out the
    customer-specific boards (Schneider Electric, Thales Canada, GE
    Appliances). The second is a confidentiality decision, not a quality one:
    an SE searching the catalogue must not find, and be able to forward, a
    board built for a different customer.

    503 of 1,005 pass, measured 2026-08-27.
    """
    return bool(demo.get("isPublic") and demo.get("isPublished")
                and not demo.get("isArchived"))


def viewer_url(demo: dict) -> str | None:
    """Where a person opens this demo — the fallback when V1 is unreachable.

    **V2 does not return `previewLink`** — V1 did, and the field is absent from
    the V2 schema entirely. Without reconstructing it every Consensus card in
    the grid is a dead end, which is most of what a Consensus result is for.

    `?preview=sales` is not decoration. Bare
    `play.goconsensus.com/<uuid>` opens a viewer that does not play: the demo
    loads without the internal preview context and there is nothing to watch.
    The first version of this function dropped the query string even though the
    docstring above it recorded the correct value, which is how every Consensus
    play button came to lead somewhere dead.

    Prefer the real `previewLink` from V1 where it can be had — see
    `media_from_v1` — and reach this only when it cannot.
    """
    uuid = demo.get("uuid")
    if not uuid:
        return None
    template = (settings.consensus_viewer_url_template
                or "https://play.goconsensus.com/{hash}?preview=sales")
    return template.format(hash=uuid)


def folder_path(demo: dict) -> list[str]:
    """The folder hierarchy, outermost first.

    V1 gave only the leaf name; V2 gives every level, so
    "PTC Digital Thread / Event Support / PTC NEXT - Spring 2026" survives
    intact instead of arriving as "PTC NEXT - Spring 2026" with no context.
    """
    info = demo.get("folderInfo") or []
    if isinstance(info, dict):          # V1 shape, tolerated
        return [info["name"]] if info.get("name") else []
    return [f["name"] for f in sorted(info, key=lambda f: f.get("level", 0))
            if f.get("name")]


def get_v2_client() -> ConsensusV2Client | None:
    """A usable V2 client, or None if nothing can authenticate.

    Two ways in, and the order matters. OAuth is the real one: it refreshes
    itself and belongs to a service account. CONSENSUS_V2_TOKEN is a token
    pasted by hand from the interactive docs — short-lived and tied to a
    person — and exists only because the OAuth client secret is currently
    unusable. OAuth wins the moment it works, with no config change.

    Returns None rather than raising so the caller can fall back to V1, which
    still works and simply has no tags.
    """
    from backend.integrations.consensus_oauth import get_oauth

    oauth = get_oauth()
    if oauth.configured and oauth.status().get("authorised"):
        return ConsensusV2Client(token_provider=oauth.access_token)
    if settings.consensus_v2_token:
        log.info("consensus v2: using the hand-supplied token; it will expire")
        return ConsensusV2Client(token=settings.consensus_v2_token)
    return None
