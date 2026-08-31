"""The segment landing pages.

Two things are worth holding still here, and they are the two the design
depends on.

*Derived content must agree with the catalogue.* A page that promises 250
assets and hands back 249 is the same failure as the sidebar that claimed Creo
had 24 demos against a real 382, and it is the reason every number on the page
comes from the same repository call the grid uses.

*Editorial content must be absent when nobody has written it.* The API may
never invent a description or an owner, because a plausible sentence with
nobody's name on it is indistinguishable from a true one until it is too late.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import app
from backend.routers import segments

client = TestClient(app)


@pytest.fixture()
def editorial_file(tmp_path, monkeypatch):
    """Redirect the editorial store, and only it.

    The real one lives under DATA_DIR/owned/, which holds irreplaceable data,
    so a test must never write there. Redirecting DATA_DIR wholesale would
    also take the catalogue with it and leave nothing to have segments of --
    only this one path moves.
    """
    path = tmp_path / "segments.json"
    monkeypatch.setattr(segments, "_editorial_path", lambda: str(path))
    return path


def test_every_segment_has_a_real_count_behind_it():
    body = client.get("/api/segments").json()
    assert body["segments"], "the catalogue has segments; the endpoint found none"

    for segment in body["segments"]:
        listed = client.get(
            "/api/assets", params={"segment": segment["key"], "limit": 1}
        ).json()
        assert segment["total"] == listed["total"], (
            f"{segment['key']} promises {segment['total']} "
            f"and delivers {listed['total']}"
        )


def test_segments_come_back_largest_first():
    totals = [s["total"] for s in client.get("/api/segments").json()["segments"]]
    assert totals == sorted(totals, reverse=True)


def test_the_family_breakdown_adds_up_to_the_segment():
    """Families overlap — an asset can carry two products — so the breakdown
    may exceed the total but must never fall short of the largest family."""
    for segment in client.get("/api/segments").json()["segments"]:
        for family in segment["families"]:
            actual = client.get("/api/assets", params={
                "segment": segment["key"], "family": family["value"], "limit": 1,
            }).json()["total"]
            assert family["count"] == actual, (
                f"{segment['key']}/{family['value']}: "
                f"facet says {family['count']}, list says {actual}"
            )


def test_editorial_content_is_absent_until_somebody_writes_it(editorial_file):
    assert not editorial_file.exists()
    for segment in client.get("/api/segments").json()["segments"]:
        assert segment["editorial"]["blurb"] is None
        assert segment["editorial"]["owner"] is None


def test_editorial_content_is_served_once_written(editorial_file):
    key = client.get("/api/segments").json()["segments"][0]["key"]
    editorial_file.write_text(json.dumps({key: {
        "blurb": "Everything a PLM conversation needs.",
        "owner": {"name": "A Person", "email": "a.person@example.com"},
        "updated_by": "A Person", "updated_at": "2026-09-02",
    }}), encoding="utf-8")

    written = next(s for s in client.get("/api/segments").json()["segments"]
                   if s["key"] == key)
    assert written["editorial"]["blurb"].startswith("Everything")
    assert written["editorial"]["owner"]["name"] == "A Person"
    # Without a date there is no way to judge whether the sentence still holds.
    assert written["editorial"]["updated_at"] == "2026-09-02"


def test_a_broken_editorial_file_does_not_take_the_page_down(editorial_file):
    """An unreadable file must degrade to "nobody has written this", which is
    visibly missing, rather than to a 500."""
    editorial_file.write_text("{ this is not json", encoding="utf-8")
    body = client.get("/api/segments")
    assert body.status_code == 200
    assert all(s["editorial"]["blurb"] is None for s in body.json()["segments"])


def test_the_latest_rail_is_ten_at_most_and_all_in_the_segment():
    key = client.get("/api/segments").json()["segments"][0]["key"]
    detail = client.get(f"/api/segments/{key}").json()
    assert 0 < len(detail["latest"]) <= 10
    assert all(a["segment"] == key for a in detail["latest"])


def test_a_segment_key_is_case_insensitive():
    """The key travels in a URL, and "plm" is what a person types."""
    key = client.get("/api/segments").json()["segments"][0]["key"]
    assert client.get(f"/api/segments/{key.lower()}").json()["key"] == key
    assert client.get(f"/api/segments/{key.upper()}").json()["key"] == key


def test_an_unknown_segment_is_a_404_not_an_empty_page():
    """IPL is in Elio's markup and in no asset. An empty page would suggest the
    segment exists and happens to be unstocked."""
    assert client.get("/api/segments/IPL").status_code == 404
