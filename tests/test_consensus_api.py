"""Router-level tests for the Consensus endpoints.

These exist because they were missing: a field rename (`demo.url` ->
`preview_link`) broke `/api/consensus/search` and `/reconcile` while the whole
suite stayed green, since nothing exercised the routers. Anything the HTTP
layer returns has to survive serialisation too, and that is what this covers.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import app
from backend.config import settings
from backend.deps import get_repo
from backend.integrations.consensus import (
    ConsensusDemo, ConsensusError, ShareLink, StubConsensusClient,
)
from backend.models import Asset, AssetType
from backend.repositories.json_repo import JsonAssetRepository
from backend.routers.consensus import get_client
from backend.tables import utcnow

SHAREABLE = "shareable-asset"
NO_UUID = "no-uuid-asset"
INTERNAL = "internal-asset"

#: Deliberately hermetic. These tests used to run against the app's real
#: catalogue, so regenerating the seed broke them for reasons unrelated to the
#: endpoints. The fixture below builds its own three-asset world instead.
FIXTURE_ASSETS = [
    Asset(id=SHAREABLE, type=AssetType.LDK, title="Windchill Overview",
          consensus_uuid="7a19-3c02", customer_facing=True),
    Asset(id=NO_UUID, type=AssetType.VDK, title="Attract Loop Subway Roadmap",
          consensus_uuid=None, customer_facing=True),
    Asset(id=INTERNAL, type=AssetType.LDK, title="Internal Only Kit",
          consensus_uuid="beef-0001", customer_facing=False),
]

FIXTURE_DEMOS = [
    ConsensusDemo(uuid="7a19-3c02", title="Windchill Overview", is_published=True,
                  preview_link="https://play.goconsensus.com/7a19-3c02"),
    ConsensusDemo(uuid="beef-0001", title="Internal Only Kit", is_published=True,
                  preview_link="https://play.goconsensus.com/beef-0001"),
    ConsensusDemo(uuid="c0de-1111", title="Registered In Consensus Only",
                  is_published=True),
]


@pytest.fixture(autouse=True)
def never_reach_a_real_tenant(monkeypatch):
    """Blank every Consensus credential for this module.

    A developer with a real .env would otherwise have these tests sync against
    production. The Graph suite already carries this guard; adding the V2 token
    to .env is what exposed its absence here.
    """
    for name in ("consensus_api_key", "consensus_api_secret",
                 "consensus_user_email", "consensus_v2_token",
                 "consensus_oauth_client_id", "consensus_oauth_client_secret"):
        monkeypatch.setattr(settings, name, None)


@pytest.fixture()
def repo(tmp_path):
    r = JsonAssetRepository(str(tmp_path))
    r.replace_source_rows(FIXTURE_ASSETS, "test")
    return r


@pytest.fixture()
def client(repo):
    """Always pins the stub.

    Without this, a developer's .env makes `get_consensus_client()` resolve to
    the real client and the suite starts calling production Consensus — slow,
    flaky, and it silently invalidates the fixed expectations below. Tests must
    never depend on ambient credentials.
    """
    # Must be zero-arg lambdas, not the classes: FastAPI introspects the
    # callable signature, and StubConsensusClient(demos=...) would be read as a
    # request parameter.
    app.dependency_overrides[get_client] = lambda: StubConsensusClient(list(FIXTURE_DEMOS))
    app.dependency_overrides[get_repo] = lambda: repo
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def override(fake):
    app.dependency_overrides[get_client] = lambda: fake


# ─────────────────────────────────────────────────────────────────── status
def test_status_reports_stub_mode(client):
    body = client.get("/api/consensus/status").json()
    assert body["configured"] is False and body["mode"] == "stub"


def test_status_reports_how_stale_the_index_is(client):
    """Nothing refreshes the mirror automatically, so "when was this last
    pulled" is the one question a stale catalogue cannot answer about itself.
    Never synced reads as null rather than being absent."""
    body = client.get("/api/consensus/status").json()
    assert body["source_system"] == "consensus"
    assert body["indexed"] == 0
    assert body["last_sync"] is None


def test_probe_works_without_credentials(client):
    body = client.get("/api/consensus/probe").json()
    assert body["mode"] == "stub" and body["configured"] is False


# ─────────────────────────────────────────────────────────────────── search
def test_search_serialises_every_field(client):
    """The regression that started this file: `preview_link`, not `url`."""
    response = client.get("/api/consensus/search?q=windchill")
    assert response.status_code == 200

    results = response.json()
    assert results, "the stub should match something for 'windchill'"
    for item in results:
        assert set(item) == {"uuid", "title", "description", "preview_link",
                             "is_published", "folder", "view_count"}
    assert any(i["preview_link"] for i in results)


def test_search_rejects_a_too_short_query(client):
    assert client.get("/api/consensus/search?q=a").status_code == 422


def test_search_surfaces_upstream_failure_as_502(client):
    class Broken(StubConsensusClient):
        def search(self, text, limit=10):
            raise ConsensusError("upstream exploded")

    override(Broken())
    response = client.get("/api/consensus/search?q=windchill")
    assert response.status_code == 502
    assert "upstream exploded" in response.json()["detail"]


# ──────────────────────────────────────────────────────────────── reconcile
def test_reconcile_returns_both_gap_directions(client):
    body = client.get("/api/consensus/reconcile").json()
    summary = body["summary"]

    # Two fixture assets carry a UUID present in Consensus; one carries none.
    assert summary["matched"] == 2
    assert summary["portal_only"] == 1
    assert summary["matched"] + summary["portal_only"] == len(FIXTURE_ASSETS)

    # The demo nothing points at is orphaned externally.
    assert {d["uuid"] for d in body["consensus_only"]} == {"c0de-1111"}
    assert [e["asset_id"] for e in body["portal_only"]] == [NO_UUID]
    for entry in body["portal_only"]:
        assert set(entry) == {"asset_id", "title", "type"}


def test_reconcile_threshold_is_honoured(client):
    loose = client.get("/api/consensus/reconcile?threshold=0.1").json()
    strict = client.get("/api/consensus/reconcile?threshold=0.99").json()
    assert loose["summary"]["portal_only"] <= strict["summary"]["portal_only"]


def test_share_is_blocked_for_an_internal_only_asset(client):
    response = client.post("/api/share/consensus",
                           json={"asset_id": INTERNAL, "organization": "Acme"})
    assert response.status_code == 409
    assert "internal-only" in response.json()["detail"]


def test_reconcile_rejects_out_of_range_threshold(client):
    assert client.get("/api/consensus/reconcile?threshold=2").status_code == 422


# ──────────────────────────────────────────────────────────────────── share
def test_share_requires_organization_for_a_trackable_board(client):
    """Consensus marks `organization` required on createsenddemo."""
    response = client.post("/api/share/consensus", json={"asset_id": SHAREABLE})
    assert response.status_code == 422
    assert "organization" in response.json()["detail"]


def test_share_creates_a_trackable_demoboard(client):
    response = client.post("/api/share/consensus", json={
        "asset_id": SHAREABLE, "organization": "Acme Robotics",
        "recipients": [{"email": "buyer@acme.com", "first_name": "John"}],
    })
    assert response.status_code == 200

    body = response.json()
    assert body["kind"] == "demoboard"
    assert body["asset_id"] == SHAREABLE
    assert body["demo_uuid"] and body["url"]
    assert [r["email"] for r in body["recipients"]] == ["buyer@acme.com"]


def test_untrackable_share_needs_no_organization(client):
    response = client.post("/api/share/consensus",
                           json={"asset_id": SHAREABLE, "trackable": False})
    assert response.status_code == 200
    assert response.json()["kind"] == "marketing"


def test_share_is_blocked_without_a_consensus_uuid(client):
    """Not a validation nicety — Consensus can only send registered content."""
    response = client.post("/api/share/consensus",
                           json={"asset_id": NO_UUID, "organization": "Acme"})
    assert response.status_code == 409
    assert "not registered in Consensus" in response.json()["detail"]


def test_share_404s_for_an_unknown_asset(client):
    response = client.post("/api/share/consensus",
                           json={"asset_id": "nope", "organization": "Acme"})
    assert response.status_code == 404


def test_share_maps_missing_schema_to_501_not_502(client):
    from backend.integrations.consensus import ConsensusSchemaUnknown

    class Unimplemented(StubConsensusClient):
        def create_share_link(self, *a, **kw):
            raise ConsensusSchemaUnknown("schema not available")

    override(Unimplemented())
    response = client.post("/api/share/consensus", json={
        "asset_id": SHAREABLE, "organization": "Acme"})
    assert response.status_code == 501, "a missing contract is not an upstream failure"


def test_share_maps_upstream_failure_to_502(client):
    class Broken(StubConsensusClient):
        def create_share_link(self, *a, **kw):
            raise ConsensusError("consensus down")

    override(Broken())
    response = client.post("/api/share/consensus", json={
        "asset_id": SHAREABLE, "organization": "Acme"})
    assert response.status_code == 502


def test_real_share_increments_the_counter(client):
    before = client.get(f"/api/assets/{SHAREABLE}").json()["stats"]["shares"]
    client.post("/api/share/consensus",
                json={"asset_id": SHAREABLE, "organization": "Acme"})
    after = client.get(f"/api/assets/{SHAREABLE}").json()["stats"]["shares"]
    assert after == before + 1


def test_test_sends_are_not_recorded_as_real_distribution(client):
    class TestSend(StubConsensusClient):
        def create_share_link(self, uuid, *a, **kw):
            return ShareLink(url="https://play.goconsensus.com/x", demo_uuid=uuid,
                             created_at=utcnow(), kind="demoboard", is_test=True)

    override(TestSend())
    before = client.get(f"/api/assets/{SHAREABLE}").json()["stats"]["shares"]
    response = client.post("/api/share/consensus", json={
        "asset_id": SHAREABLE, "organization": "Acme", "is_test": True})
    after = client.get(f"/api/assets/{SHAREABLE}").json()["stats"]["shares"]

    assert response.json()["is_test"] is True
    assert after == before, "a test send must not inflate real share counts"


def test_the_sync_endpoint_is_where_the_ui_expects_it(client):
    """It was registered at /api/sync for a while, because this router carries
    a bare /api prefix and every other route spells out /consensus/ itself. The
    debug page's button 404'd and nothing in the suite noticed."""
    response = client.post("/api/consensus/sync")

    assert response.status_code != 404, "the route must exist at this path"
    # 503 on the stub is the correct answer: reachable, but no credentials.
    assert response.status_code == 503
    assert "CONSENSUS_API_KEY" in response.json()["detail"]
