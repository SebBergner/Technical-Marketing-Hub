"""Graph endpoints through the HTTP layer.

These exist because of a specific past failure: a field rename broke two
endpoints while the service-level suite stayed green, since nothing exercised
the routers. Write-back is the last place that should be discovered that way,
so its wiring — auth, status codes, the dry-run default — is pinned here.
"""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app import app
from backend.auth import AuthMode
from backend.config import settings
from backend.deps import get_repo
from backend.models import (
    Asset, AssetResource, AssetType, MetadataProposal, ProposalOrigin, ProposalState,
)
from backend.repositories.json_repo import JsonAssetRepository
from backend.routers.graph import require_client
from tests.test_auth import CURATOR_GROUP, easyauth_headers
from tests.test_graph_writeback import (
    DRIVE_ID, ITEM_ID, SITE_ID, SITE_URL, UUID, client_for, make_handler,
)


@pytest.fixture(autouse=True)
def never_reach_a_real_tenant(monkeypatch):
    """Blank the Graph credentials for every test in this module.

    Without this, a developer with a real .env would have the "not configured"
    test resolve a live site and the write tests PATCH production SharePoint.
    The Consensus suite already learned this the expensive way. Tests that need
    a client override `require_client` with a MockTransport one instead.
    """
    for name in ("graph_tenant_id", "graph_client_id",
                 "graph_client_secret", "graph_site_url"):
        monkeypatch.setattr(settings, name, "")


@pytest.fixture()
def repo(tmp_path):
    store = JsonAssetRepository(str(tmp_path))
    store.replace_source_rows(
        [Asset(id="a-kit", type=AssetType.LDK, title="A Kit", source_item_id=ITEM_ID)],
        "sharepoint")
    store.save_proposals([MetadataProposal(
        asset_id="a-kit", field="consensus_uuid", proposed_value=UUID,
        confidence=0.9, origin=ProposalOrigin.CONSENSUS)])
    store.decide_proposal("a-kit", "consensus_uuid",
                          ProposalState.ACCEPTED.value, "elio@ptc.com")
    return store


@pytest.fixture()
def client(repo):
    app.dependency_overrides[get_repo] = lambda: repo
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def with_graph(handler):
    app.dependency_overrides[require_client] = lambda: client_for(handler)


@pytest.fixture()
def enforcing(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "auth_curator_groups", CURATOR_GROUP)


# ════════════════════════════════ the backlog ══════════════════════════════
def test_backlog_needs_no_credentials(client):
    """Usable today, before IT delivers anything — it answers "how much is
    waiting" without touching Graph."""
    body = client.get("/api/graph/writeback/backlog").json()
    assert body["accepted_awaiting_writeback"] == 1
    assert body["writable_now"] == 1
    assert body["fields"] == ["consensus_uuid"]


# ═══════════════════════════════ without Graph ═════════════════════════════
def test_writeback_reports_that_graph_is_not_configured(client):
    """503 with the setting names, not a stack trace — this is the state the
    project is actually in while the IT ticket is open."""
    response = client.post("/api/graph/writeback")
    assert response.status_code == 503
    assert "GRAPH_TENANT_ID" in response.json()["detail"]


# ═════════════════════════════════ dry run ═════════════════════════════════
def test_the_endpoint_defaults_to_a_dry_run(client):
    handler, seen = make_handler()
    with_graph(handler)

    body = client.post("/api/graph/writeback").json()

    assert body["dry_run"] is True
    assert body["counts"] == {"would_write": 1}
    assert "body" not in seen, "the default must not write to SharePoint"


def test_writing_requires_saying_so_explicitly(client):
    handler, seen = make_handler()
    with_graph(handler)

    body = client.post("/api/graph/writeback?dry_run=false").json()

    assert body["dry_run"] is False
    assert body["counts"] == {"written": 1}
    assert seen["body"] == {"ConsensusUUID": UUID}


def test_conflicts_are_surfaced_at_the_top_of_the_response(client):
    """A reviewer must not have to scan fifty rows to find the one that needs
    a decision."""
    with_graph(make_handler(current="typed-by-hand")[0])

    body = client.post("/api/graph/writeback?dry_run=false").json()

    assert body["counts"] == {"conflict": 1}
    assert len(body["conflicts"]) == 1
    assert body["conflicts"][0]["current_value"] == "typed-by-hand"


# ══════════════════════════════ setup failures ═════════════════════════════
def test_a_missing_column_is_409_not_a_run_full_of_failures(client):
    with_graph(make_handler(columns=("Title",))[0])

    response = client.post("/api/graph/writeback?dry_run=false")

    assert response.status_code == 409
    assert "ConsensusUUID" in response.json()["detail"]


def test_a_read_only_grant_is_409_naming_what_to_ask_it_for(client):
    with_graph(make_handler(patch_status=403)[0])

    response = client.post("/api/graph/writeback?dry_run=false")

    assert response.status_code == 409
    assert "read-only" in response.json()["detail"]


# ═══════════════════════════════════ auth ══════════════════════════════════
def test_anonymous_cannot_write_back(client, enforcing):
    with_graph(make_handler()[0])
    assert client.post("/api/graph/writeback?dry_run=false").status_code == 401


def test_a_viewer_cannot_write_back(client, enforcing):
    """Write-back changes a corporate system of record. Being signed in is not
    enough — this is the sharpest case for the curator role existing."""
    handler, seen = make_handler()
    with_graph(handler)

    response = client.post("/api/graph/writeback?dry_run=false",
                           headers=easyauth_headers("viewer@ptc.com"))

    assert response.status_code == 403
    assert "body" not in seen


def test_a_curator_can_write_back(client, enforcing):
    handler, _ = make_handler()
    with_graph(handler)

    response = client.post("/api/graph/writeback?dry_run=false",
                           headers=easyauth_headers("curator@ptc.com",
                                                    groups=(CURATOR_GROUP,)))

    assert response.status_code == 200
    assert response.json()["counts"] == {"written": 1}


def test_the_audit_trail_names_the_curator_who_ran_it(client, repo, enforcing):
    with_graph(make_handler()[0])

    client.post("/api/graph/writeback?dry_run=false",
                headers=easyauth_headers("curator@ptc.com", groups=(CURATOR_GROUP,)))

    entry = repo.metadata_edits()[0]
    assert "elio@ptc.com" in entry["changed_by"], "who accepted the value"
    assert "curator@ptc.com" in entry["changed_by"], "who pushed it"


# ═══════════════════════════════ file download ═════════════════════════════
# Lives here rather than a dedicated assets-router file because it reuses the
# same Graph-mocking infrastructure as the tests above -- SITE_ID, DRIVE_ID,
# client_for -- even though the route itself hangs off /api/assets.

FILE_ITEM_ID = "01FILEXXXXXXXXXXXXXX"


def download_handler(*, download_url="https://contoso.sharepoint.com/signed?x=1"):
    """Answers exactly the three calls download_file() makes: resolve the
    site, find the Demo Catalog drive, then get_item() for the download URL."""
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if ":/sites/" in path or path.endswith(f"/sites/{SITE_URL.split('/sites/')[1]}"):
            return httpx.Response(200, json={
                "id": SITE_ID, "displayName": "EXT-TDD", "webUrl": SITE_URL})
        if path.endswith(f"/sites/{SITE_ID}/drives"):
            return httpx.Response(200, json={
                "value": [{"id": DRIVE_ID, "name": "Demo Catalog"}]})
        if path.endswith(f"/drives/{DRIVE_ID}/items/{FILE_ITEM_ID}"):
            return httpx.Response(200, json={
                "id": FILE_ITEM_ID, "name": "Overview.mp4",
                "@microsoft.graph.downloadUrl": download_url})
        return httpx.Response(404, json={"error": {"message": f"unexpected {path}"}})
    return handler


@pytest.fixture()
def repo_with_a_file(repo):
    """The shared `repo` fixture again, but with one downloadable resource
    added to "a-kit" -- a fresh replace_source_rows() call, not a mutation, so
    it stays isolated to the tests that ask for it."""
    repo.replace_source_rows([Asset(
        id="a-kit", type=AssetType.LDK, title="A Kit", source_item_id=ITEM_ID,
        resources=[AssetResource(name="Overview.mp4", kind="video",
                                 item_id=FILE_ITEM_ID)],
    )], "sharepoint")
    return repo


def test_a_listed_file_redirects_to_a_fresh_signed_url(client, repo_with_a_file):
    with_graph(download_handler())

    response = client.get(f"/api/assets/a-kit/files/{FILE_ITEM_ID}/download",
                          follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "https://contoso.sharepoint.com/signed?x=1"


def test_an_item_id_not_on_this_asset_is_refused(client, repo_with_a_file):
    """The point of checking membership at all: Graph would resolve any valid
    id in the drive regardless of which asset it is nominally under."""
    with_graph(download_handler())

    response = client.get("/api/assets/a-kit/files/not-a-real-item/download",
                          follow_redirects=False)

    assert response.status_code == 404


def test_download_of_an_unknown_asset_is_404(client, repo_with_a_file):
    with_graph(download_handler())

    response = client.get(f"/api/assets/no-such-asset/files/{FILE_ITEM_ID}/download")

    assert response.status_code == 404


def test_download_without_graph_configured_is_503(client, repo_with_a_file):
    response = client.get(f"/api/assets/a-kit/files/{FILE_ITEM_ID}/download")
    assert response.status_code == 503


# ════════════════════════════════ file preview ═════════════════════════════
def preview_handler(*, preview_url="https://contoso.sharepoint.com/embed?x=1"):
    """Answers exactly what preview_file() calls: resolve the site, find the
    Demo Catalog drive, then POST .../preview for the embeddable viewer URL --
    a POST, unlike download_file()'s GET on the item itself."""
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if ":/sites/" in path or path.endswith(f"/sites/{SITE_URL.split('/sites/')[1]}"):
            return httpx.Response(200, json={
                "id": SITE_ID, "displayName": "EXT-TDD", "webUrl": SITE_URL})
        if path.endswith(f"/sites/{SITE_ID}/drives"):
            return httpx.Response(200, json={
                "value": [{"id": DRIVE_ID, "name": "Demo Catalog"}]})
        if request.method == "POST" and path.endswith(
                f"/drives/{DRIVE_ID}/items/{FILE_ITEM_ID}/preview"):
            return httpx.Response(200, json={"getUrl": preview_url, "postUrl": None})
        return httpx.Response(404, json={"error": {"message": f"unexpected {path}"}})
    return handler


def test_a_listed_file_previews_via_a_fresh_embed_url(client, repo_with_a_file):
    with_graph(preview_handler())

    response = client.get(f"/api/assets/a-kit/files/{FILE_ITEM_ID}/preview",
                          follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "https://contoso.sharepoint.com/embed?x=1"


def test_preview_of_an_item_id_not_on_this_asset_is_refused(client, repo_with_a_file):
    with_graph(preview_handler())

    response = client.get("/api/assets/a-kit/files/not-a-real-item/preview",
                          follow_redirects=False)

    assert response.status_code == 404


def test_preview_of_an_unknown_asset_is_404(client, repo_with_a_file):
    with_graph(preview_handler())

    response = client.get(f"/api/assets/no-such-asset/files/{FILE_ITEM_ID}/preview")

    assert response.status_code == 404


def test_preview_without_graph_configured_is_503(client, repo_with_a_file):
    response = client.get(f"/api/assets/a-kit/files/{FILE_ITEM_ID}/preview")
    assert response.status_code == 503
