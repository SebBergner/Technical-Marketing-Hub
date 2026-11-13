"""Titles follow the newest migration sheet (Liwei, 2026-11-12).

A video already in Demo Video or GXC Video is never uploaded again, but when
the sheet's title differs from its folder name the preview lists it and the
run renames it: the folder, and the video file named after the old title.
A Brightcove ID is looked for in both libraries and in _Archive, so the same
video is never uploaded twice (Lamborghini Technical Overview was, once).
A Demo Video's id is made from its folder name, so a rename gives it a new
id: the next sync moves the Hub's own data to it, My Hub's files included,
and old links follow it.
"""
from __future__ import annotations

import json
import os

import httpx
import pytest

from backend.config import settings
from backend.models import Asset
from backend.repositories.json_repo import JsonAssetRepository
from backend.services import brightcove_runner as run
from backend.services.brightcove_migration import batches_dir
from tests.test_brightcove_runner import DRIVE
from tests.test_brightcove_source import VIDEO
from tests.test_migration_jobs import GOOD, LIB, admin, body, client, isolated, upload  # noqa: F401

OLD = "Tech Walkthrough Audio - Change"            # GOOD's Video Title
NEW = "Change Management"                           # GOOD's Proposed Title


def folder(name, bcid, item_id="F1"):
    return {"id": item_id, "name": name, "folder": {"childCount": 2},
            "listItem": {"fields": {"BrightcoveID": bcid}}}


def serve(graph, items, children=(), archive=()):
    """Extend the jobs' fake Graph with what a rename reads and writes."""
    graph.existing = list(items) + ([{"id": "ARCH", "name": "_Archive", "folder": {}}]
                                    if archive else [])
    base = graph.handler
    names = {i["id"]: i for i in [*items, *archive]}

    def handler(request):
        path, method = request.url.path, request.method
        prefix = f"/drives/{DRIVE}/items/"
        if prefix in path:
            rest = path.split(prefix, 1)[1]
            body_ = json.loads(request.content) if request.content else None
            graph.calls.append((method, path, body_))
            if rest == "ARCH/children":
                return httpx.Response(200, json={"value": list(archive)})
            if rest.endswith("/children"):
                return httpx.Response(200, json={"value": list(children)})
            if method == "PATCH":
                return httpx.Response(200, json={"id": rest, "name": body_["name"]})
            if method == "GET" and rest in names:
                return httpx.Response(200, json=names[rest])
        return base(request)

    graph.handler = handler


def renames_written(graph):
    return [(p.rsplit("/", 1)[1], b["name"]) for m, p, b in graph.calls
            if m == "PATCH" and "/items/" in p and b and "name" in b]


# ─────────────────────────────────────────────────────────────── the plan
def rec(title, bcid="1", problems=()):
    r = run.VideoRecord(row=2, brightcove_id=bcid, title=title, description=None, segments=[],
                        products=[], customer_facing=True, contains_audio=None,
                        original_publish_date=None, gallery_url=None, source="brightcove",
                        filename="")
    r.problems = list(problems)
    return r


def test_only_a_differing_title_is_renamed():
    lib = ("Demo Video", {"1": folder("A: B", "1"), "2": folder("Same", "2", "F2")},
           {"a: b", "same"})
    out = run.plan_renames([rec("A: B"), rec("Same", "2")], [lib])
    # Compared as folder names: the sheet's "A: B" becomes "A - B".
    assert [(x["from"], x["to"], x["status"]) for x in out] == [("A: B", "A - B", "rename")]


def test_a_name_another_folder_has_blocks_the_rename():
    lib = ("Demo Video", {"1": folder("Old", "1")}, {"old", "taken"})
    [x] = run.plan_renames([rec("Taken")], [lib])
    assert x["status"] == "blocked" and "already has another folder" in x["reason"]


def test_a_change_of_case_only_is_not_blocked_by_itself():
    lib = ("Demo Video", {"1": folder("old title", "1")}, {"old title"})
    [x] = run.plan_renames([rec("Old Title")], [lib])
    assert x["status"] == "rename"


def test_a_title_problem_blocks_and_an_archived_video_is_left_alone():
    lib = ("Demo Video", {"1": folder("Old", "1"),
                          "2": dict(folder("Gone", "2", "F2"), _archived=True)}, {"old"})
    out = run.plan_renames([rec("New", problems=["title gives the same folder name as row 3"]),
                            rec("Newer", "2")], [lib])
    assert [x["status"] for x in out] == ["blocked", "archived"]


def test_only_files_named_after_the_old_title_are_renamed():
    assert run.renamed_file("Old_Technical Overview.mp4", "Old", "New") == "New_Technical Overview.mp4"
    assert run.renamed_file("Old.mp4", "Old", "New") == "New.mp4"
    assert run.renamed_file("Older_cut.mp4", "Old", "New") is None
    assert run.renamed_file("notes.pdf", "Old", "New") is None


def test_an_existing_video_with_a_problem_is_existing_not_invalid():
    """Not uploaded, so what would stop an upload does not apply."""
    status = run.plan([rec("X", problems=["customer_facing is empty"])], {"1": {}}, set())
    assert status == {"1": "existing"}


# ─────────────────────────────────────────────────────────────── preview and run
def test_the_preview_lists_the_title_and_the_run_renames_folder_and_file(client, tmp_path,
                                                                         isolated):
    serve(isolated, [folder(OLD, VIDEO["id"])],
          children=[{"id": "V1", "name": f"{OLD}_Technical Walkthrough.mp4", "file": {}},
                    {"id": "N1", "name": "notes.pdf", "file": {}}])
    admin(client)
    sid = upload(client, tmp_path)
    p = client.get(f"/api/migration/brightcove/sheets/{sid}").json()
    assert p["status"] == "ready", p.get("error")
    assert (p["counts"]["new"], p["counts"]["existing"], p["counts"]["rename"]) == (0, 1, 1)
    assert [(x["from"], x["to"], x["library"]) for x in p["renames"]] == [(OLD, NEW, LIB)]
    assert not renames_written(isolated), "the preview never writes"

    r = client.post("/api/migration/brightcove/runs", json=body(sid, operator="Liwei"))
    assert r.status_code == 200, r.text
    s = client.get(f"/api/migration/brightcove/runs/{r.json()['batch_id']}").json()
    assert s["state"] == "finished"
    assert [(i["status"], i["from"], i["title"]) for i in s["items"]] == [("renamed", OLD, NEW)]
    assert renames_written(isolated) == [("F1", NEW), ("V1", f"{NEW}_Technical Walkthrough.mp4")]
    assert not [c for c in isolated.calls if c[0] == "POST" and c[1].endswith("/children")], \
        "nothing uploaded"


def test_a_sheet_with_nothing_new_and_no_new_title_is_refused(client, tmp_path, isolated):
    serve(isolated, [folder(NEW, VIDEO["id"])])
    admin(client)
    sid = upload(client, tmp_path)
    assert client.get(f"/api/migration/brightcove/sheets/{sid}").json()["counts"]["rename"] == 0
    r = client.post("/api/migration/brightcove/runs", json=body(sid, operator="Liwei"))
    assert r.status_code == 409 and "no title to update" in r.json()["detail"]


def test_an_archived_video_is_not_uploaded_again_nor_renamed(client, tmp_path, isolated):
    serve(isolated, [], archive=[folder(OLD, VIDEO["id"], "F9")])
    admin(client)
    sid = upload(client, tmp_path)
    p = client.get(f"/api/migration/brightcove/sheets/{sid}").json()
    assert (p["counts"]["new"], p["counts"]["existing"], p["counts"]["rename"]) == (0, 1, 0)
    assert [x["status"] for x in p["renames"]] == ["archived"]


def test_a_video_in_the_gxc_library_is_not_uploaded_to_demo_video(client, tmp_path, isolated,
                                                                  monkeypatch):
    """One fake library serves both names: a usual row whose ID is already
    held is existing whichever library holds it."""
    monkeypatch.setattr(settings, "migration_gxc_library", LIB)
    serve(isolated, [folder(NEW, VIDEO["id"])])
    admin(client)
    sid = upload(client, tmp_path)
    assert client.get(f"/api/migration/brightcove/sheets/{sid}").json()["counts"]["new"] == 0


def test_a_failed_rename_is_reported_and_the_run_still_finishes(client, tmp_path, isolated):
    serve(isolated, [folder(OLD, VIDEO["id"])])
    base = isolated.handler

    def refuse(request):
        if request.method == "PATCH" and request.url.path.endswith("/items/F1"):
            isolated.calls.append(("PATCH", request.url.path, json.loads(request.content)))
            return httpx.Response(409, json={"error": {"code": "nameAlreadyExists"}})
        return base(request)

    isolated.handler = refuse
    admin(client)
    sid = upload(client, tmp_path)
    bid = client.post("/api/migration/brightcove/runs",
                      json=body(sid, operator="Liwei")).json()["batch_id"]
    s = client.get(f"/api/migration/brightcove/runs/{bid}").json()
    assert s["state"] == "finished"
    assert s["items"][0]["status"] == "failed" and "already has a folder" in s["items"][0]["error"]
    log = json.load(open(os.path.join(batches_dir(), bid + ".json")))
    assert log["items"][0]["kind"] == "rename"


# ─────────────────────────────────────────────────────────────── the Hub's data
@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    (tmp_path / "mirror").mkdir()
    return JsonAssetRepository(str(tmp_path))


def video(asset_id):
    return Asset.model_validate({"id": asset_id, "type": "video", "title": asset_id,
                                 "source_item_id": "F-1"})


def test_a_renamed_demo_video_takes_my_hub_with_it(repo, tmp_path):
    repo.replace_source_rows([video("video-old")], source_system="demo_video")
    owned = tmp_path / "owned"
    (owned / "me").mkdir(parents=True)
    (owned / "playlists").mkdir()
    (owned / "migration").mkdir()
    (owned / "me" / "p.json").write_text(json.dumps({"favorites": ["video-old"]}))
    (owned / "playlists" / "l.json").write_text(json.dumps({"items": ["video-old", "video-old-2"]}))
    (owned / "migration" / "log.json").write_text(json.dumps({"id": "video-old"}))

    repo.replace_source_rows([video("video-new")], source_system="demo_video")
    assert repo.adopt_new_ids([video("video-new")], "demo_video") == {"video-old": "video-new"}
    assert json.loads((owned / "me" / "p.json").read_text())["favorites"] == ["video-new"]
    assert json.loads((owned / "playlists" / "l.json").read_text())["items"] == \
        ["video-new", "video-old-2"], "a longer id is another id"
    assert "video-old" in (owned / "migration" / "log.json").read_text(), "records stay as they were"

    repo.replace_source_rows([video("video-newer")], source_system="demo_video")
    repo.adopt_new_ids([video("video-newer")], "demo_video")
    assert repo.renamed_to("video-old") == "video-newer", "followed to the newest id"
    assert json.loads((owned / "me" / "p.json").read_text())["favorites"] == ["video-newer"]


def test_a_folder_renamed_back_is_current_again(repo):
    repo.replace_source_rows([video("video-a")], source_system="demo_video")
    repo.replace_source_rows([video("video-b")], source_system="demo_video")
    repo.adopt_new_ids([video("video-b")], "demo_video")
    repo.replace_source_rows([video("video-a")], source_system="demo_video")
    assert repo.adopt_new_ids([video("video-a")], "demo_video") == {"video-b": "video-a"}
    assert repo.renamed_to("video-a") is None
    assert repo.renamed_to("video-b") == "video-a"
