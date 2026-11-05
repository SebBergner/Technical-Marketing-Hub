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
    words = [t.lower() for t in _TOKEN.findall(text or "")]
    # "and" is "&" (Liwei, 2026-11-05): "&" is no word at all, so "tips &
    # techniques" found 62 and "tips and techniques" 3. Dropped from query
    # and title alike, so phrases still line up -- unless it is all there is.
    kept = [w for w in words if w not in _JOINERS]
    return kept or words


_JOINERS = frozenset({"and"})


#: A word this short only counts as a whole word (Liwei, 2026-10-01).
#: Searching "E&HT" split into "e" and "ht", and "e" is inside nearly every
#: title, so the query returned 176 results instead of the one E&HT demo;
#: "ai" likewise matched "maintenance" and "chain".
SHORT_TERM = 2

#: Whole words by default (Seb, 2026-11-05): searching "CAM" found every
#: "Camera" demo, and he wanted the CAM ones. A word still matches its plural
#: ("demo" finds "demos", "cam" finds "CAMs"). Advanced Search can ask for
#: part of a word instead (`partial=True`), which is how every word longer
#: than SHORT_TERM matched before: "wind" finding "Windchill".
#:
#: Chinese, Japanese and Korean are written without spaces, so a title there
#: is one long token and a word inside it is never "whole": those terms
#: always match anywhere.
_CJK = re.compile("[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\uf900-\ufaff]")
_PLURAL = r"(?:s|es)?"


def _is_short(term: str) -> bool:
    return len(term) <= SHORT_TERM


def _anywhere(term: str, partial: bool) -> bool:
    """Whether `term` may match inside a word."""
    if _CJK.search(term):
        return True
    return partial and not _is_short(term)


def _term_pattern(term: str, partial: bool) -> str:
    if _CJK.search(term):
        return re.escape(term)
    if _anywhere(term, partial):
        # Anywhere, and its whole-word plurals too, so "part of words" finds
        # everything whole-word search does ("assembly" -> "Assemblies").
        return "(?:" + re.escape(term) + "|" + _term_pattern(term, False) + ")"
    # Partial search keeps a short word exact, as before; whole-word search
    # lets every word take a plural ending.
    return r"(?<!\S)" + _word(term, partial) + r"(?!\S)"


def _word(term: str, partial: bool) -> str:
    """The word, and in whole-word search its plurals too: "demo" ->
    "demos", "process" -> "processes", "assembly" -> "assemblies"."""
    if partial:
        return re.escape(term)
    if len(term) > 3 and term.endswith("y"):
        return re.escape(term[:-1]) + r"(?:y|ies)"
    return re.escape(term) + _PLURAL


def _bounded(phrase: str, wanted: list[str], partial: bool = False) -> str:
    """The phrase as a pattern, bounded on each end the way its first and
    last word are (_term_pattern). Normalised text is single-space-separated
    tokens, so a boundary is "not next to a non-space"."""
    start = "" if _anywhere(wanted[0], partial) else r"(?<!\S)"
    if _anywhere(wanted[-1], partial):
        return start + re.escape(phrase)
    head = phrase[: len(phrase) - len(wanted[-1])]
    return start + re.escape(head) + _word(wanted[-1], partial) + r"(?!\S)"


def _has(text: str, term: str, partial: bool = False) -> bool:
    """One query word in normalised text."""
    return re.search(_term_pattern(term, partial), text) is not None


def _find_end(text: str, term: str, partial: bool = False) -> int:
    """Where the first occurrence of `term` ends in `text`, or -1."""
    m = re.search(_term_pattern(term, partial), text)
    return m.end() if m else -1


def score(text: str | None, title: str | None, description: str | None = None,
          partial: bool = False) -> int:
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

    wanted = terms(text)
    pattern = _bounded(phrase, wanted, partial)
    if normalised_title == phrase:
        return EXACT_TITLE
    if re.match(pattern, normalised_title):
        return TITLE_PREFIX
    if re.search(rf"\b{pattern}", normalised_title):
        # Word boundary at the START only (plus the end when the last word
        # is short). "windchill" must match "Windchill PDMLink"; requiring
        # a boundary at the end too would reject it.
        return TITLE_WORD
    if re.search(pattern, normalised_title):
        return TITLE_SUBSTRING

    if all(_has(normalised_title, t, partial) for t in wanted):
        return TITLE_ALL_TERMS
    haystack = f"{normalised_title} {' '.join(terms(description))}"
    if all(_has(haystack, t, partial) for t in wanted):
        return ANY_FIELD
    return NO_MATCH


#: Stand-in span for a title that does not contain every term. Any real span is
#: smaller, so these sort last within their tier and recency then decides.
_NO_SPAN = 10_000


def span(text: str | None, title: str | None, partial: bool = False) -> int:
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
        end = _find_end(name, term, partial)
        if end < 0:
            return _NO_SPAN
        furthest = max(furthest, end)
    return furthest


def ranking(text: str | None, title: str | None,
            description: str | None = None, partial: bool = False) -> tuple[int, int]:
    """Sort key for one record, best first when sorted descending.

    Tier decides; span breaks ties inside it. Callers append their own final
    tiebreak — recency — so equally-good matches keep a stable order.
    """
    return (score(text, title, description, partial), -span(text, title, partial))


#: How search results are ORDERED, coarser than the tiers on purpose.
#:
#: Liwei, 2026-09-30: searching "BMX", the newest demo ("Introduction to
#: Behavioral Modeling (BMX) - LDK", 2026-09-25) came ninth, behind 2024 kits,
#: because a title that merely STARTS with the word, or says it a few
#: characters sooner, outranked it and the date only broke exact ties. Among
#: results that name the query in their title, the newest is the better
#: answer. So: the title being exactly the query still wins outright; every
#: other way of having the query in the title is one band, newest first;
#: then titles with the words scattered; then description-only hits. Span
#: now only orders results published the same day.
_BAND = {EXACT_TITLE: 3, TITLE_PREFIX: 2, TITLE_WORD: 2, TITLE_SUBSTRING: 2,
         TITLE_ALL_TERMS: 1, ANY_FIELD: 0}


def order_key(text: str | None, title: str | None, description: str | None,
              recency) -> tuple:
    """Sort key for search results, best first when sorted descending:
    band, then publish date, then span."""
    return (_BAND.get(score(text, title, description), -1), recency, -span(text, title))


def matches(text: str | None, title: str | None,
            description: str | None = None, partial: bool = False) -> bool:
    """Whether a record belongs in the results at all.

    Defined as "scores above zero" so membership and ranking cannot disagree.
    """
    return score(text, title, description, partial) > NO_MATCH


def names(text: str | None, name: str | None, partial: bool = False) -> bool:
    """Whether every term of the query is in a file name.

    File names are written for machines -- "Bobcat_03_Engineering.mp4" --
    so they are split into words exactly as the query is (`terms()` already
    treats underscores and dots as separators) and each term must appear
    somewhere, in any order. Used by Advanced Search only.
    """
    wanted = terms(text)
    if not wanted:
        return False
    haystack = " ".join(terms(name))
    return all(_has(haystack, t, partial) for t in wanted)


#: Advanced Search's order. A file-name hit is a stronger answer than a word
#: buried in a description, weaker than the demo's own title saying it.
_ADVANCED_BAND = {EXACT_TITLE: 5, TITLE_PREFIX: 4, TITLE_WORD: 4,
                  TITLE_SUBSTRING: 4, TITLE_ALL_TERMS: 3, ANY_FIELD: 1}
FILE_NAME_BAND = 2


def advanced_order_key(text: str | None, title: str | None,
                       description: str | None, file_hits: int, recency,
                       partial: bool = False) -> tuple:
    """Sort key for Advanced Search, best first when sorted descending:
    band (title > file name > description), then publish date, then span."""
    band = _ADVANCED_BAND.get(score(text, title, description, partial), 0)
    if file_hits:
        band = max(band, FILE_NAME_BAND)
    return (band, recency, -span(text, title, partial))
