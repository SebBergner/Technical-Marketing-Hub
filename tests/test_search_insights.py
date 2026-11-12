"""services/search_insights.py: the Searches tab's numbers (2026-11-12)."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from backend.services import search_insights as si

T0 = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)


def at(minutes=0, seconds=0):
    return (T0 + timedelta(minutes=minutes, seconds=seconds)).isoformat()


def search(q, results, user="a", minutes=0, seconds=0, filters=None):
    e = {"event": "search", "q": q, "results": results, "at": at(minutes, seconds)}
    if user:
        e["user"] = user
    if filters:
        e["filters"] = filters
    return e


def use(user, minutes, seconds=0, event="view"):
    return {"event": event, "asset_id": "x", "user": user, "at": at(minutes, seconds)}


VOCAB = Counter({"lamborghini": 3, "jetstream": 4, "associativity": 2,
                 "associations": 9, "creo": 500})
CATALOGUE = {"lamborghini": 10, "jetstream": 11, "associativity": 2, "associations": 9,
             "creo": 500}


def finds_now(q, key):
    return 0 if key else CATALOGUE.get(q.lower(), 0)


def run(events, days=7):
    until = T0 + timedelta(days=1)
    return si.insights(events, until - timedelta(days=days) if days else None, until,
                       finds_now, VOCAB, lambda key: "filtered" if key else None)


def test_typing_is_left_out_and_the_last_search_kept():
    d = run([search("bobcat service technical o", 0, seconds=0),
             search("bobcat service technical ov", 0, seconds=3),
             search("bobcat service technical overview", 0, seconds=6),
             search("bobcat", 12, user="b", seconds=1)])
    assert (d["totals"]["recorded"], d["totals"]["typing"], d["totals"]["searches"]) == (4, 2, 2)
    assert [r["q"] for r in d["rows"]] == ["bobcat", "bobcat service technical overview"] or \
        {r["q"] for r in d["rows"]} == {"bobcat", "bobcat service technical overview"}


def test_a_longer_search_much_later_is_a_new_question():
    d = run([search("creo", 500), search("creo ai", 3, minutes=5)])
    assert d["totals"]["typing"] == 0


def test_opened_means_the_same_person_opened_something_before_searching_again():
    events = [search("jetstream", 11, minutes=0), use("a", 2),
              search("creo", 500, minutes=20), search("windchill", 30, minutes=21),
              use("a", 22)]
    d = run(events)
    rows = {r["q"]: r for r in d["rows"]}
    assert rows["jetstream"]["opened_rate"] == 1
    assert rows["creo"]["opened_rate"] == 0, "the view came after the next search"
    assert d["totals"]["opened"] == 2 and d["totals"]["opened_known"] == 3


def test_a_word_cut_short_or_misspelt_is_a_near_miss_not_a_gap():
    d = run([search("lambo", 0), search("jestream", 0, user="b"), search("assoc", 0, user="c"),
             search("purdue", 0, user="d")])
    misses = {r["q"]: r["suggestion"] for r in d["near_misses"]}
    assert misses == {"lambo": "lamborghini", "jestream": "jetstream",
                      "assoc": "associations"}
    assert [g["q"] for g in d["gaps"]] == ["purdue"]


def test_a_word_people_searched_in_full_wins_the_near_miss():
    d = run([search("assoc", 0), search("associativity", 2, user="b")])
    assert d["near_misses"][0]["suggestion"] == "associativity"


def test_variants_are_counted_as_one_in_most_searched():
    d = run([search("lambo", 0, user="a"), search("Lamborghini", 10, user="b"),
             search("lamborghini", 10, user="c")])
    top = d["top"][0]
    assert (top["term"], top["people"], top["variants"]) == ("lamborghini", 3, ["lambo"])


def test_no_trend_without_enough_people_in_both_periods():
    old = [dict(search("creo", 500, user=None), at=(T0 - timedelta(days=8)).isoformat())]
    new = [search("jetstream", 11, user=f"u{i}") for i in range(6)]
    assert run(old + new)["trending"]["enough_data"] is False


def test_a_word_rising_and_a_new_word():
    before = [dict(search("creo", 500, user=f"p{i}"), at=(T0 - timedelta(days=4)).isoformat())
              for i in range(6)]
    before.append(dict(search("jetstream", 11, user="p0"), at=(T0 - timedelta(days=4)).isoformat()))
    now = [search("jetstream", 11, user=f"u{i}") for i in range(4)] + \
          [search("lamborghini", 10, user=f"u{i}") for i in range(3)] + \
          [search("creo", 500, user=f"u{i}") for i in range(5, 11)]
    d = run(before + now, days=3)
    tr = d["trending"]
    assert tr["enough_data"] is True
    assert [r["term"] for r in tr["rising"]] == ["jetstream"]
    assert [r["term"] for r in tr["new"]] == ["lamborghini"]


def test_found_but_nobody_opened_anything():
    d = run([search("polaris", 32, user="a"), search("polaris", 32, user="b", minutes=1)])
    assert [r["q"] for r in d["not_opened"]] == ["polaris"]


def test_by_day_for_a_short_window_by_week_for_a_long_one():
    assert run([search("creo", 500)], days=7)["over_time"]["by"] == "day"
    assert run([search("creo", 500)], days=30)["over_time"]["by"] == "week"
