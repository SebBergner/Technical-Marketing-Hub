"""Repository behaviour, with emphasis on the mirror/owned split.

The split is the design's most dangerous failure mode: if a sync run ever
clears human-authored data, nobody notices for weeks. It gets its own tests.

Every test runs against BOTH storage backends. That is what proves the
repository abstraction holds, rather than the two implementations quietly
drifting apart.

Expectations are derived from the seed file wherever possible. The seed is
regenerated from a SharePoint export, so hand-pinned numbers rot — only the
row count is pinned, deliberately, to catch accidental corruption.
"""
from __future__ import annotations

import json
import os
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models import Asset, AssetType
from backend.repositories.base import AssetQuery
from backend.repositories.json_repo import JsonAssetRepository
from backend.repositories.sql_repo import SqlAssetRepository
from backend.seed import load_seed
from backend.tables import Base

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED = os.path.join(ROOT, "data", "seed", "assets.json")

with open(SEED, encoding="utf-8") as _fh:
    SEED_RECORDS = json.load(_fh)
SEED_COUNT = len(SEED_RECORDS)

#: A product that genuinely appears, rather than a hardcoded guess.
SAMPLE_PRODUCT = next(p for r in SEED_RECORDS for p in r["products"])


@pytest.fixture(params=["json", "sql"])
def repo_factory(request, tmp_path):
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


@pytest.fixture(scope="module")
def _seed_cache():
    return {}


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
def test_seed_is_the_real_catalogue(repo):
    """Pinned deliberately: the seed is committed data imported from SharePoint,
    and a silent change would invalidate every count below."""
    assert SEED_COUNT == 452, "regenerate with scripts/import_sharepoint.py"
    assert repo.list(AssetQuery(limit=1000)).total == SEED_COUNT


def test_text_search_matches_title_and_description(repo):
    assert repo.list(AssetQuery(text="creo", limit=1000)).total > 0
    assert repo.list(AssetQuery(text="zzzznotathing")).total == 0


def test_filter_by_type_and_product(repo):
    kits = repo.list(AssetQuery(types=["ldk"], limit=1000))
    assert kits.total > 0
    assert all(a.type == AssetType.LDK for a in kits.items)

    matching = repo.list(AssetQuery(products=[SAMPLE_PRODUCT], limit=1000))
    assert matching.total > 0
    assert all(SAMPLE_PRODUCT in a.products for a in matching.items)


def test_no_asset_can_be_shared_externally_yet(repo):
    """SharePoint holds no Consensus UUID at all — the catalogue's biggest gap."""
    with_uuid = repo.list(AssetQuery(has_consensus_uuid=True, limit=1000))
    without = repo.list(AssetQuery(has_consensus_uuid=False, limit=1000))
    assert with_uuid.total + without.total == SEED_COUNT
    assert without.total == SEED_COUNT
    assert all(a.consensus_uuid for a in with_uuid.items)


def test_sorting(repo):
    by_views = repo.list(AssetQuery(sort="most_viewed", limit=1000)).items
    assert [a.stats.views for a in by_views] == sorted(
        (a.stats.views for a in by_views), reverse=True)

    by_title = repo.list(AssetQuery(sort="title", limit=1000)).items
    assert [a.title.lower() for a in by_title] == sorted(a.title.lower() for a in by_title)


def test_pagination(repo):
    first = repo.list(AssetQuery(sort="title", limit=5, offset=0))
    second = repo.list(AssetQuery(sort="title", limit=5, offset=5))
    assert first.total == second.total == SEED_COUNT
    assert len(first.items) == len(second.items) == 5
    assert {a.id for a in first.items}.isdisjoint({a.id for a in second.items})


def test_facet_counts_match_reality(repo):
    facets = repo.facets()
    assert facets.total == SEED_COUNT
    for facet in facets.types:
        actual = repo.list(AssetQuery(types=[facet.value], limit=1000)).total
        assert facet.count == actual, f"type facet {facet.value} count is wrong"
    for facet in facets.products[:12]:
        actual = repo.list(AssetQuery(products=[facet.value], limit=1000)).total
        assert facet.count == actual, f"product facet {facet.value} count is wrong"


# ────────────────────────────────────────────────────── real-catalogue shape
def test_resources_reflect_the_folder_structure(repo):
    """An asset is a SharePoint folder; its files are resources."""
    assets = [repo.get(a.id) for a in repo.list(AssetQuery(limit=1000)).items]

    with_video = [a for a in assets if a.video_count]
    assert len(with_video) > len(assets) // 2, "most kits ship a video"

    for asset in with_video:
        video_names = {r.name for r in asset.resources if r.kind.value == "video"}
        assert video_names
        if asset.main_video:
            assert asset.main_video in video_names, \
                "main_video must be one of the asset's own videos"


def test_ambiguous_main_video_is_left_unset(repo):
    """Several videos and no single Customer Facing one means a human chooses.
    Guessing here is how false confidence gets shipped."""
    assets = [repo.get(a.id) for a in repo.list(AssetQuery(limit=1000)).items]
    deferred = [a for a in assets if a.video_count > 1 and not a.main_video]
    assert deferred, "expected some assets to defer rather than guess"


def test_cad_files_are_counted_but_not_listed(repo):
    """42% of the catalogue is Creo version files (part.prt.1). Counted so
    'includes CAD' can be shown, never listed individually."""
    assets = [repo.get(a.id) for a in repo.list(AssetQuery(limit=1000)).items]
    with_cad = [a for a in assets if a.resource_counts.get("cad")]
    assert with_cad, "the catalogue definitely contains CAD"
    for asset in with_cad:
        assert not [r for r in asset.resources if r.kind.value == "cad"]
        assert asset.resource_count >= len(asset.resources)


# ────────────────────────────────────────────────────────── domain invariants
def test_asset_without_uuid_cannot_be_shared_externally():
    """Consensus can only send content already registered there."""
    assert make_asset(consensus_uuid=None).can_share_externally is False
    assert make_asset(consensus_uuid="7a19-3c02").can_share_externally is True
    assert make_asset(consensus_uuid="7a19-3c02",
                      customer_facing=False).can_share_externally is False


def test_no_fabricated_value_roadmaps(repo):
    """No source system holds a Value Roadmap, so every asset reports null and
    the UI shows an honest 'not indexed yet' state. Inventing value drivers
    would violate the project's own rule against fabricated content."""
    assert all(not a.has_roadmap for a in repo.list(AssetQuery(limit=1000)).items)


def test_increment_stat_rejects_unknown_field(repo):
    with pytest.raises(ValueError):
        repo.increment_stat("a1", "drop table")


def test_seed_file_matches_the_asset_model():
    """The seed is committed data; a schema change must not silently break it."""
    for record in SEED_RECORDS:
        Asset.model_validate(record)
