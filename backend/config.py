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
    #: The query string is load-bearing: without it the viewer opens but does
    #: not play. Only a fallback -- the real previewLink comes from V1.
    #:
    #: `sales`, not `marketing`. Briefly `marketing` from 2026-09-02, at
    #: Elio's request, to drop the sales preview's viewer-picker screen.
    #: Reverted 2026-09-08 -- Elio, in review with Seb: the marketing preview
    #: "performed poorly" in practice, and asked to go back.
    consensus_viewer_url_template: str = (
        "https://play.goconsensus.com/{hash}?preview=sales")

    # ---- Consensus V2 (OAuth 2.0). A SEPARATE credential from the V1 pair
    # above: V1 sends api_key/api_secret in the request body, V2 wants a
    # Bearer JWT minted through Authorization Code + PKCE. Both are needed,
    # because V2 is read-only and sharing still lives on V1.
    consensus_oauth_client_id: str | None = None
    consensus_oauth_client_secret: str | None = None
    #: Must match the Callback URL registered in Consensus, character for
    #: character — OAuth compares it exactly, not by host.
    consensus_oauth_redirect_uri: str =         "http://localhost:8000/api/consensus/oauth/callback"
    #: read:write is deliberately absent. V2 is used only for reading.
    consensus_oauth_scopes: str = "public:api:read read:read"
    #: A bearer token pasted by hand, from
    #: https://app.goconsensus.com/api/v2/docs/portal/. Short-lived and tied to
    #: a person — it exists so V2 work can proceed while the OAuth client
    #: secret is unusable, and OAuth takes precedence once authorised.
    consensus_v2_token: str | None = None

    # ---------------------------------------------------------------- Brightcove
    brightcove_account_id: str | None = None
    brightcove_client_id: str | None = None
    brightcove_client_secret: str | None = None

    # --------------------------------------------------------------------- auth
    #: "disabled" ignores the Easy Auth headers entirely — correct for local
    #: development, and safe because a forged header must never grant access.
    #: "easyauth" trusts them, and is only correct behind App Service
    #: Authentication with "Require authentication" turned on.
    #: "oidc" is the app signing people in itself (backend/oidc.py): /login,
    #: /auth/callback, /logout, and a gate in front of every other route.
    auth_mode: str = "disabled"

    #: Entra ID group object ids (or app role names) whose members may curate —
    #: decide metadata proposals and trigger a sync. Comma-separated.
    #: Empty means nobody, which fails closed rather than open.
    auth_curator_groups: str = ""
    #: Curators named by address, comma separated, matched case-insensitively
    #: against the signed-in identity.
    #:
    #: Exists because the curator list is three people who are known by name,
    #: and naming them needs nothing from the identity provider beyond the
    #: address it already asserts -- no group claim to request, no object id
    #: to copy, nothing to keep in step with a directory. Liwei, 2026-09-22.
    #:
    #: The trade-off, written down rather than discovered later: an address is
    #: a weaker key than a group. It changes when somebody's name changes, it
    #: is not revoked when they leave, and keeping it current is a person's
    #: job rather than the directory's. Right for three names; move to
    #: `auth_curator_groups` or an app role before it is a dozen.
    #:
    #: Only ever compared against an address the platform asserted, never one
    #: a caller supplied -- see principal_from_request, which ignores every
    #: header unless auth_mode is easyauth.
    auth_curator_emails: str = ""
    #: Curators by Entra object id (the `oid` claim), comma separated. The
    #: stronger of the two per-person keys: an oid never changes and is never
    #: reused, where an address can do both -- Microsoft's own guidance is not
    #: to authorise on `email` at all. /api/auth/me shows your oid once you
    #: are signed in, which is the easy way to collect the three of them.
    auth_curator_oids: str = ""

    # ------------------------------------------------ sign-in (AUTH_MODE=oidc)
    #: The Entra app registration IT creates for interactive sign-in. Not the
    #: GRAPH_* one: that reads SharePoint as the app itself, this one proves
    #: who a person is, and keeping them apart means neither can be widened
    #: by accident while configuring the other.
    oidc_tenant_id: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    #: Must match a redirect URI on the app registration exactly, and differs
    #: per slot -- so on Azure it has to be a *deployment slot setting*, or a
    #: swap hands each slot the other's address. Left blank locally, where it
    #: is derived from the request (http://localhost:8000/auth/callback).
    oidc_redirect_uri: str = ""

    # The next four keep AMP's names (Seb's app, read 2026-09-23), so the two
    # apps' Azure configuration can be compared line by line.
    #: Signs the session cookie. Unset means a random key per process: nothing
    #: forgeable, but every restart signs everyone out and two instances would
    #: not recognise each other's cookies. security_warnings() says so.
    secret_key: str = ""
    #: Marks the session cookie Secure. True on Azure; false locally, where
    #: a Secure cookie over plain http would simply never be stored.
    https_only: bool = False
    #: Idle timeout, sliding: any request within the window extends it.
    session_timeout_hours: int = 12
    #: Hard ceiling, however active the session is. The identity provider has
    #: no way to reach into our cookie, so without this a person disabled in
    #: Entra would keep access for as long as they kept clicking. Signing in
    #: again is silent while their Microsoft session is alive.
    session_absolute_hours: int = 24
    #: The canonical hostname (tmh.ptcxc.com / dev-tmh.ptcxc.com). When set,
    #: requests arriving on *.azurewebsites.net are redirected to it. A slot
    #: setting for the same reason as the redirect URI, and only to be set once
    #: the custom domain answers -- before that it points everyone at nothing.
    custom_domain: str = ""

    # ------------------------------------------------ the admin bridge (temporary)
    #: A single shared credential for the Admin page, for the stretch before
    #: Entra SSO exists. Deliberately NOT a replacement for it:
    #:
    #:   * one credential for everybody, so nothing an admin does can be
    #:     attributed to a person. That is why it unlocks only work on our own
    #:     `owned/` data and the mirror refresh, never a SharePoint write-back
    #:     (see backend/admin_auth.py for the full reasoning).
    #:   * both blank by default, and every admin route answers 503 while they
    #:     are — a half-configured deployment cannot accidentally expose the
    #:     page, it simply has no admin at all.
    #:
    #: Delete these, and the module that reads them, when SSO lands.
    admin_username: str = ""
    admin_password: str = ""

    # ---------------------------------------------------------------- behaviour
    seed_path: str = os.path.join(BASE_DIR, "data", "seed", "assets.json")
    #: Keep the mockup's aspirational sidebar numbers instead of real counts.
    #: Real data is honest but makes stakeholder demos look emptier — flag it,
    #: do not change it silently.
    show_placeholder_counts: bool = False

    @property
    def oidc_configured(self) -> bool:
        """All three, or sign-in cannot start. The redirect URI is not on the
        list because it has a sensible local default."""
        return bool(self.oidc_tenant_id and self.oidc_client_id
                    and self.oidc_client_secret)

    @property
    def admin_configured(self) -> bool:
        """Both halves, or there is no admin. Checked before every admin route
        so an empty password can never mean "no password required"."""
        return bool(self.admin_username and self.admin_password)

    @property
    def graph_configured(self) -> bool:
        return all((self.graph_tenant_id, self.graph_client_id, self.graph_client_secret))

    @property
    def consensus_v2_configured(self) -> bool:
        """Whether the OAuth client exists. Says nothing about whether anyone
        has authorised yet — that is a stored refresh token, not config."""
        return bool(self.consensus_oauth_client_id
                    and self.consensus_oauth_client_secret)

    @property
    def consensus_configured(self) -> bool:
        """All four are required — the auth block is rejected without them."""
        return all((self.consensus_base_url, self.consensus_api_key,
                    self.consensus_api_secret, self.consensus_user_email))


settings = Settings()
