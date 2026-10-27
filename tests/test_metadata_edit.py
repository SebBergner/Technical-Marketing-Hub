"""Editing a demo on its Details card (A1, Liwei 2026-10-26)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend import access
from backend.auth import AuthMode
from backend.config import settings
from backend.integrations.graph import upload_writer as uw
from backend.services import metadata_edit as me
from backend.services import upload_targets as ut
from tests.test_auth import easyauth_headers

EDITOR = easyauth_headers("editor@ptc.com")
ANN = easyauth_headers("ann@ptc.com")

CHOICES = {"Segment": ["CAD", "PLM"], "Language": ["English", "German (Germany)"],
           "Owned_x0020_By": ["Technical Demonstration Development"],
           "VideoType": ["Technical Overview"], "VideoSubtype": ["Feature"],
           "products": ["Creo", "Windchill"]}

FOLDER = {"DocumentSetDescription": "Old text", "Segment": ["CAD"], "Language": "English",
          "Customer_x0020_Facing": True, "Contains_x0020_Audio": False,
          "OriginalPublishDate": "2024-03-12T00:00:00Z", "Product_x0020_Version": "",
          "Owned_x0020_By": "Technical Demonstration Development",
          "Product": [{"Label": "Creo", "TermGuid": "g1"}], "DemoOwner": ""}


class FakeClient:
    def __init__(self):
        self.fields = dict(FOLDER)
        self.etag = '"1"'
        self.writes, self.puts = [], []

    def get_list_item(self, drive_id, item_id):
        return {"@odata.etag": self.etag, "fields": dict(self.fields)}

    def update_list_item_fields(self, drive_id, item_id, fields, etag=None):
        self.writes.append((item_id, fields, etag))
        return fields

    def _request(self, method, url, **kw):
        self.puts.append((method, url, kw.get("headers")))
        return {"id": "pic-1", "webUrl": "https://sp/Demo Catalog/Kit/Hub thumbnail.jpg"}

    def download_url(self, drive_id, item_id):
        return "https://sp/download?tempauth=x"


@pytest.fixture
def fake(monkeypatch):
    client = FakeClient()
    import backend.routers.uploads as up
    monkeypatch.setattr(up, "_client", lambda: client)

    def target(c, key, fresh=False):
        return uw.Target(spec=ut.TARGETS[key], site_id="s", drive_id="d", list_id="l",
                         demo_content_type_id="0x0120", product_note_field="Product_0",
                         choices=CHOICES, terms=None, has_demo_owner=True,
                         has_thumbnail_flag=True)
    monkeypatch.setattr(up, "_target", target)
    client.syncs = []
    monkeypatch.setattr(up, "_sync_soon", lambda repo, actor: client.syncs.append(actor))
    ticks = []
    monkeypatch.setattr(me.w, "write_fields",
                        lambda c, t, item_id, fields: ticks.append((item_id, fields)))
    client.ticks = ticks
    return client


@pytest.fixture
def client(tmp_path, monkeypatch, fake):
    from app import app
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password", "")
    (tmp_path / "mirror").mkdir()
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps([
        {"id": "kit", "type": "ldk", "title": "Kit", "source": "sharepoint",
         "source_item_id": "folder-1", "products": ["Creo"], "description": "Old text",
         "main_video": "A.mp4",
         "resources": [{"name": "A.mp4", "kind": "video", "item_id": "v1", "preview": True},
                       {"name": "B.mp4", "kind": "video", "item_id": "v2"},
                       {"name": "Old.png", "kind": "image", "item_id": "p0",
                        "hub_thumbnail": True}]}]), encoding="utf-8")
    (tmp_path / "mirror" / "consensus.json").write_text(json.dumps([
        {"id": "cons", "type": "video", "title": "Tour", "source": "consensus",
         "source_item_id": "u1"}]), encoding="utf-8")
    access.create_group("Editors", "", ["view_hub", "edit_metadata"], ["editor@ptc.com"], "test")
    return TestClient(app, base_url="http://localhost")


def test_only_editors_open_the_editor_and_consensus_is_read_only(client):
    assert client.get("/api/assets/kit/metadata", headers=ANN).status_code == 403
    form = client.get("/api/assets/kit/metadata", headers=EDITOR).json()
    keys = [f["key"] for f in form["fields"]]
    assert "title" not in keys and "demo_owner" in keys and "product_version" in keys
    assert form["values"]["products"] == ["Creo"] and form["values"]["segment"] == ["CAD"]
    assert form["values"]["original_publish_date"] == "2024-03-12"
    assert form["etag"] == '"1"' and form["preview"] == "v1"
    r = client.get("/api/assets/cons/metadata", headers=EDITOR)
    assert r.status_code == 422 and "Consensus" in r.json()["detail"]


def test_only_what_changed_is_written_and_shown_at_once(client, fake):
    r = client.put("/api/assets/kit/metadata", headers=EDITOR, json={"etag": '"1"', "values": {
        "description": "New text", "segment": ["CAD"], "product_version": "Creo 12",
        "demo_owner": "Jane.Doe@ptc.com", "customer_facing": True}})
    assert r.status_code == 200, r.text
    assert r.json()["changed"] == ["demo_owner", "description", "product_version"]
    (_, fields, etag), = fake.writes
    assert fields == {"DocumentSetDescription": "New text",
                      "Product_x0020_Version": "Creo 12", ut.OWNER_COLUMN: "jane.doe@ptc.com"}
    assert etag == '"1"' and fake.syncs == ["user:editor@ptc.com"]
    shown = client.get("/api/assets/kit", headers=ANN).json()
    assert (shown["description"], shown["product_version"], shown["demo_owner"]) == \
        ("New text", "Creo 12", "jane.doe@ptc.com"), "before the sync has run"


def test_a_stale_form_or_a_bad_value_is_refused(client, fake):
    fake.etag = '"2"'
    r = client.put("/api/assets/kit/metadata", headers=EDITOR,
                   json={"etag": '"1"', "values": {"description": "x"}})
    assert r.status_code == 409 and not fake.writes
    for values, says in (({"segment": ["Space"]}, "not an option"),
                         ({"segment": []}, "cannot be empty"),
                         ({"demo_owner": "p@partner.it"}, "PTC email")):
        r = client.put("/api/assets/kit/metadata", headers=EDITOR, json={"values": values})
        assert r.status_code == 422 and says in r.json()["detail"], (values, r.text)
    assert not fake.writes


def test_the_preview_video_is_one_tick(client, fake):
    r = client.put("/api/assets/kit/preview-video", headers=EDITOR, json={"item_id": "v2"})
    assert r.status_code == 200
    assert fake.ticks == [("v1", {"PreviewVideo": False}), ("v2", {"PreviewVideo": True})]
    assert client.put("/api/assets/kit/preview-video", headers=EDITOR,
                      json={"item_id": "nope"}).status_code == 422


def test_a_picture_goes_into_the_folder_and_is_the_one_ticked(client, fake):
    r = client.put("/api/assets/kit/thumbnail", headers=EDITOR,
                   files={"file": ("frame.jpg", b"\xff\xd8jpeg", "image/jpeg")})
    assert r.status_code == 200, r.text
    method, url, headers = fake.puts[-1]
    assert method == "PUT" and url.endswith("folder-1:/Hub thumbnail.jpg:/content")
    assert fake.ticks == [("p0", {"HubThumbnail": False}), ("pic-1", {"HubThumbnail": True})]
    assert client.put("/api/assets/kit/thumbnail", headers=EDITOR,
                      files={"file": ("x.gif", b"GIF8", "image/gif")}).status_code == 422
    assert client.get("/api/assets/kit/files/v1/frame-source",
                      headers=EDITOR).json()["url"].startswith("https://sp/")
    assert client.get("/api/assets/kit/files/v1/frame-source", headers=ANN).status_code == 403


def test_edits_lie_over_the_mirror_only_until_a_later_sync():
    rows = [{"id": "kit", "description": "old"}, {"id": "video-x", "description": "v"}]
    edits = {"kit": {"at": "2026-10-26T10:00:00", "values": {"description": "new"}},
             "video-x": {"at": "2026-10-26T10:00:00", "values": {"description": "new v"}}}
    out = me.apply_edits(rows, edits, {"sharepoint": "2026-10-26T09:00:00",
                                       "demo_video": "2026-10-26T11:00:00"})
    assert [r["description"] for r in out] == ["new", "v"]


def test_editing_a_video_applies_the_subtype_rules():
    """A15: a customer video without its customer must name it on its next
    edit; a Release video keeps Release; Other stores N/A (2026-10-27)."""
    spec = ut.DEMO_VIDEO
    target = uw.Target(spec=spec, site_id="s", drive_id="d", list_id="l",
                       demo_content_type_id="0x0120", product_note_field=None,
                       choices={**CHOICES, "VideoType": ["Technical Overview", "Other"],
                                "VideoSubtype": ["Customer", "Feature", "Release", "N/A"]},
                       terms=None)
    current = {"video_type": "Technical Overview", "video_subtype": "Customer",
               "named_customer": None, "description": "d"}
    with pytest.raises(ut.UploadInvalid, match="Named customer"):
        me.changes(spec, target, {"description": "new"}, current)
    release = {**current, "video_subtype": "Release"}
    assert me.changes(spec, target, {"description": "new"}, release) == {"description": "new"}
    assert me.changes(spec, target, {"video_type": "Other"}, release) == \
        {"video_type": "Other", "video_subtype": "N/A"}


def test_what_the_hub_assumes_is_said_not_filled_in(client, fake, tmp_path):
    """Liwei, 2026-10-28: Bobcat showed Customer facing Yes while SharePoint
    had nothing -- the editor leaves it blank and says what the Hub shows."""
    fake.fields.pop("Customer_x0020_Facing")
    rows = json.loads((tmp_path / "mirror" / "sharepoint.json").read_text(encoding="utf-8"))
    rows[0].update(customer_facing=True, assumed=["customer_facing"])
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps(rows), encoding="utf-8")
    form = client.get("/api/assets/kit/metadata", headers=EDITOR).json()
    assert form["values"]["customer_facing"] is None
    assert form["hub_shows"]["customer_facing"]["value"] == "Yes"
    assert "file names" in form["hub_shows"]["customer_facing"]["why"]
    assert "description" not in form["hub_shows"], "SharePoint has one"
    assert client.get("/api/assets/kit", headers=EDITOR).json()["assumed"] == ["customer_facing"]
    # Not for visitors or partners (Liwei, 2026-10-28).
    assert client.get("/api/assets/kit", headers=ANN).json()["assumed"] == []
    assert "assumed" not in client.get("/api/assets", headers=EDITOR).json()["items"][0]
    r = client.put("/api/assets/kit/metadata", headers=EDITOR,
                   json={"values": {"customer_facing": False}})
    assert r.status_code == 200, r.text
    shown = client.get("/api/assets/kit", headers=EDITOR).json()
    assert shown["customer_facing"] is False and shown["assumed"] == []


def test_no_is_a_change_from_yes_and_from_empty(client, fake):
    """A Yes/No set to No was once judged 'unchanged' (False read as empty)."""
    r = client.put("/api/assets/kit/metadata", headers=EDITOR,
                   json={"values": {"customer_facing": False, "contains_audio": False}})
    assert r.json()["changed"] == ["customer_facing"], "audio was already No"
    assert fake.writes[-1][1] == {"Customer_x0020_Facing": False}
