"""The /migration page and its read-only API.

Pinned here: the page is behind the same admin sign-in as /admin; the status
call never writes (GET only, whatever Graph answers); and the manager's
figures are counted the way the Hub itself will count the library, through
the sync's own mapping.
"""
from __future__ import annotations

import json
import os

import httpx
import pytest
from fastapi.testclient import TestClient

from app import app
from backend.auth import AuthMode
from backend.config import settings
from backend.integrations.graph.client import GraphClient
from backend.routers.migration import graph_client_or_none
from backend.services import brightcove_migration as bc

ADMIN_USER, ADMIN_PASS = "tddadmin", "a-long-test-password-8e1f"
SITE_URL = "https://ptccloud.sharepoint.com/sites/EXT-TDD"
SITE_ID = "ptccloud.sharepoint.com,guid-1,guid-2"
DRIVE = "drive-gb"
ROOT = f"/drives/{DRIVE}/root:"


@pytest.fixture(autouse=True)
def no_real_tenant_or_data(monkeypatch, tmp_path):
    """Blank Graph credentials and point data_dir at a temp folder, so no
    test here can read a developer's real tenant or real run logs."""
    for name in ("graph_tenant_id", "graph_client_id", "graph_client_secret"):
        monkeypatch.setattr(settings, name, "")
    monkeypatch.setattr(settings, "graph_site_url", SITE_URL)
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    # As deployed: identity is enforced. (Disabled mode hands out a local
    # principal with the curator role, which would open everything here.)
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "auth_curator_groups", "")
    monkeypatch.setattr(settings, "migration_brightcove_library", "Gallery_Brightcove")


@pytest.fixture()
def admin(monkeypatch):
    monkeypatch.setattr(settings, "admin_username", ADMIN_USER)
    monkeypatch.setattr(settings, "admin_password", ADMIN_PASS)


@pytest.fixture()
def client():
    try:
        # Loopback, as in test_auth.py: the admin cookie is Secure elsewhere.
        with TestClient(app, base_url="http://localhost") as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def sign_in(client):
    assert client.post("/api/admin/login",
                       json={"username": ADMIN_USER, "password": ADMIN_PASS}).status_code == 200


def demo(name, created="2026-10-01T15:00:00Z", **fields):
    columns = {"Demo_x0020_Type": "Video", "Segment": ["PLM"],
               "Product": [{"Label": "Creo Parametric", "TermGuid": "g1"}], **fields}
    return {"id": f"id-{name}", "name": name, "folder": {"childCount": 1},
            "createdDateTime": created, "lastModifiedDateTime": created,
            "webUrl": f"{SITE_URL}/Gallery_Brightcove/{name}",
            "parentReference": {"path": ROOT}, "listItem": {"fields": columns}}


def video(name, folder, size=1_000_000_000, millis=60_000):
    return {"id": f"file-{name}", "name": name, "file": {"mimeType": "video/mp4"},
            "size": size, "video": {"duration": millis},
            "parentReference": {"path": f"{ROOT}/{folder}"}}


# ─────────────────────────────────────────────────────────────── the summary
def test_the_summary_counts_what_the_hub_will_count():
    items = [
        demo("A", OriginalPublishDate="2019-05-14T00:00:00Z", Segment=["PLM", "CAD"],
             Customer_x0020_Facing=False),
        video("A.mp4", "A", millis=483_000),
        demo("B", created="2026-10-08T09:00:00Z", Segment=["CAD"],
             Product=[{"Label": "Windchill PDMLink", "TermGuid": "g2"},
                      {"Label": "Creo Parametric", "TermGuid": "g1"}]),
        video("B.mp4", "B", size=500_000_000),
        # a folder nobody has finished: no Demo Type, so not a demo
        {**demo("Half done"), "listItem": {"fields": {}}},
    ]
    s = bc.summarize(items)

    assert s["demos"] == 2
    assert s["incomplete_folders"] == 1
    assert s["internal_only"] == 1
    assert s["size_bytes"] == 1_500_000_000
    assert s["runtime_seconds"] == 483 + 60
    assert (s["first_migrated"], s["last_migrated"]) == ("2026-10-01", "2026-10-08")
    assert s["by_week"] == [{"week_start": "2026-09-28", "count": 1},
                            {"week_start": "2026-10-05", "count": 1}]
    # a demo counts once in each of its segments / products: shares of demos
    assert {r["name"]: r["count"] for r in s["segments"]} == {"CAD": 2, "PLM": 1}
    assert {r["name"]: r["percent"] for r in s["products"]} == {
        "Creo Parametric": 100.0, "Windchill PDMLink": 50.0}
    assert s["recent"][0]["title"] == "B"


def test_products_are_counted_from_hub_products_when_the_library_has_them():
    """Measured 2026-09-29: counting the managed-metadata Product showed only
    "Codebeamer" for a video tagged Windchill, Codebeamer and Creo, because
    Windchill and Creo are no Product terms."""
    s = bc.summarize([demo("A", HubProducts=["Windchill", "Codebeamer", "Creo"],
                           Product=[{"Label": "Codebeamer", "TermGuid": "g"}])])
    assert {r["name"] for r in s["products"]} == {"Windchill", "Codebeamer", "Creo"}
    assert s["recent"][0]["products"] == ["Windchill", "Codebeamer", "Creo"]


def test_publish_year_comes_from_the_column_never_the_folder_date():
    """uploaded_at falls back to the folder date; a publish-year chart built
    on it would call every undated video 'published on migration day'."""
    s = bc.summarize([demo("Dated", OriginalPublishDate="2015-01-02T00:00:00Z"),
                      demo("Undated")])
    assert s["by_publish_year"] == [{"year": 2015, "count": 1}, {"year": None, "count": 1}]


def test_the_product_tail_folds_into_other():
    items = [demo(f"D{i}", Product=[{"Label": f"P{i}", "TermGuid": f"g{i}"}])
             for i in range(bc.TOP_PRODUCTS + 3)]
    names = [r["name"] for r in bc.summarize(items)["products"]]
    assert len(names) == bc.TOP_PRODUCTS + 1
    assert names[-1] == "Other"


# ─────────────────────────────────────────────────────────────── access
def test_the_page_is_served(client):
    response = client.get("/migration")
    assert response.status_code == 200
    assert "<title>Migration" in response.text
    # A cached copy outlived a change to this page once; it must revalidate.
    assert response.headers["cache-control"] == "no-cache"


def test_nobody_signed_in_gets_nothing(client, monkeypatch):
    """Neither an admin sign-in nor an SSO curator: refused, whether or not
    an admin account exists on this deployment."""
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password", "")
    assert client.get("/api/migration/brightcove/status").status_code == 401


def test_the_status_needs_the_admin_sign_in(admin, client):
    assert client.get("/api/migration/brightcove/status").status_code == 401
    sign_in(client)
    assert client.get("/api/migration/brightcove/status").status_code == 200
    client.post("/api/admin/logout")
    assert client.get("/api/migration/brightcove/status").status_code == 401


def test_without_graph_the_page_says_so_instead_of_failing(admin, client):
    sign_in(client)
    body = client.get("/api/migration/brightcove/status").json()
    assert body["graph"]["configured"] is False
    assert body["summary"] is None
    assert body["plan"] == {"total": None}


# ─────────────────────────────────────────── the live read, through Graph
def graph_serving(items: list[dict] | None, seen: list):
    """A MockTransport Graph with one library, or none when items is None."""
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.method)
        path = request.url.path
        if path.endswith("/drives"):
            drives = [] if items is None else [{"id": DRIVE, "name": "Gallery_Brightcove"}]
            return httpx.Response(200, json={"value": drives})
        if path.endswith(f"/drives/{DRIVE}/root/delta"):
            bare = [{k: v for k, v in i.items() if k != "listItem"} for i in items]
            return httpx.Response(200, json={"value": bare,
                                             "@odata.deltaLink": "https://x/delta?token=t"})
        if path.endswith(f"/drives/{DRIVE}/root/children"):
            return httpx.Response(200, json={"value": [i for i in items if "folder" in i]})
        if "/sites/" in path:
            return httpx.Response(200, json={"id": SITE_ID, "webUrl": SITE_URL})
        return httpx.Response(404)

    return GraphClient(tenant_id="t", client_id="c", client_secret="s", site_url=SITE_URL,
                       transport=httpx.MockTransport(handler), token_provider=lambda: "x.e30.sig")


def test_the_status_reads_the_library_and_never_writes(admin, client):
    seen: list[str] = []
    items = [demo("A"), video("A.mp4", "A")]
    app.dependency_overrides[graph_client_or_none] = lambda: graph_serving(items, seen)
    sign_in(client)

    body = client.get("/api/migration/brightcove/status").json()
    assert body["library"] == {"name": "Gallery_Brightcove", "found": True}
    assert body["summary"]["demos"] == 1
    assert set(seen) == {"GET"}, "the status call must never write"


def test_a_missing_library_is_reported_not_raised(admin, client):
    app.dependency_overrides[graph_client_or_none] = lambda: graph_serving(None, [])
    sign_in(client)

    body = client.get("/api/migration/brightcove/status").json()
    assert body["library"] == {"name": "Gallery_Brightcove", "found": False}
    assert body["summary"] is None


# ─────────────────────────────────────────────────────────────── runs
def write_run(bid, **data):
    folder = bc.batches_dir()
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, f"{bid}.json"), "w", encoding="utf-8") as fh:
        json.dump({"batch_id": bid, **data}, fh)


def test_runs_are_listed_newest_first_and_a_broken_log_is_not_hidden(admin, client):
    write_run("b1", mode="dry-run", started_at="2026-09-28T10:00:00", counts={"new": 3},
              library="Gallery_Brightcove")
    write_run("b2", mode="upload", started_at="2026-09-28T11:00:00", planned=476,
              library="Gallery_Brightcove")
    # a run against the test library must not reach the production dashboard
    write_run("t1", mode="upload", started_at="2026-09-28T12:00:00", planned=2,
              library="Gallery_Brightcove_Test")
    with open(os.path.join(bc.batches_dir(), "broken.json"), "w", encoding="utf-8") as fh:
        fh.write("{not json")
    sign_in(client)

    body = client.get("/api/migration/brightcove/status").json()
    assert [b["batch_id"] for b in body["batches"] if "unreadable" not in b] == ["b2", "b1"]
    assert any(b["batch_id"] == "broken" and b.get("unreadable") for b in body["batches"])
    assert body["plan"] == {"total": 476}
