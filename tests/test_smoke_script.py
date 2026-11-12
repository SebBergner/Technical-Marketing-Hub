"""scripts/smoke_test.py, run against the app in-process (Liwei, 2026-11-11)."""
from __future__ import annotations

import json
import time
from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend import api_tokens
from backend.auth import AuthMode
from backend.config import settings
from backend.repositories.json_repo import JsonAssetRepository
from scripts import smoke_test


def _row(i, products, kind="video"):
    return {"id": i, "type": kind, "title": i.upper(), "products": products,
            "segment": "CAD", "uploaded_at": date.today().isoformat()}


@pytest.fixture
def hub(tmp_path, monkeypatch):
    from app import app
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "auth_mode", AuthMode.OIDC.value)
    (tmp_path / "mirror").mkdir()
    rows = [_row("creo-a", ["Creo Parametric"]), _row("wc-a", ["Windchill PDMLink"]),
            _row("cb-a", ["Codebeamer"], kind="ldk")]
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps(rows), encoding="utf-8")
    repo = JsonAssetRepository(str(tmp_path))
    repo.record_sync("sharepoint")
    repo.set_hub_settings("test", **smoke_test.EXPECTED_SETTINGS)
    from backend import auto_sync
    auto_sync.configure(True, [0, 6], "test")
    _, secret = api_tokens.create(name="Smoke test", owner="liwei@ptc.com",
                                  permissions=["view_hub"], days=30, actor="test")
    monkeypatch.setenv(smoke_test.TOKEN_ENV, f"tmh_unknown_x, {secret}")
    monkeypatch.setattr(smoke_test, "BASELINE_DIR", tmp_path / "baseline")
    client = TestClient(app, base_url="http://localhost", follow_redirects=False)

    def get(self, path, params=None):
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        started = time.monotonic()
        r = client.get(path, params=params, headers=headers)
        try:
            body = r.json()
        except ValueError:
            body = None
        return r.status_code, body, time.monotonic() - started

    monkeypatch.setattr(smoke_test.Hub, "get", get)
    return tmp_path


def levels(rep):
    return {name: level for level, name, _ in rep.rows}


def test_a_healthy_slot_passes_and_becomes_the_baseline(hub):
    rep = smoke_test.run("http://localhost", None)
    seen = levels(rep)
    # No guide video in a test catalogue: those two fail, everything else passes.
    assert {n for n, lv in seen.items() if lv == "FAIL"} == {"Guide video", "Guide video cover"}
    assert seen["Hub settings"] == "PASS"
    assert seen["SharePoint sync"] == "PASS"
    assert seen["Search \"creo\""] == "PASS"
    assert not (hub / "baseline").exists(), "a failed run does not become the baseline"


def test_counts_that_drop_are_a_warning(hub, monkeypatch):
    monkeypatch.setattr(smoke_test, "SEARCHES", ())
    monkeypatch.setattr(smoke_test.Report, "fail", smoke_test.Report.warn)
    smoke_test.run("http://localhost", None)
    rows = json.loads((hub / "mirror" / "sharepoint.json").read_text(encoding="utf-8"))
    (hub / "mirror" / "sharepoint.json").write_text(json.dumps(rows[:1]), encoding="utf-8")
    rep = smoke_test.run("http://localhost", None)
    detail = {name: d for _, name, d in rep.rows}
    assert "total 3->1" in detail["Counts vs last run"]


def test_wrong_settings_and_version_fail(hub):
    JsonAssetRepository(str(hub)).set_hub_settings("test", gxc_downloads=False)
    rep = smoke_test.run("http://localhost", "v0.0.0")
    seen = levels(rep)
    assert seen["Hub settings"] == "FAIL"
    assert seen["Expected version"] == "FAIL"


def test_no_working_token_stops_early(hub, monkeypatch):
    monkeypatch.setenv(smoke_test.TOKEN_ENV, "tmh_unknown_x")
    rep = smoke_test.run("http://localhost", None)
    assert levels(rep)["API token"] == "FAIL"
    assert len(rep.rows) == 2
