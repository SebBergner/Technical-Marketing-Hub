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


# ─────────────────────────────────────────── write-back state and audit trail
def test_marking_written_does_not_overwrite_who_accepted_it(repo):
    """Two different facts: who authorised a value, and who ran the job that
    pushed it. Collapsing them loses the one that matters for accountability."""
    from backend.models import MetadataProposal, ProposalOrigin, ProposalState

    repo.save_proposals([MetadataProposal(
        asset_id="a1", field="consensus_uuid", proposed_value="uuid-1",
        origin=ProposalOrigin.CONSENSUS)])
    repo.decide_proposal("a1", "consensus_uuid",
                         ProposalState.ACCEPTED.value, "elio@ptc.com")

    written = repo.mark_proposal_written("a1", "consensus_uuid")

    assert written.state == ProposalState.WRITTEN
    assert written.decided_by == "elio@ptc.com"
    assert written.written_at is not None


def test_written_proposals_leave_the_writeback_backlog(repo):
    from backend.models import MetadataProposal, ProposalOrigin, ProposalState

    repo.save_proposals([MetadataProposal(
        asset_id="a1", field="consensus_uuid", proposed_value="uuid-1",
        origin=ProposalOrigin.CONSENSUS)])
    repo.decide_proposal("a1", "consensus_uuid", ProposalState.ACCEPTED.value, "x")
    assert repo.proposal_summary().pending_writeback == 1

    repo.mark_proposal_written("a1", "consensus_uuid")
    assert repo.proposal_summary().pending_writeback == 0


def test_mark_written_on_a_missing_proposal_returns_none(repo):
    assert repo.mark_proposal_written("nope", "consensus_uuid") is None


def test_the_metadata_edit_log_survives_as_the_only_record_of_authorship(repo):
    """App-only Graph writes are attributed to the application in SharePoint's
    own history, so if this log does not hold the person, nothing does."""
    repo.record_metadata_edit("a1", "consensus_uuid", None, "uuid-1",
                              changed_by="elio@ptc.com")
    repo.record_metadata_edit("a1", "consensus_uuid", "uuid-1", "uuid-2",
                              changed_by="liwchen@ptc.com",
                              write_status="failed", error="403")

    entries = repo.metadata_edits("a1")
    assert [e["changed_by"] for e in entries] == ["elio@ptc.com", "liwchen@ptc.com"]
    assert entries[0]["old_value"] is None and entries[0]["new_value"] == "uuid-1"
    assert entries[1]["write_status"] == "failed" and entries[1]["error"] == "403"


def test_the_edit_log_is_append_only(repo):
    """An audit trail that can lose earlier entries is not an audit trail."""
    for n in range(3):
        repo.record_metadata_edit("a1", "consensus_uuid", None, f"uuid-{n}",
                                  changed_by="elio@ptc.com")
    assert len(repo.metadata_edits("a1")) == 3


# ──────────────────────────────────────────── one asset, one row, one id
def test_no_asset_id_appears_twice_across_source_systems(repo):
    """The invariant the first real Graph sync broke.

    The seed and the Graph sync are the same SharePoint library measured two
    ways, and the mirror partitions by source system -- so both survived and
    every asset appeared twice under one shared id. 452 + 455 = 907 rows for
    455 assets: doubled facet counts, and get() returning whichever it reached
    first.
    """
    from backend.models import Asset, AssetType

    same = [Asset(id="a1", type=AssetType.LDK, title="A Kit",
                  source_item_id="sites/x/A Kit")]
    repo.replace_source_rows(same, "seed")
    repo.replace_source_rows(
        [Asset(id="a1", type=AssetType.LDK, title="A Kit", source_item_id="01GRAPHID")],
        "sharepoint")

    ids = [a.id for a in repo.list(AssetQuery(limit=500)).items]
    assert len(ids) == len(set(ids)), f"duplicate asset ids in the catalogue: {ids}"


def test_count_source_rows_reports_each_source_separately(repo):
    from backend.models import Asset, AssetType

    repo.replace_source_rows(
        [Asset(id=f"s{n}", type=AssetType.LDK, title=f"S{n}") for n in range(3)], "seed")
    repo.replace_source_rows(
        [Asset(id=f"g{n}", type=AssetType.VDK, title=f"G{n}") for n in range(5)],
        "sharepoint")

    assert repo.count_source_rows("seed") == 3
    assert repo.count_source_rows("sharepoint") == 5
    assert repo.count_source_rows("nothing-here") == 0


def test_replacing_a_source_with_nothing_empties_only_that_source(repo):
    """How the seed is retired: it must not touch the other source."""
    from backend.models import Asset, AssetType

    repo.replace_source_rows([Asset(id="s1", type=AssetType.LDK, title="S")], "seed")
    repo.replace_source_rows([Asset(id="g1", type=AssetType.VDK, title="G")], "sharepoint")

    repo.replace_source_rows([], "seed")

    assert repo.count_source_rows("seed") == 0
    assert repo.count_source_rows("sharepoint") == 1
    assert [a.id for a in repo.list(AssetQuery(limit=10)).items] == ["g1"]


def test_an_asset_that_moves_between_sources_is_not_retired_with_the_old_one(repo):
    """The bug that deleted 288 of 455 assets on the first real Graph sync.

    Identity recorded whoever created the row, and creation used setdefault --
    so an asset first seen in the spreadsheet seed and later provided by the
    Graph sync was still labelled "seed". Retiring the seed then retired an
    asset the seed no longer owned, and it silently left the catalogue.
    """
    from backend.models import Asset, AssetType

    repo.replace_source_rows(
        [Asset(id="a1", type=AssetType.LDK, title="A Kit",
               source_item_id="sites/x/A Kit")], "seed")
    # The same asset, now coming from Graph with a real item id.
    repo.replace_source_rows(
        [Asset(id="a1", type=AssetType.LDK, title="A Kit",
               source_item_id="01GRAPHID")], "sharepoint")

    repo.replace_source_rows([], "seed")        # retire the stand-in

    surviving = [a.id for a in repo.list(AssetQuery(limit=10)).items]
    assert surviving == ["a1"], "the asset is still provided by sharepoint"
    assert repo.get("a1") is not None


def test_the_stable_slug_survives_the_move(repo):
    """Identity exists so a link shared in March still resolves in December.
    Changing source must not change the slug."""
    from backend.models import Asset, AssetType

    repo.replace_source_rows(
        [Asset(id="a1", type=AssetType.LDK, title="A Kit", source_item_id="old/path")],
        "seed")
    repo.replace_source_rows(
        [Asset(id="a1", type=AssetType.LDK, title="A Kit", source_item_id="01NEWID")],
        "sharepoint")

    assert repo.get("a1").title == "A Kit"


def test_web_url_survives_a_round_trip(repo):
    """It is the only way a user opens the asset in SharePoint. It was missing
    from the JSON backend's field list, so it silently vanished on every sync
    while the SQL backend kept it -- exactly the drift the shared test suite
    exists to catch."""
    from backend.models import Asset, AssetType

    repo.replace_source_rows([Asset(
        id="a1", type=AssetType.LDK, title="A Kit",
        web_url="https://ptccloud.sharepoint.com/sites/EXT-TDD/Demo%20Catalog/A%20Kit",
    )], "sharepoint")

    assert repo.get("a1").web_url.endswith("/A%20Kit")


# ─────────────────────────────── federated catalogue: two sources, one index
def test_two_sources_coexist_and_stay_distinguishable(empty_repo):
    """The Portal is a federated index. A result is useless if you cannot tell
    whether it is a kit to run or a recording to send."""
    from backend.models import Asset, AssetType

    empty_repo.replace_source_rows(
        [Asset(id="kit", type=AssetType.LDK, title="Windchill Kit",
               products=["Windchill PDMLink"], segment="PLM")], "sharepoint")
    empty_repo.replace_source_rows(
        [Asset(id="vid", type=AssetType.VIDEO, source="consensus",
               title="Windchill Overview", products=["Windchill"], segment="PLM",
               web_url="https://play.goconsensus.com/abc")], "consensus")

    items = {a.id: a for a in empty_repo.list(AssetQuery(limit=10)).items}
    assert items["kit"].source == "sharepoint"
    assert items["vid"].source == "consensus"
    assert empty_repo.count_source_rows("consensus") == 1


def test_web_url_reaches_list_responses_not_just_detail(empty_repo):
    """A grid card links out. A Consensus result with no link is a dead end,
    and web_url used to be set only on the detail path."""
    from backend.models import Asset, AssetType

    empty_repo.replace_source_rows([Asset(
        id="vid", type=AssetType.VIDEO, source="consensus", title="Overview",
        web_url="https://play.goconsensus.com/abc")], "consensus")

    assert empty_repo.list(AssetQuery(limit=5)).items[0].web_url.endswith("/abc")


def test_the_product_family_filter_reaches_both_platforms(empty_repo):
    """The whole point of families. SharePoint records 'Windchill PDMLink' and
    Consensus records 'Windchill'; only six product names appear verbatim in
    both, so filtering on the specific product hides half the catalogue."""
    from backend.models import Asset, AssetType

    empty_repo.replace_source_rows([Asset(id="kit", type=AssetType.LDK, title="Kit",
                                    products=["Windchill PDMLink"])], "sharepoint")
    empty_repo.replace_source_rows([Asset(id="vid", type=AssetType.VIDEO, source="consensus",
                                    title="Vid", products=["Windchill"])], "consensus")

    both = empty_repo.list(AssetQuery(product_families=["Windchill"], limit=10)).items
    assert {a.id for a in both} == {"kit", "vid"}

    # The specific product still works, and naturally reaches SharePoint only.
    exact = empty_repo.list(AssetQuery(products=["Windchill PDMLink"], limit=10)).items
    assert {a.id for a in exact} == {"kit"}


def test_filtering_by_source_isolates_one_platform(empty_repo):
    from backend.models import Asset, AssetType

    empty_repo.replace_source_rows([Asset(id="kit", type=AssetType.LDK, title="Kit")],
                             "sharepoint")
    empty_repo.replace_source_rows([Asset(id="vid", type=AssetType.VIDEO,
                                    source="consensus", title="Vid")], "consensus")

    assert [a.id for a in empty_repo.list(AssetQuery(sources=["consensus"], limit=5)).items] \
        == ["vid"]


def test_facets_report_source_and_family(empty_repo):
    from backend.models import Asset, AssetType

    empty_repo.replace_source_rows([Asset(id="kit", type=AssetType.LDK, title="Kit",
                                    products=["Windchill PDMLink"])], "sharepoint")
    empty_repo.replace_source_rows([Asset(id="vid", type=AssetType.VIDEO, source="consensus",
                                    title="Vid", products=["Windchill"])], "consensus")

    facets = empty_repo.facets()
    assert {f.value: f.count for f in facets.sources} == {"sharepoint": 1, "consensus": 1}
    assert {f.value: f.count for f in facets.product_families} == {"Windchill": 2}


def test_the_api_does_not_quietly_default_to_english(empty_repo):
    """The English default belongs to the client, not here.

    Clients preselect `en` because otherwise one recording's six translations
    fill the first page. But a repository that hides 105 items nobody excluded
    — while still reporting a total — is not a helpful default, just an
    invisible one. Asking for everything must return everything.
    """
    from backend.models import Asset, AssetType

    empty_repo.replace_source_rows([
        Asset(id="en1", type=AssetType.VIDEO, source="consensus",
              title="Overview", language="en"),
        Asset(id="ko1", type=AssetType.VIDEO, source="consensus",
              title="Overview Korean", language="ko"),
    ], "consensus")

    everything = empty_repo.list(AssetQuery(limit=10))
    assert everything.total == 2, "no filter means no filter"
    assert {a.id for a in everything.items} == {"en1", "ko1"}

    english = empty_repo.list(AssetQuery(languages=["en"], limit=10))
    assert [a.id for a in english.items] == ["en1"]


# ───────────────────────────────────────────────────── relevance ordering
def test_search_ranks_title_matches_above_description_matches(empty_repo):
    from backend.models import Asset, AssetType
    from datetime import date

    empty_repo.replace_source_rows([
        # Newest, but only mentions the term in passing.
        Asset(id="aside", type=AssetType.VIDEO, title="Something Else",
              description="mentions windchill once", uploaded_at=date(2026, 8, 1)),
        Asset(id="buried", type=AssetType.LDK, title="Managing CAD with Windchill",
              uploaded_at=date(2020, 1, 1)),
        Asset(id="prefix", type=AssetType.LDK, title="Windchill Overview",
              uploaded_at=date(2019, 1, 1)),
        Asset(id="exact", type=AssetType.LDK, title="Windchill",
              uploaded_at=date(2018, 1, 1)),
    ], "sharepoint")

    ranked = [a.id for a in empty_repo.list(
        AssetQuery(text="windchill", sort="relevance", limit=10)).items]

    assert ranked == ["exact", "prefix", "buried", "aside"], (
        "exact title, then opening match, then mid-title, then description — "
        "and the newest item comes last because it is the least relevant")


def test_recency_only_breaks_ties(empty_repo):
    """Equally relevant results keep the previous ordering, so the change is
    additive rather than a reshuffle."""
    from backend.models import Asset, AssetType
    from datetime import date

    empty_repo.replace_source_rows([
        Asset(id="older", type=AssetType.LDK, title="Windchill Overview",
              uploaded_at=date(2020, 1, 1)),
        Asset(id="newer", type=AssetType.LDK, title="Windchill Basics",
              uploaded_at=date(2026, 1, 1)),
    ], "sharepoint")

    ranked = [a.id for a in empty_repo.list(
        AssetQuery(text="windchill", sort="relevance", limit=10)).items]
    assert ranked == ["newer", "older"]


def test_relevance_is_identical_to_recent_without_a_search(empty_repo):
    """Which is why it is safe as the default — browsing behaviour is unchanged."""
    from backend.models import Asset, AssetType
    from datetime import date

    empty_repo.replace_source_rows([
        Asset(id="old", type=AssetType.LDK, title="A", uploaded_at=date(2019, 1, 1)),
        Asset(id="new", type=AssetType.LDK, title="B", uploaded_at=date(2026, 1, 1)),
    ], "sharepoint")

    by_relevance = [a.id for a in empty_repo.list(AssetQuery(sort="relevance")).items]
    by_recent = [a.id for a in empty_repo.list(AssetQuery(sort="recent")).items]
    assert by_relevance == by_recent == ["new", "old"]


def test_a_multi_word_search_finds_records_with_words_in_between(empty_repo):
    """End to end through the repository, both backends: this returned zero
    results before, because the filter tested the query as one substring."""
    from backend.models import Asset, AssetType

    empty_repo.replace_source_rows([
        Asset(id="para", type=AssetType.VDK, title="Creo Parametric Overview"),
        Asset(id="tight", type=AssetType.VDK, title="Creo Overview"),
        Asset(id="other", type=AssetType.VDK, title="Windchill Overview"),
    ], "sharepoint")

    found = [a.id for a in empty_repo.list(AssetQuery(text="Creo overview")).items]
    assert found == ["tight", "para"], "both match; the contiguous one ranks first"
    assert "other" not in found, "every term must appear"


def test_multi_word_search_ignores_word_order(empty_repo):
    from backend.models import Asset, AssetType

    empty_repo.replace_source_rows(
        [Asset(id="para", type=AssetType.VDK, title="Creo Parametric Overview")],
        "sharepoint")

    assert [a.id for a in empty_repo.list(AssetQuery(text="overview creo")).items] \
        == ["para"]


# ─────────────────────────────────── every source reports the same way
def test_both_syncs_emit_the_identical_report_shape():
    """They drifted once already: one said `assets`, the other `indexed`; one
    said `skipped_no_demo_type`, the other `skipped_private`. Neither said
    whether a number was a total or a change count, so "indexed 491" after a
    Consensus sync was unreadable — 491 updated, or 491 in total?

    This test is the thing that keeps them together.
    """
    from backend.integrations.consensus_sync import ConsensusSyncResult
    from backend.integrations.graph.sync import SyncResult
    from backend.integrations.sync_report import KEYS

    graph = SyncResult(assets=455, skipped_no_demo_type=295).as_dict()
    consensus = ConsensusSyncResult(demos_seen=637, indexed=491,
                                    skipped_private=146).as_dict()

    assert set(graph) == set(consensus) == set(KEYS)
    assert graph["source"] == "sharepoint" and consensus["source"] == "consensus"
    assert graph["indexed"] == 455 and consensus["indexed"] == 491
    assert graph["examined"] == 750, "assets plus those rejected for no Demo Type"
    assert consensus["examined"] == 637
    assert graph["skipped_total"] == 295 and consensus["skipped_total"] == 146
