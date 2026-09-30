"""The "Demo Video" library as a Hub source, without credentials.

Item shapes follow what the library returned on 2026-09-29 for the first
migrated video ("Creo 10 Top Enhancements"): a document set with its columns
under listItem.fields, and the .mp4 inside it.
"""
from __future__ import annotations

import httpx
import pytest

from backend.integrations.graph import video_sync as vs
from backend.repositories.json_repo import JsonAssetRepository
from backend.repositories.base import AssetQuery
from backend.routers import graph as graph_router
from tests.test_graph import DRIVE_ID, SITE_ID, SITE_URL, client_for


def doc_set(name, item_id=None, **fields):
    columns = {"Demo_x0020_Type": "Video", "ContentType": "Demo",
               "HubProducts": ["Creo"], "Segment": ["CAD"],
               "VideoType": "Technical Overview", "Customer_x0020_Facing": True,
               "DocumentSetDescription": "Learn what's new.",
               "OriginalPublishDate": "2023-03-31T00:00:00Z", **fields}
    columns = {k: v for k, v in columns.items() if v is not None}
    return {
        "id": item_id or f"id-{name}",
        "name": name,
        "folder": {"childCount": 1},
        "webUrl": f"{SITE_URL}/_layouts/15/DocSetHome.aspx?id=/sites/EXT-TDD/DemoVideo/{name}",
        "createdDateTime": "2026-09-29T20:11:56Z",
        "lastModifiedDateTime": "2026-09-29T20:12:20Z",
        "parentReference": {"path": f"/drives/{DRIVE_ID}/root:"},
        "listItem": {"fields": columns},
    }


def mp4(folder, name=None, millis=None):
    name = name or f"{folder}_Technical Overview.mp4"
    item = {"id": f"file-{folder}-{name}", "name": name, "size": 116_188_570,
            "file": {"mimeType": "video/mp4"},
            "parentReference": {"path": f"/drives/{DRIVE_ID}/root:/{folder}"}}
    if millis:
        item["video"] = {"duration": millis, "width": 1920, "height": 1080}
    return item


def build(*items):
    return vs.build_assets(list(items))


# ─────────────────────────────────────────────────────────── the mapping
def test_a_migrated_document_set_becomes_a_video_asset():
    (a,), result = build(doc_set("Creo 10 Top Enhancements"),
                         mp4("Creo 10 Top Enhancements", millis=312_000))
    assert a.type.value == "video"
    assert a.id == "video-creo-10-top-enhancements"
    assert a.title == "Creo 10 Top Enhancements"
    assert a.source == "sharepoint", "no new badge: it is SharePoint, like the kits"
    assert a.description == "Learn what's new."
    assert a.segment == "CAD"
    assert str(a.uploaded_at) == "2023-03-31", "the video's own publish date"
    assert a.main_video == "Creo 10 Top Enhancements_Technical Overview.mp4"
    assert a.duration_seconds == 312
    assert (result.assets, result.resources) == (1, 1)


def test_products_are_hub_products_only_and_the_rest_is_searchable():
    """Liwei, 2026-09-29: products outside the Hub's list do not enter Product,
    and can still be found by search."""
    (a,), _ = build(doc_set(
        "Vestas", HubProducts=["Windchill", "Creo View MCAD"],
        Product=[{"Label": "Windchill PDMLink", "TermGuid": "g1"},
                 {"Label": "ThingWorx Analytics", "TermGuid": "g2"},
                 {"Label": "Windchill", "TermGuid": "g3"}],
        LongDescription="Blade production quality.", NamedCustomer="Vestas",
        GallerySection="PLM - Innovators", Gallery="PTC Gallery",
        VideoSubtype="Customer"))
    assert a.products == ["Windchill", "Creo View MCAD"]
    assert "ThingWorx Analytics" in a.search_text
    assert "Windchill PDMLink" in a.search_text
    assert "Blade production quality." in a.search_text
    assert "PLM - Innovators" in a.search_text
    assert a.named_customer == "Vestas"


def test_video_type_maps_onto_the_hubs_three_for_now():
    got = {vt: build(doc_set("X", VideoType=vt))[0][0].content_depth
           for vt in ("Technical Overview", "Technical Walkthrough", "Technical Teaser",
                      "Presenter Support", "Other")}
    assert {k: (v.value if v else None) for k, v in got.items()} == {
        "Technical Overview": "Overview", "Technical Walkthrough": "Walkthrough",
        "Technical Teaser": "Teaser", "Presenter Support": None, "Other": None}


def test_the_stated_customer_facing_and_audio_win_over_the_filename():
    (a,), _ = build(doc_set("Internal One", Customer_x0020_Facing=False,
                            Contains_x0020_Audio=True),
                    mp4("Internal One", name="Internal One_Customer Facing.mp4"))
    assert a.customer_facing is False
    assert a.has_narrated_audio is True


def test_a_folder_still_being_migrated_is_not_listed():
    """The migration writes Demo Type last, after the upload."""
    assets, result = build(doc_set("Half Done", Demo_x0020_Type=None),
                           mp4("Half Done"))
    assert assets == []
    assert (result.skipped_no_demo_type, result.orphan_files) == (1, 1)


def test_multi_segment_keeps_the_first_as_segment():
    (a,), _ = build(doc_set("Both", Segment=["PLM", "CAD"]))
    assert a.segment == "PLM"


def test_without_a_publish_date_the_creation_date_is_used():
    (a,), _ = build(doc_set("New", OriginalPublishDate=None))
    assert str(a.uploaded_at) == "2026-09-29"


# ─────────────────────────────────────────────────────────── the sync
def handler_for(items, library="Demo Video"):
    def handler(request):
        path = request.url.path
        if ":/sites/" in path:
            return httpx.Response(200, json={"id": SITE_ID, "webUrl": SITE_URL})
        if path.endswith("/drives"):
            return httpx.Response(200, json={"value": [{"id": DRIVE_ID, "name": library}]})
        if "delta" in path:
            bare = [{k: v for k, v in i.items() if k != "listItem"} for i in items]
            return httpx.Response(200, json={"value": bare,
                                             "@odata.deltaLink": "https://x/delta?token=t"})
        if path.endswith("/root/children"):
            return httpx.Response(200, json={"value": [i for i in items if "folder" in i]})
        return httpx.Response(404)
    return handler


def test_the_sync_writes_its_own_mirror_and_the_catalogue_lists_it(tmp_path):
    repo = JsonAssetRepository(str(tmp_path))
    items = [doc_set("Creo 10 Top Enhancements"), mp4("Creo 10 Top Enhancements"),
             doc_set("Vestas", HubProducts=["Windchill"], Segment=["PLM"],
                     LongDescription="turbine blade quality")]
    result = vs.sync_videos(client_for(handler_for(items)), repo)

    assert result.assets == 2
    assert (tmp_path / "mirror" / "demo_video.json").exists()
    assert repo.count_source_rows("demo_video") == 2
    page = repo.list(AssetQuery(text="turbine", limit=10))
    assert [a.id for a in page.items] == ["video-vestas"], "long description is searchable"
    page = repo.list(AssetQuery(product_families=["Windchill"], limit=10))
    assert [a.id for a in page.items] == ["video-vestas"], "Product filter reads HubProducts"
    got = repo.get("video-creo-10-top-enhancements")
    assert got.main_video == "Creo 10 Top Enhancements_Technical Overview.mp4"


def test_a_missing_library_is_an_error_not_an_empty_catalogue(tmp_path):
    repo = JsonAssetRepository(str(tmp_path))
    with pytest.raises(ValueError, match="Demo Video"):
        vs.sync_videos(client_for(handler_for([], library="Something Else")), repo)


def test_emptying_a_small_test_library_is_allowed(tmp_path):
    """Liwei deletes the test items before the real migration (2026-09-29)."""
    repo = JsonAssetRepository(str(tmp_path))
    vs.sync_videos(client_for(handler_for([doc_set(f"T{i}") for i in range(10)])), repo)
    assert repo.count_source_rows("demo_video") == 10
    vs.sync_videos(client_for(handler_for([])), repo)
    assert repo.count_source_rows("demo_video") == 0


def test_a_large_library_collapsing_is_still_refused(tmp_path):
    from backend.repositories.json_repo import WouldShrinkMirror
    repo = JsonAssetRepository(str(tmp_path))
    vs.sync_videos(client_for(handler_for([doc_set(f"V{i}") for i in range(40)])), repo)
    with pytest.raises(WouldShrinkMirror):
        vs.sync_videos(client_for(handler_for([doc_set("V1")])), repo)


def test_it_rides_along_with_the_sharepoint_sync_and_fails_alone(monkeypatch):
    calls = []

    def boom(client, repo, site=None, library=None):
        calls.append(1)
        raise RuntimeError("library unreachable")

    monkeypatch.setattr(vs, "sync_videos", boom)

    class Client:
        def resolve_site(self, url=None):
            return type("S", (), {"site_id": SITE_ID, "web_url": SITE_URL})()

    out = graph_router._sync_demo_video(Client(), repo=None)
    assert calls and out["ok"] is False and "unreachable" in out["error"]


def test_a_blank_library_setting_switches_it_off(monkeypatch):
    from backend.config import settings
    monkeypatch.setattr(settings, "graph_video_library", "")
    assert graph_router._sync_demo_video(object(), repo=None) == {
        "ok": None, "skipped": "not configured"}
