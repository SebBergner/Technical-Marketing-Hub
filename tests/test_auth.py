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
def named_curators(monkeypatch):
    """Curators by address, with no group or app role in the token at all."""
    monkeypatch.setattr(settings, "auth_curator_groups", "")
    monkeypatch.setattr(settings, "auth_curator_emails",
                        "elio@ptc.com, seb@ptc.com,liwei@ptc.com")


def test_a_named_address_is_a_curator(enforcing, named_curators, client):
    """The whole point: no group claim, no app role, still a curator.

    This is what lets the identity provider send only the claims it already
    offered -- oid, email, name -- with nothing extra requested for us.
    """
    headers = easyauth_headers(email="seb@ptc.com")

    user = client.get("/api/auth/me", headers=headers).json()["user"]

    assert user["is_authenticated"] is True
    assert user["can_curate"] is True


def test_the_address_match_ignores_case_and_spacing(enforcing, named_curators,
                                                    client):
    """Addresses are case-insensitive, and a list a person typed has spaces
    in it. Neither should decide whether someone can curate."""
    user = client.get("/api/auth/me",
                      headers=easyauth_headers(email="Liwei@PTC.com")).json()["user"]

    assert user["can_curate"] is True


def test_an_address_not_on_the_list_is_only_a_viewer(enforcing, named_curators,
                                                     client):
    headers = easyauth_headers(email="someone.else@ptc.com")

    user = client.get("/api/auth/me", headers=headers).json()["user"]

    assert user["is_authenticated"] is True
    assert user["can_curate"] is False


def test_a_near_miss_address_is_not_a_curator(enforcing, named_curators, client):
    """Matched whole, not by prefix or substring: an address that merely
    contains a curator's is somebody else."""
    for near in ("seb@ptc.com.attacker.example", "xseb@ptc.com", "seb@ptc.co"):
        user = client.get("/api/auth/me",
                          headers=easyauth_headers(email=near)).json()["user"]
        assert user["can_curate"] is False, near


def test_an_empty_list_grants_nobody(enforcing, client, monkeypatch):
    """Fails closed. An empty setting is not a wildcard, and the blank
    default must never be the permissive case."""
    monkeypatch.setattr(settings, "auth_curator_groups", "")
    monkeypatch.setattr(settings, "auth_curator_emails", "")

    user = client.get("/api/auth/me",
                      headers=easyauth_headers(email="seb@ptc.com")).json()["user"]

    assert user["can_curate"] is False


def test_a_named_address_is_ignored_without_easyauth(disabled, monkeypatch, client):
    """The address is only trusted because the platform asserted it.

    With auth disabled the headers are ignored entirely, so this asserts the
    new route did not quietly become a way to grant yourself the role by
    setting a header.
    """
    monkeypatch.setattr(settings, "auth_curator_emails", "seb@ptc.com")

    user = client.get("/api/auth/me",
                      headers=easyauth_headers(email="seb@ptc.com")).json()["user"]

    # The local dev principal, not the header's identity.
    assert user["is_dev_principal"] is True
    assert user["email"] != "seb@ptc.com"


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
        # A loopback host on purpose: issue_session() only marks the admin
        # cookie Secure off-loopback, and a Secure cookie is dropped over
        # plain http -- so "testserver" would make every signed-in test fail
        # for a reason that has nothing to do with what it is testing.
        with TestClient(app, base_url="http://localhost") as c:
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


def test_asset_requests_are_the_deliberate_exception(enforcing, client):
    """"Require authentication" is not enforced at the App Service platform
    level (docs/HANDOVER-DEPLOYMENT.md §2.6), so every visitor arrives as
    ANONYMOUS today -- and unlike curation/sync/share, an anonymous caller
    must still be able to submit a request, or the feature is simply dead
    for every visitor until SSO exists. Liwei, 2026-09-09.

    Would fail against the old code, which depended on require_authenticated
    here and 401'd exactly like the endpoints above.
    """
    response = client.post("/api/requests", json={"asset_type": "video"})
    assert response.status_code == 201
    assert response.json()["requester_email"] is None


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


def test_warns_when_enforcing_without_any_way_to_grant_curator(monkeypatch):
    """Both routes blanked explicitly: a developer's own .env may set either,
    and a test that passes only on a machine without one is not a test."""
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "auth_curator_groups", "")
    monkeypatch.setattr(settings, "auth_curator_emails", "")
    assert any("nor AUTH_CURATOR_EMAILS" in w for w in security_warnings())


def test_named_curators_alone_silence_the_warning(monkeypatch):
    """Any one route is enough. Warning about a missing group while three
    named people can curate would be crying wolf, and a warning nobody can
    act on is one people learn to scroll past."""
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "auth_curator_groups", "")
    monkeypatch.setattr(settings, "auth_curator_emails", "seb@ptc.com")
    monkeypatch.delenv(APP_SERVICE_MARKER, raising=False)
    assert security_warnings() == []


def test_no_warnings_when_properly_configured(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "auth_curator_groups", CURATOR_GROUP)
    monkeypatch.setattr(settings, "auth_curator_emails", "")
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


# ════════════════════════ the temporary admin bridge (delete with SSO) ═══════
#
# The property these pin: a shared Admin sign-in may refresh our own mirror,
# and may not touch SharePoint. See backend/admin_auth.py for why the line is
# drawn there — one credential for everyone means no write to somebody else's
# system can ever be attributed to a person.
ADMIN_USER, ADMIN_PASS = "tddadmin", "a-long-test-password-8e1f"


@pytest.fixture()
def admin_configured(monkeypatch):
    monkeypatch.setattr(settings, "admin_username", ADMIN_USER)
    monkeypatch.setattr(settings, "admin_password", ADMIN_PASS)


def sign_in_as_admin(client):
    response = client.post("/api/admin/login",
                           json={"username": ADMIN_USER, "password": ADMIN_PASS})
    assert response.status_code == 200
    return response


def test_no_admin_credentials_means_no_admin_page_at_all(
        enforcing, client, monkeypatch):
    """Fails closed: an unset password is not an empty password.

    Blanked explicitly — a developer's own .env sets these, and a test that
    passes only on a machine without one is not a test."""
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password", "")
    assert client.get("/api/admin/session").json() == {
        "configured": False, "signed_in": False}
    assert client.post("/api/admin/login",
                       json={"username": "", "password": ""}).status_code == 503
    assert client.get("/api/admin/overview").status_code == 503


def test_the_wrong_password_does_not_sign_anyone_in(enforcing, admin_configured, client):
    assert client.post("/api/admin/login",
                       json={"username": ADMIN_USER, "password": "wrong"}
                       ).status_code == 401
    assert client.post("/api/admin/login",
                       json={"username": "someone-else", "password": ADMIN_PASS}
                       ).status_code == 401
    assert client.get("/api/admin/overview").status_code == 401


def test_an_admin_session_opens_the_overview_and_closes_on_sign_out(
        enforcing, admin_configured, client):
    assert client.get("/api/admin/overview").status_code == 401
    sign_in_as_admin(client)
    assert client.get("/api/admin/session").json()["signed_in"] is True
    assert client.get("/api/admin/overview").status_code == 200
    client.post("/api/admin/logout")
    assert client.get("/api/admin/overview").status_code == 401


def test_an_admin_session_may_refresh_the_mirror(enforcing, admin_configured, client):
    """The one write it is trusted with: a sync reads upstream and replaces
    our own rebuildable cache. 503 here is the Graph client being absent in
    tests — what matters is that it is no longer 401."""
    assert client.post("/api/graph/sync").status_code in (401, 503)
    sign_in_as_admin(client)
    assert client.post("/api/graph/sync").status_code != 401


@pytest.fixture()
def no_graph(monkeypatch):
    """No Graph credentials, which is what CI has and a developer does not.

    Without this the write-back test below passes on a laptop and fails in the
    pipeline: FastAPI resolves dependencies in declaration order, so whichever
    of `require_client` (503) and `require_curator` (403) comes first decides
    the answer, and only an unconfigured environment can tell them apart.
    """
    monkeypatch.setattr(settings, "graph_tenant_id", "")
    monkeypatch.setattr(settings, "graph_client_id", "")
    monkeypatch.setattr(settings, "graph_client_secret", "")


def test_an_admin_session_may_not_write_back_to_sharepoint(
        enforcing, admin_configured, no_graph, client):
    """The line that makes the bridge acceptable. Write-back edits SharePoint's
    own columns, so it stays curator-only however the admin signs in.

    Asserted with Graph deliberately unconfigured, because that is the case
    that can regress: the refusal has to come from the curator check, not from
    the credentials happening to be missing. 2026-09-22, when this returned
    503 in CI and 403 locally.
    """
    sign_in_as_admin(client)
    assert client.post("/api/graph/writeback").status_code in (401, 403)
    assert client.post("/api/curation/propose").status_code == 401


def test_graph_configuration_is_never_disclosed_before_authorising(
        enforcing, no_graph, client):
    """An anonymous caller learns that they are not signed in, and nothing
    else. 503 here would name our Graph settings to someone who has not
    authenticated, and would leave the authorisation check unproven."""
    assert client.post("/api/graph/writeback").status_code == 401
    assert client.post("/api/graph/sync").status_code == 401
    assert client.get("/api/graph/verify").status_code == 401
