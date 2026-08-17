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
from backend.integrations.consensus import ConsensusError, ShareLink, StubConsensusClient
from backend.routers.consensus import get_client
from backend.tables import utcnow

# An asset that carries a Consensus UUID in the seed, and one that does not.
SHAREABLE = "eliminate-duplicate-parts-with-windchill-ai-parts-classifica"
NO_UUID = "attract-loop-subway-roadmap"


@pytest.fixture()
def client():
    """Always pins the stub.

    Without this, a developer's .env makes `get_consensus_client()` resolve to
    the real client and the suite starts calling production Consensus — slow,
    flaky, and it silently invalidates the fixed expectations below. Tests must
    never depend on ambient credentials.
    """
    # Must be a zero-arg lambda, not the class: FastAPI introspects the
    # callable's signature, and StubConsensusClient(demos=...) would be read
    # as a request parameter.
    app.dependency_overrides[get_client] = lambda: StubConsensusClient()
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
    assert body == {"configured": False, "mode": "stub"}


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

    assert body["summary"] == {"matched": 17, "proposals": 0, "conflicts": 0,
                               "ambiguous": 0, "portal_only": 11, "consensus_only": 2}
    # 17 matched + 11 portal-only accounts for all 28 seed assets.
    assert body["summary"]["matched"] + body["summary"]["portal_only"] == 28
    assert {d["uuid"] for d in body["consensus_only"]} == {"c0de-1111", "c0de-2222"}
    for entry in body["portal_only"]:
        assert set(entry) == {"asset_id", "title", "type"}


def test_reconcile_threshold_is_honoured(client):
    loose = client.get("/api/consensus/reconcile?threshold=0.1").json()
    strict = client.get("/api/consensus/reconcile?threshold=0.99").json()
    assert loose["summary"]["portal_only"] <= strict["summary"]["portal_only"]


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
