"""What is reachable but not listed: older VM versions and "Release Notes".

Both rules came from the VM owners (2026-09-25): sellers should meet the VM
to use today, not every image ever made of it, and a Release Notes folder is
documentation rather than a demo. Neither record is removed -- a VM page
links the release notes' PDFs, and an older VM is one click from the newest.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import app
from backend.deps import get_repo
from backend.integrations.graph.vm_pages import (
    Catalogue, build_vm_assets, version_line,
)
from backend.models import Asset
from backend.repositories.base import AssetQuery
from backend.repositories.json_repo import JsonAssetRepository
from backend.services import listing

SITE = "https://ptccloud.sharepoint.com/sites/EXT-TDD/SitePages/Virtual%20Machines/"


def page(pid: str, title: str, modified: str = "2026-01-01T00:00:00Z") -> dict:
    return {"id": pid, "title": title, "lastModifiedDateTime": modified,
            "webUrl": SITE + pid + ".aspx"}


def vms(*pages):
    assets, _, result = build_vm_assets(list(pages), {}, {}, Catalogue.build([]))
    return {a.title: a for a in assets}, result


# ─────────────────────────────────────────────────────── which VM is which
@pytest.mark.parametrize("title, line, version", [
    ("Windchill 13.1.4.1 - Virtual Machine", "windchill", (13, 1, 4, 1)),
    ("Windchill 11.1 M020-CPS08 - Virtual Machine", "windchill", (11, 1)),
    ("Windchill 13.1.2.0 v.1.0 - Virtual Machine", "windchill", (13, 1, 2, 0)),
    ("ALM (CB 3.3.0 RVS 13.5 Modeler 10.3 PV 7.3.0) - Virtual Machine", "alm cb", (3, 3, 0)),
    ("ALM Pure Variants 7.3.0 v.1.0 - Virtual Machine", "alm pure variants", (7, 3, 0)),
    ("Arbortext Content Delivery (ACD) 7.2.1 with Snowmobile Demo Data",
     "arbortext content delivery acd", (7, 2, 1)),
])
def test_a_title_names_its_line_and_version(title, line, version):
    assert version_line(title) == (line, version)


def test_a_title_without_a_version_is_a_line_of_its_own():
    assert version_line("3rd Party CAD - PTC ONLY - Virtual Machine") is None


def test_the_newest_version_supersedes_the_rest_by_number_not_by_date():
    found, result = vms(
        page("a", "Windchill 13.1.4.1 - Virtual Machine", "2024-01-01T00:00:00Z"),
        page("b", "Windchill 12.1.2.6 - Virtual Machine", "2026-09-01T00:00:00Z"),
        page("c", "Windchill 11.1 M020-CPS08 - Virtual Machine", "2025-01-01T00:00:00Z"),
        page("d", "ALM (CB 3.0.0 RVS 13.2) - Virtual Machine"),
        page("e", "ALM (CB 3.3.0 RVS 13.5) - Virtual Machine"),
        page("f", "ALM Pure Variants 7.3.0 v.1.0 - Virtual Machine"),
        page("g", "3rd Party CAD - PTC ONLY - Virtual Machine"),
    )
    newest = found["Windchill 13.1.4.1 - Virtual Machine"]
    assert newest.vm.superseded_by is None
    assert found["Windchill 12.1.2.6 - Virtual Machine"].vm.superseded_by == newest.id
    assert found["Windchill 11.1 M020-CPS08 - Virtual Machine"].vm.superseded_by == newest.id
    assert [v.version for v in newest.vm.other_versions] == ["12.1.2.6", "11.1"]
    alm = found["ALM (CB 3.3.0 RVS 13.5) - Virtual Machine"]
    assert found["ALM (CB 3.0.0 RVS 13.2) - Virtual Machine"].vm.superseded_by == alm.id
    # A different VM that happens to share a word stays its own line.
    assert found["ALM Pure Variants 7.3.0 v.1.0 - Virtual Machine"].vm.superseded_by is None
    assert found["3rd Party CAD - PTC ONLY - Virtual Machine"].vm.superseded_by is None
    assert result.superseded == 3


def test_a_divested_vm_never_supersedes_a_visible_one():
    # The Hub never shows it, so it must not hide the version people can see.
    found, _ = vms(page("a", "ThingWorx Foundation 10.0 (PostgreSQL)"),
                   page("b", "ThingWorx Foundation 9.7 (PostgreSQL)"))
    assert all(a.vm.superseded_by is None for a in found.values())


# ──────────────────────────────────────────────────────────── in listings
@pytest.fixture
def repo(tmp_path):
    store = JsonAssetRepository(str(tmp_path))
    store.replace_source_rows([
        Asset(id="release-notes", type="ldk", source="sharepoint", title="Release Notes",
              resources=[{"name": "ACD 7.2.1.pdf", "item_id": "ITEM-1", "kind": "document"}]),
        Asset(id="windchill-release-notes-ldk", type="ldk", source="sharepoint",
              title="Windchill 13 Release Notes LDK"),
        Asset(id="creo-ldk", type="ldk", source="sharepoint", title="Creo LDK"),
    ], "sharepoint")
    found, _ = vms(page("new", "Windchill 13.1.4.1 - Virtual Machine"),
                   page("old", "Windchill 12.1.2.6 - Virtual Machine"))
    store.replace_source_rows(list(found.values()), "vm_pages")
    return store


def ids(page):
    return {a.id for a in page.items}


def test_listings_leave_out_older_vms_and_release_notes(repo):
    listed = ids(repo.list(AssetQuery()))
    assert listed == {"creo-ldk", "windchill-release-notes-ldk",
                      "vm-windchill-13-1-4-1-virtual-machine"}


def test_only_the_exact_title_release_notes_is_left_out(repo):
    assert listing.is_unlisted_title("  release   NOTES ")
    assert "windchill-release-notes-ldk" in ids(repo.list(AssetQuery(text="release notes")))
    assert "release-notes" not in ids(repo.list(AssetQuery(text="release notes")))


def test_older_vms_can_be_asked_for(repo):
    listed = ids(repo.list(AssetQuery(types=["vm"], include_older_vms=True)))
    assert listed == {"vm-windchill-13-1-4-1-virtual-machine",
                      "vm-windchill-12-1-2-6-virtual-machine"}


def test_counts_agree_with_what_is_listed(repo):
    types = {f.value: f.count for f in repo.facets().types}
    assert types["vm"] == 1
    assert repo.facets().total == 3
    both = repo.facets(AssetQuery(include_older_vms=True))
    assert {f.value: f.count for f in both.types}["vm"] == 2


def test_both_stay_reachable_by_id(repo):
    old = repo.get("vm-windchill-12-1-2-6-virtual-machine")
    assert old.vm.superseded_by == "vm-windchill-13-1-4-1-virtual-machine"
    notes = repo.get("release-notes")
    assert notes.resources[0].item_id == "ITEM-1"      # VM pages preview its PDFs


def test_the_api_takes_the_flag(repo):
    app.dependency_overrides[get_repo] = lambda: repo
    try:
        client = TestClient(app)
        plain = client.get("/api/assets", params={"type": "vm"}).json()
        older = client.get("/api/assets", params={"type": "vm", "include_older_vms": "true"}).json()
        facets = client.get("/api/taxonomy", params={"include_older_vms": "true"}).json()
    finally:
        app.dependency_overrides.pop(get_repo, None)
    assert (plain["total"], older["total"]) == (1, 2)
    assert {f["value"]: f["count"] for f in facets["types"]}["vm"] == 2
