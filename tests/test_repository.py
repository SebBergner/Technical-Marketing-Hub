"""Repository behaviour, with emphasis on the mirror/owned split.

The split is the design's most dangerous failure mode: if a sync run ever
clears human-authored data, nobody notices for weeks. It gets its own tests.
"""
from __future__ import annotations

import json
import os
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models import Asset, AssetType, FunnelStage
from backend.repositories.base import AssetQuery
from backend.repositories.json_repo import JsonAssetRepository
from backend.repositories.sql_repo import SqlAssetRepository
from backend.seed import load_seed
from backend.tables import Base

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED = os.path.join(ROOT, "data", "seed", "assets.json")


@pytest.fixture(params=["json", "sql"])
def repo_factory(request, tmp_path):
    """Both backends run the entire suite below.

    This is what actually proves the repository abstraction holds — if the two
    implementations ever disagree on filtering, facet counts or the mirror/owned
    split, these tests fail rather than the difference surfacing in production.
    """
    if request.param == "json":
        def make():
            return JsonAssetRepository(str(tmp_path))
    else:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine, expire_on_commit=False)()

        def make():
            return SqlAssetRepository(session)
    return make


@pytest.fixture()
def empty_repo(repo_factory):
    return repo_factory()


@pytest.fixture()
def repo(repo_factory):
    r = repo_factory()
    load_seed(r, SEED)
    return r


def make_asset(asset_id="a1", **kw) -> Asset:
    base = dict(id=asset_id, type=AssetType.VIDEO, title=f"Asset {asset_id}",
                products=["Windchill"], uploaded_at=date(2025, 1, 1))
    base.update(kw)
    return Asset(**base)


# ─────────────────────────────────────────────── the split (the important one)
def test_resync_preserves_curation_stats_and_roadmap(empty_repo):
    """A sync run must not destroy human-authored or Portal-owned data."""
    repo = empty_repo
    repo.replace_source_rows([make_asset("a1", title="Original title")], "sharepoint")

    repo.set_curation("a1", is_editor_pick=True, rails=["CAD"])
    repo.set_roadmap("a1", {"description": "AI-derived summary"})
    repo.increment_stat("a1", "views", 42)

    # SharePoint renames the item and syncs again.
    repo.replace_source_rows([make_asset("a1", title="Renamed in SharePoint")], "sharepoint")

    asset = repo.get("a1")
    assert asset.title == "Renamed in SharePoint"      # mirror updated
    assert asset.is_editor_pick is True                 # owned survived
    assert asset.rails == ["CAD"]
    assert asset.value_roadmap.description == "AI-derived summary"
    assert asset.stats.views == 42


def test_removed_item_is_retired_not_deleted(empty_repo):
    """The slug must never be reused — shared links depend on it."""
    repo = empty_repo
    repo.replace_source_rows([make_asset("a1"), make_asset("a2")], "sharepoint")
    assert repo.list(AssetQuery()).total == 2

    repo.replace_source_rows([make_asset("a1")], "sharepoint")
    assert repo.list(AssetQuery()).total == 1

    # The retired slug must not come back as a different asset later.
    repo.replace_source_rows([make_asset("a1"), make_asset("a2", title="Reused?")],
                             "sharepoint")
    revived = repo.get("a2")
    assert revived is not None and revived.title == "Reused?"


def test_sync_of_one_source_leaves_another_alone(empty_repo):
    repo = empty_repo
    repo.replace_source_rows([make_asset("sp1")], "sharepoint")
    repo.replace_source_rows([make_asset("seed1")], "seed")
    repo.replace_source_rows([make_asset("sp2")], "sharepoint")

    ids = {a.id for a in repo.list(AssetQuery()).items}
    assert ids == {"seed1", "sp2"}, "seed source should be untouched by a sharepoint sync"


# ─────────────────────────────────────────────────────────── filtering / query
def test_seed_loads(repo):
    page = repo.list(AssetQuery(limit=200))
    assert page.total == 28


def test_text_search_matches_title_and_description(repo):
    assert repo.list(AssetQuery(text="creo", limit=200)).total > 0
    assert repo.list(AssetQuery(text="zzzznotathing")).total == 0


def test_filter_by_type_and_product(repo):
    videos = repo.list(AssetQuery(types=["video"], limit=200))
    assert videos.total > 0
    assert all(a.type == AssetType.VIDEO for a in videos.items)

    windchill = repo.list(AssetQuery(products=["Windchill"], limit=200))
    assert all("Windchill" in a.products for a in windchill.items)


def test_filter_has_consensus_uuid(repo):
    with_uuid = repo.list(AssetQuery(has_consensus_uuid=True, limit=200))
    without = repo.list(AssetQuery(has_consensus_uuid=False, limit=200))
    assert with_uuid.total + without.total == 28
    assert all(a.consensus_uuid for a in with_uuid.items)


def test_sorting(repo):
    by_views = repo.list(AssetQuery(sort="most_viewed", limit=200)).items
    assert [a.stats.views for a in by_views] == sorted(
        (a.stats.views for a in by_views), reverse=True)

    by_title = repo.list(AssetQuery(sort="title", limit=200)).items
    assert [a.title.lower() for a in by_title] == sorted(a.title.lower() for a in by_title)


def test_pagination(repo):
    first = repo.list(AssetQuery(sort="title", limit=5, offset=0))
    second = repo.list(AssetQuery(sort="title", limit=5, offset=5))
    assert first.total == second.total == 28
    assert len(first.items) == len(second.items) == 5
    assert {a.id for a in first.items}.isdisjoint({a.id for a in second.items})


def test_facet_counts_match_reality(repo):
    facets = repo.facets()
    assert facets.total == 28
    for facet in facets.types:
        actual = repo.list(AssetQuery(types=[facet.value], limit=200)).total
        assert facet.count == actual, f"type facet '{facet.value}' count is wrong"
    for facet in facets.products:
        actual = repo.list(AssetQuery(products=[facet.value], limit=200)).total
        assert facet.count == actual, f"product facet '{facet.value}' count is wrong"


# ────────────────────────────────────────────────────────── domain invariants
def test_asset_without_uuid_cannot_be_shared_externally():
    """Consensus can only send content already registered there."""
    assert make_asset(consensus_uuid=None).can_share_externally is False
    assert make_asset(consensus_uuid="7a19-3c02").can_share_externally is True
    assert make_asset(consensus_uuid="7a19-3c02",
                      customer_facing=False).can_share_externally is False


def test_unindexed_assets_have_no_fabricated_roadmap(repo):
    """The mockup only ever had 6 Value Roadmaps. The rest must stay null
    rather than being invented — the UI shows an honest empty state."""
    all_assets = [repo.get(a.id) for a in repo.list(AssetQuery(limit=200)).items]
    indexed = [a for a in all_assets if a.value_roadmap]
    assert len(indexed) == 6
    for asset in indexed:
        assert asset.value_roadmap.capabilities, "an indexed roadmap should have capabilities"


def test_increment_stat_rejects_unknown_field(repo):
    with pytest.raises(ValueError):
        repo.increment_stat("a1", "drop table")


def test_seed_file_matches_the_asset_model():
    """The seed is committed data; a schema change must not silently break it."""
    with open(SEED, encoding="utf-8") as fh:
        records = json.load(fh)
    assert len(records) == 28
    for record in records:
        Asset.model_validate(record)
