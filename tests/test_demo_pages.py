"""Demo pages as a source (Liwei, 2026-10-05): page + folder, folder only, page only."""
from __future__ import annotations

import json
from collections import Counter

from backend.integrations.graph import demo_pages as dp
from backend.repositories.base import AssetQuery
from backend.repositories.json_repo import JsonAssetRepository

SITE = "https://ptccloud.sharepoint.com/sites/EXT-TDD"


def folder_row(i, name, products=("Creo",)):
    return {"id": f"kit-{i}", "type": "vdk", "title": name, "products": list(products),
            "web_url": f"{SITE}/_layouts/15/DocSetHome.aspx?id=/sites/EXT-TDD/Demo%20Catalog/"
                       + name.replace(" ", "%20").replace("&", "%26"),
            "resources": [{"name": "a.mp4", "kind": "video", "item_id": "x"}], "resource_count": 1}


def page_row(slug, title, folder, modified="2026-10-05T00:00:00Z", products=("Creo",)):
    url = f"{SITE}/SitePages/Demo%20Catalog/{slug}.aspx"
    return {"id": f"page-{slug}", "type": "vdk", "title": title, "products": list(products),
            "description": f"About {title}", "thumbnail_url": f"{SITE}/_layouts/15/getpreview.ashx?{slug}",
            "web_url": url, "page_url": url, "page_folder": folder, "page_modified": modified,
            "source": "sharepoint", "resources": []}


def repo_with(tmp_path, catalog, pages, links=True):
    (tmp_path / "mirror").mkdir()
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps(catalog), encoding="utf-8")
    (tmp_path / "mirror" / "demo_pages.json").write_text(json.dumps(pages), encoding="utf-8")
    repo = JsonAssetRepository(str(tmp_path))
    if links:
        repo.set_hub_settings("test", show_demo_page_links=True)
    return repo


def test_page_and_folder_add_the_thumbnail_and_link_to_the_folders_demo(tmp_path):
    repo = repo_with(tmp_path, [folder_row(1, "Bobcat - IPL")],
                     [page_row("bobcat", "Bobcat - IPL", "Bobcat - IPL")])
    ids = [a.id for a in repo.list(AssetQuery(limit=10)).items]
    assert ids == ["kit-1"], "the page is not listed beside its demo"
    kit = repo.get("kit-1")
    assert kit.page_url.endswith("bobcat.aspx") and "getpreview" in kit.thumbnail_url
    assert len(kit.resources) == 1, "files stay as they were"


def test_a_folder_without_a_page_is_unchanged(tmp_path):
    repo = repo_with(tmp_path, [folder_row(1, "DEX VDK v.1")], [])
    kit = repo.get("kit-1")
    assert kit.page_url is None and kit.thumbnail_url is None


def test_a_page_without_a_hub_folder_is_a_demo_of_its_own_with_no_files(tmp_path):
    repo = repo_with(tmp_path, [], [page_row("lamborghini", "Lamborghini - IPL", None)])
    got = repo.get("page-lamborghini")
    assert got.title == "Lamborghini - IPL" and got.page_url == got.web_url
    assert got.resources == [] and got.resource_count == 0


def test_a_folder_name_with_an_ampersand_still_matches(tmp_path):
    repo = repo_with(tmp_path, [folder_row(1, "Codebeamer FA&D Overview VDK v.1")],
                     [page_row("fad", "Codebeamer FA&D Overview - VDK", "Codebeamer FA&D Overview VDK v.1")])
    assert [a.id for a in repo.list(AssetQuery(limit=10)).items] == ["kit-1"]


def test_a_page_about_a_divested_demo_stays_out_with_it(tmp_path):
    """Integrity Lifecycle Manager's page names Codebeamer as its product."""
    repo = repo_with(tmp_path, [folder_row(1, "Integrity Overview v.1", products=("Integrity",))],
                     [page_row("ilm", "Integrity Lifecycle Manager Overview", "Integrity Overview v.1",
                               products=("Codebeamer",))])
    assert repo.list(AssetQuery(limit=10)).total == 0


def test_the_documents_library_web_part_decides_which_folder():
    canvas = {"horizontalSections": [{"columns": [{"webparts": [
        {"data": {"properties": {"isDocumentLibrary": True, "selectedListUrl": "/sites/EXT-TDD/Demo Catalog",
                                 "selectedFolderPath": "DEX VDK v.1",
                                 "selectedFolderKey": "id=%2Fsites%2FEXT%2DTDD%2FDemo%20Catalog%2FDEX%20VDK%20v%2E1&listurl=x"}}},
        {"data": {"properties": {"file": f"{SITE}/Demo%20Catalog/Other%20Kit/x.pptx"}}}]}]}]}
    explicit, seen = dp.folders_in(canvas)
    assert explicit == "DEX VDK v.1"
    assert dp.pick_folder("Anything", explicit, seen) == "DEX VDK v.1"


def test_without_a_library_web_part_the_folder_named_like_the_page_wins():
    seen = Counter({"Codebeamer Overview VDK v.2": 5, "Codebeamer Med Dev Overview VDK V.1": 2})
    assert dp.pick_folder("Codebeamer Med Dev Overview - VDK", None, seen) == "Codebeamer Med Dev Overview VDK V.1"
    assert dp.pick_folder("Something else", None, seen) == "Codebeamer Overview VDK v.2"


def test_a_page_without_a_demo_type_is_not_guessed():
    page = {"id": "p1", "name": "x.aspx", "title": "X", "webUrl": f"{SITE}/SitePages/Demo%20Catalog/x.aspx"}
    assert dp.build_asset(page, {"Title": "X"}, None, set()) is None
    built = dp.build_asset(page, {"Title": "X", "Demo_x0020_Type": "Video Demo Kit",
                                  "Segment": {"Label": "CAD"}, "Language": ["English"]}, None, set())
    assert built.type.value == "vdk" and built.segment == "CAD" and built.page_url == built.web_url


# ─────────────────────── the Admin switch for page links (2026-10-05)
def test_page_links_are_hidden_by_default_and_never_leave_the_server(tmp_path):
    repo = repo_with(tmp_path, [folder_row(1, "Bobcat - IPL")],
                     [page_row("bobcat", "Bobcat - IPL", "Bobcat - IPL"),
                      page_row("lamborghini", "Lamborghini - IPL", None)], links=False)
    kit = repo.get("kit-1")
    assert kit.page_url is None and "getpreview" in kit.thumbnail_url, "thumbnail stays, link goes"
    lambo = repo.get("page-lamborghini")
    assert lambo is not None and lambo.page_url is None and lambo.web_url is None,         "a page-only demo stays listed, with no address to its page"


def test_switching_page_links_on_shows_them(tmp_path):
    repo = repo_with(tmp_path, [], [page_row("lamborghini", "Lamborghini - IPL", None)], links=False)
    assert repo.get("page-lamborghini").page_url is None
    state = repo.set_hub_settings("admin-session", show_demo_page_links=True)
    assert state["show_demo_page_links"] is True and state["changed_by"] == "admin-session"
    assert repo.get("page-lamborghini").page_url.endswith("lamborghini.aspx")


def test_only_an_admin_flips_the_switch(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import app
    from backend.config import settings
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "a-test-password")
    monkeypatch.setattr(settings, "auth_mode", "easyauth")
    client = TestClient(app, base_url="http://localhost")
    assert client.put("/api/admin/hub-settings", json={"show_demo_page_links": True}).status_code == 401
    assert client.post("/api/admin/login", json={"username": "admin", "password": "a-test-password"}).status_code == 200
    assert client.get("/api/admin/hub-settings").json()["show_demo_page_links"] is False
    assert client.put("/api/admin/hub-settings", json={"show_demo_page_links": True}).json()["show_demo_page_links"] is True


def test_page_only_demos_are_listed_by_default_and_can_be_switched_off(tmp_path):
    repo = repo_with(tmp_path, [folder_row(1, "Bobcat - IPL")],
                     [page_row("bobcat", "Bobcat - IPL", "Bobcat - IPL"),
                      page_row("lamborghini", "Lamborghini - IPL", None)], links=False)
    assert repo.hub_settings()["show_page_only_demos"] is True
    assert {a.id for a in repo.list(AssetQuery(limit=10)).items} == {"kit-1", "page-lamborghini"}
    repo.set_hub_settings("admin-session", show_page_only_demos=False)
    assert [a.id for a in repo.list(AssetQuery(limit=10)).items] == ["kit-1"]
    assert repo.get("page-lamborghini") is None
    assert "getpreview" in repo.get("kit-1").thumbnail_url, "a folder's demo keeps its page thumbnail"
    assert repo.hub_settings()["show_demo_page_links"] is False, "one switch never moves the other"


def test_a_page_with_no_folder_link_matches_the_folder_named_like_it(tmp_path):
    """Lamborghini IPL, 2026-10-06: the page links no files, the folder exists."""
    repo = repo_with(tmp_path, [folder_row(1, "Lamborghini - IPL")],
                     [page_row("lamborghini", "Lamborghini - IPL", None)])
    assert [a.id for a in repo.list(AssetQuery(limit=10)).items] == ["kit-1"]
    assert repo.get("kit-1").page_url.endswith("lamborghini.aspx")
