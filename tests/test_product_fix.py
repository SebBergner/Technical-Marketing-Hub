"""Content health -> Fix products (Liwei, 2026-11-25): suggestions, and many
demos' product set at once."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend import access
from backend.auth import AuthMode
from backend.config import settings
from backend.integrations.graph import upload_writer as uw
from backend.services import product_fix as pf
from backend.services import upload_targets as ut
from tests.test_auth import easyauth_headers

KEEPER = easyauth_headers("keeper@ptc.com")        # Maintain content
VIEWER = easyauth_headers("viewer@ptc.com")        # View Hub only

CHOICES = {"Segment": ["CAD", "PLM", "ALM", "SLM"], "Language": ["English"],
           "VideoType": ["Technical Overview"], "VideoSubtype": ["Feature"],
           "products": ["Creo", "Creo Generative Design", "Windchill", "Codebeamer"]}


def creo_kit(i):
    return {"id": f"kit-{i}", "type": "ldk", "title": f"Creo kit {i}", "source": "sharepoint",
            "source_item_id": f"k{i}", "products": ["Creo Parametric"], "segment": "CAD"}


MIRROR = [creo_kit(i) for i in range(6)] + [
    {"id": "video-hill-gd", "type": "video", "source": "sharepoint", "source_item_id": "f-gd",
     "title": "Hill Helicopters Creo Generative Design Feature Overview", "products": []},
    {"id": "video-vestas", "type": "video", "source": "sharepoint", "source_item_id": "f-v",
     "title": "Vestas Attract Loop - Left", "segment": "SLM", "products": [],
     "description": "Engineering with Windchill and Codebeamer."},
    {"id": "video-sdv", "type": "video", "source": "sharepoint", "source_item_id": "f-sdv",
     "title": "SDV Part 3 System Architecture", "products": []},
    {"id": "gxc-iot", "type": "video", "source": "sharepoint", "source_item_id": "f-g",
     "title": "IoT thing", "products": [], "gxc": True},
]
CONSENSUS = [{"id": "creo-surfacing", "type": "video", "source": "consensus",
              "consensus_uuid": "u-1", "title": "Creo Surfacing: Tips & Techniques",
              "products": [], "segment": None, "tags": []}]


class FakeClient:
    def __init__(self):
        self.fields = {}
        self.writes = []

    def get_list_item(self, drive_id, item_id):
        return {"@odata.etag": '"1"', "fields": dict(self.fields.get(item_id, {}))}

    def update_list_item_fields(self, drive_id, item_id, fields, etag=None):
        self.writes.append((item_id, fields))
        return fields


@pytest.fixture
def fake(monkeypatch):
    client = FakeClient()
    import backend.routers.uploads as up
    monkeypatch.setattr(up, "_client", lambda: client)

    def target(c, key, fresh=False):
        return uw.Target(spec=ut.TARGETS[key], site_id="s", drive_id="d", list_id="l",
                         demo_content_type_id="0x0120", product_note_field="Product_0",
                         choices=CHOICES, terms=None, has_demo_owner=True,
                         has_demo_owner_name=True, has_thumbnail_flag=True)
    monkeypatch.setattr(up, "_target", target)
    client.syncs = []
    monkeypatch.setattr(up, "_sync_soon", lambda repo, actor: client.syncs.append(actor))
    return client


@pytest.fixture
def client(tmp_path, monkeypatch, fake):
    from app import app
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password", "")
    (tmp_path / "mirror").mkdir()
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps(MIRROR), encoding="utf-8")
    (tmp_path / "mirror" / "consensus.json").write_text(json.dumps(CONSENSUS), encoding="utf-8")
    access.create_group("Keepers", "", ["view_hub", "maintain_content"], ["keeper@ptc.com"], "t")
    access.create_group("Viewers", "", ["view_hub"], ["viewer@ptc.com"], "t")
    c = TestClient(app, base_url="http://localhost")
    c.fake = fake
    return c


# ───────────────────────────────────────────────────────── suggestions
def test_the_title_names_the_most_specific_product():
    s = pf.suggestion({"title": "Hill Helicopters Creo Generative Design Overview"},
                      ["Creo", "Creo Generative Design", "Windchill"])
    assert s == {"products": ["Creo Generative Design"], "from": "title"}


def test_a_word_after_another_product_belongs_to_it():
    # Seen on production: "Creo Option Modeler" is a Creo module, not PTC Modeler.
    s = pf.suggestion({"title": "Creo Option Modeler: Tips & Techniques"},
                      ["Creo", "Modeler", "Windchill"])
    assert s == {"products": ["Creo"], "from": "title"}


def test_one_spelling_per_family():
    s = pf.suggestion({"title": "PTC Jetstream VDK"}, ["PTC Jetstream", "Jetstream"])
    assert s["products"] == ["PTC Jetstream"]


def test_the_description_is_a_weaker_hint():
    s = pf.suggestion({"title": "Vestas Attract Loop", "description": "Windchill and Creo"},
                      ["Creo", "Windchill"])
    assert s["from"] == "description" and sorted(s["products"]) == ["Creo", "Windchill"]
    assert pf.suggestion({"title": "SDV Part 3"}, ["Creo"]) is None


def test_divested_products_are_never_suggested():
    assert pf.suggestion({"title": "ThingWorx Navigate demo"}, ["ThingWorx"]) is None


def test_a_segment_comes_from_what_the_family_already_carries():
    by_family = pf.family_segments(MIRROR)
    assert by_family == {"Creo": "CAD"}
    assert pf.segment_for(["Creo Generative Design"], by_family) == "CAD"
    assert pf.segment_for(["Windchill"], by_family) is None


# ───────────────────────────────────────────────────────── the list
def test_the_list_offers_what_can_be_fixed_and_suggests(client):
    d = client.get("/api/content-health/products", headers=KEEPER).json()
    rows = {r["asset_id"]: r for r in d["rows"]}
    # GXC (IoT/AR keep Product empty on purpose) and demos with a product are not offered.
    assert set(rows) == {"video-hill-gd", "video-vestas", "video-sdv", "creo-surfacing"}
    assert rows["video-hill-gd"]["suggested"] == {"products": ["Creo Generative Design"],
                                                  "from": "title"}
    assert rows["video-hill-gd"]["suggested_segment"] == "CAD"
    assert rows["video-vestas"]["suggested"]["from"] == "description"
    assert rows["video-vestas"]["suggested_segment"] is None, "it has a segment"
    assert rows["video-sdv"]["suggested"] is None
    assert rows["creo-surfacing"]["fix"] == "consensus"
    assert rows["creo-surfacing"]["suggested"]["products"] == ["Creo"]
    # Title suggestions first, then description, then none.
    assert [r["asset_id"] for r in d["rows"]][-1] == "video-sdv"
    assert d["segments"] == ["CAD", "PLM", "ALM", "SLM"]


def test_the_page_can_suggest_the_segment_again_after_a_change(client):
    # Changing a demo's products must not keep the old product's segment.
    d = client.get("/api/content-health/products", headers=KEEPER).json()
    assert d["product_segments"] == {"Creo": "CAD", "Creo Generative Design": "CAD",
                                     "Creo Parametric": "CAD"}, \
        "only products whose family agrees on a segment (Windchill, Codebeamer: none)"


def test_only_people_who_maintain_content(client):
    assert client.get("/api/content-health/products", headers=VIEWER).status_code == 403
    r = client.post("/api/content-health/products", headers=VIEWER,
                    json={"items": [{"asset_id": "video-sdv", "products": ["Codebeamer"]}]})
    assert r.status_code == 403


# ───────────────────────────────────────────────────────── saving
def test_many_at_once_each_with_its_own_answer(client):
    r = client.post("/api/content-health/products", headers=KEEPER, json={"items": [
        {"asset_id": "video-hill-gd", "products": ["Creo Generative Design"], "segment": "CAD"},
        {"asset_id": "creo-surfacing", "products": ["Creo"], "segment": "CAD"},
        {"asset_id": "video-sdv", "products": ["Not a product"]},
        {"asset_id": "kit-0", "products": ["Creo"]},
    ]})
    assert r.status_code == 200, r.text
    res = {x["asset_id"]: x for x in r.json()["results"]}
    assert r.json()["saved"] == 2
    assert res["video-hill-gd"]["ok"] and sorted(res["video-hill-gd"]["changed"]) == [
        "products", "segment"]
    assert res["creo-surfacing"]["ok"]
    assert not res["video-sdv"]["ok"] and res["video-sdv"]["error"]
    assert "already" in res["kit-0"]["error"]
    # Written to the folder once, and one sync for the lot.
    assert [w[0] for w in client.fake.writes] == ["f-gd"]
    assert client.fake.syncs == ["user:keeper@ptc.com"]
    # Shown at once, without waiting for the sync.
    a = client.get("/api/assets/video-hill-gd", headers=KEEPER).json()
    assert a["products"] == ["Creo Generative Design"]
    c = client.get("/api/assets/creo-surfacing", headers=KEEPER).json()
    assert c["products"] == ["Creo"] and c["segment"] == "CAD"
    left = {x["asset_id"] for x in client.get("/api/content-health/products",
                                              headers=KEEPER).json()["rows"]}
    assert left == {"video-vestas", "video-sdv"}


def test_a_product_already_in_sharepoint_is_not_overwritten(client):
    from backend.services.upload_targets import TARGETS
    column = TARGETS["demo_video"].product_choice_column
    client.fake.fields["f-sdv"] = {column: ["Codebeamer"]}
    r = client.post("/api/content-health/products", headers=KEEPER,
                    json={"items": [{"asset_id": "video-sdv", "products": ["Windchill"]}]})
    res = r.json()["results"][0]
    assert not res["ok"] and "SharePoint already has" in res["error"]
    assert client.fake.writes == []


def test_an_existing_segment_is_kept(client):
    r = client.post("/api/content-health/products", headers=KEEPER, json={"items": [
        {"asset_id": "video-vestas", "products": ["Windchill"], "segment": "PLM"}]})
    assert r.json()["results"][0]["changed"] == ["products"]


def test_the_admin_log_has_it(client):
    from backend import admin_log
    client.post("/api/content-health/products", headers=KEEPER, json={"items": [
        {"asset_id": "creo-surfacing", "products": ["Creo"]}]})
    rows = [x for x in admin_log.read(limit=20)["items"]
            if x["path"] == "/api/content-health/products"]
    assert len(rows) == 1 and rows[0]["category"] == "Metadata"
    assert rows[0]["action"] == "Set the product of demos that had none"


def test_too_many_at_once(client):
    items = [{"asset_id": "video-sdv", "products": ["Creo"]}] * 101
    assert client.post("/api/content-health/products", headers=KEEPER,
                       json={"items": items}).status_code == 422
