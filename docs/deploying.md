# Deploying to Azure App Service

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
| `segments.json` | the segment page descriptions and owners |
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
| `CONSENSUS_VIEWER_URL_TEMPLATE` | `https://play.goconsensus.com/{hash}?preview=sales` — the query string is load-bearing; without it the viewer opens with nothing to play |

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
