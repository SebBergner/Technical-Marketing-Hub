"""The script policy and the API reference behind View Admin (audit 2026-11-26, WS-D)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.auth import AuthMode
from backend.config import settings
from tests.test_auth import easyauth_headers

ROOT = Path(__file__).resolve().parent.parent


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


# ───────────────────────────────────────────────────── Content-Security-Policy
def test_every_answer_locks_scripts_plugins_and_base_to_the_hub(client):
    for path in ("/", "/admin", "/health", "/api/version", "/no-such-page"):
        policy = client.get(path).headers["content-security-policy"]
        directives = {d.strip().split(" ", 1)[0]: d.strip() for d in policy.split(";")}
        assert directives["frame-ancestors"] == "frame-ancestors 'self'", path
        assert directives["script-src"] == "script-src 'self'", path
        assert directives["object-src"] == "object-src 'none'", path
        assert directives["base-uri"] == "base-uri 'self'", path
        # Previews frame SharePoint and Consensus; pages use inline styles.
        for left_alone in ("frame-src", "style-src", "img-src", "default-src"):
            assert left_alone not in directives, (path, left_alone)


def test_no_page_has_a_script_the_policy_would_block():
    """script-src 'self' blocks inline scripts, on*= handlers and javascript:
    links. None may creep into the pages."""
    pages = [ROOT / "index.html", *sorted((ROOT / "static").glob("*.html"))]
    assert len(pages) >= 4
    for page in pages:
        text = page.read_text(encoding="utf-8")
        for m in re.finditer(r"<script\b([^>]*)>(.*?)</script>", text, re.I | re.S):
            assert "src=" in m.group(1) and not m.group(2).strip(), (page.name, m.group(0)[:80])
        assert not re.search(r"\son[a-z]+\s*=", text, re.I), page.name
        assert "javascript:" not in text.lower(), page.name


def test_the_sign_in_pages_have_no_script():
    from backend.oidc import _page
    body = _page("Title", "Message", 400).body.decode()
    assert "<script" not in body.lower()
    assert not re.search(r"\son[a-z]+\s*=", body, re.I)


# ─────────────────────────────────────────────────────────── the API reference
def test_the_api_reference_is_for_view_admin_only(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path, headers=easyauth_headers("someone@ptc.com")).status_code == 403, path
        assert client.get(path, headers=easyauth_headers("someone@partner.example")
                          ).status_code == 403, path
        assert client.get(path).status_code == 401, path
        assert client.get(path, headers=BOSS).status_code == 200, path
    schema = client.get("/openapi.json", headers=BOSS).json()
    assert "/api/assets" in schema["paths"]
    assert not any(p in schema["paths"] for p in ("/docs", "/redoc", "/openapi.json"))


def test_the_api_reference_pages_allow_exactly_their_own_scripts(client):
    """Swagger's page starts itself with an inline script: its hash, and the
    CDN, are allowed on that page alone."""
    import base64
    import hashlib
    page = client.get("/docs", headers=BOSS)
    inline = re.findall(r"<script>(.*?)</script>", page.text, re.S)
    assert inline, "Swagger's page is expected to carry its start-up script"
    policy = page.headers["content-security-policy"]
    for script in inline:
        digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
        assert f"'sha256-{digest}'" in policy
    assert "https://cdn.jsdelivr.net" in policy
    assert "unsafe-inline" not in policy and "unsafe-eval" not in policy
    assert "frame-ancestors 'self'" in policy and "object-src 'none'" in policy
