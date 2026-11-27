"""Connection behaviour of the Graph, Consensus and Brightcove clients.

Retries, budgets, shared clients and logging -- the plumbing under every
integration (optimisation plan 2026-11-26, workstream WS-B). Everything runs
on httpx.MockTransport; nothing here reaches a real tenant.
"""
from __future__ import annotations

import httpx
import pytest

from backend.integrations.graph.client import GraphClient

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
