"""Content age: bands, the Published filter and oldest-first (Serge, 2026-10-13)."""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.config import settings
from backend.services import content_age as age

TODAY = date(2026, 10, 14)


def ago(years: float) -> date:
    return TODAY - timedelta(days=round(365 * years))


@pytest.mark.parametrize("years, band", [
    (0.1, age.NEW), (0.99, age.NEW), (1.0, age.RECENT), (1.9, age.RECENT),
    (2.0, age.AGING), (3.9, age.AGING), (4.0, age.OLDER), (12, age.OLDER)])
def test_the_bands_follow_serges_spec(years, band):
    assert age.band(ago(years), TODAY) == band


def test_no_date_no_band_and_dust_starts_at_seven_years():
    assert age.band(None, TODAY) is None
    assert not age.collecting_dust(ago(6.9), TODAY) and age.collecting_dust(ago(7), TODAY)


def test_a_filter_value_is_a_band_or_a_year():
    d = date(2023, 5, 1)
    assert age.matches(d, ["aging"], TODAY) and age.matches(d, ["2023"], TODAY)
    assert age.matches(d, ["new", "2023"], TODAY), "any one matches"
    assert not age.matches(d, ["2024"], TODAY) and not age.matches(None, ["new"], TODAY)


# ─────────────────────────────────────────────── through the API
@pytest.fixture
def client(tmp_path, monkeypatch):
    from app import app
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    (tmp_path / "mirror").mkdir()
    today = date.today()
    rows = [{"id": i, "type": "video", "title": f"Clip {i}", "products": ["Creo"],
             "uploaded_at": (today - timedelta(days=days)).isoformat() if days is not None
             else None}
            for i, days in (("fresh", 30), ("two", 400), ("three", 1100), ("old", 2000),
                            ("nodate", None))]
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps(rows), encoding="utf-8")
    return TestClient(app, base_url="http://localhost")


def ids(response):
    return [a["id"] for a in response.json()["items"]]


def test_published_filters_by_band_and_by_year(client):
    assert ids(client.get("/api/assets?published=new")) == ["fresh"]
    assert set(ids(client.get("/api/assets?published=new&published=older"))) == {"fresh", "old"}
    year = (date.today() - timedelta(days=1100)).year
    assert "three" in ids(client.get(f"/api/assets?published={year}"))


def test_oldest_first_puts_undated_content_last(client):
    assert ids(client.get("/api/assets?sort=oldest")) == ["old", "three", "two", "fresh", "nodate"]
    assert ids(client.get("/api/assets?sort=recent"))[:4] == ["fresh", "two", "three", "old"]


def test_the_facet_lists_every_band_then_the_years(client):
    facets = client.get("/api/taxonomy?published=new").json()["published"]
    bands = {f["value"]: f["count"] for f in facets[:4]}
    assert bands == {"new": 1, "recent": 1, "aging": 1, "older": 1}, \
        "counted over everything but the Published filter itself"
    years = [f["value"] for f in facets[4:]]
    assert years == sorted(years, reverse=True)


# ─────────────────────────────────────────────── Still current
def test_every_demo_carries_its_band(client):
    bands = {a["id"]: a["age_band"] for a in client.get("/api/assets?limit=10").json()["items"]}
    assert bands == {"fresh": "new", "two": "recent", "three": "aging", "old": "older",
                     "nodate": None}


@pytest.fixture
def reviewer(monkeypatch):
    from backend.auth import AuthMode
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password", "")
    monkeypatch.setattr(settings, "hub_admin_emails", "boss@ptc.com")
    from tests.test_auth import easyauth_headers
    return easyauth_headers("boss@ptc.com"), easyauth_headers("someone@ptc.com")


def test_review_content_marks_still_current_for_a_while(client, reviewer, tmp_path):
    boss, staff = reviewer
    url = "/api/assets/old/still-current"
    assert client.put(url, json={"still_current": True}, headers=staff).status_code == 403
    r = client.put(url, json={"still_current": True}, headers=boss)
    assert r.status_code == 200 and r.json()["still_current_by"] == "user:boss@ptc.com"
    until = date.fromisoformat(r.json()["still_current_until"])
    assert 360 <= (until - date.today()).days <= 370, "twelve months by default"
    old = client.get("/api/assets/old", headers=staff).json()
    assert old["age_band"] == "older" and old["still_current_until"], "band kept, mark on top"
    assert (tmp_path / "owned" / "content_review.json").exists()
    client.put(url, json={"still_current": False}, headers=boss)
    assert client.get("/api/assets/old", headers=staff).json()["still_current_until"] is None


def test_an_expired_confirmation_counts_for_nothing(client, tmp_path):
    (tmp_path / "owned").mkdir(exist_ok=True)
    (tmp_path / "owned" / "content_review.json").write_text(json.dumps(
        {"old": {"by": "x", "until": (date.today() - timedelta(days=1)).isoformat()}}),
        encoding="utf-8")
    assert client.get("/api/assets/old").json()["still_current_until"] is None
