"""Uploads through the Hub (2026-10-15): metadata first, new folders only,
files confirmed, review before listing. SharePoint is faked at the
upload_writer seam; the real calls are migration_writer's, proven earlier."""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from backend import access
from backend.auth import AuthMode
from backend.config import settings
from backend.integrations.graph import upload_writer as uw
from backend.services import upload_targets as ut
from tests.test_auth import easyauth_headers

BOSS = easyauth_headers("boss@ptc.com")          # administrator: uploads and reviews
ANN = easyauth_headers("ann@ptc.com")            # PTC employee: neither
PARTNER = easyauth_headers("p@partner.it")

CHOICES = {"Segment": ["CAD", "PLM"], "Language": ["English", "German (Germany)"],
           "Owned_x0020_By": ["Technical Demonstration Development"],
           "VideoType": ["Technical Overview"], "VideoSubtype": ["Feature"],
           "products": ["Creo", "Windchill"]}


class FakeSharePoint:
    def __init__(self):
        self.folders = {"Existing Kit"}
        self.created, self.sessions, self.written, self.items = [], [], [], {}

    def install(self, monkeypatch):
        def resolve(client, spec, fresh=False):
            return uw.Target(spec=spec, site_id="s", drive_id="d-" + spec.key, list_id="l",
                             demo_content_type_id="0x0120", product_note_field="Product_0",
                             choices=CHOICES, terms=None)
        monkeypatch.setattr(uw, "resolve", resolve)
        monkeypatch.setattr(uw, "name_taken", lambda c, t, name: name in self.folders)

        def create_folder(c, t, name):
            self.folders.add(name)
            self.created.append((t.spec.library, name))
            return {"id": "folder-" + name.replace(" ", "-"), "webUrl": "https://sp/" + name}
        monkeypatch.setattr(uw, "create_folder", create_folder)
        monkeypatch.setattr(uw, "ensure_subfolders",
                            lambda c, t, folder, path: folder + "/" + "/".join(path.split("/")[:-1]))

        def session(c, t, parent, filename):
            self.sessions.append((parent, filename))
            return {"upload_url": "https://upload/" + filename, "expires": None}
        monkeypatch.setattr(uw, "upload_session", session)
        monkeypatch.setattr(uw, "file_item", lambda c, t, item_id: self.items.get(item_id) or {})
        monkeypatch.setattr(uw, "write_metadata",
                            lambda c, t, folder, fields, note: self.written.append((folder, fields)))
        self.previews = []
        monkeypatch.setattr(uw, "mark_preview",
                            lambda c, t, item_id: self.previews.append(item_id))
        import backend.routers.uploads as router
        monkeypatch.setattr(router, "get_graph_client", lambda: object())
        self.syncs = []
        monkeypatch.setattr(router, "_sync_soon", lambda repo, actor: self.syncs.append(actor))


@pytest.fixture
def sp(monkeypatch):
    fake = FakeSharePoint()
    fake.install(monkeypatch)
    return fake


@pytest.fixture
def client(tmp_path, monkeypatch, sp):
    from app import app
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password", "")
    monkeypatch.setattr(settings, "hub_admin_emails", "boss@ptc.com")
    (tmp_path / "mirror").mkdir()
    (tmp_path / "mirror" / "sharepoint.json").write_text("[]", encoding="utf-8")
    return TestClient(app, base_url="http://localhost")


KIT = {"title": "Creo Sheetmetal Kit", "description": "Sheetmetal design end to end.",
       "products": ["Creo"], "segment": ["CAD"], "customer_facing": True,
       "contains_audio": False, "original_publish_date": "2026-09-01",
       "language": "English", "owned_by": "Technical Demonstration Development"}
FILES = [{"path": "Videos/Overview_CF.mp4", "size": 1000},
         {"path": "Script.docx", "size": 20}]


def start(client, values=KIT, files=FILES, who=BOSS, target="demo_catalog", kind="ldk"):
    return client.post("/api/uploads", json={"target": target, "kind": kind, "values": values,
                                             "files": files}, headers=who)


def upload_all(client, sp, record, who=BOSS):
    for i, f in enumerate(record["files"]):
        s = client.post(f"/api/uploads/{record['id']}/files/{i}/session", headers=who).json()
        assert s["upload_url"].startswith("https://upload/")
        item = f"item-{i}"
        sp.items[item] = {"id": item, "size": f["size"], "name": f["path"].rsplit("/", 1)[-1]}
        r = client.post(f"/api/uploads/{record['id']}/files/{i}/done", json={"item_id": item},
                        headers=who)
        assert r.status_code == 200, r.text


def test_metadata_is_required_before_anything_is_created(client, sp):
    r = start(client, values={**KIT, "description": "", "segment": [], "customer_facing": None})
    assert r.status_code == 422
    for word in ("Description", "Segment", "Customer facing"):
        assert word in r.json()["detail"]
    assert sp.created == [], "no folder for an incomplete form"


def test_choices_come_from_the_library_and_dates_cannot_be_future(client, sp):
    future = (date.today() + timedelta(days=3)).isoformat()
    r = start(client, values={**KIT, "segment": ["Aerospace"], "original_publish_date": future})
    assert r.status_code == 422
    assert "Aerospace" in r.json()["detail"] and "future" in r.json()["detail"]


def test_an_existing_name_is_refused_never_merged(client, sp):
    r = start(client, values={**KIT, "title": "Existing Kit"})
    assert r.status_code == 409 and sp.created == []


def test_only_upload_content_starts_one_and_never_a_partner(client, sp):
    assert start(client, who=ANN).status_code == 403
    access.update_group(access.PARTNERS, "t", permissions=["view_hub", "upload_content"])
    assert start(client, who=PARTNER).status_code == 403, "partners never upload"


def test_a_video_upload_is_exactly_one_video(client, sp):
    video = {k: v for k, v in KIT.items() if k not in ("language", "owned_by")}
    video.update(title="Creo Teaser", video_type="Technical Overview")
    r = start(client, values=video, target="demo_video", kind="video", files=FILES)
    assert r.status_code == 422 and "exactly one video" in r.json()["detail"]
    r = start(client, values=video, target="demo_video", kind="video",
              files=[{"path": "Creo Teaser.mp4", "size": 10}])
    assert r.status_code == 201 and sp.created == [("Demo Video", "Creo Teaser")]


def test_the_whole_flow_hidden_until_published(client, sp, tmp_path):
    r = start(client)
    assert r.status_code == 201, r.text
    record = r.json()
    assert sp.created == [("Demo Catalog", "Creo Sheetmetal Kit")]
    assert client.post(f"/api/uploads/{record['id']}/finish", headers=BOSS).status_code == 422, \
        "not before every file is in"
    upload_all(client, sp, record)
    assert sp.sessions[0] == ("folder-Creo-Sheetmetal-Kit/Videos", "Overview_CF.mp4"), \
        "sub-folders kept"
    done = client.post(f"/api/uploads/{record['id']}/finish", headers=BOSS).json()
    assert done["status"] == "pending"
    folder, fields = sp.written[0]
    assert fields["Demo_x0020_Type"] == "Live Demo Kit" and fields["Segment"] == ["CAD"]
    assert fields["DocumentSetDescription"] == KIT["description"]
    dates = json.loads((tmp_path / "owned" / "publish_dates.json").read_text())
    assert dates[folder] == "2026-09-01", "Demo Catalog has no date column: the Hub keeps it"

    # Indexed by a sync, it stays out of every list until published.
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps([
        {"id": "creo-sheetmetal-kit", "type": "ldk", "title": "Creo Sheetmetal Kit",
         "products": ["Creo"], "source_item_id": folder, "uploaded_at": "2026-10-15"}]),
        encoding="utf-8")
    ids = lambda who: [a["id"] for a in client.get("/api/assets", headers=who).json()["items"]]
    assert ids(BOSS) == [] and ids(ANN) == []
    assert client.get("/api/assets/creo-sheetmetal-kit", headers=ANN).status_code == 404
    page = client.get("/api/assets/creo-sheetmetal-kit", headers=BOSS).json()
    assert page["upload_review"] == "pending" and page["uploaded_at"] == "2026-09-01"

    published = client.post(f"/api/uploads/{record['id']}/publish", json={}, headers=BOSS)
    assert published.json()["status"] == "published"
    assert ids(ANN) == ["creo-sheetmetal-kit"]


def test_send_back_then_resubmit_with_corrected_metadata(client, sp):
    record = start(client).json()
    upload_all(client, sp, record)
    client.post(f"/api/uploads/{record['id']}/finish", headers=BOSS)
    assert client.post(f"/api/uploads/{record['id']}/send-back", json={"note": ""},
                       headers=BOSS).status_code == 422, "say what needs changing"
    back = client.post(f"/api/uploads/{record['id']}/send-back",
                       json={"note": "Segment should be PLM"}, headers=BOSS).json()
    assert (back["status"], back["note"]) == ("sent_back", "Segment should be PLM")
    renamed = client.post(f"/api/uploads/{record['id']}/resubmit",
                          json={"values": {**KIT, "title": "New Name"}}, headers=BOSS)
    assert renamed.status_code == 422, "the title is the folder name"
    again = client.post(f"/api/uploads/{record['id']}/resubmit",
                        json={"values": {**KIT, "segment": ["PLM"]}}, headers=BOSS).json()
    assert again["status"] == "pending" and sp.written[-1][1]["Segment"] == ["PLM"]


def test_a_file_that_did_not_arrive_whole_is_refused(client, sp):
    record = start(client).json()
    client.post(f"/api/uploads/{record['id']}/files/0/session", headers=BOSS)
    sp.items["short"] = {"id": "short", "size": 999, "name": "Overview_CF.mp4"}
    r = client.post(f"/api/uploads/{record['id']}/files/0/done", json={"item_id": "short"},
                    headers=BOSS)
    assert r.status_code == 422


def test_uploads_are_in_the_admin_log(client, sp):
    record = start(client).json()
    upload_all(client, sp, record)
    client.post(f"/api/uploads/{record['id']}/finish", headers=BOSS)
    log = client.get("/api/admin/admin-log?category=Uploads", headers=BOSS).json()
    actions = [e["action"] for e in log["items"]]
    assert actions[0] == "Finished an upload" and actions[-1] == "Started an upload"


def test_a_future_library_is_one_entry():
    """The interface for libraries added later: an entry in TARGETS."""
    assert set(ut.TARGETS) == {"demo_catalog", "demo_video"}
    with pytest.raises(ut.UploadInvalid):
        ut.target("documents")


def test_a_target_can_be_pointed_at_a_test_library(monkeypatch):
    monkeypatch.setattr(settings, "upload_library_overrides", "demo_video=Gallery_Brightcove_Test")
    assert ut.target("demo_video").library == "Gallery_Brightcove_Test"
    assert ut.target("demo_catalog").library == "Demo Catalog"
    monkeypatch.setattr(settings, "upload_library_overrides", "demo_video=Documents")
    with pytest.raises(ut.UploadInvalid):
        ut.target("demo_video")


def test_product_terms_are_gathered_from_the_library_when_the_term_store_is_closed():
    """2026-10-15: the term store answers 404 to this app, so the products a
    Demo Catalog upload may carry are the terms its demos already use."""
    class Client:
        def _paged(self, url, params):
            yield {"listItem": {"fields": {"Product": [
                {"Label": "Creo Parametric", "TermGuid": "g-1"},
                {"Label": "Windchill PDMLink", "TermGuid": "g-2"}]}}}
            yield {"listItem": {"fields": {"Product": [{"Label": "Creo Parametric",
                                                        "TermGuid": "g-1"}]}}}
            yield {"listItem": {"fields": {}}}
    terms = uw.harvest_terms(Client(), "drive")
    assert terms.labels() == ["Creo Parametric", "Windchill PDMLink"]
    assert terms.get("creo parametric") == ("Creo Parametric", "g-1")


def test_destinations_list_sharepoint_and_the_platforms_still_to_come(client, sp):
    body = client.get("/api/uploads/targets", headers=BOSS).json()
    assert [(p["key"], p["available"]) for p in body["platforms"]] == [
        ("sharepoint", True), ("consensus", False), ("brightcove", False)]
    assert {t["platform"] for t in body["targets"]} == {"sharepoint"}


TWO_VIDEOS = [{"path": "Overview_CF.mp4", "size": 10}, {"path": "Training/Walkthrough.mp4", "size": 20},
              {"path": "Script.docx", "size": 5}]


def test_several_videos_need_a_chosen_preview_which_is_ticked_in_sharepoint(client, sp):
    r = start(client, files=TWO_VIDEOS)
    assert r.status_code == 422 and "preview" in r.json()["detail"]
    assert sp.created == [], "nothing created without the choice"
    r = client.post("/api/uploads", json={"target": "demo_catalog", "kind": "ldk", "values": KIT,
                                          "files": TWO_VIDEOS, "preview": "Training/Walkthrough.mp4"},
                    headers=BOSS)
    assert r.status_code == 201 and r.json()["preview"] == "Training/Walkthrough.mp4"
    record = r.json()
    upload_all(client, sp, record)
    client.post(f"/api/uploads/{record['id']}/finish", headers=BOSS)
    assert sp.previews == ["item-1"], "PreviewVideo ticked on the chosen file only"


def test_one_video_is_the_preview_without_asking(client, sp):
    record = start(client).json()
    assert record["preview"] == "Videos/Overview_CF.mp4"


def test_a_product_no_longer_sold_is_refused_with_the_reason(client, sp):
    """2026-10-15: a test kit with Kepware+ among its products was created and
    published, and never appeared -- the Hub lists nothing touching a divested
    product. The form no longer offers them; the server says why."""
    r = start(client, values={**KIT, "products": ["Creo", "Kepware+", "KEPServerEX"]})
    assert r.status_code == 422 and "Kepware+" in r.json()["detail"]
    assert "no longer sold" in r.json()["detail"] and sp.created == []


def test_retired_segments_are_not_offered():
    from backend.services import taxonomy
    assert {"IoT", "AR"} <= taxonomy.RETIRED_SEGMENTS


def test_publishing_a_demo_the_hub_has_not_read_yet_asks_for_a_sync(client, sp):
    record = start(client).json()
    upload_all(client, sp, record)
    client.post(f"/api/uploads/{record['id']}/finish", headers=BOSS)
    asked = len(sp.syncs)
    client.post(f"/api/uploads/{record['id']}/publish", json={}, headers=BOSS)
    assert len(sp.syncs) == asked + 1, "not indexed yet: publishing asks again"


def test_index_now_is_for_the_reviewer_or_the_uploader(client, sp):
    record = start(client).json()
    assert client.post(f"/api/uploads/{record['id']}/index", headers=ANN).status_code == 403
    assert client.post(f"/api/uploads/{record['id']}/index", headers=BOSS).json() == {"queued": True}
