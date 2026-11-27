"""Writes only from the Hub's own pages: the CSRF origin check (backend/csrf.py,
audit 2026-11-26, WS-D)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend import csrf
from backend.auth import AuthMode
from backend.config import settings
from tests.test_auth import easyauth_headers


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import app
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "a-test-password-long-enough")
    monkeypatch.setattr(settings, "hub_admin_emails", "boss@ptc.com")
    (tmp_path / "mirror").mkdir()
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps([
        {"id": "bobcat", "type": "ldk", "title": "Bobcat", "products": ["Creo"]}]),
        encoding="utf-8")
    return TestClient(app, base_url="http://localhost", follow_redirects=False)


BOSS = easyauth_headers("boss@ptc.com")


# ──────────────────────────────────────────────────────────────────────── CSRF
def hide(client, **headers):
    return client.post("/api/content-health/hidden", json={"asset_id": "bobcat"},
                       headers={**BOSS, **headers})


@pytest.mark.parametrize("site", ["same-origin", "none", "Same-Origin"])
def test_a_write_from_the_hubs_own_page_passes(client, site):
    assert hide(client, **{"Sec-Fetch-Site": site}).status_code == 200


@pytest.mark.parametrize("site", ["same-site", "cross-site", "something-else"])
def test_a_write_from_another_site_or_slot_is_refused(client, site):
    """same-site is staging versus production: both are under ptcxc.com."""
    response = hide(client, **{"Sec-Fetch-Site": site})
    assert response.status_code == 403
    assert "did not come from a Hub page" in response.json()["detail"]
    assert response.headers["x-content-type-options"] == "nosniff"


def test_sec_fetch_site_decides_even_when_origin_looks_right(client):
    assert hide(client, **{"Sec-Fetch-Site": "same-site",
                           "Origin": "http://localhost"}).status_code == 403


def test_without_sec_fetch_site_the_origin_must_be_our_own(client):
    # Hiding twice is a 422, so "passes" means "not refused here".
    assert hide(client, Origin="http://localhost").status_code == 200
    assert hide(client, Origin="http://localhost/").status_code != 403
    for other in ("https://dev-tmh.ptcxc.com", "http://evil.example", "null",
                  "http://localhost.evil.example", "http://localhost:8001"):
        assert hide(client, Origin=other).status_code == 403, other


def test_behind_app_service_the_forwarded_scheme_counts(client):
    """The app sees http; the browser was on https."""
    headers = {"Host": "tmh.ptcxc.com", "X-Forwarded-Proto": "https"}
    assert hide(client, Origin="https://tmh.ptcxc.com", **headers).status_code != 403
    assert hide(client, Origin="https://dev-tmh.ptcxc.com", **headers).status_code == 403


def test_a_request_with_neither_header_is_not_a_browser_page_and_passes(client):
    """No browser omits both on a cross-site write; curl and scripts do, and
    they carry nobody's cookie."""
    assert hide(client).status_code == 200


def test_reads_are_never_checked(client):
    assert client.get("/api/version", headers={"Sec-Fetch-Site": "cross-site"}
                      ).status_code == 200


def test_the_admin_sign_in_cannot_be_forged_from_another_site(client):
    body = {"username": "admin", "password": "a-test-password-long-enough"}
    assert client.post("/api/admin/login", json=body,
                       headers={"Sec-Fetch-Site": "same-site"}).status_code == 403
    assert client.post("/api/admin/login", json=body,
                       headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200


def test_an_api_token_is_left_to_the_token(client):
    """A page cannot attach Authorization cross-site without a preflight the
    Hub never answers; the token check, not this one, decides."""
    response = client.post("/api/content-health/hidden", json={"asset_id": "bobcat"},
                           headers={"Authorization": "Bearer not-a-real-token",
                                    "Sec-Fetch-Site": "cross-site"})
    assert response.status_code != 403 or "Hub page" not in response.text


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
def test_every_writing_method_is_checked(client, method):
    response = client.request(method, "/api/content-health/hidden/bobcat",
                              headers={**BOSS, "Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 403


def test_the_sign_in_callbacks_are_unaffected(client, monkeypatch):
    """Both are returns from another site's sign-in."""
    class Req:
        def __init__(self, method, path):
            self.method = method
            self.url = type("U", (), {"path": path, "scheme": "https"})()
            self.headers = {"sec-fetch-site": "cross-site", "origin": "https://login.example"}
    for path in ("/auth/callback", "/api/consensus/oauth/callback"):
        for method in ("GET", "POST"):
            assert csrf.refusal(Req(method, path)) is None, (method, path)
    assert csrf.refusal(Req("POST", "/api/anything")) is not None
    # And through the app: the callbacks answer as they always did.
    monkeypatch.setattr(settings, "auth_mode", AuthMode.OIDC.value)
    response = client.get("/auth/callback", headers={"Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 400 and "expired" in response.text
    response = client.get("/api/consensus/oauth/callback",
                          headers={"Sec-Fetch-Site": "cross-site"})
    assert "Hub page" not in response.text
