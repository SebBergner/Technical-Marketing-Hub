"""Consensus videos against SharePoint (backend/services/consensus_inventory.py)."""
from __future__ import annotations

from backend.services import consensus_inventory as ci


def single(uuid, title, video, duration, internal=None, public=True):
    return {"uuid": uuid, "title": title, "internalTitle": internal or title, "type": "single",
            "isPublic": public, "createdAt": "2026-01-01T00:00:00+00:00",
            "mainVideo": {"videoUuid": video, "duration": str(duration)}, "features": [],
            "subDemos": []}


def playlist(uuid, title, chapters, kind="standard"):
    return {"uuid": uuid, "title": title, "type": kind, "isPublic": True,
            "mainVideo": None, "subDemos": [],
            "features": [{"name": name, "longVideoUuid": video,
                          "longVideoDuration": str(duration), "shortVideoUuid": ""}
                         for name, video, duration in chapters]}


def sp(file, duration, asset="", size=100, language="en", library="Demo Video"):
    return {"library": library, "asset_id": file, "asset_title": asset or file, "file": file,
            "item_id": "I-" + file, "size_bytes": size, "duration": duration,
            "language": language}


# ───────────────────────────────────────────── one row per Consensus video
def test_a_video_is_one_row_with_its_demo_and_its_playlists():
    details = [
        single("d1", "Codebeamer Streams", "v1", 291.2),
        playlist("p1", "Codebeamer Playlist", [("Streams", "v1", 291.2), ("Baselines", "v2", 80)]),
    ]
    videos, playlists, no_video = ci.consensus_videos(details)
    by = {v.video_uuid: v for v in videos}
    assert [d["uuid"] for d in by["v1"].demos] == ["d1"]
    assert [p["chapter"] for p in by["v1"].playlists] == ["Streams"]
    assert by["v2"].demos == [] and by["v2"].title == "Baselines", "a chapter with no demo of its own"
    assert [c["video_uuid"] for c in playlists[0]["chapters"]] == ["v1", "v2"]
    assert no_video == []


def test_advanced_demos_nest_whole_demos_and_singles_without_video_are_listed():
    advanced = {"uuid": "a1", "title": "Mathcad", "type": "advanced", "isPublic": True,
                "features": [], "mainVideo": None,
                "subDemos": [single("s1", "What's New", "v9", 342.7)]}
    videos, playlists, no_video = ci.consensus_videos(
        [advanced, {**single("x", "HTML tour", None, 0), "mainVideo": {}}])
    assert [v.video_uuid for v in videos] == ["v9"]
    assert videos[0].playlists[0]["title"] == "Mathcad"
    assert [d["uuid"] for d in no_video] == ["x"]


def test_languages_come_from_demo_search():
    videos, _, _ = ci.consensus_videos([single("d1", "A", "v1", 10)], {"d1": "fr"})
    assert videos[0].language == "fr"


# ───────────────────────────────────────────────────────────── names
def test_boilerplate_and_numbering_are_not_part_of_a_name():
    assert ci.clean("PTC NEXT - Spring 2026 - Codebeamer Demonstration Spotlight Streams") \
        == "Codebeamer Streams"
    assert ci.clean("Codebeamer Streams_Technical Walkthrough.mp4") == "Codebeamer Streams"
    assert ci.clean("2.Working with Geometry and Visualization.mp4") \
        == "Working with Geometry and Visualization"
    assert ci.internal_topic("CAD | Creo | Digital Thread | Synopsis | 11:00") \
        == "Creo Digital Thread Synopsis"


# ───────────────────────────────────────────────────────────── matching
def video(title, duration, language="en", internal=None):
    videos, _, _ = ci.consensus_videos([single("d", title, "v", duration, internal)],
                                       {"d": language})
    return videos[0]


def test_name_and_length_together_make_a_match():
    m = ci.match(video("PTC NEXT - Spring 2026 - Codebeamer Demonstration Spotlight Streams",
                       291.2),
                 [sp("Codebeamer Streams_Technical Walkthrough.mp4", 291)])
    assert m.status == ci.IN_SP and m.duration_diff == 0.2


def test_the_same_length_alone_is_not_a_match():
    """Measured 2026-10-09: ~7 unrelated SharePoint videos per Consensus
    video fall within two seconds by coincidence."""
    m = ci.match(video("6 - Audit Change", 34.97), [sp("Video-1_DPM-Intro.mp4", 35)])
    assert m.status == ci.MIGRATE


def test_a_shared_product_name_alone_does_not_carry_a_match():
    m = ci.match(video("Codebeamer AI Requirement Assistant", 227),
                 [sp("Codebeamer Test Basics_Technical Overview.mp4", 227)])
    assert m.status == ci.MIGRATE


def test_different_products_are_different_videos():
    m = ci.match(video("Mathcad Prime - Symbolics Overview", 378),
                 [sp("AutoCAD Symbolics Overview_Demo Video.mp4", 377)])
    assert m.status == ci.MIGRATE


def test_the_same_title_at_another_length_is_another_cut():
    m = ci.match(video("Creo AI Automate", 756.7),
                 [sp("Creo AI Automate_Technical Walkthrough.mp4", 165)])
    assert m.status == ci.OTHER_CUT


def test_another_language_is_flagged_not_merged():
    m = ci.match(video("Advanced Visualization Windchill", 259.3, language="fr"),
                 [sp("Windchill Advanced Visualization_Technical Walkthrough.mp4", 259)])
    assert m.status == ci.OTHER_LANGUAGE


def test_a_localized_title_never_matches_an_english_file():
    m = ci.match(video("모델 기반 정의 (MBD)", 282, internal="Creo | MBD Model Based Definition KO"),
                 [sp("Creo Model-Based Definition_Technical Walkthrough.mp4", 281)])
    assert m.status == ci.MIGRATE


def test_copies_of_the_same_file_are_grouped_and_a_different_file_is_the_runner_up():
    m = ci.match(video("Windchill Overview Demo", 1981),
                 [sp("Windchil_Overview_NCF.mp4", 1981, "Windchill Overview VDK v.2", size=7),
                  sp("Windchill Overview.mp4", 1981, "Windchill Overview", size=7,
                     library="Demo Catalog"),
                  sp("Windchill Overview Short.mp4", 400, "Windchill Overview")])
    assert m.status == ci.IN_SP
    assert len(m.copies) == 1 and m.copies[0]["library"] == "Demo Catalog"
    assert m.runner_up["file"] == "Windchill Overview Short.mp4"


def test_build_counts_files_claimed_by_more_than_one_video():
    details = [single("d1", "Creo Routed Systems", "v1", 259),
               single("d2", "Creo Routed Systems Spotlight", "v2", 259.4)]
    out = ci.build(details, {"Demo Video": [{"id": "a", "title": "Creo Routed Systems",
                                             "language": "en", "resources": [
        {"kind": "video", "name": "Creo Routed Systems_Technical Walkthrough.mp4",
         "item_id": "I-1", "size_bytes": 5, "duration_seconds": 259}]}]})
    assert {m.status for _, m in out["videos"]} == {ci.IN_SP}
    assert list(out["shared_files"]) == ["I-1"]
