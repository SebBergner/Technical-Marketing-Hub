"""Authentication and authorisation.

Easy Auth delivers identity as HTTP headers, which means the failure mode to
guard against is not "login is broken" but "someone set the header themselves".
Most of these tests exist for that.
"""
from __future__ import annotations

import base64
import json

import pytest
from fastapi.testclient import TestClient

from app import app
from backend.auth import (
    APP_SERVICE_MARKER, AuthMode, Role, security_warnings,
)
from backend.config import settings
from backend.deps import get_repo
from backend.integrations.consensus import StubConsensusClient
from backend.models import Asset, AssetType
from backend.repositories.json_repo import JsonAssetRepository
from backend.routers.curation import get_client

CURATOR_GROUP = "11111111-2222-3333-4444-555555555555"


def principal_header(email="user@ptc.com", roles=(), groups=()) -> str:
    claims = [{"typ": "name", "val": email}]
    claims += [{"typ": "roles", "val": r} for r in roles]
    claims += [{"typ": "groups", "val": g} for g in groups]
    payload = {"auth_typ": "aad", "name": email, "claims": claims}
    return base64.b64encode(json.dumps(payload).encode()).decode()


def easyauth_headers(email="user@ptc.com", roles=(), groups=()) -> dict:
    return {
        "X-MS-CLIENT-PRINCIPAL-NAME": email,
        "X-MS-CLIENT-PRINCIPAL-ID": "oid-123",
        "X-MS-CLIENT-PRINCIPAL-IDP": "aad",
        "X-MS-CLIENT-PRINCIPAL": principal_header(email, roles, groups),
    }


@pytest.fixture()
def enforcing(monkeypatch):
    """Behave as if deployed behind App Service Easy Auth."""
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "auth_curator_groups", CURATOR_GROUP)


@pytest.fixture()
def disabled(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", AuthMode.DISABLED.value)
    monkeypatch.setattr(settings, "auth_curator_groups", "")


@pytest.fixture()
def client(tmp_path):
    store = JsonAssetRepository(str(tmp_path))
    store.replace_source_rows(
        [Asset(id="a1", type=AssetType.LDK, title="A Kit")], "test")
    app.dependency_overrides[get_repo] = lambda: store
    app.dependency_overrides[get_client] = lambda: StubConsensusClient([])
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


# ════════════════════════════ the spoofing question ════════════════════════
def test_headers_are_ignored_when_auth_is_disabled(disabled, client):
    """A forged header must not grant anything on a machine where auth was
    never switched on. Believing it there is the whole vulnerability."""
    body = client.get("/api/auth/me",
                      headers=easyauth_headers("attacker@evil.com",
                                               groups=(CURATOR_GROUP,))).json()

    assert body["user"]["email"] == "dev@localhost", \
        "the forged identity must not be adopted"
    assert body["user"]["is_authenticated"] is False
    assert body["user"]["is_dev_principal"] is True
    assert body["enforcing"] is False


def test_no_headers_while_enforcing_is_anonymous(enforcing, client):
    body = client.get("/api/auth/me").json()
    assert body["user"]["is_authenticated"] is False
    assert body["user"]["roles"] == []
    assert body["enforcing"] is True


def test_write_endpoints_refuse_an_anonymous_caller(enforcing, client):
    """With enforcement on and no principal, nothing that writes may proceed."""
    assert client.post("/api/curation/propose").status_code == 401
    assert client.post("/api/graph/sync").status_code in (401, 503)
    assert client.post("/api/share/consensus",
                       json={"asset_id": "a1", "organization": "Acme"}).status_code == 401


# ════════════════════════════ identity parsing ═════════════════════════════
def test_principal_is_read_from_the_headers(enforcing, client):
    body = client.get("/api/auth/me", headers=easyauth_headers("liwchen@ptc.com")).json()
    user = body["user"]
    assert user["email"] == "liwchen@ptc.com"
    assert user["object_id"] == "oid-123"
    assert user["provider"] == "aad"
    assert user["is_authenticated"] is True
    assert user["is_dev_principal"] is False


def test_authenticated_user_is_a_viewer_but_not_a_curator(enforcing, client):
    """Fails closed: being signed in is not being allowed to curate."""
    user = client.get("/api/auth/me",
                      headers=easyauth_headers("someone@ptc.com")).json()["user"]
    assert user["roles"] == [Role.VIEWER.value]
    assert user["can_curate"] is False


def test_configured_group_grants_curator(enforcing, client):
    user = client.get("/api/auth/me",
                      headers=easyauth_headers(groups=(CURATOR_GROUP,))).json()["user"]
    assert user["can_curate"] is True
    assert set(user["roles"]) == {Role.VIEWER.value, Role.CURATOR.value}


def test_an_unrelated_group_grants_nothing(enforcing, client):
    user = client.get("/api/auth/me",
                      headers=easyauth_headers(groups=("some-other-group",))).json()["user"]
    assert user["can_curate"] is False


def test_an_app_role_named_curator_also_works(enforcing, client):
    """So the app registration can use app roles instead of group object ids."""
    user = client.get("/api/auth/me",
                      headers=easyauth_headers(roles=("curator",))).json()["user"]
    assert user["can_curate"] is True


def test_a_corrupt_principal_blob_degrades_to_viewer(enforcing, client):
    """Undecodable claims must not crash the request, and must not escalate."""
    headers = easyauth_headers()
    headers["X-MS-CLIENT-PRINCIPAL"] = "!!!not-base64!!!"
    user = client.get("/api/auth/me", headers=headers).json()["user"]
    assert user["is_authenticated"] is True
    assert user["can_curate"] is False


# ══════════════════════════════ enforcement ════════════════════════════════
def test_viewer_may_share_but_not_curate(enforcing, client):
    viewer = easyauth_headers("viewer@ptc.com")
    assert client.post("/api/curation/propose", headers=viewer).status_code == 403
    # Sharing needs only authentication; 409 here means it got past auth and
    # failed on the asset having no Consensus UUID, which is correct.
    assert client.post("/api/share/consensus", headers=viewer,
                       json={"asset_id": "a1", "organization": "Acme"}).status_code == 409


def test_curator_may_curate(enforcing, client):
    curator = easyauth_headers("curator@ptc.com", groups=(CURATOR_GROUP,))
    assert client.post("/api/curation/propose", headers=curator).status_code == 200


def test_forbidden_message_says_how_to_get_access(enforcing, client):
    response = client.post("/api/curation/propose",
                           headers=easyauth_headers("viewer@ptc.com"))
    assert "AUTH_CURATOR_GROUPS" in response.json()["detail"]


def test_reads_stay_open_to_the_platform_gate(enforcing, client):
    """Easy Auth blocks unauthenticated requests before they reach us, so read
    endpoints are not separately gated — double-gating would only produce
    confusing 401s behind a working sign-in."""
    assert client.get("/api/assets?limit=1").status_code == 200
    assert client.get("/api/taxonomy").status_code == 200


# ═════════════════════════ misconfiguration warnings ═══════════════════════
def test_warns_when_deployed_on_app_service_with_auth_off(disabled, monkeypatch):
    """The dangerous deploy: AUTH_MODE never set, so everyone is a curator."""
    monkeypatch.setenv(APP_SERVICE_MARKER, "technical-marketing-hub")
    warnings = security_warnings()
    assert any("AUTH IS DISABLED ON APP SERVICE" in w for w in warnings)


def test_warns_when_graph_write_is_live_but_auth_is_off(disabled, monkeypatch):
    monkeypatch.setenv(APP_SERVICE_MARKER, "technical-marketing-hub")
    monkeypatch.setattr(settings, "graph_tenant_id", "t")
    monkeypatch.setattr(settings, "graph_client_id", "c")
    monkeypatch.setattr(settings, "graph_client_secret", "s")
    assert any("Graph write access is configured" in w for w in security_warnings())


def test_warns_when_enforcing_without_any_curator_group(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "auth_curator_groups", "")
    assert any("AUTH_CURATOR_GROUPS is empty" in w for w in security_warnings())


def test_no_warnings_when_properly_configured(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "auth_curator_groups", CURATOR_GROUP)
    monkeypatch.delenv(APP_SERVICE_MARKER, raising=False)
    assert security_warnings() == []


def test_local_development_is_not_warned_about(disabled, monkeypatch):
    """Auth off on a laptop is normal and must not cry wolf."""
    monkeypatch.delenv(APP_SERVICE_MARKER, raising=False)
    assert security_warnings() == []


def test_warnings_are_exposed_on_the_diagnostics_endpoints(disabled, client, monkeypatch):
    monkeypatch.setenv(APP_SERVICE_MARKER, "technical-marketing-hub")
    assert client.get("/api/auth/me").json()["warnings"]
    assert client.get("/api/debug/backend").json()["security_warnings"]
