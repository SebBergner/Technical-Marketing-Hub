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


def test_sharing_through_consensus_needs_a_licence(client, tmp_path):
    import json
    (tmp_path / "mirror" / "consensus.json").write_text(json.dumps([
        {"id": "c1", "type": "video", "title": "Clip", "source": "consensus",
         "consensus_uuid": "u-1", "customer_facing": True}]), encoding="utf-8")
    body = {"asset_id": "c1", "trackable": False}
    for who in ("p@partner.it", "someone@ptc.com"):
        r = client.post("/api/share/consensus", json=body, headers=easyauth_headers(who))
        assert r.status_code == 403 and "licence" in r.json()["detail"], who
