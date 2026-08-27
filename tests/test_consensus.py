"""Consensus matching, reconciliation, and the share gate.

The matching logic is pure, so it is tested hard here. The HTTP client's field
mapping is NOT tested against reality — it cannot be until credentials exist —
which is exactly why `/api/consensus/probe` exists.
"""
from __future__ import annotations

import pytest

from backend.integrations.consensus import (
    ConsensusDemo, ConsensusError, StubConsensusClient,
)
from backend.models import AssetSummary, AssetType
from backend.services import relevance
from backend.services.consensus_match import (
    normalise, reconcile, similarity, best_candidates, MATCH_THRESHOLD, STRONG_MATCH,
)


def asset(asset_id: str, title: str, uuid: str | None = None) -> AssetSummary:
    return AssetSummary(id=asset_id, type=AssetType.VIDEO, title=title, consensus_uuid=uuid)


def demo(uuid: str, title: str) -> ConsensusDemo:
    return ConsensusDemo(uuid=uuid, title=title)


# ────────────────────────────────────────────────────────────── normalisation
def test_normalise_strips_punctuation_dashes_and_noise():
    assert normalise("Windchill AI – Parts Rationalization LDK") == \
           normalise("Windchill AI Parts Rationalization LDK")
    assert normalise("The Intelligent Product Lifecycle") == "intelligent product lifecycle"
    assert normalise("") == ""


def test_similarity_bounds():
    assert similarity("Creo 13 Top Enhancements", "Creo 13 Top Enhancements") == 1.0
    assert similarity("Creo 13 Top Enhancements", "") == 0.0
    assert similarity("", "") == 0.0


def test_similarity_tolerates_real_title_drift():
    """The two systems genuinely spell the same asset differently."""
    pairs = [
        ("Windchill AI – Parts Rationalization LDK", "Windchill AI Parts Rationalization LDK"),
        ("The Intelligent Product Lifecycle — Executive Overview",
         "Intelligent Product Lifecycle: Executive Overview"),
        ("Creo Chapters S1E4 — Composites Deep Dive (Replay)",
         "Creo Chapters S1E4 Composites Deep Dive"),
    ]
    for a, b in pairs:
        assert similarity(a, b) >= STRONG_MATCH, f"{a!r} vs {b!r} scored too low"


def test_similarity_separates_genuinely_different_titles():
    assert similarity("Creo 13 Top Enhancements", "Windchill Quality Management") < 0.5
    # Same product family, different asset — must not be a confident match.
    assert similarity("Creo 11 Top Enhancements", "Windchill Volvo Trucks") < 0.5


# ─────────────────────────────────────── regressions: real false positives
# Every pair below was produced by an earlier version of the matcher as a
# confident proposal against the actual seed catalogue. They are the reason
# the containment heuristic was removed and the disqualifiers added.
@pytest.mark.parametrize("portal_title, consensus_title, why", [
    ("Tech Walkthrough No Audio — Engineering Part 1",
     "Tech Walkthrough Audio — Engineering",
     "'No Audio' and 'Audio' are opposites; scored 0.950"),
    ("Tech Walkthrough No Audio — Manufacturing Part 3",
     "Tech Walkthrough Audio — Manufacturing",
     "same inversion, different subject; scored 0.950"),
    ("Tech Walkthrough No Audio — Service Part 4",
     "Tech Walkthrough Audio — Engineering",
     "different subject entirely; scored 0.754"),
    ("Windchill AI – Parts Rationalization LDK",
     "Windchill AI Parts Rationalization — Walkthrough with Audio",
     "an LDK is not the video; scored 0.822"),
    ("The Intelligent Product Lifecycle Presentation",
     "The Intelligent Product Lifecycle — Executive Overview",
     "genuinely two different assets; scored 0.778"),
])
def test_known_false_positives_stay_below_threshold(portal_title, consensus_title, why):
    score = similarity(portal_title, consensus_title)
    assert score < MATCH_THRESHOLD, f"{why} — now {score:.3f}"


def test_differing_numbers_block_a_match():
    assert similarity("Tech Walkthrough Manufacturing Part 1",
                      "Tech Walkthrough Manufacturing Part 3") < MATCH_THRESHOLD
    assert similarity("Creo 11 Top Enhancements",
                      "Creo 13 Top Enhancements") < MATCH_THRESHOLD


def test_negation_blocks_a_match():
    assert similarity("Attract Loop Audio — Introduction",
                      "Attract Loop No Audio — Introduction") < MATCH_THRESHOLD


# ──────────────────────────────────────────────────────────────── candidates
def test_best_candidates_discards_near_misses_entirely():
    """Only the real match survives — 'Creo 11' is not a weak candidate for
    'Creo 13', it is the wrong asset."""
    demos = [demo("u1", "Windchill Volvo Trucks"),
             demo("u2", "Creo 13 Top Enhancements"),
             demo("u3", "Creo 11 Top Enhancements")]
    hits = best_candidates("Creo 13 Top Enhancements", demos)
    assert [h.demo.uuid for h in hits] == ["u2"]
    assert hits[0].confidence == 1.0


def test_best_candidates_ranks_when_several_are_plausible():
    demos = [demo("u1", "Windchill Change Management Walkthrough"),
             demo("u2", "Windchill Change Management Walkthrough Overview"),
             demo("u3", "Something Entirely Unrelated")]
    hits = best_candidates("Windchill Change Management Walkthrough", demos)
    assert [h.demo.uuid for h in hits] == ["u1", "u2"]
    assert hits[0].confidence > hits[1].confidence


def test_below_threshold_yields_nothing():
    assert best_candidates("Completely Unrelated Thing", [demo("u1", "Creo 13 Top")]) == []


# ────────────────────────────────────────────────────────────── reconciliation
def test_existing_uuid_wins_over_title_similarity():
    """A recorded UUID is a human decision and outranks a heuristic."""
    demos = [demo("real-uuid", "Something Totally Different"),
             demo("other", "Creo 13 Top Enhancements")]
    report = reconcile([asset("a1", "Creo 13 Top Enhancements", uuid="real-uuid")], demos)

    assert len(report.matched) == 1
    assert report.matched[0].demo.uuid == "real-uuid"
    assert report.matched[0].confidence == 1.0
    assert report.proposals == []


def test_proposal_for_asset_without_uuid():
    report = reconcile([asset("a1", "Creo 13 Top Enhancements")],
                       [demo("u1", "Creo 13 Top Enhancements")])
    assert len(report.proposals) == 1
    assert report.proposals[0].demo.uuid == "u1"
    assert report.proposals[0].strong


def test_conflict_when_recorded_uuid_disagrees():
    """A stale UUID must surface as a conflict, never be silently overwritten."""
    report = reconcile([asset("a1", "Creo 13 Top Enhancements", uuid="stale-not-in-consensus")],
                       [demo("u1", "Creo 13 Top Enhancements")])
    assert len(report.conflicts) == 1
    assert report.proposals == []


def test_ambiguous_matches_are_refused_not_guessed():
    """Duplicate registrations in Consensus are real; we must not pick one."""
    demos = [demo("u1", "Windchill Change Management Walkthrough"),
             demo("u2", "Windchill Change Management Walkthrough")]
    report = reconcile([asset("a1", "Windchill Change Management Walkthrough")], demos)
    assert len(report.ambiguous) == 1
    assert report.proposals == [], "an ambiguous match must not become a proposal"


def test_gaps_reported_in_both_directions():
    assets = [asset("a1", "Creo 13 Top Enhancements"),
              asset("a2", "An Asset Consensus Has Never Heard Of")]
    demos = [demo("u1", "Creo 13 Top Enhancements"),
             demo("u2", "A Demo The Portal Has Never Heard Of")]
    report = reconcile(assets, demos)

    assert [a.id for a in report.portal_only] == ["a2"]
    assert [d.uuid for d in report.consensus_only] == ["u2"]
    assert report.summary() == {
        "matched": 1, "proposals": 1, "conflicts": 0,
        "ambiguous": 0, "portal_only": 1, "consensus_only": 1,
    }


def test_reconcile_handles_empty_inputs():
    assert reconcile([], []).summary()["matched"] == 0
    assert len(reconcile([asset("a1", "Anything")], []).portal_only) == 1
    assert len(reconcile([], [demo("u1", "Anything")]).consensus_only) == 1


# ─────────────────────────────────────────────────────────────── stub client
def test_stub_is_seeded_from_the_real_catalogue():
    client = StubConsensusClient()
    demos = client.list_demos()
    assert len(demos) > 5
    # It must contain demos with no Portal counterpart, so the reconciliation
    # report exercises both directions during development.
    assert any(d.uuid.startswith("c0de-") for d in demos)


def test_stub_search_and_get():
    client = StubConsensusClient()
    assert client.search("windchill")
    assert client.search("") == []
    known = client.list_demos()[0]
    assert client.get_demo(known.uuid) == known
    assert client.get_demo("nope") is None


def test_stub_refuses_to_share_unregistered_demo():
    """Consensus cannot send what is not registered there."""
    with pytest.raises(ConsensusError):
        StubConsensusClient().create_share_link("not-registered")


def test_client_has_no_create_method():
    """Absence is the design: the Consensus API cannot create or upload demos."""
    for name in ("create_demo", "upload", "create"):
        assert not hasattr(StubConsensusClient(), name)


# ─────────────────────────── cross-script false positives, measured live
# normalise() keeps only [a-z0-9], so a Japanese or Korean title survives as
# whatever Latin fragment it happens to contain. Every pair below scored 1.000
# against the production Consensus tenant on 2026-08-26, and every one is a
# different-language recording that must not be shared in place of the English
# one. Threshold is 0.72.
CROSS_SCRIPT_FALSE_POSITIVES = [
    ("MBD - Demo Video - CF", "모델 기반 정의 (MBD)"),
    ("AAX - Demo Video - CF", "고급 어셈블리 확장 모듈 (AAX)"),
    ("Codebeamer Demo Video CF", "Codebeamer ご紹介"),
    ("Codebeamer_CF", "Codebeamer 概要"),
]


@pytest.mark.parametrize("asset_title,demo_title", CROSS_SCRIPT_FALSE_POSITIVES)
def test_a_localised_demo_is_not_matched_to_an_english_asset(asset_title, demo_title):
    score = similarity(asset_title, demo_title)
    assert score < 0.72, (
        f"{asset_title!r} matched the non-English {demo_title!r} at {score:.3f}. "
        f"Sharing that asset would send the wrong language to the customer.")


def test_two_titles_reduced_to_the_same_remnant_do_not_match():
    """Both of these Korean titles normalise to '10 0' -- same script, so the
    mismatch rule cannot see it. Nothing survived to compare, and scoring that
    1.000 made two different demos identical."""
    a, b = "크레오 10.0 업그레이드 - 기본기능편", "크레오 10.0 업그레이드 - 특화기능편"
    assert normalise(a) == normalise(b), "premise: normalisation destroys both"
    assert similarity(a, b) < 0.72


def test_the_identical_token_shortcut_does_not_skip_the_disqualifiers():
    """`if ta == tb: return 1.0` ran before every penalty, which is precisely
    how the cross-script pairs reached exactly 1.000 -- both sides had been
    reduced to the same single token."""
    english, korean = "MBD Demo Video", "모델 기반 정의 (MBD)"
    assert normalise(english) == normalise(korean) == "mbd",         "premise: both sides reduce to the same single token"
    assert similarity(english, korean) < 0.72


@pytest.mark.parametrize("asset_title,demo_title,floor", [
    ("Windchill BOM Management_Demo Video_CF", "Windchill BOM Management", 0.72),
    ("Windchill Overview VDK v.2", "Windchill Overview VDK v.2 Demo", 0.95),
    ("Model Based Definition MBD Demo Video", "Creo Model Based Definition (MBD)", 0.72),
])
def test_genuine_matches_survive_the_new_disqualifiers(asset_title, demo_title, floor):
    """Tightening must not cost real matches -- these are live pairs."""
    assert similarity(asset_title, demo_title) >= floor


# ────────────────────────────────────────────────────── relevance scoring
@pytest.mark.parametrize("title,expected", [
    ("Windchill", relevance.EXACT_TITLE),
    ("Windchill PDMLink Overview", relevance.TITLE_PREFIX),
    ("Managing CAD with Windchill", relevance.TITLE_WORD),
    ("PreWindchillThing", relevance.TITLE_SUBSTRING),
    ("Something Else", relevance.NO_MATCH),
])
def test_title_match_tiers(title, expected):
    assert relevance.score("windchill", title) == expected


def test_a_description_match_still_counts_but_ranks_last():
    assert relevance.score("windchill", "Other", "about windchill") \
        == relevance.DESCRIPTION
    assert relevance.DESCRIPTION < relevance.TITLE_SUBSTRING


def test_an_empty_query_matches_nothing():
    """Guards the default: with no search text the sort must fall through to
    recency rather than scoring everything equally."""
    assert relevance.score("", "Windchill") == relevance.NO_MATCH
    assert relevance.score(None, "Windchill") == relevance.NO_MATCH


def test_scoring_is_case_and_whitespace_insensitive():
    assert relevance.score("  WINDCHILL  ", "windchill") == relevance.EXACT_TITLE


# ─────────────────────────────── multi-word search: the "Creo overview" bug
def test_words_need_not_be_adjacent():
    """The reported bug. The filter tested the whole query as one substring, so
    a search for "Creo overview" returned NOTHING while
    "Creo Parametric Overview" sat in the catalogue."""
    assert relevance.matches("Creo overview", "Creo Parametric Overview")
    assert relevance.score("Creo overview", "Creo Parametric Overview") \
        == relevance.TITLE_ALL_TERMS


def test_word_order_does_not_matter():
    assert relevance.matches("overview creo", "Creo Parametric Overview")


def test_every_term_must_appear():
    """AND, not OR. Adding a word has to narrow the results, or a search box
    gives no way to home in on anything."""
    assert not relevance.matches("creo windchill", "Creo Parametric Overview")
    assert relevance.matches("creo parametric", "Creo Parametric Overview")


def test_a_contiguous_phrase_outranks_the_same_words_scattered():
    tight = relevance.score("creo overview", "Creo Overview")
    loose = relevance.score("creo overview", "Creo Parametric Overview")
    assert tight > loose, "both match, and the closer one must come first"


def test_a_term_found_only_in_the_description_still_matches_but_ranks_lower():
    assert relevance.score("creo overview", "Creo Parametric",
                           "an overview of the basics") == relevance.ANY_FIELD
    assert relevance.ANY_FIELD < relevance.TITLE_ALL_TERMS


def test_span_prefers_the_title_that_says_it_soonest():
    """Six tiers barely discriminate on multi-word queries -- "Creo overview"
    put all 61 live hits into two of them. Span orders within a tier."""
    assert relevance.span("creo overview", "Creo Parametric Overview") \
        < relevance.span("creo overview", "PTC NEXT - Spring 2026 - Creo 13 AI Overview")
    assert relevance.span("creo overview", "Windchill Only") == 10_000


def test_ranking_puts_tier_before_span():
    """A weaker tier must never win on a tighter span alone."""
    exact = relevance.ranking("creo overview", "Creo Overview")
    scattered = relevance.ranking("creo overview", "Creo X Overview")
    assert exact > scattered


def test_terms_keep_non_latin_titles():
    """The catalogue holds Japanese, Korean and Chinese titles. An ASCII-only
    tokeniser would silently drop them from search entirely."""
    assert relevance.terms("모델 기반 정의") == ["모델", "기반", "정의"]
    assert relevance.matches("모델", "모델 기반 정의 (MBD)")
