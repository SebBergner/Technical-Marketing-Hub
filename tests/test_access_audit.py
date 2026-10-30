"""The access audit of 2026-10-30: diagnostics and integration controls no
page calls were open to anyone signed in, partners included."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend import access
from backend.auth import AuthMode
from backend.config import settings
from tests.test_auth import easyauth_headers

CLOSED = [("get", "/api/debug/backend"), ("get", "/api/graph/status"),
          ("get", "/api/graph/verify"), ("get", "/api/graph/writeback/backlog"),
          ("get", "/api/consensus/status"), ("get", "/api/consensus/probe"),
          ("get", "/api/consensus/reconcile"), ("get", "/api/consensus/oauth/status"),
          ("get", "/api/consensus/oauth/start"), ("post", "/api/consensus/oauth/revoke"),
          ("get", "/api/curation/summary"), ("get", "/api/curation/proposals"),
          ("get", "/api/requests/unsynced")]


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import app
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password", "")
    monkeypatch.setattr(settings, "hub_admin_emails", "boss@ptc.com")
    (tmp_path / "mirror").mkdir()
    return TestClient(app, base_url="http://localhost")


@pytest.mark.parametrize("method,url", CLOSED)
def test_diagnostics_are_closed_to_partners_and_staff(client, method, url):
    access.create_group("Everything", "", sorted(access.ALL), ["p@partner.it"], "t")
    for who in ("p@partner.it", "someone@ptc.com"):
        r = getattr(client, method)(url, headers=easyauth_headers(who))
        assert r.status_code == 403, (who, r.status_code)


def test_every_answer_carries_the_security_headers(client, monkeypatch):
    """D3, 2026-10-30: answers from the route, the gate and an error alike."""
    for url in ("/api/version", "/api/assets/nope"):
        h = client.get(url, headers=easyauth_headers("someone@ptc.com")).headers
        assert h["X-Content-Type-Options"] == "nosniff", url
        assert h["X-Frame-Options"] == "SAMEORIGIN", url
        assert h["Content-Security-Policy"] == "frame-ancestors 'self'", url
        assert h["Referrer-Policy"] == "strict-origin-when-cross-origin", url
    assert "Strict-Transport-Security" not in client.get("/api/version").headers
    monkeypatch.setattr(settings, "https_only", True)
    assert "max-age" in client.get("/api/version").headers["Strict-Transport-Security"]


def test_overview_says_how_this_slot_is_set_and_never_who(client, monkeypatch):
    """D5, 2026-10-30: the checks a swap needs, without Cloud Shell."""
    monkeypatch.setattr(settings, "auth_curator_emails", "old@ptc.com, older@ptc.com")
    monkeypatch.setattr(settings, "upload_library_overrides", "demo_video=Test")
    monkeypatch.setattr(settings, "hub_tasks_list", "")
    r = client.get("/api/admin/overview", headers=easyauth_headers("boss@ptc.com"))
    rows = {c["label"]: c for c in r.json()["configuration"]}
    assert rows["Hub Tasks list"]["value"] == "Off on this slot"
    assert rows["Upload test library"]["warn"] is True
    assert rows["Shared Admin password"] == {"label": "Shared Admin password", "value": "Off",
                                             "warn": False}
    curators = rows["Curator settings (AUTH_CURATOR_*)"]
    assert curators["warn"] is False and curators["value"].startswith("2 entries")
    assert "old@ptc.com" not in r.text
    assert rows["Permanent administrators (HUB_ADMIN_EMAILS)"]["value"] == "1"


def test_sharing_through_consensus_needs_a_licence(client, tmp_path):
    import json
    (tmp_path / "mirror" / "consensus.json").write_text(json.dumps([
        {"id": "c1", "type": "video", "title": "Clip", "source": "consensus",
         "consensus_uuid": "u-1", "customer_facing": True}]), encoding="utf-8")
    body = {"asset_id": "c1", "trackable": False}
    for who in ("p@partner.it", "someone@ptc.com"):
        r = client.post("/api/share/consensus", json=body, headers=easyauth_headers(who))
        assert r.status_code == 403 and "licence" in r.json()["detail"], who
