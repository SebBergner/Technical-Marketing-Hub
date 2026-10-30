# Deployment Handover — Technical Marketing Hub

**Rewritten 2026-10-30** to describe how the Hub is deployed today. The earlier
text (September: no SSO, no staging routine, data copied by hand) is in git
history: `git log -- docs/HANDOVER-DEPLOYMENT.md`.

Checked on 2026-10-30 against the code, the workflow and the live staging slot.
This machine has no Azure CLI, so anything only the portal can show is marked
**[verify in portal]**. `SWAP-CHECKLIST.md` is the step-by-step list for a
release; this document explains the setup behind it.

> 中文导读：推送到 `main` 只会部署到 **staging**；production 只在有人点 Swap 时才变。
> 每个 slot 有自己的数据（`owned/`），切换不会带过去。切换步骤看
> `SWAP-CHECKLIST.md`，日常推送看 `GUIDE-zh-push-and-deploy.md`。

---

## 1. The state today

| | Staging | Production |
|---|---|---|
| URL | `https://dev-tmh.ptcxc.com` | `https://tmh.ptcxc.com` |
| Version | see `/api/version` | see `/api/version` |
| Sign-in | OIDC SSO, client id starts `5cc8e937` | OIDC SSO, client id starts `c965ef60` |
| Data share | `portaldatastaging` | `portaldata` |
| Hub Tasks | off (`HUB_TASKS_LIST` empty) | on ("Hub Tasks") |

- The version is the GitHub Actions run number: `v2026.3.<run>`.
- Admin → Overview → **Configuration** shows how a slot is set: sign-in mode,
  Hub Tasks, the upload test library, the shared Admin password, the curator
  settings and the permanent administrators. Use it instead of Cloud Shell for
  those. It first reaches production with the next swap.

---

## 2. How a change ships

```
commit → push to liwei-backend-dev and main → GitHub Actions → staging → (later) Swap → production
```

```bash
git push origin HEAD:liwei-backend-dev HEAD:main
gh run watch <run-id> --repo SebBergner/Technical-Marketing-Hub
```

`.github/workflows/main_technical-marketing-hub.yml` runs on every push to
`main`, and by hand (`workflow_dispatch`):

1. Python 3.13 (local development is 3.12), `pip install -r requirements.txt`.
2. Writes the run number to `BUILD_NUMBER`.
3. **Runs the tests.** A failure stops the deploy.
4. Deploys to app `Technical-Marketing-Hub`, slot **`staging`**, with the
   secret `AZUREAPPSERVICE_PUBLISHPROFILE_STAGING`.

`requirements.txt` is not pinned, so every deploy takes the latest versions
(backlog D14).

**After a push**, poll `https://dev-tmh.ptcxc.com/api/version` until it shows the
new number, because the run finishes before the slot restarts. Then expect,
without signing in:

- `/` → 302;
- `/api/assets` → 401;
- `/login` → 302 to `login.microsoftonline.com` with staging's client id.

**Production moves only by Swap** (Portal → Deployment slots → Swap), by Liwei
only, following `SWAP-CHECKLIST.md`. After a swap staging runs the old code, so
rerun the last deploy.

---

## 3. Azure resources

| | |
|---|---|
| App Service | `Technical-Marketing-Hub`, Python on Linux, built by Oryx (`SCM_DO_BUILD_DURING_DEPLOYMENT`) |
| Resource group / subscription | `Technical-Marketing-Hub_RG` / `AZURE-PTC-CXC` |
| Default host | `technical-marketing-hub-c8gxg4fagycjh5dz.eastus-01.azurewebsites.net`; sign-in returns only to the custom domain, and `oidc.canonical_host` redirects there |
| `DATA_DIR` | `/mnt/data`, an Azure Files mount named `TechnicalMarketingHubFileStorage` |
| Mount | a slot setting, so each slot keeps its own share across a swap |
| Always On | needed per slot for the scheduled sync **[verify in portal]** |

### Which settings stay with a slot

Slot settings stay with the slot; **everything else moves with the code on a
swap**, so production receives staging's values.

- Slot settings, from `SWAP-CHECKLIST.md` **[verify in portal]**: `AUTH_MODE`,
  `OIDC_*`, `SECRET_KEY`, `HTTPS_ONLY`, `AUTH_CURATOR_EMAILS`, `CUSTOM_DOMAIN`,
  `BRIGHTCOVE_*`, and `HUB_TASKS_LIST` on staging.
- Swap trap: `AUTH_MODE` defaults to `disabled`, which gives every caller a
  development principal. Never let a slot run without it. Check sign-in on both
  slots straight after every swap.

### Settings worth knowing

Every setting is in `backend/config.py`, most with the reason beside it.
`.env.example` covers the older ones and has no real values.

| Setting | Meaning |
|---|---|
| `HUB_ADMIN_EMAILS` | Permanent administrators; moves with a swap. **This is what prevents a lockout.** One address on staging on 2026-10-30 (Liwei). Partner addresses are ignored. |
| `AUTH_CURATOR_EMAILS` | Kept on purpose as a spare way in (Liwei, Elio, Seb). Grants Maintain content, not administration. |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | The old shared Admin sign-in. Removed from both slots on 2026-10-30; the code is still there (backlog D2). Do not set them again. |
| `HUB_TASKS_LIST` | The SharePoint list for feedback and tasks. Empty switches it off. |
| `UPLOAD_LIBRARY_OVERRIDES` | Points Create New Demo at a test library. Must be empty outside trials. |
| `GRAPH_GXC_LIBRARY`, `MIGRATION_GXC_LIBRARY` | Default to "GXC Video". Nothing to set. |
| `AUTO_SYNC_SCHEDULER` | The in-process scheduler; on by default. |
| `CONSENSUS_V2_TOKEN` | A token pasted by hand; expires without warning. OAuth takes over if it is ever connected. |

---

## 4. Data

`DATA_DIR` holds two folders. Nothing in them is in git, and **nothing crosses a
swap**.

- **`mirror/`** — copies of SharePoint and Consensus. Rebuilt by a sync.
- **`owned/`** — what only the Hub knows, and **the one thing that must be backed
  up**: groups, Admin log, feedback, archive marks, metadata edits, Related
  picks, Featured, the Consensus licence list, API tokens, usage history.

### Backup

Before every swap, by hand: download `owned/` from share `portaldata` and add a
snapshot of the share. The steps are in `SWAP-CHECKLIST.md`. A manual backup was
taken on 2026-10-30. A recurring Azure Backup is backlog D1 **[verify in portal
whether it was set up]**.

### Refresh

The Hub syncs itself: twice a day by default (06:00 and 18:00 UTC, set on Admin →
Overview), or with the Sync buttons, which need **Run sync & migration**. A lock
file on the share keeps gunicorn workers from running it twice, and a stale lock
is taken over after three hours. Results are in each source's Sync history.

`sync.MAPPING_VERSION` forces a full rebuild on a slot's first sync after it
changes.

### A known risk

Asset ids are slugified titles. For **duplicate Consensus titles** the `-2`, `-3`
suffix follows the order Consensus returns them in, so a shared link could point
at a different demo after a reorder. Measured 2026-09-03: 36 Consensus demos in
such groups. Not fixed; settle it before links are shared outside.

---

## 5. Who can do what

`backend/access.py` holds a fixed list of permissions. Groups and members are kept
on Admin → Users & groups. Every endpoint checks on the server.

| Heading | Permissions |
|---|---|
| Viewing | View the Hub, Preview files, Download files, Access PTC Only content, Access GXC videos, View Hub activity |
| Contributing | Create new demo (Request new asset is hidden while its form is) |
| Maintaining content | Maintain content |
| Administration | View Admin, Manage the Home page, Manage users & groups, Run sync & migration |

- **Built-in groups:** Administrators (everything, always), PTC employees and
  Partners (automatic at sign-in, by account type).
- **The team's group is "Team Member"**, by that name: new permissions are given
  to it once by name (`access.TEAM`). Removing one later sticks.
- **Partners are capped** by `access.PARTNER_ALLOWED`: View the Hub, Preview,
  Download, Request new asset, whatever group they are in. A permission added
  later is not theirs unless that list names it.
- **Retired permissions** in a saved `access.json` are read as the one that took
  them over (`access.MERGED`).
- **API tokens** hold only what `api_tokens.TOKEN_PERMISSIONS` lists, never an
  administrative one, and cannot see GXC.
- **Sign-in gate:** `oidc.require_sign_in` denies by default. Without a sign-in
  only `/health`, `/api/version` and the login routes answer. Diagnostics
  (`/api/debug`, `/api/graph/status`, Consensus status and OAuth) need Run sync &
  migration.

### Restricted content

- **PTC Only:** the card shows to everyone; files open only with Access PTC Only
  content, and it is never customer facing.
- **GXC:** the library "GXC Video" is filtered out at the repository
  (`JsonAssetRepository(gxc=...)`) for anyone without Access GXC videos, so it does
  not exist for them. Downloads follow an Admin switch, off by default. Its
  SharePoint permissions are separate and kept by hand: add people to both lists.
- **Create DemoBoard / sharing through Consensus:** only people on the Consensus
  licence list, administrators included.

---

## 6. Where every credential lives

| Credential | Where |
|---|---|
| Graph, Consensus, Brightcove, OIDC secrets | App Service app settings on each slot; `.env` locally (gitignored) |
| `SECRET_KEY` | App settings, per slot. Without it a restart signs everyone out |
| Publish profile | GitHub secret `AZUREAPPSERVICE_PUBLISHPROFILE_STAGING`. If exposed, reset it in the portal and update the secret |
| API tokens | Only their SHA-256, in `owned/api_tokens.json` |

Never put a secret in chat, a document or the repo. `.env.example` stays free of
real values.

---

## 7. Rollback

- **Production, right after a swap:** press Swap again. Production returns to the
  old code with its own share. Files only the new code reads are ignored, and are
  there again on the next swap forward.
- **A demo archived after the swap** sits in `_Archive` in SharePoint. The old code
  was never run against it, so restore such demos before swapping back.
- **Staging only:**
  ```bash
  gh workflow run "Build and deploy Python app to Azure Web App - Technical-Marketing-Hub" \
    --ref <sha> --repo SebBergner/Technical-Marketing-Hub
  ```
- **Never rolled back by any of these:** app settings and `owned/`. There is no
  migration mechanism for `owned/`, so change its file formats with care.

---

## 8. Other documents

| Document | For |
|---|---|
| `SWAP-CHECKLIST.md` | Each release, step by step |
| `GUIDE-zh-push-and-deploy.md` | Pushing and deploying by hand, in Chinese |
| `deploying.md` | Why each Azure setting exists (some of it predates SSO) |
| `HANDOVER-DEVELOPMENT.md` | The code |
| `BACKLOG.md` | What is left |
