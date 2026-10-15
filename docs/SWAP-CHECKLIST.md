# Slot swap checklist (staging → production)

Written 2026-10-15 for the swap planned on **Friday 2026-10-16**: production
goes from **v2026.3.72** (2026-10-06) to the staging build (**v2026.3.100**
or later). Reusable for later swaps; update the version numbers and the
"what is new" list each time.

> 中文导读：明天切换照着这份做。最要紧的三件事：切换前确认 /migration 没在跑；
> 切换后**马上**检查两个 slot 的登录（并把当前代码重新部署到 staging）；生产上
> 跑一次完整同步，再设好管理员和权限组。生产的数据（owned/）和 staging 是分开的，
> staging 上做的设置不会带过去。

## What changes for production users

Everything built since 2026-10-06, all of it new on production:

- Users & groups (Administrators / PTC employees / Partners + custom groups) and
  17 permissions; partners never get View Admin, Manage users, access requests
  or Create new demo.
- Open / Internal per demo, the SharePoint partner rule, and **requests** to make
  a demo Internal (PTC employees ask, Manage content access decides).
- Content age: kit dates from files, Published filter and Sort, age badges,
  Still current (12 months), Content review and Hub-only **archive**.
- Hub activity (`#/activity`) for all PTC employees; per-person usage tracking
  for PTC accounts, partners anonymous.
- Admin page reorganised (Overview, Home page, Content dashboard + Data
  completeness, Content review, Content access, Hub usage, Users & groups,
  Sign-ins + the append-only **Admin log**).
- Demo pages: a Details | Manage tab for people who may change a demo.
- **Create New Demo** (2026-10-15): people with "Create new demo" (only
  Administrators by default) create a video in Demo Video or a kit in the Demo
  Catalog, metadata first; it is listed once someone with Review content
  publishes it. New folders only -- nothing existing is changed. Tested end to
  end against the test library only; the first real kit on production is worth
  watching in SharePoint (its Language / Owned By columns were never written by
  a test).
- The Hub page rebuilt (index.html 2.6 MB → 79 KB; scripts as ES modules).

## Facts that shape the swap

- **Each slot has its own data share** (`portaldata` for production,
  `portaldatastaging` for staging; the mount is a slot setting). Nothing set on
  staging — groups, Featured, hidden demos, archive marks, Still current,
  access requests, the Admin log, usage history, sample activity — exists on
  production. Production starts from its own `owned/` as of 2026-10-06.
- **Sticky (slot) settings stay with the slot:** the nine SSO settings
  (AUTH_MODE, OIDC_*, SECRET_KEY, HTTPS_ONLY, AUTH_CURATOR_EMAILS,
  CUSTOM_DOMAIN) and the three BRIGHTCOVE_* settings. **Everything else moves
  with the code**, so production receives staging's values for them.
- **New settings since v2026.3.72:** `HUB_ADMIN_EMAILS` (no default; names the
  Hub's permanent administrators) and `STILL_CURRENT_MONTHS` (default 12).
- `sync.MAPPING_VERSION` is 3 in the new code: **the first SharePoint sync on
  production rebuilds the mirror in full** (kit dates from files, demo
  creators). Until it has run, production shows migration-day dates on kits
  and an empty "Whose demos were used most".

## Before the swap

1. **No migration is running** — `/migration` on both slots shows no active run.
2. **Staging is the build you want**: `https://dev-tmh.ptcxc.com/api/version`
   shows the expected version; sign in and spot-check Home, a demo page, Hub
   activity and the Admin page.
3. **Settings by name** (Cloud Shell; there is no az CLI on the workstation):
   ```bash
   az webapp config appsettings list -g Technical-Marketing-Hub_RG -n Technical-Marketing-Hub \
     --query "[].[name,slotSetting]" -o table
   az webapp config appsettings list -g Technical-Marketing-Hub_RG -n Technical-Marketing-Hub \
     --slot staging --query "[].[name,slotSetting]" -o table
   ```
   - `HUB_ADMIN_EMAILS` is set on **staging** with the people who must always be
     administrators (it moves to production with the swap). At least one PTC
     address; partner addresses are ignored for admin rights.
   - The SSO and BRIGHTCOVE settings are slot settings on both slots.
4. **Back up production `owned/`** (Azure Portal → storage account → file share
   `portaldata` → `owned/` → download). It is the only data a sync cannot
   rebuild; the swap does not touch it, this is just the safety net.

## The swap

5. Azure Portal → Technical-Marketing-Hub → Deployment slots → **Swap**
   staging → production. Note the time.

## Immediately after (first five minutes)

6. **Both slots enforce sign-in.** Anonymously:
   - `https://tmh.ptcxc.com/` and `https://dev-tmh.ptcxc.com/` → 302 to `/login`;
   - `/api/auth/me` on both → 401.
   Then sign in to production: the Microsoft page shows production's client
   id (starts `c965ef60`) and comes back to `tmh.ptcxc.com`.
7. **Redeploy the current commit to staging.** After a swap, staging runs the
   old code (v2026.3.72) against staging's newer data. Rerun the last deploy so
   both slots run the same build:
   ```bash
   gh run rerun $(gh run list --repo SebBergner/Technical-Marketing-Hub --limit 1 \
     --json databaseId -q '.[0].databaseId') --repo SebBergner/Technical-Marketing-Hub
   ```
   Then `https://dev-tmh.ptcxc.com/api/version` shows the new version again.
8. `https://tmh.ptcxc.com/api/version` shows the new version.

## On production, in order

9. **Admin → Users & groups.** You should be in Administrators (via
   `HUB_ADMIN_EMAILS` or as a member). Add the other administrators and any
   team groups (e.g. a group with View Admin + Review content for reviewers;
   Marketing ops). PTC employees gain View Hub activity and Request content
   access change automatically.
10. **Admin → Overview → Sync SharePoint now**, then **Sync Consensus now**.
    The SharePoint run is a full rebuild this once (MAPPING_VERSION 3); expect
    it to take longer than a normal sync. Afterwards:
    - Content dashboard: totals close to staging's (about 1,287 demos);
    - a few demo pages: kit dates are no longer 2024-03/05 migration days;
    - Sync history shows every part (Demo Catalog, Demo Video, pages, VMs,
      partner downloads) succeeded.
11. **Automatic sync**: Overview → switch on, two times a day; and in the Azure
    Portal, **Always On** for the production slot if not already.
12. **Home page tab**: Featured demos and the two display options (production
    has its own; re-pick if wanted). **Content access → Hidden demos**: hide the
    four old page-only story pages if still wanted.
13. **`UPLOAD_LIBRARY_OVERRIDES` must be empty** on both slots (it points
    Create New Demo at a test library; only for trials).
14. **Do not load sample activity on production.** Hub activity starts empty
    and fills with real use from today; per-person tracking on production
    starts at the swap.
15. **Spot checks**: search and filters; a demo page (Files, Manage tab for an
    admin); Hub activity opens; Admin → Sign-ins → Admin log shows your sync
    and group changes; a partner test account (if you have one) cannot open
    `/admin`.

## If something is wrong

- **Swap back** (same Swap button). Production returns to v2026.3.72 with its
  own share; files the new code wrote there (`access.json`, `admin_log.jsonl`,
  `archived.json`, ...) are ignored by the old code, and are there again on
  the next swap forward.
- Settings are not rolled back by a swap or a redeploy; undo a setting change
  by hand.
- Code-only rollback of a slot: `gh workflow run "Build and deploy Python app to
  Azure Web App - Technical-Marketing-Hub" --ref <sha> --repo SebBergner/Technical-Marketing-Hub`
  (deploys to staging).
