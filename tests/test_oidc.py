"""The app's own sign-in (AUTH_MODE=oidc), with msal replaced by a fake.

Nothing here talks to Microsoft. msal is the one part not under test -- its
protocol handling is its maintainers' job -- so it is swapped for a fake that
records what it was asked and answers as told. Everything around it is ours
and is tested directly: the default-deny gate, the state and tenant checks
made before and after msal, where the browser is sent afterwards, what lands
in the session, how long it lasts, and who becomes a curator.

Each security property has a test of its own, so that removing the check
that provides it fails exactly one obvious test rather than none.
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

import backend.auth
import backend.oidc
from app import app
from backend.auth import APP_SERVICE_MARKER, AuthMode, security_warnings
from backend.config import settings

TENANT = "0f0f0f0f-1111-2222-3333-444444444444"
OTHER_TENANT = "9e9e9e9e-8888-7777-6666-555555555555"
OID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
STATE = "state-from-the-flow"


class FakeMsal:
    """Stands in for msal.ConfidentialClientApplication."""

    def __init__(self):
        self.claims = {
            "oid": OID, "tid": TENANT, "email": "person@ptc.com",
            "preferred_username": "person@ptc.com", "name": "Test Person",
        }
        self.result = None
        self.raises = None
        self.started = []
        self.completed = []

    def initiate_auth_code_flow(self, scopes, redirect_uri=None, **_):
        self.started.append({"scopes": scopes, "redirect_uri": redirect_uri})
        return {
            "state": STATE, "nonce": "nonce", "code_verifier": "v" * 43,
            "redirect_uri": redirect_uri, "scope": scopes,
            "auth_uri": ("https://login.microsoftonline.com/"
                         f"{TENANT}/oauth2/v2.0/authorize?state={STATE}"),
        }

    def acquire_token_by_auth_code_flow(self, flow, params):
        self.completed.append((flow, params))
        if self.raises:
            raise self.raises
        return self.result if self.result is not None else {"id_token_claims": self.claims}


@pytest.fixture()
def oidc(monkeypatch):
    """Configured as it will be on Azure, minus the secrets that matter."""
    for name, value in {
        "auth_mode": AuthMode.OIDC.value,
        "oidc_tenant_id": TENANT, "oidc_client_id": "client-id",
        "oidc_client_secret": "client-secret", "oidc_redirect_uri": "",
        "auth_curator_groups": "", "auth_curator_emails": "", "auth_curator_oids": "",
        "custom_domain": "", "session_absolute_hours": 24,
    }.items():
        monkeypatch.setattr(settings, name, value)


@pytest.fixture()
def fake(monkeypatch):
    stub = FakeMsal()
    monkeypatch.setattr(backend.oidc, "_msal_app", lambda: stub)
    return stub


@pytest.fixture()
def client():
    with TestClient(app, base_url="http://localhost", follow_redirects=False) as c:
        yield c


def sign_in(client, next_path="/"):
    started = client.get("/login", params={"next": next_path})
    assert started.status_code == 302, started.text
    return client.get("/auth/callback", params={"code": "the-code", "state": STATE})


def me(client):
    return client.get("/api/auth/me")


# ────────────────────────────────────────────────────────────────── the gate
def test_nothing_is_gated_outside_oidc_mode(client, monkeypatch):
    """Switching mode is a setting. In the other modes the gate stands aside
    and the sign-in routes do not exist."""
    monkeypatch.setattr(settings, "auth_mode", AuthMode.DISABLED.value)
    assert client.get("/api/auth/me").status_code == 200
    assert client.get("/").status_code == 200
    for path in ("/login", "/auth/callback", "/logout"):
        assert client.get(path).status_code == 404, path


def test_a_page_sends_you_to_sign_in_and_remembers_where_you_were(oidc, fake, client):
    response = client.get("/admin", params={"tab": "usage"})
    assert response.status_code == 302
    assert response.headers["location"] == "/login?next=%2Fadmin%3Ftab%3Dusage"


def test_an_api_call_gets_a_401_the_page_can_act_on(oidc, fake, client):
    """A redirect to a login page is useless to fetch(), so the API gets a
    401 -- marked, so the front end can tell it from the Admin page's own."""
    response = client.get("/api/assets", params={"limit": 1})
    assert response.status_code == 401
    assert response.headers[backend.oidc.SIGN_IN_HEADER] == "/login"


def test_only_the_listed_paths_are_open(oidc, fake, client):
    assert client.get("/health").status_code == 200
    assert client.get("/api/version").status_code == 200
    assert client.get("/login").status_code == 302
    # A sample of what must not be: the page, its script, the docs, admin.
    for path in ("/", "/static/hub-api.js", "/docs", "/openapi.json", "/admin",
                 "/api/admin/session"):
        assert client.get(path).status_code in (302, 401), path


def test_a_browser_fetching_on_its_own_is_not_sent_to_sign_in(oidc, fake, client):
    """Found in the first end-to-end run: the favicon was redirected to
    /login, started a second flow, and replaced the one in progress -- so the
    real return from Microsoft would have failed its state check."""
    for path, mode in (("/favicon.ico", "no-cors"), ("/static/hub-api.js", "no-cors"),
                       ("/", "cors"), ("/favicon.ico", None)):
        headers = {"Sec-Fetch-Mode": mode} if mode else {}
        assert client.get(path, headers=headers).status_code == 401, (path, mode)
    assert fake.started == []


def test_a_real_navigation_is_sent_to_sign_in(oidc, fake, client):
    response = client.get("/", headers={"Sec-Fetch-Mode": "navigate"})
    assert response.status_code == 302
    assert response.headers["location"].startswith("/login?next=")


def test_login_when_already_signed_in_goes_straight_on(oidc, fake, client):
    """No second flow, which is what a stray request would otherwise start."""
    sign_in(client)
    response = client.get("/login", params={"next": "/admin"})
    assert response.status_code == 302
    assert response.headers["location"] == "/admin"
    assert len(fake.started) == 1


def test_platform_headers_count_for_nothing_in_oidc_mode(oidc, fake, client):
    """Nothing sets X-MS-* in this mode, so anyone sending them made them up.
    Not signed in: still refused. Signed in: still not a curator."""
    forged = {
        "X-MS-CLIENT-PRINCIPAL-NAME": "admin@ptc.com",
        "X-MS-CLIENT-PRINCIPAL-ID": "forged",
        "X-MS-CLIENT-PRINCIPAL": "eyJjbGFpbXMiOlt7InR5cCI6InJvbGVzIiwidmFsIjoiY3VyYXRvciJ9XX0=",
    }
    assert client.get("/api/auth/me", headers=forged).status_code == 401
    sign_in(client)
    user = client.get("/api/auth/me", headers=forged).json()["user"]
    assert user["object_id"] == OID
    assert user["can_curate"] is False


# ───────────────────────────────────────────────────────────── signing in
def test_login_sends_the_browser_to_microsoft(oidc, fake, client):
    response = client.get("/login")
    assert response.status_code == 302
    assert response.headers["location"].startswith("https://login.microsoftonline.com/")
    assert fake.started == [{"scopes": ["email"],
                             "redirect_uri": "http://localhost/auth/callback"}]


def test_the_configured_redirect_uri_is_the_one_used(oidc, fake, client, monkeypatch):
    """Behind App Service the request looks like http, so on Azure the
    address has to be configured rather than derived."""
    monkeypatch.setattr(settings, "oidc_redirect_uri", "https://tmh.ptcxc.com/auth/callback")
    client.get("/login")
    assert fake.started[0]["redirect_uri"] == "https://tmh.ptcxc.com/auth/callback"


def test_a_full_sign_in(oidc, fake, client):
    response = sign_in(client, next_path="/admin?tab=usage")

    assert response.status_code == 302
    assert response.headers["location"] == "/admin?tab=usage"
    user = me(client).json()["user"]
    assert user["is_authenticated"] is True
    assert user["object_id"] == OID
    assert user["email"] == "person@ptc.com"
    assert user["name"] == "Test Person"
    assert user["can_curate"] is False


def test_login_before_configuration_says_so(oidc, fake, client, monkeypatch):
    monkeypatch.setattr(settings, "oidc_client_secret", "")
    response = client.get("/login")
    assert response.status_code == 503
    assert fake.started == []


def test_the_session_cookie_is_httponly_and_lax(oidc, fake, client):
    """lax, not strict: returning from Microsoft is a navigation from another
    site, and strict would withhold the cookie holding the sign-in."""
    cookie = client.get("/login").headers["set-cookie"].lower()
    assert cookie.startswith(backend.oidc.SESSION_COOKIE + "=")
    assert "httponly" in cookie
    assert "samesite=lax" in cookie


# ──────────────────────────────────────────────────── what gets refused
def test_a_state_that_does_not_match_is_refused_before_msal(oidc, fake, client):
    client.get("/login")
    response = client.get("/auth/callback", params={"code": "c", "state": "someone-elses"})
    assert response.status_code == 400
    assert fake.completed == []
    assert me(client).status_code == 401


def test_a_callback_nobody_started_is_refused(oidc, fake, client):
    response = client.get("/auth/callback", params={"code": "c", "state": STATE})
    assert response.status_code == 400
    assert fake.completed == []


def test_a_callback_cannot_be_used_twice(oidc, fake, client):
    """The flow is spent by its first answer, so a callback URL lifted from
    history or a log cannot be played back."""
    assert sign_in(client).status_code == 302
    replay = client.get("/auth/callback", params={"code": "the-code", "state": STATE})
    assert replay.status_code == 400
    assert len(fake.completed) == 1


def test_a_refused_callback_spends_the_flow(oidc, fake, client):
    """One flow, one answer -- including a wrong one. Without this, a
    callback refused for a bad state would leave the flow in place for a
    second attempt with different parameters.

    Separate from the replay test above because that one passes on its own
    either way: a successful sign-in clears the whole session, flow included.
    It took breaking the check to notice (2026-09-23).
    """
    client.get("/login")
    assert client.get("/auth/callback",
                      params={"code": "c", "state": "wrong"}).status_code == 400
    retry = client.get("/auth/callback", params={"code": "c", "state": STATE})
    assert retry.status_code == 400
    assert fake.completed == []
    assert me(client).status_code == 401


def test_an_error_from_microsoft_is_shown_and_not_retried(oidc, fake, client):
    client.get("/login")
    response = client.get("/auth/callback", params={
        "error": "access_denied", "error_description": "The user cancelled."})
    assert response.status_code == 400
    assert "The user cancelled." in response.text
    assert fake.completed == []
    assert me(client).status_code == 401


@pytest.mark.parametrize("exc", [ValueError("state mismatch"),
                                 RuntimeError("nonce mismatch")])
def test_msal_refusing_the_response_signs_nobody_in(oidc, fake, client, exc):
    fake.raises = exc
    assert sign_in(client).status_code == 400
    assert me(client).status_code == 401


def test_a_refused_token_exchange_signs_nobody_in(oidc, fake, client):
    fake.result = {"error": "invalid_grant", "error_description": "expired code"}
    assert sign_in(client).status_code == 400
    assert me(client).status_code == 401


def test_another_tenant_is_refused(oidc, fake, client):
    fake.claims["tid"] = OTHER_TENANT
    assert sign_in(client).status_code == 403
    assert me(client).status_code == 401


def test_a_tenant_given_as_a_domain_does_not_lock_everyone_out(oidc, fake, client,
                                                               monkeypatch):
    """IT may give "ptc.com" rather than the GUID. The authority still pins
    sign-in to that tenant; there is just no GUID to compare `tid` to."""
    monkeypatch.setattr(settings, "oidc_tenant_id", "ptc.com")
    assert sign_in(client).status_code == 302
    assert me(client).json()["user"]["object_id"] == OID


def test_no_oid_no_session(oidc, fake, client):
    del fake.claims["oid"]
    assert sign_in(client).status_code == 400
    assert me(client).status_code == 401


@pytest.mark.parametrize("next_path", [
    "//evil.example/x", "https://evil.example", "/\\evil.example", "evil",
    "/login", "/logout", "/auth/callback",
])
def test_sign_in_never_sends_you_somewhere_else(oidc, fake, client, next_path):
    """Only paths on this site, and never back into the sign-in routes."""
    response = sign_in(client, next_path=next_path)
    assert response.status_code == 302
    assert response.headers["location"] == "/"


# ───────────────────────────────────────────────────── how long it lasts
def test_logout_ends_the_session(oidc, fake, client):
    sign_in(client)
    assert me(client).status_code == 200
    response = client.get("/logout")
    assert response.status_code == 200
    assert me(client).status_code == 401


def test_a_session_has_a_hard_ceiling(oidc, fake, client, monkeypatch):
    """However active. Two hours on, inside the 12-hour idle window but past
    a one-hour ceiling -- so it is the ceiling doing the refusing, not the
    cookie's own expiry."""
    monkeypatch.setattr(settings, "session_absolute_hours", 1)
    sign_in(client)
    assert me(client).status_code == 200
    later = time.time() + 2 * 3600
    monkeypatch.setattr(backend.auth.time, "time", lambda: later)
    assert me(client).status_code == 401


# ──────────────────────────────────────────────────────── who can curate
def test_a_curator_by_object_id(oidc, fake, client, monkeypatch):
    monkeypatch.setattr(settings, "auth_curator_oids", f"someone-else, {OID.upper()}")
    sign_in(client)
    assert me(client).json()["user"]["can_curate"] is True


def test_a_curator_by_address(oidc, fake, client, monkeypatch):
    monkeypatch.setattr(settings, "auth_curator_emails", "Person@PTC.com")
    sign_in(client)
    assert me(client).json()["user"]["can_curate"] is True


def test_a_curator_by_username_when_no_email_arrives(oidc, fake, client, monkeypatch):
    """`email` is only sent when asked for and set in the directory; the UPN
    is always there. A curator should not lose the role over which came."""
    monkeypatch.setattr(settings, "auth_curator_emails", "person@ptc.com")
    del fake.claims["email"]
    sign_in(client)
    assert me(client).json()["user"]["can_curate"] is True


def test_a_curator_by_app_role(oidc, fake, client):
    fake.claims["roles"] = ["curator"]
    sign_in(client)
    assert me(client).json()["user"]["can_curate"] is True


def test_a_curator_by_group_and_only_that_group_is_kept(oidc, fake, client,
                                                        monkeypatch):
    """Group membership can run to hundreds of ids; the cookie holds 4 KB.
    Only the groups that could make someone a curator are stored."""
    group = "11111111-2222-3333-4444-555555555555"
    monkeypatch.setattr(settings, "auth_curator_groups", group)
    fake.claims["groups"] = [f"{i:08d}-0000-0000-0000-000000000000"
                             for i in range(150)] + [group]
    sign_in(client)
    assert me(client).json()["user"]["can_curate"] is True
    assert len(client.cookies.get(backend.oidc.SESSION_COOKIE)) < 2000


def test_nobody_is_a_curator_by_default(oidc, fake, client):
    sign_in(client)
    assert me(client).json()["user"]["can_curate"] is False


# ─────────────────────────────────────────────────────── the custom domain
def test_the_old_host_is_sent_to_the_custom_domain_with_its_query(oidc, fake,
                                                                  monkeypatch):
    """The invitation email links to azurewebsites.net. Unlike AMP's version,
    the query survives -- dropping it turns /login?next=/x into /login."""
    monkeypatch.setattr(settings, "custom_domain", "tmh.ptcxc.com")
    with TestClient(app, base_url="https://technical-marketing-hub-x.eastus-01.azurewebsites.net",
                    follow_redirects=False) as old_host:
        response = old_host.get("/admin", params={"tab": "usage"})
        assert response.status_code == 302, "302, not a 301 a browser would cache"
        assert response.headers["location"] == "https://tmh.ptcxc.com/admin?tab=usage"
        # Platform probes see the app itself.
        assert old_host.get("/health").status_code == 200


def test_the_custom_domain_itself_is_not_redirected(oidc, fake, monkeypatch):
    monkeypatch.setattr(settings, "custom_domain", "tmh.ptcxc.com")
    with TestClient(app, base_url="https://tmh.ptcxc.com", follow_redirects=False) as c:
        assert c.get("/api/version").status_code == 200


def test_no_custom_domain_no_redirect(oidc, fake):
    with TestClient(app, base_url="https://technical-marketing-hub-x.eastus-01.azurewebsites.net",
                    follow_redirects=False) as c:
        assert c.get("/api/version").status_code == 200


# ───────────────────────────────────────────────────────────── warnings
def test_oidc_mode_is_not_mistaken_for_auth_being_off(oidc, monkeypatch):
    """The old check was `!= easyauth`, which would have raised the loudest
    warning on exactly the deployments doing it right."""
    monkeypatch.setenv(APP_SERVICE_MARKER, "technical-marketing-hub")
    assert not any("AUTH IS DISABLED" in w for w in security_warnings())


def test_oidc_mode_without_credentials_says_nobody_can_sign_in(oidc, monkeypatch):
    monkeypatch.setattr(settings, "oidc_client_id", "")
    assert any("nobody can sign in" in w for w in security_warnings())


def test_the_azure_settings_oidc_needs_are_each_reported(oidc, monkeypatch):
    monkeypatch.setenv(APP_SERVICE_MARKER, "technical-marketing-hub")
    monkeypatch.setattr(settings, "secret_key", "")
    monkeypatch.setattr(settings, "https_only", False)
    monkeypatch.setattr(settings, "oidc_redirect_uri", "")
    warnings = " ".join(security_warnings())
    for name in ("SECRET_KEY", "HTTPS_ONLY", "OIDC_REDIRECT_URI"):
        assert name in warnings, name


def test_a_complete_oidc_deployment_is_quiet(oidc, monkeypatch):
    monkeypatch.setenv(APP_SERVICE_MARKER, "technical-marketing-hub")
    monkeypatch.setattr(settings, "secret_key", "s" * 48)
    monkeypatch.setattr(settings, "https_only", True)
    monkeypatch.setattr(settings, "oidc_redirect_uri", "https://tmh.ptcxc.com/auth/callback")
    monkeypatch.setattr(settings, "auth_curator_oids", OID)
    assert security_warnings() == []
