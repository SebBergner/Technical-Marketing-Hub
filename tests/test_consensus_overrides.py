"""A Consensus demo's values, set on the Hub (Liwei, 2026-11-18)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend import access
from backend.auth import AuthMode
from backend.config import settings
from backend.services import consensus_overrides as co
from tests.test_auth import easyauth_headers

KEEPER = easyauth_headers("keeper@ptc.com")        # Maintain content
VIEWER = easyauth_headers("viewer@ptc.com")        # View Hub only

IGNITION = {"id": "ptc-ignition", "type": "video", "source": "consensus", "title": "PTC Ignition",
            "consensus_uuid": "u-ignition", "internal_title": "PTC Ignition",
            "products": [], "segment": None, "tags": []}
TAGGED = {"id": "creo-teaser", "type": "video", "source": "consensus", "title": "Creo Teaser",
          "consensus_uuid": "u-creo", "products": ["Creo"], "segment": "CAD",
          "funnel_stage": "Awareness", "tags": ["Creo", "CAD"]}
KIT = {"id": "kit", "type": "ldk", "source": "sharepoint", "title": "A Kit",
       "products": ["Windchill"], "segment": "PLM", "source_item_id": "f1"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import app
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password", "")
    (tmp_path / "mirror").mkdir()
    (tmp_path / "mirror" / "consensus.json").write_text(json.dumps([IGNITION, TAGGED]),
                                                        encoding="utf-8")
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps([KIT]), encoding="utf-8")
    access.create_group("Keepers", "", ["view_hub", "maintain_content"], ["keeper@ptc.com"], "t")
    access.create_group("Viewers", "", ["view_hub"], ["viewer@ptc.com"], "t")
    c = TestClient(app, base_url="http://localhost")
    c.tmp = tmp_path
    return c


def _put(client, asset_id, values, headers=KEEPER):
    return client.put(f"/api/assets/{asset_id}/consensus-metadata", json={"values": values},
                      headers=headers)


def test_the_form_offers_ptc_ignition_and_says_what_consensus_says(client):
    d = client.get("/api/assets/ptc-ignition/consensus-metadata", headers=KEEPER).json()
    fields = {f["key"]: f for f in d["fields"]}
    assert "PTC Ignition" in fields["products"]["choices"], "no demo carries it yet"
    assert fields["products"]["kind"] == "multi"
    assert fields["segment"]["choices"] == ["CAD", "PLM", "ALM", "SLM", "IoT"]
    assert d["consensus"]["products"] == [] and d["hub_set"] == []


def test_setting_ptc_ignition_puts_the_demo_under_ipe_at_once(client):
    r = _put(client, "ptc-ignition", {"products": ["PTC Ignition"], "segment": "PLM"})
    assert r.status_code == 200, r.text
    assert sorted(r.json()["changed"]) == ["products", "segment"]
    a = client.get("/api/assets/ptc-ignition", headers=KEEPER).json()
    assert a["products"] == ["PTC Ignition"] and a["segment"] == "PLM"
    assert a["umbrella_families"] == ["IPE"]
    assert sorted(a["hub_set"]) == ["products", "segment"]
    assert a["consensus_values"]["products"] == []
    listed = client.get("/api/assets?umbrella=IPE", headers=KEEPER).json()
    assert [h["id"] for h in listed["items"]] == ["ptc-ignition"]
    # Kept by the Consensus uuid, not the Hub's id (made from the title).
    store = json.loads((client.tmp / "owned" / "consensus_overrides.json").read_text("utf-8"))
    assert set(store) == {"u-ignition"}


def test_it_survives_a_sync_and_follows_a_renamed_demo(client):
    _put(client, "ptc-ignition", {"products": ["PTC Ignition"]})
    renamed = {**IGNITION, "id": "ptc-ignition-2027", "title": "PTC Ignition 2027"}
    (client.tmp / "mirror" / "consensus.json").write_text(json.dumps([renamed, TAGGED]),
                                                          encoding="utf-8")
    a = client.get("/api/assets/ptc-ignition-2027", headers=KEEPER).json()
    assert a["products"] == ["PTC Ignition"]


def test_consensus_values_clear_an_override(client):
    _put(client, "creo-teaser", {"segment": "PLM"})
    assert client.get("/api/assets/creo-teaser", headers=KEEPER).json()["segment"] == "PLM"
    r = _put(client, "creo-teaser", {"segment": "CAD"})
    assert r.json()["changed"] == ["segment"]
    a = client.get("/api/assets/creo-teaser", headers=KEEPER).json()
    assert a["segment"] == "CAD" and a["hub_set"] == []
    store = json.loads((client.tmp / "owned" / "consensus_overrides.json").read_text("utf-8"))
    assert store == {}


def test_only_values_on_the_list(client):
    r = _put(client, "ptc-ignition", {"products": ["Ignition Pro"]})
    assert r.status_code == 422 and "Ignition Pro" in r.json()["detail"]
    assert _put(client, "ptc-ignition", {"segment": "Sales"}).status_code == 422


def test_a_sharepoint_demo_is_not_set_here(client):
    assert client.get("/api/assets/kit/consensus-metadata", headers=KEEPER).status_code == 422
    assert _put(client, "kit", {"segment": "CAD"}).status_code == 422


def test_it_needs_edit_metadata_and_others_do_not_see_the_marks(client):
    assert client.get("/api/assets/ptc-ignition/consensus-metadata",
                      headers=VIEWER).status_code == 403
    assert _put(client, "ptc-ignition", {"segment": "PLM"}, VIEWER).status_code == 403
    _put(client, "ptc-ignition", {"segment": "PLM"})
    a = client.get("/api/assets/ptc-ignition", headers=VIEWER).json()
    assert a["segment"] == "PLM", "everyone sees the value"
    assert a["hub_set"] == [] and a["consensus_values"] is None, "only editors see it was set"


def test_the_admin_log_names_it(client):
    from backend import admin_log
    assert admin_log.category_of("/api/assets/x/consensus-metadata") == "Metadata"


def test_a_save_is_written_to_the_admin_log(client):
    # Found on staging 2026-11-24: the save worked but left no Admin log line,
    # because the path was missing from admin_log.WATCHED.
    from backend import admin_log
    assert _put(client, "ptc-ignition", {"products": ["PTC Ignition"]}).status_code == 200
    rows = [r for r in admin_log.read(limit=50)["items"]
            if r["path"] == "/api/assets/ptc-ignition/consensus-metadata"]
    assert len(rows) == 1
    assert rows[0]["action"] == "Set a Consensus demo's values on the Hub"
    assert rows[0]["actor"] == "user:keeper@ptc.com" and rows[0]["category"] == "Metadata"


def test_content_health_lists_no_product_and_disagreements(client):
    d = client.get("/api/content-health/checks", headers=KEEPER).json()
    assert [r["asset_id"] for r in d["consensus_no_product"]] == ["ptc-ignition"]
    assert d["consensus_differs"] == []
    assert "kit" not in [r["asset_id"] for r in d["no_product"]]

    _put(client, "ptc-ignition", {"products": ["PTC Ignition"]})
    _put(client, "creo-teaser", {"funnel_stage": "Decision"})
    d = client.get("/api/content-health/checks", headers=KEEPER).json()
    assert d["consensus_no_product"] == []
    differs = d["consensus_differs"]
    assert [r["asset_id"] for r in differs] == ["creo-teaser"]
    assert differs[0]["differences"] == [
        {"field": "Stage", "hub": "Decision", "consensus": "Awareness"}]


def test_apply_leaves_other_sources_alone():
    rows = [{**KIT, "consensus_uuid": "u-creo"}, TAGGED]
    out = co.apply(rows, {"u-creo": {"values": {"segment": "PLM"}}})
    assert out[0] == rows[0], "a SharePoint row is never overridden"
    assert out[1]["segment"] == "PLM" and out[1]["hub_set"] == ["segment"]
    assert out[1]["consensus_values"]["segment"] == "CAD"
