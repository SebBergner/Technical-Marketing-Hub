"""Search results: newest first among equally good title matches (Liwei, 2026-09-30)."""
from __future__ import annotations

import json

from backend.repositories.base import AssetQuery
from backend.repositories.json_repo import JsonAssetRepository
from backend.services import relevance


def repo_with(tmp_path, rows):
    (tmp_path / "mirror").mkdir()
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps(
        [{"id": f"a{i}", "type": "ldk", "title": t, "uploaded_at": d, "description": desc}
         for i, (t, d, desc) in enumerate(rows)]), encoding="utf-8")
    return JsonAssetRepository(str(tmp_path))


def titles(repo, text):
    return [a.title for a in repo.list(AssetQuery(text=text, sort="relevance", limit=50)).items]


def test_the_newest_bmx_demo_comes_first(tmp_path):
    """The live case: it came ninth, behind 2024 kits whose titles merely
    start with the word or say it sooner."""
    repo = repo_with(tmp_path, [
        ("BMX LDK v.1", "2024-05-22", None),
        ("Creo Behavioral Modeling Extension (BMX) Overview", "2025-01-13", None),
        ("Introduction to Behavioral Modeling (BMX) - LDK", "2026-09-25", None),
        ("What's New in Creo 9.0 - Pocket Demos - LDK v.1", "2024-05-22", "covers BMX"),
    ])
    assert titles(repo, "BMX") == [
        "Introduction to Behavioral Modeling (BMX) - LDK",
        "Creo Behavioral Modeling Extension (BMX) Overview",
        "BMX LDK v.1",
        "What's New in Creo 9.0 - Pocket Demos - LDK v.1",   # description only: last
    ]


def test_an_exact_title_still_wins_over_a_newer_one(tmp_path):
    repo = repo_with(tmp_path, [("Windchill", "2020-01-01", None),
                                ("Windchill AI Assistant", "2026-09-01", None)])
    assert titles(repo, "windchill")[0] == "Windchill"


def test_scattered_words_rank_below_the_phrase_even_when_newer(tmp_path):
    repo = repo_with(tmp_path, [("Creo Overview", "2020-01-01", None),
                                ("Creo 13 AI Overview", "2026-09-01", None)])
    assert titles(repo, "creo overview") == ["Creo Overview", "Creo 13 AI Overview"]


def test_same_day_results_fall_back_to_the_tighter_title():
    a = relevance.order_key("bmx", "BMX Overview", None, "2025-01-01")
    b = relevance.order_key("bmx", "Creo Behavioral Modeling (BMX)", None, "2025-01-01")
    assert a > b


def test_a_short_word_only_matches_a_whole_word(tmp_path):
    """Liwei, 2026-10-01: "E&HT" split into "e" and "ht" and returned 176
    results, because "e" is inside nearly every title."""
    repo = repo_with(tmp_path, [
        ("E&HT - ADAS (Technical Overview)", "2026-01-01", None),
        ("The Bobcat Intelligent Product Lifecycle", "2026-01-01", "lightweight"),
        ("Windchill AI Assistant", "2026-01-01", None),
        ("Maintenance Planning", "2026-01-01", None),
    ])
    assert titles(repo, "E&HT") == ["E&HT - ADAS (Technical Overview)"]
    assert titles(repo, "ai") == ["Windchill AI Assistant"]


def test_a_word_is_whole_unless_part_of_words_is_asked_for():
    """Seb, 2026-11-05: "CAM" found every Camera demo."""
    assert relevance.score("cam", "Creo Camera Integration") == 0
    assert relevance.score("cam", "CAD/CAM Machining Overview") > 0
    assert relevance.score("wind", "Windchill PDMLink") == 0
    assert relevance.score("windchill", "Windchill PDMLink") > 0
    assert relevance.score("creo 11", "Creo 11.0 Overview") > 0
    # Advanced Search's "Match part of words": inside words, as before.
    assert relevance.score("cam", "Creo Camera Integration", partial=True) > 0
    assert relevance.score("wind", "Windchill PDMLink", partial=True) > 0
    assert relevance.names("e&ht", "E&HT_ADAS.mp4") and not relevance.names("ht", "Bobcat_Light.mp4")
    assert relevance.names("ht", "Bobcat_Light.mp4", partial=True) is False   # short stays whole


def test_a_whole_word_still_finds_its_plural():
    assert relevance.score("demo", "Demos of Creo") > 0
    assert relevance.score("process", "Manufacturing Processes") > 0
    assert relevance.score("assembly", "Large Assemblies") > 0
    assert relevance.score("vm", "Windchill VMs") > 0
    assert relevance.score("assembly", "Large Assemblies", partial=True) > 0


def test_chinese_japanese_korean_match_inside_a_title():
    """No spaces between words there, so "whole word" cannot apply."""
    assert relevance.score("概要", "Creo概要紹介") > 0


def test_advanced_search_part_of_words(tmp_path):
    repo = repo_with(tmp_path, [("Creo Camera Integration", "2025-01-01", None),
                                ("CAD/CAM Machining Overview", "2025-01-02", None)])
    whole = repo.advanced_search(AssetQuery(text="cam"))
    part = repo.advanced_search(AssetQuery(text="cam", partial=True))
    assert [h.asset.title for h in whole.items] == ["CAD/CAM Machining Overview"]
    assert len(part.items) == 2


def test_and_and_ampersand_are_the_same_word(tmp_path):
    """Liwei, 2026-11-05: "tips and techniques" found 3, "tips & techniques" 62."""
    repo = repo_with(tmp_path, [("Sheetmetal Design: Tips & Techniques", "2025-01-01", None),
                                ("Tips and Techniques Landing Page", "2024-01-01", None),
                                ("Standard Parts", "2024-01-01", None)])
    both = {"Sheetmetal Design: Tips & Techniques", "Tips and Techniques Landing Page"}
    assert set(titles(repo, "tips and techniques")) == both
    assert set(titles(repo, "tips & techniques")) == both
    assert relevance.terms("and") == ["and"], "a query of only the joiner still searches"


def test_a_product_name_finds_what_is_tagged_with_it(tmp_path):
    """The 240 ProENGINEER Wildfire datasets never say so in their titles."""
    (tmp_path / "mirror").mkdir()
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps([
        {"id": "a", "type": "cad_model", "title": "EFX Steel Building", "uploaded_at": "2018-01-01",
         "products": ["ProENGINEER Wildfire"]},
        {"id": "b", "type": "video", "title": "Wildfire Tips", "uploaded_at": "2017-01-01"},
        {"id": "c", "type": "video", "title": "Something Else", "uploaded_at": "2026-01-01"},
    ]), encoding="utf-8")
    repo = JsonAssetRepository(str(tmp_path))
    assert titles(repo, "proengineer wildfire") == ["EFX Steel Building"]
    assert titles(repo, "wildfire") == ["Wildfire Tips", "EFX Steel Building"], \
        "a title match still comes first"
