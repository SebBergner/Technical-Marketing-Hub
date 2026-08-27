"""Ordering search results by how well they match, not by how new they are.

Text search is a substring test, so before this every query fell back to
`recent` — which is a poor default for a search box in any catalogue, and
actively misleading in a federated one. Consensus content is simply newer than
SharePoint's, so recency systematically buried one platform: a search for
"codebeamer" put the first SharePoint result at position 18.

Deliberately crude. Six tiers, no term weighting, no stemming, no index. That
is enough to put a title match above a description match and an opening match
above one buried mid-string, which is the whole of the complaint. A real
ranker can replace this when there is evidence it is needed.
"""
from __future__ import annotations

import re

#: Higher is better. The gaps are meaningless — only the order matters.
EXACT_TITLE = 5
TITLE_PREFIX = 4
TITLE_WORD = 3
TITLE_SUBSTRING = 2
DESCRIPTION = 1
NO_MATCH = 0


def score(text: str | None, title: str | None, description: str | None = None) -> int:
    """How well one record answers a query. 0 when it does not."""
    needle = (text or "").strip().lower()
    if not needle:
        return NO_MATCH

    name = (title or "").strip().lower()
    if name == needle:
        return EXACT_TITLE
    if name.startswith(needle):
        return TITLE_PREFIX
    if name and re.search(rf"\b{re.escape(needle)}", name):
        # Word-boundary at the START only: "windchill" should match
        # "Windchill PDMLink", and requiring a boundary at the end too would
        # reject it.
        return TITLE_WORD
    if needle in name:
        return TITLE_SUBSTRING
    if needle in (description or "").lower():
        return DESCRIPTION
    return NO_MATCH
