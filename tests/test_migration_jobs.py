"""Upload a sheet, preview it, start / pause / resume a run -- from /migration.

Everything runs against fakes (Graph, Brightcove, the upload session and the
CDN); background threads are run inline so each test is deterministic. Pinned:
who may start a run (Liwei's decision, 2026-09-29: an SSO curator, or the
shared admin sign-in WITH a typed operator name), that only one run can hold
the lock, that a pause stops between videos, and that a restart resumes an
unfinished run from its batch log.
"""
from __future__ import annotations

import json
import os
from datetime import datetime

import httpx
import openpyxl
import pytest
from fastapi.testclient import TestClient

from app import app
from backend.auth import AuthMode
from backend.config import settings
from backend.services import migration_jobs as jobs
from backend.services.brightcove_migration import batches_dir
from tests.test_auth import easyauth_headers
from tests.test_brightcove_runner import FakeGraph, FakeUploader
from tests.test_brightcove_source import VIDEO, FakeBrightcove

ADMIN_USER, ADMIN_PASS = "tddadmin", "a-long-test-password-8e1f"
CURATORS = "11111111-2222-3333-4444-555555555555"
LIB = "Demo Video"
SIZE = 50_000                                       # FakeBrightcove's 1080p rendition


class Inline:
    """threading.Thread stand-in: runs the target when started."""

    def __init__(self, target, args=(), **_):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    for name in ("graph_tenant_id", "graph_client_id", "graph_client_secret"):
        monkeypatch.setattr(settings, name, "")
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "auth_curator_groups", CURATORS)
    monkeypatch.setattr(settings, "admin_username", ADMIN_USER)
    monkeypatch.setattr(settings, "admin_password", ADMIN_PASS)
    monkeypatch.setattr(settings, "migration_brightcove_library", LIB)
    monkeypatch.setattr(settings, "migration_runner_enabled", True)
    monkeypatch.setattr(jobs.threading, "Thread", Inline)

    graph, brightcove = FakeGraph(library=LIB), FakeBrightcove()
    monkeypatch.setattr(jobs, "clients", lambda: (graph.client(), brightcove.client()))

    def cdn(request):
        start = int((request.headers.get("range") or "bytes=0-").split("=")[1].rstrip("-"))
        return httpx.Response(206 if start else 200, content=b"x" * (SIZE - start))

    monkeypatch.setattr(jobs, "http_clients", lambda: (
        FakeUploader(size=SIZE).client(), httpx.Client(transport=httpx.MockTransport(cdn))))
    yield graph


@pytest.fixture()
def client():
    with TestClient(app, base_url="http://localhost") as c:
        yield c


def admin(client):
    assert client.post("/api/admin/login",
                       json={"username": ADMIN_USER, "password": ADMIN_PASS}).status_code == 200


CURATOR = easyauth_headers("seb@ptc.com", groups=(CURATORS,))


def workbook(tmp_path, rows) -> bytes:
    """A workbook shaped like V29, with the Segment / Customer Facing columns
    the final version adds."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "PLM (PTC Gallery)"
    ws.append(["Section", "Id", "Video Title", "Proposed Title", "Delete?", "Short Description",
               "Long Description", "Tags", "Proposed Tags", "Published Date", "Video Type",
               "Subtype", "Segment", "Customer Facing"])
    for r in rows:
        ws.append(r)
    ws.append([None, None, "Total", None, len(rows)])
    path = tmp_path / "v.xlsx"
    wb.save(path)
    return path.read_bytes()


GOOD = ["PLM - All", VIDEO["id"], "Tech Walkthrough Audio - Change", "Change Management", False,
        "Short.", "Long.", "plm_gallery", "Windchill, Vestas", datetime(2019, 5, 14),
        "Technical Walkthrough", "Customer", "PLM", "Yes"]
DROPPED = ["PLM - All", "6300000000009", "Old", None, True, "", "", "", "", None, "", "", "", ""]


def upload(client, tmp_path, rows=(GOOD, DROPPED), headers=None):
    r = client.post("/api/migration/brightcove/sheets", headers=headers or {},
                    files={"file": ("Gallery V30.xlsx", workbook(tmp_path, rows),
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    return r.json()["sheet_id"]


# ─────────────────────────────────────────────────────────────── preview
def test_an_uploaded_sheet_is_previewed_without_writing(client, tmp_path, isolated):
    admin(client)
    sid = upload(client, tmp_path)
    p = client.get(f"/api/migration/brightcove/sheets/{sid}").json()
    assert p["status"] == "ready", p.get("error")
    assert p["sheet"]["to_migrate"] == 1 and p["sheet"]["left_out"] == 1
    assert p["sheet"]["has_segment_column"] and p["sheet"]["has_customer_facing_column"]
    assert p["counts"]["new"] == 1
    assert p["volume_bytes"] == SIZE
    assert {s["name"] for s in p["hub_products"]} == {"Windchill"}
    assert p["customers"][0]["name"] == "Vestas"
    assert not [m for m, *_ in isolated.calls if m not in ("GET",)], "the preview never writes"


def test_the_plan_is_the_latest_workbook_not_the_latest_run(client, tmp_path):
    """A one-video test run once made the page say "of 1 planned"."""
    admin(client)
    upload(client, tmp_path)
    assert jobs.planned_total() == 1          # the one kept row of this workbook
    assert client.get("/api/migration/brightcove/status").json()["plan"]["total"] == 1


def test_a_preview_interrupted_by_a_restart_is_computed_again(client, tmp_path):
    admin(client)
    sid = upload(client, tmp_path)
    path = os.path.join(jobs._sheets_dir(), sid, "preview.json")
    p = json.load(open(path, encoding="utf-8"))
    p["status"] = "running"                            # as a killed thread leaves it
    jobs._write_json(path, p)
    old = jobs.time.time() - jobs.STALE_PREVIEW_SECONDS - 5
    os.utime(path, (old, old))
    jobs.load_preview(sid)                             # notices, restarts (inline here)
    assert jobs.load_preview(sid)["status"] == "ready"


def test_problems_are_grouped_and_exported(client, tmp_path):
    admin(client)
    bad = list(GOOD)
    bad[13] = ""                                         # no Customer Facing
    sid = upload(client, tmp_path, rows=(bad,))
    p = client.get(f"/api/migration/brightcove/sheets/{sid}").json()
    assert p["problems"][0]["reason"] == "customer_facing is empty"
    assert p["problems"][0]["count"] == 1
    csv_text = client.get(f"/api/migration/brightcove/sheets/{sid}/problems.csv").text
    assert "customer_facing is empty" in csv_text and VIDEO["id"] in csv_text


def test_only_xlsx_is_accepted(client):
    admin(client)
    r = client.post("/api/migration/brightcove/sheets",
                    files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 415


# ─────────────────────────────────────────────────────────────── who may start
def body(sid, **kw):
    return {"sheet_id": sid, "confirm_library": LIB, **kw}


def test_the_shared_admin_sign_in_must_name_an_operator(client, tmp_path):
    admin(client)
    sid = upload(client, tmp_path)
    assert client.post("/api/migration/brightcove/runs", json=body(sid)).status_code == 422
    r = client.post("/api/migration/brightcove/runs", json=body(sid, operator="Liwei Chen"))
    assert r.status_code == 200, r.text
    log = json.load(open(os.path.join(batches_dir(), r.json()["batch_id"] + ".json")))
    assert (log["operator"], log["via"]) == ("Liwei Chen", "admin-session")


def test_an_sso_curator_is_recorded_as_themselves(client, tmp_path):
    sid = upload(client, tmp_path, headers=CURATOR)
    r = client.post("/api/migration/brightcove/runs", headers=CURATOR,
                    json=body(sid, operator="someone else"))
    assert r.status_code == 200, r.text
    log = json.load(open(os.path.join(batches_dir(), r.json()["batch_id"] + ".json")))
    assert log["operator"] == "seb@ptc.com"


def test_a_signed_in_non_curator_cannot_use_the_page(client):
    viewer = easyauth_headers("viewer@ptc.com")
    assert client.get("/api/migration/brightcove/status", headers=viewer).status_code == 403


def test_the_library_name_must_be_typed_exactly(client, tmp_path):
    admin(client)
    sid = upload(client, tmp_path)
    r = client.post("/api/migration/brightcove/runs",
                    json={"sheet_id": sid, "confirm_library": "demo video", "operator": "Liwei"})
    assert r.status_code == 409 and "library name exactly" in r.json()["detail"]


def test_runs_only_start_where_they_are_enabled(client, tmp_path, monkeypatch):
    admin(client)
    sid = upload(client, tmp_path)
    monkeypatch.setattr(settings, "migration_runner_enabled", False)
    r = client.post("/api/migration/brightcove/runs", json=body(sid, operator="Liwei"))
    assert r.status_code == 409 and "not enabled" in r.json()["detail"]


# ─────────────────────────────────────────────────────────────── running
def test_a_run_carries_every_video_to_done_and_reports_progress(client, tmp_path, isolated):
    admin(client)
    sid = upload(client, tmp_path)
    bid = client.post("/api/migration/brightcove/runs", json=body(sid, operator="Liwei")).json()["batch_id"]
    s = client.get(f"/api/migration/brightcove/runs/{bid}").json()
    assert s["state"] == "finished"
    assert s["counts"] == {"done": 1}
    assert s["bytes_done"] == s["bytes_total"] == SIZE
    writes = [p for m, p, _ in isolated.calls if m != "GET"]
    assert any(p.endswith("/root/children") for p in writes), "a folder was created"
    assert not os.path.exists(jobs._lock_path()), "the lock is released"


def test_a_second_run_is_refused_while_one_holds_the_lock(client, tmp_path):
    admin(client)
    sid = upload(client, tmp_path)
    assert jobs._claim("someone-else")
    r = client.post("/api/migration/brightcove/runs", json=body(sid, operator="Liwei"))
    assert r.status_code == 409 and "still going" in r.json()["detail"]


def test_a_stale_lock_from_a_dead_worker_is_taken_over(tmp_path):
    assert jobs._claim("dead")
    old = jobs.time.time() - jobs.STALE_LOCK_SECONDS - 5
    os.utime(jobs._lock_path(), (old, old))
    assert jobs.active_run() is None
    assert jobs._claim("new")


def test_pause_stops_between_videos_and_resume_finishes(client, tmp_path, monkeypatch):
    admin(client)
    sid = upload(client, tmp_path)
    started = []
    monkeypatch.setattr(jobs, "_spawn", lambda bid: started.append(bid))   # hold the thread
    bid = client.post("/api/migration/brightcove/runs", json=body(sid, operator="Liwei")).json()["batch_id"]
    client.post(f"/api/migration/brightcove/runs/{bid}/pause")
    jobs.execute(bid)                                   # the worker sees the pause first
    s = client.get(f"/api/migration/brightcove/runs/{bid}").json()
    assert s["state"] == "paused" and s["counts"] == {"pending": 1}

    monkeypatch.setattr(jobs, "_spawn", lambda b: jobs.execute(b))
    assert client.post(f"/api/migration/brightcove/runs/{bid}/resume",
                       json={"operator": "Liwei"}).status_code == 200
    assert client.get(f"/api/migration/brightcove/runs/{bid}").json()["state"] == "finished"


def test_a_restart_resumes_an_unfinished_run_but_not_a_paused_one(client, tmp_path, monkeypatch):
    admin(client)
    sid = upload(client, tmp_path)
    monkeypatch.setattr(jobs, "_spawn", lambda bid: None)          # "the server died"
    bid = client.post("/api/migration/brightcove/runs", json=body(sid, operator="Liwei")).json()["batch_id"]

    jobs.pause(bid)
    assert jobs.auto_resume() is None, "a paused run waits for a person"
    os.remove(jobs._pause_path(bid))

    monkeypatch.setattr(jobs, "_spawn", lambda b: jobs.execute(b))
    assert jobs.auto_resume() == bid
    assert jobs.run_status(bid)["state"] == "finished"
