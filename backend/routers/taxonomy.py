"""Taxonomy and facet endpoints.

These exist so the frontend stops hardcoding things. Today the mockup has the
filter <option> lists written into the markup and the sidebar counts typed in
by hand (Videos 86, LDKs 22, …) with no data behind them. Both come from here
instead, which means they cannot drift from reality.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from backend.deps import get_repo
from backend.models import ContentDepth, Facets
from backend.repositories.base import AssetQuery, AssetRepository

router = APIRouter(prefix="/api/taxonomy", tags=["taxonomy"])

#: Distribution channel -> content depth, used by the Request-New-Asset form.
#:
#: The requirements doc flags this mapping as "defined by Claude as a sensible
#: default, not dictated by the requester — should be reviewed". Serving it from
#: the API means correcting it is a config change, not a code deploy.
#:
#: Keyed by a stable slug, NOT by the pill's visible label. The mockup keys on
#: `textContent`, which works only by luck; any copy edit silently collapses
#: every recommendation to "Overview".
CHANNEL_TO_DEPTH: dict[str, str] = {
    "social": "Teaser",
    "event": "Teaser",
    "web": "Overview",
    "estore": "Overview",
    "prospect": "Explainer",
    "customer": "Explainer",
    "velocity": "Explainer",
    "enablement": "Walkthrough",
    "internal": "Walkthrough",
}

CHANNEL_LABELS: dict[str, str] = {
    "social": "Social (LinkedIn / YouTube)",
    "web": "Web (PTC.com)",
    "estore": "eStore",
    "prospect": "Share with a prospect",
    "customer": "Share with an existing customer",
    "enablement": "Internal sales enablement",
    "event": "Event / trade show",
    "internal": "Internal Hub only",
    "velocity": "Push to PTC Velocity",
}

DEPTH_HINTS: dict[str, str] = {
    "Teaser": "Under 60 seconds. One hook, no setup, built to stop a scroll.",
    "Overview": "2–3 minutes. What it is and why it matters, no click-by-click.",
    "Explainer": "4–6 minutes. Enough product to make the value concrete.",
    "Walkthrough": "8 minutes or more. Full flow, narrated, for people who will run it.",
}


@router.get("", response_model=Facets)
def get_facets(
    q: str | None = Query(default=None),
    type: list[str] = Query(default=[]),
    product: list[str] = Query(default=[]),
    family: list[str] = Query(default=[]),
    stage: list[str] = Query(default=[]),
    segment: list[str] = Query(default=[]),
    language: list[str] = Query(default=[]),
    depth: list[str] = Query(default=[]),
    source: list[str] = Query(default=[]),
    tag: list[str] = Query(default=[]),
    customer_facing: bool | None = None,
    repo: AssetRepository = Depends(get_repo),
):
    """Every filter value with a real count behind it.

    Takes the same filters as `/api/assets`, and the counts then describe that
    slice rather than the whole catalogue. Without this a filter panel lies as
    soon as anything is selected: choose Type=VDK and "Creo (382)" still claims
    382, when clicking it yields far fewer. A count has to promise what you
    will actually get.

    With no filters it behaves exactly as before.
    """
    query = AssetQuery(
        text=q, types=type, products=product, product_families=family,
        funnel_stages=stage, segments=segment, languages=language,
        content_depths=depth, sources=source, tags=tag,
        customer_facing=customer_facing,
    )
    any_filter = any([q, type, product, family, stage, segment, language,
                      depth, source, tag]) or customer_facing is not None
    return repo.facets(query if any_filter else None)


@router.get("/video-levels")
def get_video_levels():
    """The Teaser/Overview/Explainer/Walkthrough taxonomy and its channel mapping."""
    return {
        "levels": [d.value for d in ContentDepth],
        "hints": DEPTH_HINTS,
        "channels": [
            {"key": key, "label": CHANNEL_LABELS[key], "depth": CHANNEL_TO_DEPTH[key]}
            for key in CHANNEL_LABELS
        ],
    }


@router.get("/rails")
def get_rails(repo: AssetRepository = Depends(get_repo)):
    """Gallery rail name -> ordered asset ids."""
    return repo.rails()
