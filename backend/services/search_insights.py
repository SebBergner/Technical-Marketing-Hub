"""Search insights for Content health -> Searches (Liwei, 2026-11-12).

Modelled on what search-analytics products show (Algolia Analytics, Google
Search Console, Coveo): counted by people as well as searches, compared with
the period before, with variants of one word counted as one, and with the
question that matters most after "did it find anything": did anyone open
what it found.

Measured on production's events (22 Sep - 11 Nov 2026, 742 searches) before
this was built:

* 161 of them (22%) were typing: the same person searching again within a
  minute for a longer string that starts with it ("bobcat service technical
  o", "...ov", "...ove" ...). The box records once typing pauses for two
  seconds, which a slow typist does mid-word. They are left out, the last
  one kept.
* Many "no results" were a word cut short or misspelt: "lambo" (12 times)
  for Lamborghini, "jestream" for Jetstream, "asso" for Associativity. The
  catalogue has the content; the words differ. These are near misses, apart
  from real gaps ("purdue", "coastguard": nothing like it anywhere).

Everything is counted per person, never shown by name.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

#: A search followed by the same person's longer search starting with it,
#: this soon after, was typing, not a question.
TYPING_SECONDS = 60
#: A view, preview or download by the same person this soon after a search,
#: before their next one, counts as opening what it found.
OPEN_SECONDS = 10 * 60
#: "Few": this many results or fewer.
FEW = 2
#: Trends need people, not repeats: a word must be searched by at least this
#: many different people in a period to rise, or to be new.
TREND_MIN_PEOPLE = 3
#: Below this many people searching in both periods together, no trend is
#: claimed at all.
TREND_MIN_TOTAL_PEOPLE = 10
#: How many words get "finds now" (a catalogue search each).
MAX_LOOKUPS = 150
OPEN_EVENTS = ("view", "preview", "download")


# ───────────────────────────────────────────────────────────── words
def norm(q) -> str:
    return " ".join(str(q or "").split()).lower()


def _parse(at: str | None) -> datetime | None:
    if not at:
        return None
    try:
        d = datetime.fromisoformat(at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _edit1(a: str, b: str) -> bool:
    """One letter added, dropped or changed (jestream / jetstream)."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:]


_WORD = re.compile(r"[a-z0-9][a-z0-9+&.-]*")


def vocabulary(records) -> Counter:
    """The catalogue's own words -- titles, products, families, customers,
    tags -- with how many demos carry each."""
    vocab: Counter = Counter()
    for r in records:
        words = set()
        for text in [r.get("title")] + list(r.get("products") or []) \
                + list(r.get("product_families") or []) + list(r.get("tags") or []) \
                + [r.get("named_customer")]:
            if isinstance(text, str):
                words.update(w.strip(".-") for w in _WORD.findall(text.lower()))
        vocab.update(w for w in words if len(w) >= 3)
    return vocab


def near_word(q: str, vocab: Counter, searched: Counter | None = None) -> str | None:
    """The catalogue word a search probably meant: one it is the start of
    ("lambo" -> "lamborghini", at least 4 letters), or one letter away from
    ("jestream" -> "jetstream", at least 5). A word people searched for in
    full wins ("assoc" -> "associativity", not "associations"), then the
    word most demos carry. Only for single words: a phrase's words are each
    looked up on their own by the search itself."""
    if " " in q or q in vocab:
        return None
    searched = searched or Counter()
    best = None
    for word, n in vocab.items():
        if word == q:
            continue
        hit = (len(q) >= 4 and len(word) > len(q) and word.startswith(q))             or (len(q) >= 5 and _edit1(q, word))
        rank = (searched.get(word, 0), n)
        if hit and (best is None or rank > best[1]):
            best = (word, rank)
    return best[0] if best else None


# ─────────────────────────────────────────────────────────── events
def without_typing(searches: list[dict]) -> tuple[list[dict], int]:
    """Drop the searches that were someone still typing (module doc)."""
    by_user: dict[object, list[dict]] = defaultdict(list)
    for e in searches:
        by_user[e.get("user")].append(e)
    kept, dropped = [], 0
    for events in by_user.values():
        events.sort(key=lambda e: e.get("at") or "")
        for i, e in enumerate(events):
            q, at = norm(e.get("q")), _parse(e.get("at"))
            typing = False
            if e.get("user") and at:
                for later in events[i + 1:]:
                    t2 = _parse(later.get("at"))
                    if not t2 or (t2 - at).total_seconds() > TYPING_SECONDS:
                        break
                    q2 = norm(later.get("q"))
                    if q2 != q and q2.startswith(q):
                        typing = True
                        break
            if typing:
                dropped += 1
            else:
                kept.append(e)
    return kept, dropped


def mark_opened(searches: list[dict], uses: list[dict]) -> None:
    """Set `_opened` on each search: did the same person open, preview or
    download something within OPEN_SECONDS, before searching again."""
    uses_by_user: dict[object, list[datetime]] = defaultdict(list)
    for u in uses:
        if u.get("user") and (t := _parse(u.get("at"))):
            uses_by_user[u["user"]].append(t)
    for times in uses_by_user.values():
        times.sort()
    by_user: dict[object, list[dict]] = defaultdict(list)
    for e in searches:
        by_user[e.get("user")].append(e)
    for user, events in by_user.items():
        events.sort(key=lambda e: e.get("at") or "")
        times = uses_by_user.get(user) or []
        for i, e in enumerate(events):
            e["_opened"] = None
            at = _parse(e.get("at"))
            if not user or not at:
                continue                       # unknown person: cannot tell
            nxt = _parse(events[i + 1].get("at")) if i + 1 < len(events) else None
            end = at + timedelta(seconds=OPEN_SECONDS)
            if nxt and nxt < end:
                end = nxt
            e["_opened"] = any(at <= t <= end for t in times)


# ───────────────────────────────────────────────────────── analysis
def _filters_key(filters) -> tuple:
    return tuple(sorted((k, tuple(sorted(v))) for k, v in (filters or {}).items() if v))


def _bucket_label(at: datetime, daily: bool) -> str:
    if daily:
        return at.date().isoformat()
    monday = at.date() - timedelta(days=at.weekday())
    return monday.isoformat()


def _counts(events: list[dict]) -> dict:
    people = {e.get("user") for e in events if e.get("user")}
    zero = sum(1 for e in events if not e.get("results"))
    few = sum(1 for e in events if 0 < (e.get("results") or 0) <= FEW)
    known = [e for e in events if e.get("_opened") is not None and e.get("results")]
    opened = sum(1 for e in known if e["_opened"])
    return {"searches": len(events), "people": len(people), "no_results": zero,
            "few_results": few, "found": len(events) - zero,
            "opened_known": len(known), "opened": opened}


def insights(events: list[dict], since: datetime | None, until: datetime,
             finds_now, vocab: Counter, filters_words) -> dict:
    """Everything the Searches tab shows. `events` is every usage event
    (any period), `finds_now(q, key)` what a search finds today,
    `filters_words(key)` a filter set in words."""
    def within(e, lo, hi):
        t = _parse(e.get("at"))
        return t is not None and (lo is None or t >= lo) and t < hi

    searches = [e for e in events if e.get("event") == "search" and norm(e.get("q"))]
    uses = [e for e in events if e.get("event") in OPEN_EVENTS]
    searches, typing = without_typing(searches)
    mark_opened(searches, uses)

    current = [e for e in searches if within(e, since, until)]
    recorded = sum(1 for e in events if e.get("event") == "search" and within(e, since, until))
    if since is not None:
        prev_since = since - (until - since)
        previous = [e for e in searches if within(e, prev_since, since)]
    else:
        prev_since, previous = None, []

    # Variants counted as one: a word the catalogue does not have, but nearly
    # does, joins the word it nearly is ("lambo" with "lamborghini").
    near: dict[str, str | None] = {}
    searched = Counter(norm(e.get("q")) for e in current + previous)

    def term(q: str) -> str:
        if q not in near:
            near[q] = near_word(q, vocab, searched)
        return near[q] or q

    # ── by words, for Most searched and Trending (filters set aside)
    def by_term(evs):
        out: dict[str, dict] = {}
        for e in evs:
            q = norm(e.get("q"))
            # Only a search that found little joins the word it nearly is:
            # "code" finding plenty is its own question, not Codebeamer.
            key = term(q) if (e.get("results") or 0) <= FEW else q
            t = out.setdefault(key, {"variants": Counter(), "times": 0, "people": set(),
                                         "opened": 0, "known": 0})
            t["variants"][q] += 1
            t["times"] += 1
            if e.get("user"):
                t["people"].add(e["user"])
            if e.get("_opened") is not None and e.get("results"):
                t["known"] += 1
                t["opened"] += 1 if e["_opened"] else 0
        return out

    now_terms, prev_terms = by_term(current), by_term(previous)

    looked: dict[tuple, int | None] = {}

    def lookup(q: str, key: tuple = ()) -> int | None:
        if (q, key) in looked:
            return looked[(q, key)]
        if len(looked) >= MAX_LOOKUPS:
            return None
        looked[(q, key)] = finds_now(q, key)
        return looked[(q, key)]

    top = []
    for t, info in sorted(now_terms.items(), key=lambda kv: (-len(kv[1]["people"]),
                                                             -kv[1]["times"], kv[0]))[:15]:
        before = prev_terms.get(t)
        top.append({"term": t, "variants": sorted(v for v in info["variants"] if v != t),
                    "times": info["times"], "people": len(info["people"]),
                    "prev_people": len(before["people"]) if before else 0,
                    "opened_rate": round(info["opened"] / info["known"], 2) if info["known"] else None,
                    "finds_now": lookup(t)})

    # Both periods must say who searched: before mid-October searches were
    # recorded without the person, and every word would read as new.
    cur_known = len({e.get("user") for e in current if e.get("user")})
    prev_known = len({e.get("user") for e in previous if e.get("user")})
    enough = since is not None and min(cur_known, prev_known) * 2 >= TREND_MIN_TOTAL_PEOPLE
    rising, new = [], []
    if enough:
        cur_all = max(1, len({e.get("user") for e in current if e.get("user")}))
        prev_all = max(1, len({e.get("user") for e in previous if e.get("user")}))
        for t, info in now_terms.items():
            n = len(info["people"])
            if n < TREND_MIN_PEOPLE:
                continue
            before = prev_terms.get(t)
            p = len(before["people"]) if before else 0
            row = {"term": t, "people": n, "prev_people": p, "times": info["times"],
                   "finds_now": lookup(t)}
            if p == 0:
                new.append(row)
            # Share of the people searching, so a busier period (the usage
            # contest) does not make everything look like it is rising.
            elif n / cur_all >= 1.5 * (p / prev_all):
                rising.append(row)
        new.sort(key=lambda r: (-r["people"], r["term"]))
        rising.sort(key=lambda r: (-(r["people"] - r["prev_people"]), r["term"]))

    # ── by words and filters, for the problem lists and the full table
    rows: dict[tuple, dict] = {}
    for e in current:
        q, key = norm(e.get("q")), _filters_key(e.get("filters"))
        r = rows.setdefault((q, key), {"q": e.get("q").strip(), "key": key, "times": 0,
                                       "zero": 0, "few": 0, "people": set(), "last_at": "",
                                       "opened": 0, "known": 0})
        r["times"] += 1
        n = e.get("results") or 0
        r["zero"] += 1 if n == 0 else 0
        r["few"] += 1 if 0 < n <= FEW else 0
        if e.get("user"):
            r["people"].add(e["user"])
        r["last_at"] = max(r["last_at"], e.get("at") or "")
        if e.get("_opened") is not None and n:
            r["known"] += 1
            r["opened"] += 1 if e["_opened"] else 0

    def weight(r):
        return (-len(r["people"]), -r["times"], r["q"].lower())

    # A short string that a longer search in this period starts with is
    # that search unfinished ("coa", "coastguard"), not a question of its own.
    asked = {q for q, _ in rows}

    def unfinished(q: str) -> bool:
        return len(q) <= 4 and any(o != q and o.startswith(q) for o in asked)

    gaps, misses, thin, not_opened, table = [], [], [], [], []
    for (q, key), r in sorted(rows.items(), key=lambda kv: weight(kv[1])):
        base = {"q": r["q"], "filters": filters_words(key), "times": r["times"],
                "people": len(r["people"]), "last_at": r["last_at"][:10] or None,
                "no_results": r["zero"], "few_results": r["few"],
                "opened_rate": round(r["opened"] / r["known"], 2) if r["known"] else None}
        if r["zero"] or r["few"]:
            now = lookup(q, key)
            base["finds_now"] = now
            suggestion = None
            if not key:
                term(q)
                suggestion = near.get(q)
            better = lookup(suggestion) if suggestion else None
            if suggestion and better and (now is None or better > now):
                misses.append({**base, "suggestion": suggestion, "finds_suggestion": better})
            elif now == 0 and not unfinished(q):
                gaps.append(base)
            elif now is not None and now <= FEW:
                thin.append(base)
        elif r["known"] >= 2 and r["opened"] == 0:
            not_opened.append(base)
        table.append(base)

    # ── over time
    daily = since is not None and (until - since).days <= 14
    buckets: dict[str, dict] = {}
    for e in current:
        t = _parse(e.get("at"))
        b = buckets.setdefault(_bucket_label(t, daily),
                               {"opened": 0, "not_opened": 0, "unknown": 0, "nothing": 0})
        if not e.get("results"):
            b["nothing"] += 1
        elif e.get("_opened") is None:
            b["unknown"] += 1            # found; who searched was not recorded
        elif e["_opened"]:
            b["opened"] += 1
        else:
            b["not_opened"] += 1

    return {
        "since": since.isoformat() if since else None, "until": until.isoformat(),
        "previous_since": prev_since.isoformat() if prev_since else None,
        "few_results_max": FEW, "typing_seconds": TYPING_SECONDS,
        "open_minutes": OPEN_SECONDS // 60, "trend_min_people": TREND_MIN_PEOPLE,
        "totals": {**_counts(current), "recorded": recorded,
                   "typing": recorded - len(current)},
        "previous": _counts(previous) if since is not None else None,
        "over_time": {"by": "day" if daily else "week",
                      "buckets": [{"start": k, **v} for k, v in sorted(buckets.items())]},
        # All of them: the page shows eight and opens the rest in place.
        "gaps": gaps, "near_misses": misses, "thin": thin, "not_opened": not_opened,
        "top": top,
        "trending": {"enough_data": bool(enough), "rising": rising[:10], "new": new[:10]},
        "rows": table,
    }


# ───────────────────────────────────────── filters, and what a search finds
#: A recorded search's filters: (query parameter, AssetQuery field, words).
_FILTERS = (("type", "types", "Type"), ("umbrella", "umbrella_families", "Product"),
            ("family", "product_families", "Product"), ("segment", "segments", "Segment"),
            ("stage", "funnel_stages", "Funnel stage"), ("language", "languages", "Language"),
            ("published", "published", "Published"), ("depth", "content_depths", "Video type"),
            ("tag", "tags", "Tag"), ("customer_facing", None, "Customer facing"),
            ("archived", None, "Archived"))
_TYPE_WORDS = {"video": "Video", "ldk": "LDK", "vdk": "VDK", "vm": "Virtual Machine",
               "cad_model": "CAD Dataset"}


def filters_words(key: tuple) -> str | None:
    """{"type": ["vm"], "family": ["Windchill"]} -> "Type: Virtual Machine ·
    Product: Windchill"; None for a plain search."""
    words = dict((k, w) for k, _, w in _FILTERS)
    parts = []
    for k, values in key:
        shown = [_TYPE_WORDS.get(v, v) if k == "type" else v for v in values]
        parts.append(f"{words.get(k, k)}: {', '.join(shown)}")
    return " · ".join(parts) or None


def finds_now(repo, q: str, key: tuple) -> int | None:
    """What the same words and filters find today."""
    from backend.repositories.base import AssetQuery
    from backend.models import video_type_filter
    query = AssetQuery(text=q, limit=1)
    fields = {k: f for k, f, _ in _FILTERS}
    for k, values in key:
        field_name = fields.get(k)
        if k == "customer_facing":
            query.customer_facing = values[0] == "true"
        elif k == "depth":
            query.content_depths = video_type_filter(list(values))
        elif field_name:
            setattr(query, field_name, list(values))
    try:
        counter = getattr(repo, "count", None)
        return counter(query) if counter else repo.list(query).total
    except Exception:                                      # noqa: BLE001
        return None
