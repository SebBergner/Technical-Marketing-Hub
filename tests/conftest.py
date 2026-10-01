"""Suite-wide guards.

Everything here exists to keep the tests off the live tenants. The Graph half
of this lesson is already written down in test_graph_api.py's
`never_reach_a_real_tenant` ("the Consensus suite already learned this the
expensive way"); the Consensus half was never generalised, and on 2026-09-21
it bit: adding an endpoint that reads the OAuth status was enough to make
`test_the_sync_endpoint_is_where_the_ui_expects_it` run a **real sync against
the live Consensus tenant** and come back 200 instead of the 503 it asserts.

The mechanism is worth understanding before removing any of this.
`consensus_oauth.get_oauth()` caches a process-wide instance whose token store
path is fixed at construction from `settings.data_dir`. Whichever test touches
it first decides, for the whole run, whether the suite is looking at a
developer's real refresh token or at nothing — so the same test passed alone
and failed in the full suite, which is the signature of exactly this class of
bug rather than a flaky one.
"""
from __future__ import annotations

import pytest

from backend.config import settings


@pytest.fixture(autouse=True)
def no_daily_sync_loop(monkeypatch):
    """The app's startup would otherwise start the daily-sync loop, and the
    suite shares the developer's real data directory -- where the schedule
    may well be switched on (backend/auto_sync.py)."""
    monkeypatch.setattr(settings, "auto_sync_scheduler", False)


@pytest.fixture(autouse=True)
def never_reach_brightcove(monkeypatch):
    """The Demo Video sync now reads posters from Brightcove whenever the
    settings name an account, and a developer's .env may well do so. Tests
    that want a Brightcove client build one with a mock transport and pass
    it in; nothing reaches the real account through the settings."""
    monkeypatch.setattr(settings, "brightcove_client_id", "")
    monkeypatch.setattr(settings, "brightcove_client_secret", "")


@pytest.fixture(autouse=True)
def no_migration_runs(monkeypatch):
    """A developer's .env may enable migration runs on their machine; the
    suite must never start or resume one against the real tenant. Tests of
    the runner switch it on themselves, with fake clients."""
    monkeypatch.setattr(settings, "migration_runner_enabled", False)


@pytest.fixture(autouse=True)
def never_reach_consensus(monkeypatch):
    """No test authenticates to Consensus unless it deliberately builds a
    client with a mock transport.

    Both doors into `get_v2_client()` are shut — the OAuth client, and the
    hand-pasted token that predates it — and the cached OAuth singleton is
    reset on either side, since a neighbouring test may have primed it against
    the developer's real token directory before this fixture ever ran.

    Deliberately NOT done by repointing `settings.data_dir`: that is the whole
    catalogue's home, and blanking it here broke the segment tests, which
    legitimately read real seeded data. The narrow fix is to remove the
    credentials, not the data.
    """
    import backend.integrations.consensus_oauth as oauth_module

    for name in ("consensus_oauth_client_id", "consensus_oauth_client_secret",
                 "consensus_v2_token"):
        monkeypatch.setattr(settings, name, "")
    oauth_module._singleton = None
    yield
    oauth_module._singleton = None
