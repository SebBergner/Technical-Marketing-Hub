"""Search terms that mean the same (Liwei, 2026-11-13; Hub Tasks #15, #17, #29)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend import access
from backend.auth import AuthMode
from backend.config import settings
from backend.services import relevance
from backend.services import search_terms as st
from tests.test_auth import easyauth_headers

BOSS, VIC = easyauth_headers("boss@ptc.com"), easyauth_headers("vic@ptc.com")


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(st, "_seen", {"path": None, "at": 0.0, "stamp": None, "table": ()})
    return tmp_path


@pytest.fixture
def client(data, monkeypatch):
    from app import app
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password", "")
    monkeypatch.setattr(settings, "hub_admin_emails", "boss@ptc.com")
    (data / "mirror").mkdir()
    (data / "mirror" / "sharepoint.json").write_text(json.dumps([
        {"id": "a", "type": "video", "title": "PTC Modeler - MBSE in Windchill"},
        {"id": "b", "type": "video", "title": "Model-Based Systems Engineering Overview"},
        {"id": "c", "type": "vdk", "title": "E&HT - Change Management"},
        {"id": "d", "type": "vdk", "title": "EHT - BOM and Configuration"},
        {"id": "e", "type": "video", "title": "Electronics & High-Tech Story"},
        {"id": "f", "type": "video", "title": "Creo Parametric Overview"}]), encoding="utf-8")
    access.create_group("Viewers", "", ["view_hub", "view_admin"], ["vic@ptc.com"], "test")
    return TestClient(app, base_url="http://localhost")


def found(client, q):
    r = client.get("/api/assets", params={"q": q, "limit": 50}, headers=BOSS)
    assert r.status_code == 200, r.text
    return sorted(a["id"] for a in r.json()["items"])


# ─────────────────────────────────────────────────────────────── the search
def test_an_abbreviation_and_its_words_find_the_same_demos(client):
    assert found(client, "MBSE") == found(client, "model-based systems engineering") == ["a", "b"]
    assert found(client, "eht") == found(client, "E&HT") == ["c", "d", "e"]
    assert found(client, "electronics and high tech") == ["c", "d", "e"]
    assert found(client, "mbse windchill") == ["a"], "the other words still narrow"


def test_variants_swap_a_groups_term_for_the_others(data):
    assert st.variants("mbse demo") == ("mbse demo", "model based systems engineering demo")
    assert st.variants("creo overview") == ("creo overview",)
    assert "ipl" in st.variants("intelligent product lifecycles"), "a plural still names it"
    assert st.variants("sdv mbse")[0] == "sdv mbse" and len(st.variants("sdv mbse")) == 4


def test_relevance_takes_the_best_of_the_variants(data):
    assert relevance.score("mbse", "Model-Based Systems Engineering Overview") == relevance.TITLE_PREFIX
    assert relevance.names("mbse", "Model_Based_Systems_Engineering.pdf")


# ─────────────────────────────────────────────────────────────── the Admin page
def test_the_first_version_until_the_first_change(client, data):
    d = client.get("/api/admin/search-terms", headers=VIC).json()
    assert not d["saved"] and len(d["groups"]) == len(st.DEFAULTS)
    r = client.post("/api/admin/search-terms", headers=BOSS,
                    json={"terms": ["ESS", "Enterprise Service Strategy"], "note": "test"})
    assert r.status_code == 200, r.text
    d = client.get("/api/admin/search-terms", headers=VIC).json()
    assert d["saved"] and len(d["groups"]) == len(st.DEFAULTS) + 1
    assert json.loads((data / "owned" / st.FILE).read_text())["changed_by"].endswith("boss@ptc.com")


def test_only_maintain_content_changes_them(client):
    assert client.get("/api/admin/search-terms", headers=VIC).status_code == 200
    assert client.get("/api/admin/search-terms/try?q=mbse", headers=VIC).json()["also"] == \
        ["model based systems engineering"]
    assert client.post("/api/admin/search-terms", headers=VIC,
                       json={"terms": ["A1", "Alpha One"]}).status_code == 403
    assert client.delete("/api/admin/search-terms/d1", headers=VIC).status_code == 403
    assert client.get("/api/admin/search-terms", headers=easyauth_headers("x@ptc.com")).status_code == 403


def test_a_group_needs_two_terms_and_a_term_is_in_one_group(client):
    def add(terms):
        return client.post("/api/admin/search-terms", headers=BOSS, json={"terms": terms})
    assert add(["Lonely"]).status_code == 422
    assert add(["X1", "x1"]).status_code == 422, "the same search twice"
    r = add(["mbse", "Systems Engineering"])
    assert r.status_code == 422 and "already in the group" in r.json()["detail"]


def test_a_change_and_a_removal_reach_the_search(client):
    r = client.put("/api/admin/search-terms/d2", headers=BOSS,
                   json={"terms": ["IPL", "Intelligent Product Lifecycle", "MBSE"], "note": ""})
    assert r.status_code == 422, "MBSE is in another group"
    assert client.put("/api/admin/search-terms/d1", headers=BOSS,
                      json={"terms": ["MBSE", "Systems Engineering"]}).status_code == 200
    st._seen["at"] = 0.0
    assert found(client, "mbse") == ["a", "b"]
    assert client.delete("/api/admin/search-terms/d1", headers=BOSS).status_code == 200
    st._seen["at"] = 0.0
    assert found(client, "mbse") == ["a"]
    assert client.delete("/api/admin/search-terms/d1", headers=BOSS).status_code == 404


def test_changes_are_in_the_admin_log_under_their_own_name():
    from backend.admin_log import category_of
    assert category_of("/api/admin/search-terms/d1") == "Search terms"
