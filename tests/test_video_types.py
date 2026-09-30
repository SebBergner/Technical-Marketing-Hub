"""The five Video Types (Liwei, 2026-09-29), and the older three mapping onto them."""
from __future__ import annotations

import json

from backend.models import AssetSummary, video_type, video_type_filter
from backend.repositories.base import AssetQuery
from backend.repositories.json_repo import JsonAssetRepository
from backend.services import sharepoint_mapping as m


def test_the_older_three_map_onto_the_five():
    assert video_type("Overview") == "Technical Overview"
    assert video_type("Walkthrough") == "Technical Walkthrough"
    assert video_type("Teaser") == "Technical Teaser"
    assert video_type("Presenter Support") == "Presenter Support"
    assert video_type("Explainer") is None, "a Request-form value, never an asset's"
    assert video_type(None) is None


def test_a_model_accepts_an_old_spelling_and_says_the_new_one():
    a = AssetSummary(id="x", type="video", title="X", content_depth="Walkthrough")
    assert a.content_depth.value == "Technical Walkthrough"


def test_filenames_now_classify_into_the_five():
    assert m.content_depth("Windchill Quick Overview VDK") == "Technical Overview"
    assert m.content_depth("Creo Walkthrough") == "Technical Walkthrough"
    assert m.content_depth("Codebeamer Introduction") == "Technical Teaser"


def test_an_old_depth_link_still_filters_and_unknown_values_match_nothing():
    assert video_type_filter(["Overview", "Explainer", "Other"]) == [
        "Technical Overview", "Explainer", "Other"]


def test_a_mirror_written_before_the_switch_is_read_the_new_way(tmp_path):
    (tmp_path / "mirror").mkdir()
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps([
        {"id": "a", "type": "video", "title": "A", "content_depth": "Overview"},
        {"id": "b", "type": "video", "title": "B", "content_depth": "Teaser"},
    ]), encoding="utf-8")
    repo = JsonAssetRepository(str(tmp_path))

    facets = {f.value: f.count for f in repo.facets().content_depths}
    assert facets == {"Technical Overview": 1, "Technical Teaser": 1}
    page = repo.list(AssetQuery(content_depths=["Technical Overview"], limit=10))
    assert [a.id for a in page.items] == ["a"]
