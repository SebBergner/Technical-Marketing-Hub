"""What counts as a search hit, and how hits are ordered.

Both questions live here on purpose. When the filter and the ranking are
written separately they drift, and the failure is silent: a record scores well
but was already excluded, or is included but scores zero and sinks.

Two problems this fixes, in order of how much they mattered.

**Multi-word queries returned nothing.** The filter tested the whole query as
one substring, so "Creo overview" did not match "Creo Parametric Overview" —
the words are there, but not adjacent. Every term must now be present
somewhere, in any order. Adding a word narrows the result set, which is what a
search box is expected to do.

**Ordering was by age.** Text search had no scoring, so every query fell back
to recency. That is a poor default anywhere, and in a federated catalogue an
actively biased one: Consensus content is newer than SharePoint's, so recency
buried one platform.

Deliberately crude — no term weighting, no stemming, no index, no fuzzy
matching. It answers the actual complaints. A real ranker can replace it when
there is evidence one is needed.
"""
from __future__ import annotations

import re

#: Higher is better. The gaps carry no meaning; only the order does.
EXACT_TITLE = 6         # title is the query
TITLE_PREFIX = 5        # title opens with the query, as typed
TITLE_WORD = 4          # the query, as typed, starts a word in the title
TITLE_SUBSTRING = 3     # the query, as typed, appears anywhere in the title
TITLE_ALL_TERMS = 2     # every term is in the title, but scattered
ANY_FIELD = 1           # every term is somewhere in title or description
DESCRIPTION = ANY_FIELD  # retained name; a description-only hit lands here
NO_MATCH = 0

_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


def terms(text: str | None) -> list[str]:
    """The query split into words, lowercased.

    Unicode-aware, because the catalogue holds Japanese, Korean and Chinese
    titles and `\\w` under `re.UNICODE` keeps them rather than discarding them
    the way an ASCII class would.
    """
    return [t.lower() for t in _TOKEN.findall(text or "")]


def score(text: str | None, title: str | None, description: str | None = None) -> int:
    """How well one record answers a query. 0 means it does not.

    A contiguous phrase match always outranks the same words scattered, so
    "Creo Overview" beats "Creo Parametric Overview" for the query
    "creo overview" — both match, and the closer one comes first.
    """
    phrase = " ".join(terms(text))
    if not phrase:
        return NO_MATCH

    name = (title or "").strip().lower()
    normalised_title = " ".join(terms(name))

    if normalised_title == phrase:
        return EXACT_TITLE
    if normalised_title.startswith(phrase):
        return TITLE_PREFIX
    if re.search(rf"\b{re.escape(phrase)}", normalised_title):
        # Word boundary at the START only. "windchill" must match
        # "Windchill PDMLink"; requiring a boundary at the end too would
        # reject it.
        return TITLE_WORD
    if phrase in normalised_title:
        return TITLE_SUBSTRING

    wanted = terms(text)
    if all(t in normalised_title for t in wanted):
        return TITLE_ALL_TERMS
    haystack = f"{normalised_title} {' '.join(terms(description))}"
    if all(t in haystack for t in wanted):
        return ANY_FIELD
    return NO_MATCH


#: Stand-in span for a title that does not contain every term. Any real span is
#: smaller, so these sort last within their tier and recency then decides.
_NO_SPAN = 10_000


def span(text: str | None, title: str | None) -> int:
    """How far into the title you must read before every term has appeared.

    The tiers alone barely discriminate on multi-word queries: "Creo overview"
    put all 61 live hits into just two of the six, leaving a 31-item bucket
    ordered by nothing but age. Within a tier, the title that says it soonest
    is the better answer —

        Creo Parametric Overview                      -> 24
        PTC NEXT - Spring 2026 - Creo 13 AI Overview  -> 40

    which also, for free, prefers the tighter title over the padded one.
    """
    wanted = terms(text)
    name = " ".join(terms(title))
    if not wanted or not name:
        return _NO_SPAN
    furthest = 0
    for term in wanted:
        at = name.find(term)
        if at < 0:
            return _NO_SPAN
        furthest = max(furthest, at + len(term))
    return furthest


def ranking(text: str | None, title: str | None,
            description: str | None = None) -> tuple[int, int]:
    """Sort key for one record, best first when sorted descending.

    Tier decides; span breaks ties inside it. Callers append their own final
    tiebreak — recency — so equally-good matches keep a stable order.
    """
    return (score(text, title, description), -span(text, title))


def matches(text: str | None, title: str | None,
            description: str | None = None) -> bool:
    """Whether a record belongs in the results at all.

    Defined as "scores above zero" so membership and ranking cannot disagree.
    """
    return score(text, title, description) > NO_MATCH
