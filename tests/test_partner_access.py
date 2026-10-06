"""Partners download only where SharePoint lets the partner group read (2026-10-06)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.auth import CurrentUser, DEV_PRINCIPAL
from backend.config import settings
from backend.integrations.graph.partner_access import partner_can_download
from backend.repositories.json_repo import JsonAssetRepository

VISITORS = "GPX TDD Scalable Demo Catalog  Visitors"     # as SharePoint spells it


def perm(name, *roles):
    return {"roles": list(roles), "grantedToV2": {"siteGroup": {"displayName": name}}}


# ─────────────────────────────────────────────── who is a partner
def test_staff_by_domain_partners_by_domain_or_guest_token():
    assert not CurrentUser(email="liwchen@ptc.com").is_partner
    assert CurrentUser(email="abertagna@parametricdesign.it").is_partner
    assert CurrentUser(email="someone@ptc.com", external=True).is_partner, "a guest token decides"
    assert not DEV_PRINCIPAL.is_partner, "local development is never a partner"


# ─────────────────────────────────────────────── the SharePoint rule
def test_read_lets_partners_download_view_only_or_nothing_does_not():
    assert partner_can_download([perm(VISITORS, "read")])
    assert partner_can_download([perm("GPX TDD Scalable Demo Catalog Visitors", "read")]), "spacing"
    assert not partner_can_download([perm(VISITORS, "restrictedView")]), "View Only blocks downloads"
    assert not partner_can_download([perm("GPX TDD Scalable Demo Catalog  Members", "write")]), \
        "the Lamborghini case: Visitors removed"


# ─────────────────────────────────────────────── the endpoints
@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    (tmp_path / "mirror").mkdir()
    rows = [{"id": "lambo", "type": "vdk", "title": "Lamborghini IPL", "products": ["Creo"],
             "source_item_id": "F-LAMBO",
             "resources": [{"name": "Lambo.mp4", "kind": "video", "item_id": "I-1"}]},
            {"id": "bobcat", "type": "vdk", "title": "Bobcat IPL", "products": ["Creo"],
             "source_item_id": "F-BOBCAT",
             "resources": [{"name": "Bobcat.mp4", "kind": "video", "item_id": "I-2"}]}]
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps(rows), encoding="utf-8")
    r = JsonAssetRepository(str(tmp_path))
    r.replace_partner_access({"F-LAMBO": True, "F-BOBCAT": False})
    return r


def client_as(monkeypatch, user):
    from app import app
    from backend.auth import get_current_user
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, base_url="http://localhost")


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    from app import app
    app.dependency_overrides.clear()


def test_a_partner_sees_the_names_of_closed_files_but_cannot_open_them(repo, monkeypatch):
    client = client_as(monkeypatch, CurrentUser(email="p@partner.it", is_authenticated=True))
    lambo = client.get("/api/assets/lambo").json()
    assert lambo["files_locked"] is True and lambo["partner_restricted"] is True
    assert [f["name"] for f in lambo["resources"]] == ["Lambo.mp4"]
    assert lambo["resources"][0]["item_id"] is None
    assert client.get("/api/assets/lambo/files/I-1/download", follow_redirects=False).status_code == 403
    assert client.get("/api/assets/lambo/files/I-1/preview", follow_redirects=False).status_code == 403
    bobcat = client.get("/api/assets/bobcat").json()
    assert bobcat["files_locked"] is False and bobcat["resources"][0]["item_id"] == "I-2"
    hit = client.get("/api/assets/advanced-search", params={"q": "lambo"}).json()["items"][0]
    assert hit["files"][0]["item_id"] is None


def test_ptc_staff_are_not_affected(repo, monkeypatch):
    client = client_as(monkeypatch, CurrentUser(email="liwchen@ptc.com", is_authenticated=True))
    lambo = client.get("/api/assets/lambo").json()
    assert lambo["files_locked"] is False and lambo["resources"][0]["item_id"] == "I-1"


def test_a_failed_scan_keeps_a_closed_folder_closed(repo):
    from backend.integrations.graph import partner_access as pa

    class Drive:
        drive_id = "D"

    class Client:
        def resolve_site(self, url=None): return None
        def find_drive(self, site_id, name): return Drive()
        def _request(self, method, url, **kw):
            if "F-LAMBO" in url:
                raise RuntimeError("HTTP 503 from Graph")
            return {"value": [perm(VISITORS, "read")]}

    class Site:
        site_id = "S"

    result = pa.sync_partner_access(Client(), repo, Site())
    assert repo.partner_access() == {"F-LAMBO": True, "F-BOBCAT": False}
    assert result.kept_from_last_time == 1 and result.restricted == 1
