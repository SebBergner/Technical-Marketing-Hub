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

Since 2026-11-28 (optimisation plan WS-H) every test also gets its own empty
DATA_DIR (`data_dir_in_tmp` below), so the suite never reads or writes the
developer's real `data/runtime`, and a run on a laptop sees what CI sees.
"""
from __future__ import annotations

import pytest

from backend.config import settings


@pytest.fixture(autouse=True)
def data_dir_in_tmp(tmp_path_factory, monkeypatch):
    """Each test's own, empty DATA_DIR.

    Until 2026-11-28 the suite shared the developer's real data directory:
    a full run left a seeded catalogue, curation and identity files in
    `data/runtime`, and tests could pass or fail on whatever a developer had
    synced. Every module reads `settings.data_dir` when it is called (none
    fixes the path at import), so repointing it here is enough; DATA_DIR in
    the environment covers the processes some tests start. A test that wants
    the folder somewhere else (often its own `tmp_path`) still sets it, and
    its fixture runs after this one.

    Not `tmp_path` itself: many tests use that for files of their own and
    then make it the data directory, or not, as they choose."""
    folder = tmp_path_factory.mktemp("data_dir")
    monkeypatch.setattr(settings, "data_dir", str(folder))
    monkeypatch.setenv("DATA_DIR", str(folder))
    return folder


@pytest.fixture(scope="session")
def _seeded_template(tmp_path_factory):
    """The seed catalogue (data/seed/assets.json) loaded once per run."""
    from backend.repositories.json_repo import JsonAssetRepository
    from backend.seed import load_seed
    folder = tmp_path_factory.mktemp("seeded_template")
    load_seed(JsonAssetRepository(str(folder)))
    return folder


@pytest.fixture
def seeded_catalogue(data_dir_in_tmp, _seeded_template):
    """This test's DATA_DIR holding the seed catalogue, as a fresh clone
    without credentials has it after startup. For tests that need a real
    catalogue to have segments, families or rails of; a copy each time, so
    what one test changes the next never sees."""
    import shutil
    shutil.copytree(_seeded_template, data_dir_in_tmp, dirs_exist_ok=True)
    return data_dir_in_tmp


@pytest.fixture(autouse=True)
def no_thumbnail_warming(monkeypatch):
    """After a sync the Hub fetches SharePoint pictures in the background
    (services/thumbnails.py) -- with the developer's real Graph client."""
    from backend.services import thumbnails
    monkeypatch.setattr(thumbnails, "warm_soon", lambda repo: None)
    # ...and reads Create New Demo's options ahead (upload_writer.warm_soon).
    from backend.integrations.graph import upload_writer
    monkeypatch.setattr(upload_writer, "warm_soon", lambda: None)


@pytest.fixture(autouse=True)
def never_reach_sharepoint(monkeypatch):
    """A developer's .env names the real Graph app, and get_graph_client()
    builds a live client from it. On 2026-10-28 making a demo PTC Only began
    reading its folder in SharePoint, and test_content_access reached the
    real tenant. Tests that need Graph pass a fake client in themselves."""
    monkeypatch.setattr(settings, "graph_client_secret", "")


@pytest.fixture(autouse=True)
def no_hub_tasks_list(monkeypatch):
    """The Hub Tasks list is real and the team watches it
    (integrations/graph/hub_tasks.py); tests that want it switch it on with
    a fake client."""
    monkeypatch.setattr(settings, "hub_tasks_list", "")


@pytest.fixture(autouse=True)
def no_daily_sync_loop(monkeypatch):
    """The app's startup would otherwise start the daily-sync loop
    (backend/auto_sync.py). Each test's data directory is empty now, so the
    schedule is off there anyway; this stays as the second lock."""
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

    The empty DATA_DIR every test now gets (`data_dir_in_tmp`) means the
    token store holds no real refresh token either; the credentials are
    removed as well, so this guard does not depend on that one.
    """
    import backend.integrations.consensus_oauth as oauth_module

    for name in ("consensus_oauth_client_id", "consensus_oauth_client_secret",
                 "consensus_v2_token"):
        monkeypatch.setattr(settings, name, "")
    oauth_module._singleton = None
    yield
    oauth_module._singleton = None


@pytest.fixture(autouse=True)
def fresh_connections():
    """The circuit breaker counts failures per service across calls
    (integrations/http_policy.py); one test's simulated outage must not make
    the next test's calls fail fast. The Graph, Consensus and V2 clients are
    shared per process too, so each test starts without one."""
    from backend.integrations import consensus, consensus_v2, http_policy
    from backend.integrations.graph import client as graph_client

    def reset():
        http_policy.reset_breakers()
        graph_client.reset_graph_client()
        consensus.reset_consensus_client()
        consensus_v2.reset_v2_client()
    reset()
    yield
    reset()


@pytest.fixture(autouse=True)
def access_files_in_tmp(tmp_path_factory, monkeypatch):
    """Users & groups (backend/access.py) live in owned/ under DATA_DIR,
    which until 2026-11-28 the tests shared with the developer's real data.
    A sign-in in a test would otherwise be recorded in their users.json, and
    groups edited on their Admin page would change what the tests see. Each
    test gets the built-in groups and nobody signed in -- kept apart from
    `data_dir_in_tmp` because many tests point DATA_DIR at their own folder
    and should not find users.json there."""
    import backend.access as access
    folder = tmp_path_factory.mktemp("access")
    monkeypatch.setattr(access, "_owned", lambda name: str(folder / name))
    access._cache.clear()
    # The Admin log (backend/admin_log.py) beside them, for the same reason.
    import backend.admin_log as admin_log
    monkeypatch.setattr(admin_log, "_path", lambda: str(folder / admin_log.LOG_FILE))
