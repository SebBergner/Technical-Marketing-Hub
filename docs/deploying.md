# Deploying to Azure App Service

> **See also `docs/HANDOVER-DEPLOYMENT.md`** (written 2026-09-03). This file is
> the *reference* for each Azure setting and why it exists. That one is the
> *current state and running order*: what is live today, the PR to merge, the
> sequence to follow, and the verification steps. Read that one to deploy;
> read this one to understand a setting.

Merging to `main` triggers `.github/workflows/main_technical-marketing-hub.yml`,
which builds and deploys immediately. Two things must be true **before** that
merge, and a third is worth doing the same day.

---

## 1. Turn authentication on

This is the one that matters. `AUTH_MODE` defaults to `disabled`, and in that
mode the app hands every caller a development principal with full rights —
deliberately, so it can be run locally without a tenant. Deployed with Graph
credentials present and auth still disabled, **an anonymous visitor can create
list items in SharePoint and upload files to the document library**.

The app detects exactly this and says so — in the startup log, in
`/api/auth/me` and in `/api/debug/backend` — but a warning is not a guard.
Nothing refuses the request.

There are two ways to turn it on. **1a is the plan of record** (2026-09-23);
1b stays documented and working because it is a legitimate alternative.
Never both at once: with App Service Authentication switched on, the platform
answers `/login` and `/auth/callback` itself and the app's own sign-in never
sees the request.

### 1a. The app's own sign-in — `AUTH_MODE=oidc`

The app runs OpenID Connect against Entra itself (`backend/oidc.py`), on the
callback addresses Seb gave IT on 2026-09-23 — the same pattern AMP is
planned to use. Every route except `/login`, `/auth/callback`, `/logout`,
`/health` and `/api/version` needs a session.

**From IT**, one app registration (or one per slot, which Microsoft
recommends):

- Platform **Web**, redirect URIs
  `https://tmh.ptcxc.com/auth/callback`,
  `https://dev-tmh.ptcxc.com/auth/callback`, and
  `http://localhost:8000/auth/callback` if sign-in should work locally
- Delegated permissions `openid`, `profile`, `email`, admin-consented.
  Nothing else: the app never calls Graph as the signed-in user.
- Back to us: the **tenant id**, **client id** and a **client secret**
- `oid` needs no optional claim — the `profile` scope brings it

**Order matters**, because the last step closes the site:

1. Seb binds `tmh.ptcxc.com` / `dev-tmh.ptcxc.com` to production / staging,
   with TLS, and each answers.
2. On the **staging** slot, add the settings below. `AUTH_MODE=oidc` last.
3. Check on `https://dev-tmh.ptcxc.com`: it sends you to Microsoft and back;
   `/api/auth/me` shows your `object_id` and an empty `warnings`; the
   staging slot's `azurewebsites.net` address redirects to `dev-tmh`.
4. Add the curators' `object_id`s to `AUTH_CURATOR_OIDS` (read them off
   `/api/auth/me` once each of them has signed in).
5. Production the same way, once staging has been lived with.

| Setting | Value | Slot setting? |
|---|---|---|
| `AUTH_MODE` | `oidc` | no — same on both |
| `OIDC_TENANT_ID` / `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` | from IT | only if IT gives one registration per slot |
| `OIDC_REDIRECT_URI` | `https://tmh.ptcxc.com/auth/callback` (prod), `https://dev-tmh…` (staging) | **yes** |
| `CUSTOM_DOMAIN` | `tmh.ptcxc.com` / `dev-tmh.ptcxc.com` | **yes** |
| `SECRET_KEY` | long and random, different per slot | **yes** |
| `HTTPS_ONLY` | `true` | no |
| `SESSION_TIMEOUT_HOURS` / `SESSION_ABSOLUTE_HOURS` | `12` / `24` (the defaults) | no |
| `AUTH_CURATOR_OIDS` | curators' object ids | no — same on both |

The three **yes** rows are the ones a swap would otherwise exchange, which
would send each slot's sign-in to the other slot's address. They are
different per slot by nature, so mark them before the first swap.

Set `CUSTOM_DOMAIN` only once the domain answers: it redirects every
`azurewebsites.net` request to it, so set early it points everyone at
nothing. It is a 302 rather than a 301 for the same reason — a browser never
caches a mistake.

`OIDC_REDIRECT_URI` cannot be derived on Azure: behind App Service the
request reaches the app as http, so a derived address would not match the
https one IT registered. The app warns when it is missing.

### 1b. App Service Authentication — `AUTH_MODE=easyauth`

The platform signs people in and hands the app their identity as headers.
Callbacks are the platform's own, fixed at `/.auth/login/aad/callback`, so
IT would register those instead of the addresses in 1a.

**In the Azure portal, on the Web App:**

1. **Settings → Authentication → Add identity provider**
   - Identity provider: **Microsoft**
   - Tenant type: Workforce
   - App registration: *Create new* (or pick the existing one — it does not
     have to be the same registration the app uses for Graph, and keeping them
     separate is tidier: one identifies visitors, the other reads SharePoint).
   - **Restrict access: Require authentication**
   - Unauthenticated requests: **HTTP 302 redirect to log in**
2. **Settings → Environment variables → App settings**, add:

   | Name | Value |
   |---|---|
   | `AUTH_MODE` | `easyauth` |
   | `AUTH_CURATOR_GROUPS` | the Entra group object id(s), comma separated |

`AUTH_CURATOR_GROUPS` is not optional in the way it looks. With `easyauth` and
an empty value, nobody holds the curator role and every curation endpoint
refuses everyone — the app warns about this too.

**How to check it worked.** Open `/api/auth/me` in a browser after signing in.
It should show your address, `is_dev_principal: false`, and an empty
`warnings` array. If `warnings` is non-empty, read it: each entry names what is
still wrong.

---

### Why this is load-bearing, not good practice

The Consensus api key and secret are organisation-wide. `auth.user_email` is
what selects which Consensus user they act as, and everything the call creates
is owned by that person — so a DemoBoard sent through the Hub is created and
owned by whoever pressed the button, not by the account in configuration. No
per-user Consensus login is involved, which is just as well: their OAuth flow
does not work, the client secret arriving as a bcrypt hash.

Verified read-only on 2026-09-02: `info/userInfo` with a colleague's address
returns *their* profile, and an address with no Consensus account returns 401
rather than quietly falling back to the configured one. It either acts as the
right person or it fails.

Without a signed-in identity there is no address to act as, so every board
would be attributed to one person and the per-recipient tracking a DemoBoard
exists for would be meaningless. Letting the requester type their own address
would be worse: anyone could send a DemoBoard in a colleague's name.

One sentence for IT: *without this app registration, every Consensus DemoBoard
sent from the team's tool is recorded against a single person.*

## 2. Point `DATA_DIR` at Azure Files

App Service local disk does **not** survive a restart, a redeploy or a
scale-out. Everything under `DATA_DIR/owned/` is irreplaceable:

| File | What is lost with it |
|---|---|
| `identity.json` | the stable asset ids. Cannot be rebuilt — every link and every curation reference is keyed on them |
| `curation.json` | editors' picks and rails |
| `stats.json` | view, share and download counters |
| `segments.json` | segment descriptions and owners — `/api/segments` still serves this, but segment pages have had no nav entry point since 2026-09-08 (see `docs/HANDOVER-DEVELOPMENT.md` §8.3), so this file does not currently exist and filling it is low priority |
| `requests.jsonl` | the local copy of intake submissions |

Requests reach SharePoint immediately, so losing `requests.jsonl` costs only
the ones an outage left unsynced. `identity.json` is the one with no second
copy anywhere.

1. Create a storage account and a **file share** (a few GB is ample).
2. Web App → **Settings → Configuration → Path mappings → New Azure Storage
   Mount**
   - Name: `data`
   - Storage type: **Azure Files**
   - Mount path: `/mnt/data`
3. **Environment variables → App settings**: `DATA_DIR` = `/mnt/data`

Then run a sync from the UI so the mirror is populated on the new volume.

---

## 3. The application settings

**Settings → Environment variables → App settings** is the right home for
these — App Service injects them as process environment variables, which is
exactly where `backend/config.py` reads them from, and they are encrypted at
rest. `.env` is not deployed and must not be: it is gitignored precisely so
secrets never enter the repository.

For a PoC this is fine. If this becomes a real service, move the three secrets
to Key Vault and reference them as
`@Microsoft.KeyVault(SecretUri=...)` — the value in App Settings then becomes
a pointer rather than the secret itself, and rotation stops being a redeploy.

### Required

| Name | Notes |
|---|---|
| `AUTH_MODE` | `easyauth` — see above |
| `AUTH_CURATOR_GROUPS` | Entra group object id(s) |
| `DATA_DIR` | `/mnt/data` — see above |
| `GRAPH_TENANT_ID` | |
| `GRAPH_CLIENT_ID` | |
| `GRAPH_CLIENT_SECRET` | **secret** |
| `GRAPH_SITE_URL` | `https://ptccloud.sharepoint.com/sites/EXT-TDD` |
| `GRAPH_LIST_NAME` | `Demo Catalog` |
| `CONSENSUS_BASE_URL` | `https://app.goconsensus.com` |
| `CONSENSUS_API_KEY` | |
| `CONSENSUS_API_SECRET` | **secret** |
| `CONSENSUS_USER_EMAIL` | the fallback acting account. A DemoBoard is created as the **signed-in user**; this is only used when there is no identity, i.e. locally |
| `CONSENSUS_SOURCE_NAME` | `TDD Portal` |
| `CONSENSUS_VIEWER_URL_TEMPLATE` | `https://play.goconsensus.com/{hash}?preview=sales` — the query string is load-bearing; without it the viewer opens with nothing to play. Flipped to `marketing` on 2026-09-02 (Elio: the sales preview shows "Viewer 1"-style usernames and lets a customer be handed a raw preview link), then back to `sales` on 2026-09-08 (Elio, after reviewing with Seb: `marketing` "performed poorly" in practice). Second flip in a week — if it moves again, worth making a single setting the frontend reads too, rather than a value hardcoded in three places |

### Only needed to re-sync Consensus

`CONSENSUS_V2_TOKEN` is a manually obtained bearer token, because Consensus's
OAuth client secret arrives as a bcrypt hash and no encoding of it is accepted
by their token endpoint — see the open questions note. **It will expire.**

That is survivable: the mirror is a file, so the catalogue keeps serving with
a dead token. Only a re-sync fails, and the sync report says so rather than
quietly indexing nothing. The V1 credentials above are separate and healthy,
and they are what sharing and thumbnails use.

`CONSENSUS_OAUTH_*` can be left unset. The flow does not work yet.

---

## After the first deploy

- `/api/debug/backend` — reports which repository, whether Graph and Consensus
  are configured, and the security warnings. Read it first.
- `/api/auth/me` — confirms Easy Auth is actually in front of the app.
- Run a sync from the UI. Nothing runs on a schedule yet, so a fresh instance
  starts from whatever `DATA_DIR` holds.
- Consensus's OAuth redirect URI, if that flow is ever fixed, will need the
  deployed origin rather than `http://localhost:8000`.
