"""PTC Only is never customer facing (Seb, Elio, 2026-10-28)."""
from __future__ import annotations

import pytest

from backend import access
from backend.config import settings
from backend.repositories.json_repo import JsonAssetRepository
from tests.test_metadata_edit import ANN, EDITOR, client, fake  # noqa: F401


@pytest.fixture
def manager(client):
    access.create_group("Managers", "", ["view_hub", "edit_metadata", "manage_content_access",
                                         "review_content"], ["editor@ptc.com"], "test")
    return client


def test_making_a_demo_ptc_only_writes_customer_facing_no(manager, fake):
    r = manager.put("/api/assets/kit/access", headers=EDITOR, json={"level": "internal"})
    assert r.status_code == 200, r.text
    (folder, fields, _), = fake.writes
    assert folder == "folder-1" and fields == {"Customer_x0020_Facing": False}
    shown = manager.get("/api/assets/kit", headers=ANN).json()
    assert (shown["internal"], shown["customer_facing"]) == (True, False)


def test_opening_it_again_leaves_customer_facing_as_it_is(manager, fake):
    manager.put("/api/assets/kit/access", headers=EDITOR, json={"level": "internal"})
    manager.put("/api/assets/kit/access", headers=EDITOR, json={"level": "open"})
    assert len(fake.writes) == 1
    assert manager.get("/api/assets/kit", headers=ANN).json()["customer_facing"] is False


def test_already_no_is_not_written_again(manager, fake):
    fake.fields["Customer_x0020_Facing"] = False
    manager.put("/api/assets/kit/access", headers=EDITOR, json={"level": "internal"})
    assert fake.writes == []


def test_sharepoint_failing_refuses_the_change(manager, fake):
    from backend.integrations.graph.client import GraphError

    def broken(*a, **kw):
        raise GraphError("down")
    fake.update_list_item_fields = broken
    r = manager.put("/api/assets/kit/access", headers=EDITOR, json={"level": "internal"})
    assert r.status_code == 502
    assert manager.get("/api/assets/kit", headers=ANN).json()["internal"] is False


def test_a_demo_the_hub_does_not_write_only_shows_no(manager, fake):
    r = manager.put("/api/assets/cons/access", headers=EDITOR, json={"level": "internal"})
    assert r.status_code == 200, r.text
    assert fake.writes == []
    assert manager.get("/api/assets/cons", headers=ANN).json()["customer_facing"] is False


def test_the_editor_locks_it_and_saving_writes_no(manager, fake):
    JsonAssetRepository(settings.data_dir).set_access("kit", "internal", "user:x@ptc.com")
    form = manager.get("/api/assets/kit/metadata", headers=EDITOR).json()
    assert form["values"]["customer_facing"] is False and "customer_facing" in form["locked"]
    r = manager.put("/api/assets/kit/metadata", headers=EDITOR, json={
        "etag": '"1"', "values": {"customer_facing": True, "description": "Old text"}})
    assert r.status_code == 200, r.text
    assert r.json()["changed"] == ["customer_facing"]
    assert fake.writes[-1][1] == {"Customer_x0020_Facing": False}


def test_an_open_demo_is_not_locked(manager, fake):
    form = manager.get("/api/assets/kit/metadata", headers=EDITOR).json()
    assert form["locked"] == {} and form["values"]["customer_facing"] is True


def test_a_folder_closed_in_sharepoint_but_customer_facing_is_on_the_data_clean_list(
        manager, fake):
    repo = JsonAssetRepository(settings.data_dir)
    repo.replace_partner_access({"folder-1": True})
    assert repo.get("kit").customer_facing is False
    rows = manager.get("/api/reports/content-to-review", headers=EDITOR).json()["items"]
    kit, = [r for r in rows if r["asset_id"] == "kit"]
    assert "customer_facing" in kit["missing"]
