"""Search round 2: a search that finds nothing is tried again in other words
(relevance.rescue, Liwei 2026-11-25). The cases are real production searches."""
from __future__ import annotations

import json

from backend.repositories.base import AssetQuery
from backend.repositories.json_repo import JsonAssetRepository

CATALOGUE = [
    ("Creo 13 Teaser", "2026-06-01", None),
    ("What's New in Creo 13.0 - VDK - v.1", "2026-05-01", None),
    ("Creo User Productivity Enhancements", "2026-04-01", "Demonstrates Creo 13 user productivity"),
    ("Creo Parametric Overview", "2025-01-01", "covers 13 new features of Creo"),
    ("ServiceMax AI Demonstration Spotlight", "2026-03-01", None),
    ("Customer service at full speed", "2026-03-02", None),
    ("Windchill Part Management", "2025-02-01", None),
    ("Part design for manufacturing", "2025-02-02", None),
    ("MedTech Quality Walkthrough", "2025-03-01", None),
    ("Lamborghini Technical Overview", "2025-04-01", None),
    ("PTC Ignition", "2025-05-01", None),
]


def repo_with(tmp_path, rows=CATALOGUE):
    (tmp_path / "mirror").mkdir()
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps(
        [{"id": f"a{i}", "type": "ldk", "title": t, "uploaded_at": d, "description": desc}
         for i, (t, d, desc) in enumerate(rows)]), encoding="utf-8")
    return JsonAssetRepository(str(tmp_path))


def search(repo, text, **kw):
    page = repo.list(AssetQuery(text=text, sort="relevance", limit=50, **kw))
    return [a.title for a in page.items], page.searched_as


def test_a_version_written_together_finds_that_version(tmp_path):
    titles, used = search(repo_with(tmp_path), "Creo13")
    assert used == "creo 13"
    assert set(titles) == {"Creo 13 Teaser", "What's New in Creo 13.0 - VDK - v.1",
                           "Creo User Productivity Enhancements"}
    # "13" somewhere else in the text is not "Creo 13": the two must be adjacent.
    assert "Creo Parametric Overview" not in titles


def test_two_words_that_are_one_catalogue_word(tmp_path):
    titles, used = search(repo_with(tmp_path), "service max")
    assert used == "servicemax"
    assert titles == ["ServiceMax AI Demonstration Spotlight"]


def test_a_search_that_finds_anything_is_left_alone(tmp_path):
    # A demo says "service max", so the search finds it and is not rewritten.
    rows = CATALOGUE + [("Service max workshop", "2026-01-01", None)]
    titles, used = search(repo_with(tmp_path, rows), "service max")
    assert used is None
    assert "ServiceMax AI Demonstration Spotlight" not in titles


def test_a_last_word_still_being_typed_follows_the_word_before(tmp_path):
    titles, used = search(repo_with(tmp_path), "Part man")
    assert used == "part man"
    # "Part design for manufacturing": "man" is not right after "part".
    assert titles == ["Windchill Part Management"]


def test_two_words_with_the_space_missed(tmp_path):
    titles, used = search(repo_with(tmp_path), "Technical OverviewLambo")
    assert used == "technical overview lambo"
    assert titles == ["Lamborghini Technical Overview"]


def test_med_tech_and_ptc_ig(tmp_path):
    repo = repo_with(tmp_path)
    assert search(repo, "Med tech") == (["MedTech Quality Walkthrough"], "medtech")
    assert search(repo, "PTC Ig") == (["PTC Ignition"], "ptc ig")


def test_nothing_is_invented(tmp_path):
    repo = repo_with(tmp_path)
    # Not a catalogue word either way, a part number, a short single word.
    for q in ("Deere", "844J", "co", "asset360"):
        assert search(repo, q) == ([], None), q


def test_filters_still_apply_to_the_rewritten_search(tmp_path):
    repo = repo_with(tmp_path)
    assert search(repo, "Creo13", types=["vdk"]) == ([], None)
    assert search(repo, "Creo13", types=["ldk"])[1] == "creo 13"


def test_counts_and_facets_agree_with_the_list(tmp_path):
    repo = repo_with(tmp_path)
    q = AssetQuery(text="Creo13")
    assert repo.count(q) == 3
    assert repo.facets(q).total == 3


def test_the_search_api_says_what_it_searched(tmp_path, monkeypatch):
    from backend.routers import search_api
    assert "searched_as" in search_api.SearchResponse.model_fields
