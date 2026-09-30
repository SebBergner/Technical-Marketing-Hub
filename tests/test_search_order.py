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
