"""How old a piece of content is, in the bands people see (Serge, 2026-10-13).

One place for the bands, so the "Published" filter, the age badges on cards
and the content-review list can never disagree about what "New" means.
Age = today minus the publish date (`uploaded_at`):

    new      under 1 year        badge "New"
    recent   1 to 2 years        no badge
    aging    2 to 4 years        badge with the year ("2023")
    older    4 years or more     badge "Older UI · 2019"

Collecting dust (7 years or more, not confirmed Still current) is a review
view only, never a band on search results.

A year is 365 days here, not a calendar year: the bands are about how far
the software has moved on, and an off-by-one-day leap year is noise.
"""
from __future__ import annotations

from datetime import date, timedelta

NEW, RECENT, AGING, OLDER = "new", "recent", "aging", "older"
#: In the order the filter lists them, with the words it shows.
BANDS = [(NEW, "Under 1 year"), (RECENT, "1–2 years"), (AGING, "2–4 years"),
         (OLDER, "4 years or more")]
#: Upper bounds in years: a date this many years back or less is in the band.
_LIMITS = [(NEW, 1), (RECENT, 2), (AGING, 4)]
DUST_YEARS = 7


def _years(days: int) -> float:
    return days / 365.0


def band(published: date | None, today: date | None = None) -> str | None:
    """The band a publish date falls in, or None without a date."""
    if published is None:
        return None
    age = _years(((today or date.today()) - published).days)
    for name, limit in _LIMITS:
        if age < limit:
            return name
    return OLDER


def collecting_dust(published: date | None, today: date | None = None) -> bool:
    if published is None:
        return False
    return _years(((today or date.today()) - published).days) >= DUST_YEARS


def matches(published: date | None, wanted: list[str], today: date | None = None) -> bool:
    """For the Published filter: each wanted value is a band or a year."""
    if not wanted:
        return True
    if published is None:
        return False
    mine = band(published, today)
    return any(w == mine or w == str(published.year) for w in wanted)


def is_band(value: str) -> bool:
    return value in {name for name, _ in BANDS}


def since(years: int, today: date | None = None) -> date:
    return (today or date.today()) - timedelta(days=round(365 * years))
