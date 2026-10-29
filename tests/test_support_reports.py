"""Reports about content and Get help, sent to each segment's owners (A2, 2026-10-28)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend import access
from backend.auth import AuthMode
from backend.config import settings
from backend.integrations.graph import hub_tasks
from backend.services import support_reports as sr
from tests.test_auth import easyauth_headers

BOSS, ANN = easyauth_headers("boss@ptc.com"), easyauth_headers("ann@ptc.com")
PARTNER = easyauth_headers("p@partner.it")


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import app
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password", "")
    monkeypatch.setattr(settings, "hub_admin_emails", "boss@ptc.com")
    (tmp_path / "mirror").mkdir()
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps([
        {"id": i, "type": "video", "title": f"Clip {i}", "segment": seg}
        for i, seg in (("cad", "CAD"), ("plm", "PLM"), ("iot", "IoT"))]), encoding="utf-8")
    rows = []
    monkeypatch.setattr(hub_tasks, "note_report", lambda repo, record: rows.append(
        hub_tasks.report_fields(record)))
    monkeypatch.setattr(sr, "_status_cache", {"at": 0.0, "value": None})
    monkeypatch.setattr(hub_tasks, "read_statuses", lambda prefix: {})
    access.create_group("Viewers", "", ["view_hub", "view_admin"], ["vic@ptc.com"], "test")
    c = TestClient(app, base_url="http://localhost")
    c.rows = rows
    return c


def owners(client, segment, people, who=BOSS):
    return client.put(f"/api/admin/report-owners/{segment}", json={"owners": people}, headers=who)


def report(client, who, asset_id=None, category=None, details="The UI is from 2019"):
    if category is None:
        category = sr.DEMO_CATEGORIES[1] if asset_id else sr.HUB_CATEGORIES[1]
    return client.post("/api/support/reports", headers=who,
                       json={"asset_id": asset_id, "category": category, "details": details})


def test_only_manage_users_changes_owners_and_owners_are_ptc_staff(client):
    vic = easyauth_headers("vic@ptc.com")
    assert client.get("/api/admin/report-owners", headers=vic).status_code == 200
    assert owners(client, "CAD", [{"email": "a@ptc.com"}], who=vic).status_code == 403
    r = owners(client, "CAD", [{"email": "p@partner.it"}])
    assert r.status_code == 422 and "PTC" in r.json()["detail"]
    assert owners(client, "Space", [{"email": "a@ptc.com"}]).status_code == 422
    r = owners(client, "CAD", [{"name": "Avi", "email": "Avi@PTC.com"}])
    assert r.json()["owners"] == [{"name": "Avi", "email": "avi@ptc.com", "notify": True}]


def test_a_report_tells_its_segments_owners_and_falls_back_to_general(client):
    owners(client, "CAD", [{"name": "Avi", "email": "avi@ptc.com"},
                           {"name": "Elio", "email": "elio@ptc.com"},
                           {"name": "Off", "email": "off@ptc.com", "notify": False}])
    owners(client, "PLM", [{"name": "Quiet", "email": "q@ptc.com", "notify": False}])
    owners(client, "General", [{"name": "Liwei", "email": "liwei@ptc.com"}])
    for asset in ("cad", "plm", "iot", None):
        assert report(client, ANN, asset).status_code == 200, asset
    cad, plm, iot, help_ = client.rows
    assert cad["NotifyTo"] == "avi@ptc.com; elio@ptc.com" and cad["Segment"] == "CAD"
    assert cad["TaskType"] == "Support request" and cad["Category"] == sr.DEMO_CATEGORIES[1]
    assert cad["RequestedBy"] == "ann@ptc.com" and cad["Title"] == "Report: Clip cad"
    assert cad["HubLink"].endswith("/#/asset/cad")
    assert plm["NotifyTo"] == "liwei@ptc.com" and plm["Segment"] == "PLM", \
        "counted under PLM, told to General, as nobody in PLM is notified"
    assert "nobody is notified for PLM" in plm["Details"]
    assert iot["Segment"] == "General" and help_["Segment"] == "General"
    assert help_["Title"] == "Help: Demo list is out of date"
    segs = {s["segment"]: s for s in client.get("/api/admin/report-owners", headers=BOSS)
            .json()["segments"]}
    assert (segs["CAD"]["total"], segs["PLM"]["total"], segs["General"]["total"]) == (1, 1, 2)
    assert segs["PLM"]["notified"] is False and segs["CAD"]["notified"] is True


def test_a_demo_and_the_hub_each_have_their_own_categories(client):
    """Liwei 2026-10-28: a demo's page asks about the demo, Get help about the Hub."""
    assert report(client, ANN, category="Broken").status_code == 422
    assert report(client, ANN, details="").status_code == 422
    assert report(client, ANN, asset_id="nope").status_code == 404
    assert report(client, ANN, "cad", category="Hub won\u2019t load or is slow").status_code == 422
    assert report(client, ANN, None,
                  category="File won\u2019t open or is missing").status_code == 422
    assert report(client, ANN, None, category="Other").status_code == 200
    opts = client.get("/api/support/options", headers=ANN).json()
    assert "Details are wrong (product, date, owner)" in opts["demo"]
    assert "Can\u2019t find content" in opts["hub"] and "Can\u2019t find content" not in opts["demo"]


def test_share_feedback_offers_more_than_problems_in_groups(client):
    """Liwei 2026-10-28: what went well and ideas first, then the problems."""
    opts = client.get("/api/support/options", headers=ANN).json()
    groups = opts["demo_groups"]
    assert [g["label"] for g in groups][:2] == ["Share something", "Something isn\u2019t right"]
    assert [c for g in groups for c in g["items"]] == opts["demo"]
    assert report(client, ANN, "cad", category="This demo helped me").status_code == 200


def test_a_partner_reports_anonymously_and_sees_only_their_own(client, monkeypatch):
    rid = report(client, PARTNER, "cad").json()["id"]
    report(client, ANN, "plm")
    assert client.rows[0]["RequestedBy"] == "partner"
    [own] = client.get("/api/support/reports/mine", headers=PARTNER).json()["items"]
    assert own["id"] == rid and own["status"] == "Open" and "reported_by" not in own
    listed = client.get("/api/admin/report-owners/CAD/reports", headers=BOSS).json()["items"]
    assert listed[0]["reported_by"] == "partner"
    stored = (settings.data_dir + "/owned/support_reports.json")
    assert "partner.it" not in open(stored, encoding="utf-8").read()
    # Handled in SharePoint: the status comes back from the list.
    monkeypatch.setattr(hub_tasks, "read_statuses", lambda prefix: {rid: "Done"})
    monkeypatch.setattr(sr, "_status_cache", {"at": 0.0, "value": None})
    assert client.get("/api/support/reports/mine", headers=PARTNER).json()["items"][0][
        "status"] == "Done"
    assert len(client.get("/api/support/reports/mine", headers=ANN).json()["items"]) == 1


def test_statuses_are_read_back_by_hub_id(monkeypatch):
    monkeypatch.setattr(settings, "hub_tasks_list", "Hub Tasks")

    class Fake:
        def resolve_site(self):
            return type("S", (), {"site_id": "s"})()

        def _paged(self, url, params=None):
            return [{"id": "1", "fields": {"HubId": "report:abc", "TaskStatus": "Done"}},
                    {"id": "2", "fields": {"HubId": "upload:x", "TaskStatus": "Open"}}]
    assert hub_tasks.read_statuses("report:", client=Fake()) == {"abc": "Done"}
