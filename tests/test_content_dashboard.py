"""The content dashboard (HLR-F1), counted over what the Hub lists."""
from __future__ import annotations

import json
from datetime import date

from backend.repositories.json_repo import JsonAssetRepository
from backend.services import content_dashboard as cd

TODAY = date(2026, 10, 1)


def repo_with(tmp_path):
    (tmp_path / "mirror").mkdir()
    rows = [
        {"id": "kit", "type": "ldk", "title": "Kit", "products": ["Creo"], "segment": "CAD",
         "uploaded_at": "2024-05-01"},
        {"id": "video-new", "type": "video", "title": "New", "products": ["Windchill"],
         "uploaded_at": "2026-09-14", "named_customer": "Bobcat"},
        {"id": "video-old", "type": "video", "title": "Old", "products": ["Creo", "Windchill"],
         "uploaded_at": "2016-01-01"},
        {"id": "gone", "type": "ldk", "title": "Divested", "products": ["ThingWorx"]},
    ]
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps(rows), encoding="utf-8")
    return JsonAssetRepository(str(tmp_path))


def dim(summary, key):
    d = next(d for d in summary["dimensions"] if d["key"] == key)
    return d["of"], {b["label"]: b["count"] for b in d["buckets"]}


def test_counts_what_the_hub_lists_and_shows_the_gaps(tmp_path):
    s = cd.summary(repo_with(tmp_path), TODAY)
    assert s["total"] == 3, "divested products are not in the Hub, so not counted"
    assert dim(s, "type") == (3, {"Videos": 2, "LDKs": 1})
    assert dim(s, "segment")[1] == {"CAD": 1, "Not set": 2}
    assert dim(s, "product")[1] == {"Creo": 2, "Windchill": 2}, "a demo counts under each product"
    assert dim(s, "where")[1] == {"SharePoint · Demo Catalog": 1, "SharePoint · Demo Video": 2}


def test_age_is_for_videos_only(tmp_path):
    s = cd.summary(repo_with(tmp_path), TODAY)
    assert dim(s, "age") == (2, {"Under 1 year": 1, "7+ years": 1})


def test_a_bar_drills_into_its_assets_newest_first(tmp_path):
    repo = repo_with(tmp_path)
    assert [a["id"] for a in cd.assets_in(repo, "product", "Windchill", TODAY)] == ["video-new", "video-old"]
    assert [a["id"] for a in cd.assets_in(repo, "segment", "Not set", TODAY)] == ["video-new", "video-old"]
    assert [a["id"] for a in cd.assets_in(repo, "age", "7+ years", TODAY)] == ["video-old"]
