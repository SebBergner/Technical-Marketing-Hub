"""Application settings, all environment-driven.

Local development needs no configuration at all — it falls back to a SQLite
file. Production sets DATABASE_URL to Azure SQL. Credentials are never
defaulted and never committed; see .env.example.
"""
from __future__ import annotations

import os

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Settings(BaseSettings):
    # Absolute, not ".env" — a relative path resolves against the working
    # directory, so launching from anywhere but the repo root would silently
    # ignore the file and leave every integration on its stub.
    model_config = SettingsConfigDict(
        env_file=os.path.join(BASE_DIR, ".env"), extra="ignore"
    )

    # ---------------------------------------------------------------- storage
    #: "json" keeps the Portal a server-side index with SharePoint as the centre
    #: of gravity — no database to provision. "sql" is retained and tested, for
    #: if the catalogue outgrows files.
    storage_backend: str = "json"

    #: Where file-backed data lives. Local disk on App Service is EPHEMERAL —
    #: it does not survive a restart, a redeploy or scale-out. Point this at an
    #: Azure Files mount before real users submit anything, or every intake
    #: submission is lost on the next deploy. See docs/ARCHITECTURE.md.
    data_dir: str = os.path.join(BASE_DIR, "data", "runtime")

    # Only used when storage_backend == "sql".
    database_url: str = f"sqlite:///{os.path.join(BASE_DIR, 'data', 'runtime', 'hub.db')}"
    sql_echo: bool = False

    # ------------------------------------------------------------ Microsoft Graph
    # Pending the IT ticket. Sites.Selected, app-only.
    graph_tenant_id: str | None = None
    graph_client_id: str | None = None
    graph_client_secret: str | None = None
    graph_site_url: str | None = None
    graph_list_name: str = "Demo Catalog"

    # ---------------------------------------------------------------- Consensus
    # Auth is a body object on every call, not a header — the OpenAPI spec
    # declares no securitySchemes and every path uses `security: []`.
    consensus_base_url: str = "https://app.goconsensus.com"
    consensus_api_key: str | None = None
    consensus_api_secret: str | None = None
    consensus_user_email: str | None = None
    #: Free label we choose; Consensus records it as the calling integration.
    consensus_source_name: str = "TDD Portal"
    #: Sends return only a hash, never a full URL. Configurable so correcting
    #: the viewer host is a config change rather than a code change.
    consensus_viewer_url_template: str = "https://play.goconsensus.com/{hash}"

    # ---------------------------------------------------------------- Brightcove
    brightcove_account_id: str | None = None
    brightcove_client_id: str | None = None
    brightcove_client_secret: str | None = None

    # --------------------------------------------------------------------- auth
    #: "disabled" ignores the Easy Auth headers entirely — correct for local
    #: development, and safe because a forged header must never grant access.
    #: "easyauth" trusts them, and is only correct behind App Service
    #: Authentication with "Require authentication" turned on.
    auth_mode: str = "disabled"

    #: Entra ID group object ids (or app role names) whose members may curate —
    #: decide metadata proposals and trigger a sync. Comma-separated.
    #: Empty means nobody, which fails closed rather than open.
    auth_curator_groups: str = ""

    # ---------------------------------------------------------------- behaviour
    seed_path: str = os.path.join(BASE_DIR, "data", "seed", "assets.json")
    #: Keep the mockup's aspirational sidebar numbers instead of real counts.
    #: Real data is honest but makes stakeholder demos look emptier — flag it,
    #: do not change it silently.
    show_placeholder_counts: bool = False

    @property
    def graph_configured(self) -> bool:
        return all((self.graph_tenant_id, self.graph_client_id, self.graph_client_secret))

    @property
    def consensus_configured(self) -> bool:
        """All four are required — the auth block is rejected without them."""
        return all((self.consensus_base_url, self.consensus_api_key,
                    self.consensus_api_secret, self.consensus_user_email))


settings = Settings()
