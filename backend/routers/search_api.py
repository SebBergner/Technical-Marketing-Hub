"""A search API for other programs: Growth OS and the like (Seb, 2026-11-17).

`GET /api/v1/search` takes a search term and filters and returns a JSON list
of demos, each with a link to its Hub page and to its files. It is the
Hub's own search, not a second one: the same `repo.list(AssetQuery(...))`
the page calls, so search-term groups, relevance and who may see what are
exactly the page's.

The contract is the point. `/api/assets` returns whatever the page needs and
changes with it; this answer is documented in docs/search-api.md and only
grows (new fields), so a program can rely on it.

A caller is a person or an API token (backend/api_tokens.py, Bearer
`tmh_<id>_<secret>`). It needs View the Hub, as everything does.

This is not a person searching, so it is **not** recorded as a search
(`/search-event`): the Content Health numbers count people (Seb, 2026-11-17).
"""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.access import Perm
from backend.auth import CurrentUser, require_authenticated
from backend.config import settings
from backend.deps import get_repo
from backend.repositories.base import AssetQuery, AssetRepository
from backend.routers.assets import _gxc_downloads, _locked_for

router = APIRouter(prefix="/api/v1", tags=["search api"])

#: A long description is cut here; the Hub page has the whole of it.
SUMMARY_CHARS = 500
MAX_LIMIT = 100


class SearchFile(BaseModel):
    name: str
    kind: str
    size_bytes: int | None = None
    #: Both left out (None) when the caller may not open or download that
    #: file: the name is still listed, as on the demo's page.
    preview_url: str | None = None
    download_url: str | None = None


class SearchHit(BaseModel):
    id: str
    title: str
    summary: str | None = None
    type: str
    products: list[str] = Field(default_factory=list)
    families: list[str] = Field(default_factory=list)
    segment: str | None = None
    industry: str | None = None
    language: str
    published: str | None = None
    customer_facing: bool
    internal: bool
    hub_url: str
    #: False when no file of this demo can be opened or downloaded by the
    #: caller (a locked demo, a source without files, a token without
    #: Preview and Download); `files` then lists names only, or nothing.
    files_available: bool
    files: list[SearchFile] = Field(default_factory=list)


class SearchResponse(BaseModel):
    query: str | None = None
    total: int
    limit: int
    offset: int
    items: list[SearchHit]
    #: Set when `q` as given found nothing and the Hub searched these words
    #: instead ("creo13" -> "creo 13"), as its own search page does
    #: (2026-11-25). Absent otherwise.
    searched_as: str | None = None


def _require_view_hub(user: CurrentUser = Depends(require_authenticated)) -> CurrentUser:
    if not user.can(Perm.VIEW_HUB):
        raise HTTPException(status_code=403,
                            detail="Your account does not have permission for this.")
    return user


def _summary(text: str | None) -> str | None:
    text = (text or "").strip()
    if len(text) <= SUMMARY_CHARS:
        return text or None
    return text[:SUMMARY_CHARS].rsplit(" ", 1)[0].rstrip(".,;: ") + "…"


def _files(asset, user: CurrentUser, repo: AssetRepository, base: str) -> list[SearchFile]:
    """The demo's files, by name, with the two links each caller may use."""
    locked = _locked_for(user, asset)
    may_preview = not locked and user.can(Perm.PREVIEW)
    may_download = (not locked and user.can(Perm.DOWNLOAD)
                    and not (asset.gxc and not _gxc_downloads(repo)))
    out = []
    for r in asset.resources:
        mine = f"{base}/api/assets/{quote(asset.id, safe='')}/files/{quote(r.item_id or '', safe='')}"
        out.append(SearchFile(
            name=r.name, kind=r.kind.value, size_bytes=r.size_bytes,
            preview_url=f"{mine}/preview" if r.item_id and may_preview else None,
            download_url=f"{mine}/download" if r.item_id and may_download else None))
    return out


@router.get("/search", response_model=SearchResponse)
def search(
    q: str | None = Query(default=None, description="search text; the Hub's own "
                          "search, search-term groups and relevance included"),
    product: list[str] = Query(default=[]),
    family: list[str] = Query(default=[], description="product family, as in the Hub"),
    umbrella: list[str] = Query(default=[]),
    segment: list[str] = Query(default=[]),
    industry: list[str] = Query(default=[]),
    type: list[str] = Query(default=[]),
    language: list[str] = Query(default=[]),
    limit: int = Query(default=20, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    repo: AssetRepository = Depends(get_repo),
    user: CurrentUser = Depends(_require_view_hub),
):
    page = repo.list(AssetQuery(
        text=q, products=product, product_families=family, umbrella_families=umbrella,
        segments=segment, industries=industry, types=type, languages=language,
        sort="relevance", limit=limit, offset=offset))
    base = settings.public_base_url.rstrip("/")
    items = []
    for s in page.items:
        # The summary has no file list: the full record does (and applies the
        # same visibility as the demo's page).
        full = repo.get(s.id) or s
        files = _files(full, user, repo, base) if hasattr(full, "resources") else []
        items.append(SearchHit(
            id=s.id, title=s.title, summary=_summary(s.description), type=s.type.value,
            products=s.products, families=s.product_families, segment=s.segment,
            industry=s.industry, language=s.language,
            published=s.uploaded_at.isoformat() if s.uploaded_at else None,
            customer_facing=s.customer_facing, internal=s.internal,
            hub_url=f"{base}/#/asset/{quote(s.id, safe='')}",
            files_available=any(f.preview_url or f.download_url for f in files),
            files=files))
    return SearchResponse(query=q, total=page.total, limit=page.limit,
                          offset=page.offset, items=items, searched_as=page.searched_as)
