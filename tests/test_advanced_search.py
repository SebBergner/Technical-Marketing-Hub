"""Advanced Search: the demo's own fields plus its files' names (Liwei, 2026-09-30)."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from backend.repositories.base import AssetQuery
from backend.repositories.json_repo import JsonAssetRepository
from backend.services import relevance


def repo_with(tmp_path, rows):
    (tmp_path / "mirror").mkdir()
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps(rows), encoding="utf-8")
    return JsonAssetRepository(str(tmp_path))


def row(i, title, uploaded="2025-01-01", description=None, files=(), **extra):
    return {"id": f"a{i}", "type": "ldk", "title": title, "uploaded_at": uploaded,
            "description": description,
            "resources": [{"name": n, "kind": "video" if n.endswith(".mp4") else "document",
                           "item_id": f"f{i}-{k}"} for k, n in enumerate(files)],
            **extra}


def search(repo, text):
    return repo.advanced_search(AssetQuery(text=text, limit=50)).items


def test_a_file_name_finds_the_demo_that_holds_it(tmp_path):
    repo = repo_with(tmp_path, [
        row(1, "Bobcat IPL Demo", files=["Bobcat_03_Engineering.mp4", "Bobcat_IPL_Demo.pptx"]),
        row(2, "Creo Overview"),
    ])
    hits = search(repo, "engineering")
    assert [h.asset.title for h in hits] == ["Bobcat IPL Demo"]
    assert hits[0].matched_in == []
    assert [f.name for f in hits[0].files] == ["Bobcat_03_Engineering.mp4"]


def test_only_the_matching_files_travel(tmp_path):
    repo = repo_with(tmp_path, [
        row(1, "Bobcat IPL Demo", files=["Bobcat_01_Intro.mp4", "Bobcat_IPL_Demo.pptx"]),
    ])
    hit = search(repo, "bobcat")[0]
    assert hit.matched_in == ["title"]
    assert [f.name for f in hit.files] == ["Bobcat_01_Intro.mp4", "Bobcat_IPL_Demo.pptx"]
    assert [f.name for f in search(repo, "pptx")[0].files] == ["Bobcat_IPL_Demo.pptx"]


def test_tags_and_products_count_as_details(tmp_path):
    repo = repo_with(tmp_path, [row(1, "Test Run", tags=["Innovation"], products=["Codebeamer"])])
    assert search(repo, "innovation")[0].matched_in == ["details"]
    assert search(repo, "codebeamer")[0].matched_in == ["details"]


def test_title_beats_file_name_beats_description(tmp_path):
    repo = repo_with(tmp_path, [
        row(1, "Something else", "2026-09-01", description="talks about service"),
        row(2, "Bobcat", "2020-01-01", files=["Bobcat_06_Service.mp4"]),
        row(3, "Service Overview", "2019-01-01"),
    ])
    assert [h.asset.title for h in search(repo, "service")] == [
        "Service Overview", "Bobcat", "Something else"]


def test_every_term_must_be_in_the_same_file_name():
    assert relevance.names("bobcat service", "Bobcat_06_Service.mp4")
    assert not relevance.names("bobcat manufacturing", "Bobcat_06_Service.mp4")


def test_the_endpoint_is_not_taken_for_an_asset_id():
    from app import app
    response = TestClient(app).get("/api/assets/advanced-search", params={"q": "zzzznothing"})
    assert response.status_code == 200
    assert response.json()["total"] == 0
