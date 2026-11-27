"""Connection behaviour of the Graph, Consensus and Brightcove clients.

Retries, budgets, shared clients and logging -- the plumbing under every
integration (optimisation plan 2026-11-26, workstream WS-B). Everything runs
on httpx.MockTransport; nothing here reaches a real tenant.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from backend.integrations import http_policy
from backend.integrations.consensus import PATHS, ConsensusError, HttpConsensusClient
from backend.integrations.graph.client import GraphClient, GraphError

SITE_URL = "https://ptccloud.sharepoint.com/sites/EXT-TDD"


@pytest.fixture(autouse=True)
def no_sleeping(monkeypatch):
    """Backoff waits are real `time.sleep` calls; record them instead."""
    waits: list[float] = []
    monkeypatch.setattr("time.sleep", lambda s: waits.append(s))
    return waits


def graph_for(handler) -> GraphClient:
    return GraphClient(tenant_id="t", client_id="c", client_secret="s", site_url=SITE_URL,
                       transport=httpx.MockTransport(handler),
                       token_provider=lambda: "token")


def consensus_for(handler) -> HttpConsensusClient:
    return HttpConsensusClient(base_url="https://app.goconsensus.com", api_key="k",
                               api_secret="s", user_email="me@example.com",
                               transport=httpx.MockTransport(handler))


# ───────────────────────────────────────────── 1. headers survive a retry
def test_a_throttled_patch_keeps_if_match_on_every_attempt():
    """Attempts 2-4 used to lose If-Match and Content-Type, so a throttled
    write could overwrite a concurrent SharePoint edit."""
    seen = []

    def handler(request):
        seen.append((request.headers.get("If-Match"), request.headers.get("Content-Type")))
        if len(seen) == 1:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, json={"Title": "x"})

    graph_for(handler).update_list_item_fields("d", "i", {"Title": "x"}, etag='"etag,7"')
    assert seen == [('"etag,7"', "application/json")] * 2


# ───────────────────────────────────── 2. a write is not sent twice blind
def test_a_post_that_timed_out_after_sending_is_not_resent():
    """A ReadTimeout means SharePoint may have created the item already;
    retrying it made two Demo Requests."""
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(GraphError, match="not retried"):
        graph_for(handler)._request("POST", "/sites/s/lists/l/items", json={"fields": {}})
    assert len(calls) == 1


def test_a_post_that_got_a_500_is_not_resent():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(500, json={"error": {"message": "boom"}})

    with pytest.raises(GraphError):
        graph_for(handler)._request("POST", "/sites/s/lists/l/items", json={"fields": {}})
    assert len(calls) == 1


def _connect_error(request):
    raise httpx.ConnectError("refused", request=request)


@pytest.mark.parametrize("first", [
    _connect_error,
    lambda request: httpx.Response(429, headers={"Retry-After": "1"}),
    lambda request: httpx.Response(503, headers={"Retry-After": "1"}),
], ids=["connect-error", "429", "503-retry-after"])
def test_a_post_that_never_ran_is_resent(first):
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return first(request)
        return httpx.Response(201, json={"id": "7"})

    assert graph_for(handler)._request("POST", "/x", json={})["id"] == "7"
    assert len(calls) == 2


def test_a_get_is_still_retried_after_a_read_timeout_and_a_502():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ReadTimeout("slow", request=request)
        if len(calls) == 2:
            return httpx.Response(502)
        return httpx.Response(200, json={"id": "site"})

    assert graph_for(handler)._request("GET", "/sites/x")["id"] == "site"
    assert len(calls) == 3


def test_an_attachment_put_with_rename_is_not_resent_after_a_timeout():
    from backend.integrations.graph import requests_list
    calls = []

    def handler(request):
        if request.url.path.endswith("/drives"):
            return httpx.Response(200, json={"value": [
                {"id": "docs", "name": requests_list.ATTACHMENT_LIBRARY}]})
        calls.append(request.method)
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(requests_list.RequestWriteError):
        requests_list.upload_attachment(graph_for(handler), "site", "R-1", "brief.docx", b"x")
    assert calls == ["PUT"]


def test_createsenddemo_is_not_resent_after_a_500_but_a_search_is():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(500, json={"status": 500})

    client = consensus_for(handler)
    with pytest.raises(ConsensusError):
        client._post(PATHS["send_demo"], {"organization": "Acme"})
    assert calls == [PATHS["send_demo"]], "a second DemoBoard is worse than an error"

    calls.clear()
    with pytest.raises(ConsensusError):
        client._post(PATHS["demo_search"], {})
    assert len(calls) == 3


def test_createsenddemo_is_resent_when_throttled():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, json={"status": 200, "data": {"item": {}}})

    consensus_for(handler)._post(PATHS["send_demo"], {"organization": "Acme"})
    assert len(calls) == 2


# ───────────────────────────────────────────── 3. Retry-After, both forms
def test_retry_after_reads_seconds_and_http_dates():
    now = datetime(2026, 11, 26, 10, 0, 0, tzinfo=timezone.utc)
    assert http_policy.parse_retry_after("7", now=now) == 7
    assert http_policy.parse_retry_after("Thu, 26 Nov 2026 10:00:30 GMT", now=now) == 30
    assert http_policy.parse_retry_after("Thu, 26 Nov 2026 09:00:00 GMT", now=now) == 0
    assert http_policy.parse_retry_after("-3", now=now) == 0
    assert http_policy.parse_retry_after("soon", now=now) is None
    assert http_policy.parse_retry_after(None) is None


def test_an_http_date_retry_after_no_longer_raises_and_the_wait_is_capped(no_sleeping):
    """Graph and Consensus parsed Retry-After with float(), so the date form
    raised ValueError out of the client."""
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "Fri, 01 Jan 2100 00:00:00 GMT"})
        return httpx.Response(200, json={"status": 200, "data": {"items": []}})

    assert consensus_for(handler).search("x") == []
    assert no_sleeping == [http_policy.CONSENSUS_BACKGROUND.max_wait]


# ─────────────────────────────────────────────────── 6. budgets, breaker
def test_an_interactive_call_tries_twice_and_never_sleeps_past_its_deadline(no_sleeping):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503)

    with http_policy.interactive(), pytest.raises(GraphError):
        graph_for(handler)._request("GET", "/sites/x")
    assert len(calls) == 2
    assert sum(no_sleeping) <= http_policy.INTERACTIVE.deadline


def test_an_interactive_call_gives_up_at_once_when_told_to_come_back_later(no_sleeping):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, headers={"Retry-After": "60"})

    with http_policy.interactive(), pytest.raises(GraphError, match="429"):
        graph_for(handler)._request("GET", "/sites/x")
    assert len(calls) == 1 and no_sleeping == []


def test_an_interactive_call_carries_a_short_timeout():
    seen = {}

    def handler(request):
        seen.update(request.extensions["timeout"])
        return httpx.Response(200, json={})

    with http_policy.interactive():
        graph_for(handler)._request("GET", "/sites/x")
    assert seen["connect"] <= http_policy.INTERACTIVE.connect
    assert seen["read"] <= http_policy.INTERACTIVE.deadline


def test_background_calls_keep_the_long_budget():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503)

    with pytest.raises(GraphError):
        graph_for(handler)._request("GET", "/sites/x")
    assert len(calls) == http_policy.GRAPH_BACKGROUND.attempts


def test_the_breaker_fails_interactive_calls_fast_and_lets_sync_through():
    calls = []

    def down(request):
        calls.append(1)
        raise httpx.ConnectError("down", request=request)

    client = graph_for(down)
    for _ in range(http_policy.BREAKER_THRESHOLD):
        with http_policy.interactive(), pytest.raises(GraphError):
            client._request("GET", "/sites/x")
    calls.clear()
    with http_policy.interactive(), pytest.raises(GraphError, match="failing"):
        client._request("GET", "/sites/x")
    assert calls == [], "an open breaker costs a page view nothing"

    # A background call still goes out, and its success closes the breaker.
    up = graph_for(lambda request: httpx.Response(200, json={"id": "ok"}))
    assert up._request("GET", "/sites/x")["id"] == "ok"
    with http_policy.interactive():
        assert up._request("GET", "/sites/x")["id"] == "ok"


def test_a_404_does_not_count_against_the_breaker():
    client = graph_for(lambda request: httpx.Response(404))
    for _ in range(http_policy.BREAKER_THRESHOLD + 1):
        with http_policy.interactive():
            assert client._request("GET", "/x") is None


# ─────────────────────────────────────── 4. no blocking work on the loop
def test_no_router_endpoint_is_async():
    """With one gunicorn worker, an `async def` route that waits on Graph,
    openpyxl or the disk freezes every other request. Plain `def` routes run
    in the thread pool. Async *dependencies* that only read the request are
    fine; this checks the endpoints."""
    import inspect

    from fastapi.routing import APIRoute

    from app import app
    offenders = [f"{sorted(r.methods)} {r.path}" for r in app.routes
                 if isinstance(r, APIRoute)
                 and r.endpoint.__module__.startswith("backend.routers")
                 and inspect.iscoroutinefunction(r.endpoint)]
    assert offenders == []


@pytest.fixture
def api(tmp_path):
    from fastapi.testclient import TestClient

    from app import app
    from backend.deps import get_repo
    from backend.repositories.json_repo import JsonAssetRepository
    repo = JsonAssetRepository(str(tmp_path))
    app.dependency_overrides[get_repo] = lambda: repo
    try:
        yield TestClient(app, base_url="http://localhost")
    finally:
        app.dependency_overrides.pop(get_repo, None)


def test_a_request_takes_at_most_ten_files_and_reports_the_true_size(api):
    import json

    from backend.integrations.graph.requests_list import MAX_ATTACHMENT_BYTES
    from backend.routers.requests import MAX_ATTACHMENTS
    body = {"asset_type": "vdk", "products": ["Windchill"], "brief": "A story"}
    files = [("files", (f"f{i}.pdf", b"%PDF", "application/pdf"))
             for i in range(MAX_ATTACHMENTS + 2)]
    files.append(("files", ("big.pdf", b"x" * (MAX_ATTACHMENT_BYTES + 3 * 1024 * 1024),
                            "application/pdf")))
    r = api.post("/api/requests/with-files", data={"request": json.dumps(body)}, files=files)
    assert r.status_code == 201
    rejected = r.json()["attachments_rejected"]
    assert sum("only 10 files" in x for x in rejected) == 3
    assert "big.pdf" in " ".join(rejected)          # over the cap, refused unread

    r = api.post("/api/requests/with-files", data={"request": json.dumps(body)},
                 files=[("files", ("big.pdf", b"x" * (MAX_ATTACHMENT_BYTES + 3 * 1024 * 1024),
                                   "application/pdf"))])
    assert "7.0 MB is over" in " ".join(r.json()["attachments_rejected"])
