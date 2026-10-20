"""SharePoint-hosted thumbnails go through the Hub (services/thumbnails.py,
2026-10-20): Lambo and Hill lost their pictures whenever the viewer's
browser had no SharePoint session."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.auth import AuthMode
from backend.config import settings
from backend.services import thumbnails
from tests.test_auth import easyauth_headers

HILL = ("https://ptccloud.sharepoint.com/_layouts/15/getpreview.ashx?path=%2Fsites%2FEXT-TDD"
        "%2FSiteAssets%2FSitePages%2FHill%20Helicopters%2FHillHelicopters.jpg")
ANN = easyauth_headers("ann@ptc.com")


def test_only_sharepoint_pictures_are_rewritten():
    assert thumbnails.public_url("hill", HILL) == "/api/assets/hill/thumbnail"
    consensus = "https://app.goconsensus.com/api/mps/media/abc"
    assert thumbnails.public_url("c1", consensus) == consensus
    assert thumbnails.public_url("x", None) is None


def test_the_file_address_behind_getpreview():
    assert thumbnails.direct_url(HILL) == ("https://ptccloud.sharepoint.com/sites/EXT-TDD/"
                                           "SiteAssets/SitePages/Hill%20Helicopters/HillHelicopters.jpg")
    cad = "https://ptccloud.sharepoint.com/sites/EXT-TDD/SiteAssets/CAD Model/Missile.png"
    assert thumbnails.direct_url(cad).endswith("/SiteAssets/CAD%20Model/Missile.png")


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import app
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password", "")
    (tmp_path / "mirror").mkdir()
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps([
        {"id": "hill", "type": "vdk", "title": "Hill Helicopters", "products": ["Windchill"],
         "thumbnail_url": HILL},
        {"id": "plain", "type": "vdk", "title": "No picture", "products": ["Windchill"]}]),
        encoding="utf-8")
    return TestClient(app, base_url="http://localhost")


def test_cards_get_the_hub_address_and_the_hub_serves_the_picture(client, monkeypatch, tmp_path):
    calls = []

    def fake_fetch(graph, url):
        calls.append(url)
        return b"\xff\xd8jpeg", "image/jpeg"
    monkeypatch.setattr(thumbnails, "fetch", fake_fetch)
    monkeypatch.setattr("backend.integrations.graph.client.get_graph_client", lambda: object())

    page = client.get("/api/assets/hill", headers=ANN).json()
    assert page["thumbnail_url"] == "/api/assets/hill/thumbnail"
    r = client.get("/api/assets/hill/thumbnail", headers=ANN)
    assert (r.status_code, r.headers["content-type"], r.content) == (200, "image/jpeg", b"\xff\xd8jpeg")
    assert "private" in r.headers["cache-control"]
    client.get("/api/assets/hill/thumbnail", headers=ANN)
    assert calls == [HILL], "the second view comes from the cache"
    assert list((tmp_path / "mirror" / "private" / "thumbs").glob("*.bin"))

    assert client.get("/api/assets/plain/thumbnail", headers=ANN).status_code == 404
    assert client.get("/api/assets/nope/thumbnail", headers=ANN).status_code == 404


def test_sharepoint_unreachable_means_404_so_the_card_shows_its_cover(client, monkeypatch):
    def broken(graph, url):
        raise RuntimeError("Graph is down")
    monkeypatch.setattr(thumbnails, "fetch", broken)
    monkeypatch.setattr("backend.integrations.graph.client.get_graph_client", lambda: object())
    assert client.get("/api/assets/hill/thumbnail", headers=ANN).status_code == 404


def test_warming_fetches_each_picture_once(client, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(thumbnails, "fetch",
                        lambda graph, url: calls.append(url) or (b"img", "image/png"))
    from backend.deps import get_repo
    repo = get_repo()
    assert thumbnails.warm(repo, client=object()) == 1
    assert thumbnails.warm(repo, client=object()) == 0, "fresh in the cache"
    assert calls == [HILL]
