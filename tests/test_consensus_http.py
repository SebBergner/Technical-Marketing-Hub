"""HttpConsensusClient against the shapes the OpenAPI spec actually documents.

No credentials needed — `httpx.MockTransport` serves payloads copied from the
spec's own examples. This is what verifies the parsing, and it is the layer
that was previously untested (a field rename shipped past a green suite).

Spec: https://app.goconsensus.com/api-documentation/openapi.yaml
"""
from __future__ import annotations

import json

import httpx
import pytest

from backend.integrations.consensus import (
    ConsensusAPIError, ConsensusError, HttpConsensusClient, ShareRecipient,
)

BASE = "https://app.goconsensus.com"

#: A demo item exactly as `demo/search` documents it.
DEMO_ITEM = {
    "uuid": "11111111-2222-3333-4444-555555555555",
    "uuidType": "demo",
    "title": "Windchill AI Parts Rationalization",
    "internalTitle": "WC-AI-PR-internal",
    "description": "Duplicate part detection walkthrough.",
    "type": "single",
    "isPublic": True,
    "isArchived": False,
    "isPublished": True,
    # Note the offset has no colon — older ISO parsers reject this.
    "createdAt": "2018-08-22T08:22:55+0000",
    "previewLink": "https://play.goconsensus.com/abc123",
    "ownerData": {"uuid": "o-1", "email": "owner@ptc.com",
                  "firstName": "Ann", "lastName": "Owner"},
    "creatorData": {"uuid": "c-1", "email": "creator@ptc.com",
                    "firstName": "Bob", "lastName": "Creator"},
    "folderInfo": {"uuid": "f-1", "name": "Windchill Demos"},
    "language": {"code": "en", "title": "English"},
    "previewThumbs": ["https://cdn.example/t1.jpg", "https://cdn.example/t2.jpg"],
}


def envelope(items, *, page=1, next_page=0, count=None):
    return {
        "data": {
            "items": items,
            "paging": {"countItems": count if count is not None else len(items),
                       "limit": 500, "page": page,
                       "nextPage": next_page, "previousPage": 0},
            "sorting": ["createdAt"],
        },
        "status": 200,
    }


def client_for(handler) -> HttpConsensusClient:
    return HttpConsensusClient(
        base_url=BASE, api_key="k", api_secret="s", user_email="me@ptc.com",
        source_name="TDD Portal", transport=httpx.MockTransport(handler),
    )


# ──────────────────────────────────────────────────────────────────── auth
def test_auth_travels_in_the_body_not_a_header():
    """The spec declares no securitySchemes; every path is `security: []`."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        seen["method"] = request.method
        return httpx.Response(200, json=envelope([DEMO_ITEM]))

    client_for(handler).search("windchill")

    assert seen["method"] == "POST", "even searches are POST"
    assert "authorization" not in {k.lower() for k in seen["headers"]}
    assert seen["body"]["auth"] == {
        "api_key": "k", "api_secret": "s", "user_email": "me@ptc.com",
        "source_name": "TDD Portal", "user_activity": False,
    }


def test_search_sends_documented_paging_shape():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        seen["path"] = request.url.path
        return httpx.Response(200, json=envelope([]))

    client_for(handler).search("creo", limit=7)

    assert seen["path"] == "/api/integr/v1.0/demo/search"
    assert seen["body"]["query"] == "creo"
    assert seen["body"]["paging"] == {"limit": 7, "page": 1}


# ────────────────────────────────────────────────────────────────── mapping
def test_demo_mapping_matches_documented_fields():
    demo = client_for(lambda r: httpx.Response(200, json=envelope([DEMO_ITEM]))).search("x")[0]

    assert demo.uuid == "11111111-2222-3333-4444-555555555555"
    assert demo.title == "Windchill AI Parts Rationalization"
    assert demo.internal_title == "WC-AI-PR-internal"
    assert demo.preview_link == "https://play.goconsensus.com/abc123"
    assert demo.owner_email == "owner@ptc.com"
    assert demo.folder == "Windchill Demos"
    assert demo.language == "en"
    assert demo.demo_type == "single"
    assert demo.is_published is True
    assert demo.thumbnails == ("https://cdn.example/t1.jpg", "https://cdn.example/t2.jpg")
    # Engagement is not on this object — it must not be invented.
    assert demo.view_count is None


def test_offset_without_colon_parses():
    """'+0000' is what Consensus sends, and it is not universally accepted."""
    demo = client_for(lambda r: httpx.Response(200, json=envelope([DEMO_ITEM]))).search("x")[0]
    assert demo.created_at is not None
    assert demo.created_at.year == 2018 and demo.created_at.month == 8


def test_unparseable_date_degrades_to_none_rather_than_raising():
    item = {**DEMO_ITEM, "createdAt": "not a date"}
    demo = client_for(lambda r: httpx.Response(200, json=envelope([item]))).search("x")[0]
    assert demo.created_at is None


def test_owner_falls_back_to_creator_data():
    """Verified against the live PTC tenant: the spec documents `ownerData`,
    but real records carry only `creatorData`. Losing the field silently is
    worse than falling back."""
    item = {k: v for k, v in DEMO_ITEM.items() if k != "ownerData"}
    demo = client_for(lambda r: httpx.Response(200, json=envelope([item]))).search("x")[0]
    assert demo.owner_email == "creator@ptc.com"


def test_owner_data_still_wins_when_present():
    demo = client_for(lambda r: httpx.Response(200, json=envelope([DEMO_ITEM]))).search("x")[0]
    assert demo.owner_email == "owner@ptc.com"


def test_missing_folder_info_is_not_an_error():
    """Root-level demos come back with no folderInfo."""
    item = {**DEMO_ITEM, "folderInfo": None}
    demo = client_for(lambda r: httpx.Response(200, json=envelope([item]))).search("x")[0]
    assert demo.folder is None


def test_title_falls_back_to_internal_title():
    item = {**DEMO_ITEM, "title": None}
    demo = client_for(lambda r: httpx.Response(200, json=envelope([item]))).search("x")[0]
    assert demo.title == "WC-AI-PR-internal"


# ─────────────────────────────────────────────────────────────── pagination
def test_list_demos_follows_next_page():
    pages = {
        1: envelope([{**DEMO_ITEM, "uuid": "u1"}], page=1, next_page=2, count=2),
        2: envelope([{**DEMO_ITEM, "uuid": "u2"}], page=2, next_page=0, count=2),
    }
    seen_pages = []

    def handler(request):
        page = json.loads(request.content)["paging"]["page"]
        seen_pages.append(page)
        return httpx.Response(200, json=pages[page])

    demos = client_for(handler).list_demos(limit=100)
    assert seen_pages == [1, 2]
    assert [d.uuid for d in demos] == ["u1", "u2"]


def test_list_demos_stops_when_next_page_is_zero():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json=envelope([DEMO_ITEM], next_page=0))

    client_for(handler).list_demos(limit=500)
    assert len(calls) == 1, "nextPage=0 means stop; anything else loops forever"


def test_archived_demos_excluded_by_default():
    items = [{**DEMO_ITEM, "uuid": "live", "isArchived": False},
             {**DEMO_ITEM, "uuid": "old", "isArchived": True}]
    c = client_for(lambda r: httpx.Response(200, json=envelope(items)))
    assert [d.uuid for d in c.list_demos()] == ["live"]
    assert len(c.list_demos(include_archived=True)) == 2


# ─────────────────────────────────────────────────────────────────── errors
def test_error_inside_a_200_body_is_still_an_error():
    """The spec puts the authoritative status in the body; the docs never say
    the HTTP status agrees."""
    body = {"status": 400, "data": {"error": {"code": "BAD_REQUEST", "values": None,
                                              "message": "Bad request message"}}}

    with pytest.raises(ConsensusAPIError) as exc:
        client_for(lambda r: httpx.Response(200, json=body)).search("x")

    assert exc.value.status == 400
    assert exc.value.code == "BAD_REQUEST"
    assert "Bad request message" in str(exc.value)


def test_http_401_surfaces():
    body = {"status": 401, "data": {"error": {"code": "UNAUTHORIZED",
                                              "message": "Invalid auth token"}}}
    with pytest.raises(ConsensusAPIError):
        client_for(lambda r: httpx.Response(401, json=body)).search("x")


def test_non_json_response_is_a_clean_error_not_a_traceback():
    with pytest.raises(ConsensusError, match="non-JSON"):
        client_for(lambda r: httpx.Response(200, text="<html>gateway</html>")).search("x")


def test_server_error_is_retried_then_reported(monkeypatch):
    # Don't actually sleep through the backoff — it would add seconds to every run.
    monkeypatch.setattr("backend.integrations.consensus.time.sleep", lambda _: None)
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(500, json={"status": 500})

    with pytest.raises(ConsensusError):
        client_for(handler).search("x")
    assert len(calls) == 3, "should retry twice before giving up"


# ─────────────────────────────────────────────────────────── createsenddemo
SEND_RESPONSE = {
    "data": {"item": {
        "senddemo_uuid": "99999999-8888-7777-6666-555555555555",
        "senddemo_hash": "ddfsdfsd",
        "isTest": False,
        "recipients": [{
            "invite_hash": "inv123", "invite_uuid": "i-1", "contact_uuid": "c-1",
            "email": "buyer@acme.com", "first_name": "John", "last_name": "Smith",
        }],
    }},
    "status": 200,
}


def test_create_demoboard_sends_documented_body_and_maps_response():
    seen = {}

    def handler(request):
        body = json.loads(request.content)
        if request.url.path.endswith("/demo/search"):
            return httpx.Response(200, json=envelope([DEMO_ITEM]))
        seen["path"] = request.url.path
        seen["body"] = body
        return httpx.Response(200, json=SEND_RESPONSE)

    link = client_for(handler).create_share_link(
        DEMO_ITEM["uuid"], trackable=True, organization="Acme Robotics",
        recipients=[ShareRecipient(email="buyer@acme.com", first_name="John",
                                   last_name="Smith")],
        opportunity="OPP-1", title="Board title", is_test=False,
    )

    assert seen["path"] == "/api/integr/v1.0/sales/createsenddemo"
    assert seen["body"]["organization"] == "Acme Robotics"
    assert seen["body"]["demo_uuid"] == DEMO_ITEM["uuid"]
    assert seen["body"]["creationSource"] == "api"
    # Verified against the live API on 2026-08-31. The address key is
    # `contact_email` -- `email` fails with "This value is required" -- while
    # the names stay `first_name`/`last_name`; `contact_first_name` and
    # `contact_last_name` are accepted and silently ignored.
    assert seen["body"]["share_to"] == [
        {"contact_email": "buyer@acme.com",
         "first_name": "John", "last_name": "Smith"}]

    assert link.kind == "demoboard"
    assert link.send_demo_uuid == "99999999-8888-7777-6666-555555555555"
    assert link.send_demo_hash == "ddfsdfsd"
    # No viewer URL is returned by the API — it is built from the template.
    assert link.url == "https://play.goconsensus.com/ddfsdfsd"
    assert [r.email for r in link.recipients] == ["buyer@acme.com"]
    assert link.recipients[0].invite_hash == "inv123"


def test_demoboard_requires_organization():
    """The spec marks `organization` required; fail before the round trip."""
    def handler(request):
        return httpx.Response(200, json=envelope([DEMO_ITEM]))

    with pytest.raises(ConsensusError, match="organization"):
        client_for(handler).create_share_link(DEMO_ITEM["uuid"], trackable=True)


def test_is_test_is_plumbed_through():
    def handler(request):
        if request.url.path.endswith("/demo/search"):
            return httpx.Response(200, json=envelope([DEMO_ITEM]))
        assert json.loads(request.content)["isTest"] is True
        return httpx.Response(200, json={"data": {"item": {
            **SEND_RESPONSE["data"]["item"], "isTest": True}}, "status": 200})

    link = client_for(handler).create_share_link(
        DEMO_ITEM["uuid"], trackable=True, organization="Acme", is_test=True)
    assert link.is_test is True


def test_sharing_an_unregistered_demo_fails():
    """Consensus can only send what is already registered there."""
    with pytest.raises(ConsensusError, match="not registered"):
        client_for(lambda r: httpx.Response(200, json=envelope([]))).create_share_link(
            "missing-uuid", trackable=True, organization="Acme")


# ───────────────────────────────────────────────────────────── createlink
def test_marketing_link_maps_data_item():
    def handler(request):
        if request.url.path.endswith("/demo/search"):
            return httpx.Response(200, json=envelope([DEMO_ITEM]))
        assert request.url.path == "/api/integr/v1.0/marketing/createlink"
        return httpx.Response(200, json={
            "data": {"item": {"uuid": "l-1", "hash": "mkt99"}}, "status": 200})

    link = client_for(handler).create_share_link(DEMO_ITEM["uuid"], trackable=False)
    assert link.kind == "marketing"
    assert link.url == "https://play.goconsensus.com/mkt99"


def test_untrackable_falls_back_to_preview_link_when_createlink_fails():
    def handler(request):
        if request.url.path.endswith("/demo/search"):
            return httpx.Response(200, json=envelope([DEMO_ITEM]))
        return httpx.Response(200, json={"status": 403, "data": {"error": {
            "code": "FORBIDDEN", "message": "no permission"}}})

    link = client_for(handler).create_share_link(DEMO_ITEM["uuid"], trackable=False)
    assert link.kind == "preview"
    assert link.url == DEMO_ITEM["previewLink"]


def test_viewer_url_template_is_configurable():
    def handler(request):
        if request.url.path.endswith("/demo/search"):
            return httpx.Response(200, json=envelope([DEMO_ITEM]))
        return httpx.Response(200, json=SEND_RESPONSE)

    c = HttpConsensusClient(base_url=BASE, api_key="k", api_secret="s",
                            user_email="me@ptc.com",
                            viewer_url_template="https://demo.ptc.com/v/{hash}",
                            transport=httpx.MockTransport(handler))
    link = c.create_share_link(DEMO_ITEM["uuid"], trackable=True, organization="Acme")
    assert link.url == "https://demo.ptc.com/v/ddfsdfsd"


# ──────────────────────────────────────────────────────────────────── probe
def test_probe_checks_auth_first_then_search():
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/info/userInfo"):
            return httpx.Response(200, json={"data": {
                "user": {"email": "me@ptc.com", "displayName": "Me"},
                "group": {"name": "TDD"}}, "status": 200})
        return httpx.Response(200, json=envelope([DEMO_ITEM]))

    result = client_for(handler).probe()

    assert paths[0] == "/api/integr/v1.0/info/userInfo", "cheapest call verifies creds first"
    assert result["auth"] == {"ok": True, "user_email": "me@ptc.com",
                              "display_name": "Me", "group": "TDD"}
    assert result["demo_search"]["ok"] is True
    assert "uuid" in result["demo_search"]["record_keys"]
    assert result["demo_search"]["mapped"]["uuid"] == DEMO_ITEM["uuid"]


def test_probe_reports_bad_credentials_without_raising():
    def handler(request):
        return httpx.Response(401, json={"status": 401, "data": {"error": {
            "code": "UNAUTHORIZED", "message": "Invalid auth token"}}})

    result = client_for(handler).probe()
    assert result["auth"]["ok"] is False
    assert "Invalid auth token" in result["auth"]["error"]
    assert "demo_search" not in result, "should not continue past a failed auth check"


def test_a_validation_failure_names_the_field_that_is_wrong():
    """Consensus reports validation errors in a top-level `errors` map, not in
    `data.error`, and dropping it turned a precise complaint into
    "error from /sales/createsenddemo" -- which cost a debugging round.
    """
    from backend.integrations.consensus import ConsensusAPIError

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={
            "status": 400, "data": None,
            "errors": {"auth": {"source_name": "Invalid value for source_name field"},
                       "share_to": [{"contact_email": "This value is required."}]},
        })

    client = client_for(handler)
    with pytest.raises(ConsensusAPIError) as caught:
        client.list_demos(limit=1)
    message = str(caught.value)
    assert "share_to[0].contact_email" in message
    assert "This value is required." in message
    assert "auth.source_name" in message


def test_a_recipients_link_is_not_the_sales_preview_link():
    """`?preview=sales` belongs on a card in our own catalogue, not on
    something sent to a customer."""
    client = HttpConsensusClient(
        base_url="https://example.test", api_key="k", api_secret="s",
        user_email="a@b.c",
        viewer_url_template="https://play.goconsensus.com/{hash}?preview=sales")
    assert client._viewer_url("abc") == "https://play.goconsensus.com/abc?preview=sales"
    assert client._share_url("abc") == "https://play.goconsensus.com/abc"
