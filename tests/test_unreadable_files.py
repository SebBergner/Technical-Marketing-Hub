"""An owned file that exists but cannot be read is never taken for empty.

Before 2026-11-26 most readers returned their default ({} / []) on a parse
or OS error, and the read-modify-write that followed saved that default plus
one change over the real file: identity, hidden, groups, API tokens,
favourites, search terms. These tests write a damaged file, try a change,
and check the change is refused AND the file is left exactly as it was.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from backend import access, api_tokens
from backend.config import settings
from backend.file_safety import UnreadableFile, read_json
from backend.repositories.base import AssetQuery
from backend.repositories.json_repo import JsonAssetRepository

DAMAGED = '{"half": '


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    (tmp_path / "mirror").mkdir()
    (tmp_path / "owned").mkdir()
    rows = [{"id": "kit-a", "type": "vdk", "title": "A", "products": ["Creo"]}]
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps(rows), encoding="utf-8")
    access._cache.clear()
    yield tmp_path
    access._cache.clear()


def _damage(path):
    path.write_text(DAMAGED, encoding="utf-8")
    return path


# ─────────────────────────────────────────────── the reader itself
def test_a_missing_file_is_the_default(tmp_path):
    assert read_json(str(tmp_path / "nope.json"), {"d": 1}) == {"d": 1}


def test_a_damaged_file_raises(tmp_path):
    path = _damage(tmp_path / "x.json")
    with pytest.raises(UnreadableFile):
        read_json(str(path), {})


# ─────────────────────────────────────────────── the repository
def test_hiding_a_demo_with_a_damaged_hidden_file_changes_nothing(data):
    hidden = _damage(data / "owned" / "hidden.json")
    with pytest.raises(UnreadableFile):
        JsonAssetRepository(str(data)).unhide("kit-a")
    assert hidden.read_text(encoding="utf-8") == DAMAGED


def test_a_stat_is_not_counted_over_a_damaged_stats_file(data):
    stats = _damage(data / "owned" / "stats.json")
    with pytest.raises(UnreadableFile):
        JsonAssetRepository(str(data)).increment_stat("kit-a", "views")
    assert stats.read_text(encoding="utf-8") == DAMAGED


def test_a_damaged_access_file_never_shows_hidden_demos(data):
    """The catalogue fails rather than being built as if nothing were hidden."""
    (data / "owned" / "hidden.json").write_text(json.dumps({"kit-a": {}}), encoding="utf-8")
    assert JsonAssetRepository(str(data)).list(AssetQuery(limit=10)).total == 0
    _damage(data / "owned" / "hidden.json")
    with pytest.raises(UnreadableFile):
        JsonAssetRepository(str(data)).list(AssetQuery(limit=10))


def test_a_damaged_mirror_file_is_not_cached_as_empty(data):
    path = data / "mirror" / "sharepoint.json"
    good = path.read_text(encoding="utf-8")
    _damage(path)
    with pytest.raises(UnreadableFile):
        JsonAssetRepository(str(data)).list(AssetQuery(limit=10))
    path.write_text(good, encoding="utf-8")
    assert JsonAssetRepository(str(data)).list(AssetQuery(limit=10)).total == 1


def test_a_repository_keeps_its_last_good_copy_of_a_mirror_file(data):
    repo = JsonAssetRepository(str(data))
    path = str(data / "mirror" / "sharepoint.json")
    assert [r["id"] for r in repo._mirror_file(path)] == ["kit-a"]
    _damage(data / "mirror" / "sharepoint.json")
    assert [r["id"] for r in repo._mirror_file(path)] == ["kit-a"]


# ─────────────────────────────────────────────── groups, tokens, favourites, terms
def test_a_group_change_over_a_damaged_access_file_changes_nothing(data):
    path = _damage(Path(access._owned(access.STATE_FILE)))
    with pytest.raises(UnreadableFile):
        access.create_group("New group", "", [], [], "a@ptc.com")
    assert path.read_text(encoding="utf-8") == DAMAGED


def test_permission_checks_use_the_last_good_groups(data):
    access.create_group("Kept", "", [], [], "a@ptc.com")
    assert "Kept" in [g["name"] for g in access.load_state()["groups"]]
    path = _damage(Path(access._owned(access.STATE_FILE)))
    os.utime(path, (1, 1))                  # a different mtime than the cached one
    assert "Kept" in [g["name"] for g in access.load_state()["groups"]]


def test_a_new_token_over_a_damaged_token_file_changes_nothing(data):
    path = _damage(Path(api_tokens._path()))
    with pytest.raises(UnreadableFile):
        api_tokens.create(name="t", owner="a@ptc.com", permissions=["view_hub"], days=30,
                          actor="a@ptc.com")
    assert path.read_text(encoding="utf-8") == DAMAGED


def test_a_favourite_over_a_damaged_file_changes_nothing(data):
    from backend.services import my_hub
    my_hub.set_favorite("someone", "kit-a", True, data_dir=str(data))
    path = _damage(data / "owned" / "me" / os.path.basename(my_hub._path("someone", str(data))))
    with pytest.raises(UnreadableFile):
        my_hub.set_favorite("someone", "kit-b", True, data_dir=str(data))
    assert path.read_text(encoding="utf-8") == DAMAGED


def test_search_terms_read_as_defaults_but_an_edit_is_refused(data):
    from backend.services import search_terms
    path = _damage(data / "owned" / search_terms.FILE)
    assert search_terms.load(str(data))["saved"] is False
    with pytest.raises(UnreadableFile):
        search_terms.add(["plm", "product lifecycle"], "", "a@ptc.com", data_dir=str(data))
    assert path.read_text(encoding="utf-8") == DAMAGED


# ─────────────────────────────────────────────── a refused sync is a failed attempt
def test_a_sync_the_shrink_guard_refuses_is_recorded_as_failed(data, monkeypatch):
    """WouldShrinkMirror is not a Graph error; until 2026-11-26 it escaped
    _run_sync unrecorded and Admin kept showing the previous success."""
    from backend.repositories.json_repo import WouldShrinkMirror
    from backend.routers import graph

    def refused(*a, **kw):
        raise WouldShrinkMirror("sharepoint would drop from 455 to 3 rows")

    monkeypatch.setattr(graph, "sync_catalogue", refused)
    repo = JsonAssetRepository(str(data))
    with pytest.raises(WouldShrinkMirror):
        graph._run_sync(object(), repo, "test", full=True)
    state = repo.sync_state("sharepoint")
    assert state.get("last_attempt_ok") is False
    assert "WouldShrinkMirror" in (state.get("last_error") or "")
