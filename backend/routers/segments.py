"""Segment landing pages.

A segment is the one grouping in this catalogue that is both small enough to
curate and large enough to be worth visiting: six of them against nineteen
product families, whose long tail runs down to one asset each.

The page has two kinds of content and they are kept strictly apart.

*Derived* content — how many demos, which products, what types, what is newest
— is computed from the catalogue on every request and cannot go stale. It is
the same repository call the filters use, so a page can never promise a number
the grid then fails to deliver.

*Editorial* content — a description and who owns the segment — is written by a
person and stored under `owned/`. It is absent until somebody writes it, and
the API says so plainly rather than inventing a plausible sentence. This
project has already been bitten by hand-typed content that drifted (a sidebar
claiming Creo had 24 demos against a real 382), so the rule is: anything a
human writes carries their name and the date they wrote it, and anything
missing looks missing.

Release announcements deliberately have no home here. They were the one block
with a shelf life measured in weeks, and they already reach people through the
demo itself and through email.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from backend.config import settings
from backend.deps import get_repo
from backend.models import AssetSummary, FacetValue
from backend.repositories.base import AssetQuery, AssetRepository
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/segments", tags=["segments"])

#: How many recent assets a landing page shows. Ten is what was asked for, and
#: it is a rail rather than a catalogue: the full grid is directly underneath.
LATEST_LIMIT = 10


class SegmentOwner(BaseModel):
    name: str
    email: str | None = None
    teams: str | None = None


class SegmentEditorial(BaseModel):
    """The half a person writes. Every field may legitimately be missing."""
    blurb: str | None = None
    owner: SegmentOwner | None = None
    #: Who last edited this and when. Without it there is no way to judge
    #: whether the sentence above is still true.
    updated_by: str | None = None
    updated_at: str | None = None


class Segment(BaseModel):
    key: str
    label: str
    #: Everything below is derived and therefore always current.
    total: int
    families: list[FacetValue] = Field(default_factory=list)
    types: list[FacetValue] = Field(default_factory=list)
    sources: list[FacetValue] = Field(default_factory=list)
    editorial: SegmentEditorial = Field(default_factory=SegmentEditorial)


class SegmentDetail(Segment):
    latest: list[AssetSummary] = Field(default_factory=list)


def _editorial_path() -> str:
    return os.path.join(settings.data_dir, "owned", "segments.json")


def _load_editorial() -> dict[str, Any]:
    """Portal-owned, so it lives under owned/ and no sync may touch it.

    Note for deployment: `DATA_DIR` on Azure App Service is ephemeral, so this
    file does not survive a restart until it points at Azure Files. Until then
    the honest state after a redeploy is "nobody has written this yet", which
    is at least visibly wrong rather than quietly stale.
    """
    path = _editorial_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh) or {}
    except (OSError, ValueError):
        # A broken file must not take the page down; an empty editorial block
        # renders as "not written yet", which is the truthful fallback.
        log.exception("segments.json is unreadable, serving no editorial content")
        return {}


def _build(repo: AssetRepository, key: str, total: int) -> Segment:
    facets = repo.facets(AssetQuery(segments=[key]))
    editorial = _load_editorial().get(key) or {}
    return Segment(
        key=key, label=key, total=total,
        families=facets.product_families, types=facets.types,
        sources=facets.sources,
        editorial=SegmentEditorial(**editorial),
    )


@router.get("")
def list_segments(repo: AssetRepository = Depends(get_repo)) -> dict[str, list[Segment]]:
    """Every segment with a real count behind it, largest first.

    Which segments exist is a question for the catalogue, not for a list in
    the markup. Elio's file offers CAD/PLM/ALM/SLM/IPL; the data holds
    CAD/PLM/ALM/SLM/IoT/SCO, so "IPL" would have been a page matching nothing
    and IoT — 78 demos — would have had no page at all.
    """
    counts = {f.value: f.count for f in repo.facets().segments}
    ordered = sorted(counts.items(), key=lambda kv: -kv[1])
    return {"segments": [_build(repo, key, total) for key, total in ordered]}


@router.get("/{key}", response_model=SegmentDetail)
def get_segment(key: str, repo: AssetRepository = Depends(get_repo)) -> SegmentDetail:
    counts = {f.value: f.count for f in repo.facets().segments}
    # Case-insensitive, because a segment key travels in a URL and "plm" is
    # what a person types.
    match = next((k for k in counts if k.lower() == key.lower()), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"no such segment: {key}")

    base = _build(repo, match, counts[match])
    latest = repo.list(AssetQuery(segments=[match], sort="recent", limit=LATEST_LIMIT))
    return SegmentDetail(**base.model_dump(), latest=latest.items)
