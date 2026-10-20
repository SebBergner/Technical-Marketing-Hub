"""The Hub Tasks list: a row for each thing waiting for a person
(backend/integrations/graph/hub_tasks.py, 2026-10-15)."""
from __future__ import annotations

import json

import pytest

from backend.config import settings
from backend.integrations.graph import hub_tasks
from tests.test_access_requests import ANN, ask
from tests.test_access_requests import client as access_client  # noqa: F401 (fixture)
from tests.test_uploads import BOSS, MAKER, sp, start, upload_all  # noqa: F401 (fixture)
from tests.test_uploads import client as upload_client  # noqa: F401 (fixture)


class FakeList:
    """Graph's list items endpoint, enough for hub_tasks."""

    def __init__(self):
        self.rows, self.calls, self.down = {}, [], False

    def resolve_site(self):
        return type("Site", (), {"site_id": "site"})()

    def _request(self, method, url, params=None, json=None):
        self.calls.append((method, url))
        if self.down:
            raise RuntimeError("Graph is down")
        assert url.startswith("/sites/site/lists/Hub%20Tasks/items")
        if method == "GET":
            hub_id = params["$filter"].split("'")[1]
            return {"value": [{"id": i} for i, r in self.rows.items() if r.get("HubId") == hub_id]}
        if method == "POST":
            item_id = str(len(self.rows) + 1)
            self.rows[item_id] = dict(json["fields"])
            return {"id": item_id}
        if method == "PATCH":
            self.rows[url.split("/")[-2]].update(json)
            return {}
        raise AssertionError(method)


@pytest.fixture
def sp_list(monkeypatch):
    monkeypatch.setattr(settings, "hub_tasks_list", "Hub Tasks")
    monkeypatch.setattr(settings, "custom_domain", "dev-tmh.ptcxc.com")
    monkeypatch.setattr(hub_tasks, "flush_soon", lambda repo: None)   # sent by hand below
    return FakeList()


def _repo():
    from backend.deps import get_repo
    return get_repo()


def _rows(fake):
    hub_tasks.flush(_repo(), client=fake)
    return list(fake.rows.values())


def test_an_upload_waiting_for_review_is_a_row_closed_when_published(upload_client, sp, sp_list):
    record = start(upload_client).json()
    upload_all(upload_client, sp, record)
    upload_client.post(f"/api/uploads/{record['id']}/finish", headers=MAKER)
    [row] = _rows(sp_list)
    assert row["Title"] == "Review: Creo Sheetmetal Kit"
    assert (row["TaskType"], row["TaskStatus"]) == ("Upload review", "Open")
    assert row["RequestedBy"] == "maker@ptc.com" and row["HubId"] == f"upload:{record['id']}"
    assert row["HubLink"] == "https://dev-tmh.ptcxc.com/admin#review"
    assert "DecidedBy" not in row, "nothing empty is written to a new row"

    upload_client.post(f"/api/uploads/{record['id']}/publish", json={}, headers=BOSS)
    [row] = _rows(sp_list)
    assert (row["TaskStatus"], row["DecidedBy"]) == ("Done", "boss@ptc.com")
    assert len(row["DecidedAt"]) == 10, "a date"
    assert [m for m, _ in sp_list.calls].count("POST") == 1, "the same row, updated"


def test_send_back_and_resubmit_reopen_the_same_row(upload_client, sp, sp_list):
    record = start(upload_client).json()
    upload_all(upload_client, sp, record)
    upload_client.post(f"/api/uploads/{record['id']}/finish", headers=MAKER)
    _rows(sp_list)
    upload_client.post(f"/api/uploads/{record['id']}/send-back",
                       json={"note": "Segment should be PLM"}, headers=BOSS)
    [row] = _rows(sp_list)
    assert row["TaskStatus"] == "Rejected" and "Sent back: Segment should be PLM" in row["Details"]
    upload_client.post(f"/api/uploads/{record['id']}/resubmit",
                       json={"values": {"title": "Creo Sheetmetal Kit",
                                        **{k: v for k, v in json.loads(json.dumps(
                                            record["values"])).items() if k != "title"},
                                        "segment": ["PLM"]}}, headers=MAKER)
    [row] = _rows(sp_list)
    assert (row["TaskStatus"], row["DecidedBy"]) == ("Open", ""), "text clears with ''"
    assert len(row["DecidedAt"]) == 10, "a date cannot be cleared through Graph; it stays"
    assert row["Details"].endswith("Resubmitted after being sent back.")


def test_published_on_submission_is_never_a_to_do(upload_client, sp, sp_list):
    record = start(upload_client, who=BOSS).json()           # Create without review
    upload_all(upload_client, sp, record, who=BOSS)
    done = upload_client.post(f"/api/uploads/{record['id']}/finish", headers=BOSS).json()
    assert done["status"] == "published"
    assert _rows(sp_list) == [] and sp_list.calls == []


def test_an_access_request_is_a_row_closed_by_the_decision(access_client, sp_list):
    pending = ask(access_client).json()["pending"]
    [row] = _rows(sp_list)
    assert row["Title"] == "Make Internal: Bobcat" and row["TaskType"] == "Access request"
    assert row["HubLink"] == "https://dev-tmh.ptcxc.com/#/asset/bobcat"
    assert row["Details"] == "Customer data in the recording"
    access_client.post(f"/api/admin/access-requests/{pending['id']}/decision",
                       json={"approve": False, "note": "Not customer data"}, headers=BOSS)
    [row] = _rows(sp_list)
    assert (row["TaskStatus"], row["DecidedBy"]) == ("Rejected", "boss@ptc.com")
    assert row["Details"].endswith("Decision note: Not customer data")


def test_withdrawn_by_the_requester(access_client, sp_list):
    pending = ask(access_client).json()["pending"]
    _rows(sp_list)
    access_client.post(f"/api/assets/bobcat/access-requests/{pending['id']}/withdraw", headers=ANN)
    [row] = _rows(sp_list)
    assert row["TaskStatus"] == "Withdrawn"


def test_graph_down_never_stops_the_hub_and_the_row_goes_later(access_client, sp_list):
    sp_list.down = True
    assert ask(access_client).status_code == 201, "the request itself is the Hub's"
    out = hub_tasks.flush(_repo(), client=sp_list)
    assert out["failed"] == 1 and hub_tasks.unsent(_repo()) == 1
    sp_list.down = False
    [row] = _rows(sp_list)
    assert row["TaskStatus"] == "Open" and hub_tasks.unsent(_repo()) == 0


def test_a_lost_create_answer_finds_the_row_rather_than_making_two(access_client, sp_list):
    pending = ask(access_client).json()["pending"]
    sp_list.rows["7"] = {"HubId": f"access:{pending['id']}", "TaskStatus": "Open"}
    _rows(sp_list)
    assert len(sp_list.rows) == 1 and "POST" not in [m for m, _ in sp_list.calls]


def test_switched_off_writes_nothing(access_client, sp_list, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "hub_tasks_list", "")
    ask(access_client)
    assert hub_tasks.flush(_repo(), client=sp_list) == {"sent": 0, "failed": 0, "skipped": 0}
    assert not (tmp_path / "owned" / "hub_tasks.json").exists()


def test_an_api_upload_for_someone_names_them_in_the_list(monkeypatch):
    monkeypatch.setattr(settings, "custom_domain", "tmh.ptcxc.com")
    row = hub_tasks.upload_fields({"id": "u1", "status": "pending", "title": "Kit",
                                   "uploaded_by": "token:AMP UI",
                                   "submitted_by": "ann@ptc.com", "values": {}})
    assert row["RequestedBy"] == "ann@ptc.com"
    assert "Uploaded through API token AMP UI." in row["Details"]
