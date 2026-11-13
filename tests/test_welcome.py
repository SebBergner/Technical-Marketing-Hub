"""The welcome pop-up: until "Don't show again", and again after a big update
(Liwei, 2026-11-08, 2026-11-13)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend import welcome
from backend.auth import AuthMode
from backend.config import settings
from tests.test_auth import easyauth_headers


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import app
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password", "")
    return TestClient(app, base_url="http://localhost")


def status(client, who):
    return client.get("/api/welcome", headers=easyauth_headers(who)).json()


def test_shown_until_seen_per_person(client):
    first = status(client, "ann@ptc.com")
    assert first["required"] and first["version"] == welcome.VERSION
    assert status(client, "ann@ptc.com")["required"], "until Don't show again records it"
    assert client.post("/api/welcome/seen", headers=easyauth_headers("ann@ptc.com")).status_code == 200
    assert not status(client, "ann@ptc.com")["required"], "not again, in any browser"
    assert status(client, "bob@ptc.com")["required"], "per person"


def test_a_big_update_shows_what_is_new_to_everyone(client, monkeypatch):
    client.post("/api/welcome/seen", headers=easyauth_headers("ann@ptc.com"))
    new = ({"icon": "i-star", "title": "Playlists", "text": "Save demos."},)
    monkeypatch.setattr(welcome, "VERSION", "2027-01-15")
    monkeypatch.setattr(welcome, "WHATS_NEW", new)
    again = status(client, "ann@ptc.com")
    assert again["required"] and again["kind"] == "whats_new" and again["whats_new"] == list(new)
    assert status(client, "new@ptc.com")["kind"] == "whats_new", "someone new is told too"
    monkeypatch.setattr(welcome, "WHATS_NEW", ())
    assert status(client, "new@ptc.com")["kind"] == "welcome", "nothing new: the welcome"
    client.post("/api/welcome/seen", headers=easyauth_headers("ann@ptc.com"))
    assert not status(client, "ann@ptc.com")["required"]


# ── the training video at the top of the user guide (Liwei, 2026-11-10)

class FakeGraph:
    def __init__(self, files=None, folder=True, url="https://signed.example/v.mp4"):
        self.files = files if files is not None else [
            {"id": "OLD", "name": "a.mp4", "file": {"mimeType": "video/mp4"},
             "lastModifiedDateTime": "2026-11-01T00:00:00Z"},
            {"id": "NEW", "name": "b.mp4", "file": {"mimeType": "video/mp4"},
             "lastModifiedDateTime": "2026-11-10T00:00:00Z", "video": {"duration": 182066}},
            {"id": "DOC", "name": "notes.docx", "file": {"mimeType": "application/msword"},
             "lastModifiedDateTime": "2026-11-11T00:00:00Z"}]
        self.folder, self.url, self.asked = folder, url, []

    def resolve_site(self):
        from types import SimpleNamespace
        return SimpleNamespace(site_id="S")

    def find_drive(self, site_id, name):
        from types import SimpleNamespace
        assert name == settings.graph_video_library
        return SimpleNamespace(drive_id="D")

    def list_children(self, drive_id, item_id="root"):
        if item_id == "root":
            return [{"id": "F", "name": settings.guide_video_folder, "folder": {}}] if self.folder else []
        return self.files

    thumbs = [{"large": {"url": "https://thumb.example/large.jpg"}}]

    def thumbnails(self, drive_id, item_id):
        self.asked.append("thumb:" + item_id)
        return self.thumbs

    def download_url(self, drive_id, item_id):
        self.asked.append(item_id)
        return self.url


@pytest.fixture
def graph(monkeypatch):
    from app import app
    from backend.routers.graph import require_client
    from backend.routers import disclaimer as routes
    routes._guide_cache.clear()
    fake = FakeGraph()
    app.dependency_overrides[require_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(require_client, None)
    routes._guide_cache.clear()


def test_training_video_plays_the_newest_video_in_the_folder(client, graph):
    r = client.get("/api/welcome/video", headers=easyauth_headers("ann@ptc.com"),
                   follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "https://signed.example/v.mp4"
    assert graph.asked == ["NEW"]


def test_training_video_missing_is_404(client, graph):
    graph.folder = False
    r = client.get("/api/welcome/video", headers=easyauth_headers("ann@ptc.com"),
                   follow_redirects=False)
    assert r.status_code == 404
    graph.folder, graph.files = True, []
    r = client.get("/api/welcome/video", headers=easyauth_headers("ann@ptc.com"),
                   follow_redirects=False)
    assert r.status_code == 404


def test_training_video_needs_sign_in(client, graph):
    r = client.get("/api/welcome/video", follow_redirects=False)
    assert r.status_code in (401, 403)
    assert graph.asked == []


def test_training_video_card_shows_its_length(client, graph):
    r = client.get("/api/welcome/video/info", headers=easyauth_headers("ann@ptc.com"))
    assert r.json() == {"duration_seconds": 182}


def test_training_video_cover_is_sharepoints_still(client, graph):
    h = easyauth_headers("ann@ptc.com")
    r = client.get("/api/welcome/video/poster", headers=h, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "https://thumb.example/large.jpg"
    assert graph.asked == ["thumb:NEW"]
    from backend.routers import disclaimer as routes
    routes._guide_cache.clear()               # a fresh lookup, as after ten minutes
    graph.thumbs = []
    assert client.get("/api/welcome/video/poster", headers=h,
                      follow_redirects=False).status_code == 404


def test_training_video_lookup_and_cover_are_reused(client, graph, monkeypatch):
    """2026-11-11: four Graph calls per visit made the card's cover and length
    arrive 4-5 s late on production. They are reused for ten minutes."""
    from backend.routers import disclaimer as routes
    h = easyauth_headers("ann@ptc.com")
    calls = []
    real = graph.list_children
    monkeypatch.setattr(graph, "list_children", lambda *a, **k: calls.append(a) or real(*a, **k))
    for _ in range(3):
        assert client.get("/api/welcome/video/info", headers=h).json() == {"duration_seconds": 182}
        assert client.get("/api/welcome/video/poster", headers=h,
                          follow_redirects=False).status_code == 302
    assert len(calls) == 2                      # root, then the folder: once
    assert graph.asked == ["thumb:NEW"]         # the cover asked once
    # Past the ten minutes, looked up again.
    monkeypatch.setattr(routes.time, "monotonic", lambda: 10 ** 9)
    client.get("/api/welcome/video/info", headers=h)
    assert len(calls) == 4


def test_a_missing_training_video_is_not_remembered(client, graph):
    h = easyauth_headers("ann@ptc.com")
    graph.folder = False
    assert client.get("/api/welcome/video/info", headers=h).status_code == 404
    graph.folder = True
    assert client.get("/api/welcome/video/info", headers=h).status_code == 200
