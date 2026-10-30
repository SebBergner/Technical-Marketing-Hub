# Slot swap checklist (staging → production)

Updated 2026-10-29 for the release swap before **Monday 2026-11-02**:
production goes from **v2026.3.123** (2026-10-20, `6cdd300`) to the staging
build (**v2026.3.163** or later, `6afc0e9`+). The first version of this list
was written for the 10/16 swap (v72 → v100). Reusable for later swaps; update
the version numbers and the "what is new" list each time.

> 中文导读：切换前做三件事：在 staging 上测一次归档和恢复、确认 /migration 没在跑、
> 备份 production 的 owned/。切换后**马上**检查两个 slot 的登录，并把当前代码重新部署到
> staging。然后在 production 上：确认 Team Member 组拿到了 Maintain content 和 View GXC videos，跑一次完整同步，
> 上传 Consensus 名单，填 Report owners，按需要建 GXC 组。production 的数据（owned/）
> 和 staging 是分开的，staging 上做的设置不会带过去。

## What changes for production users

Everything built since 2026-10-20 is new on production:

- **No review** (Liwei 10/28): whoever may create, edit or upload does it
  directly. "Create without review" and "Request content access change" are
  gone; people without a permission use Share feedback instead.
- **Edit metadata** on a demo's Details card (A1), including the preview video
  and the card picture; only changed fields are checked. Demo Owner (A4),
  product version (A11), video subtypes that follow the video type (A15), and
  "assumed" marks for values the Hub guessed.
- **Archive** moves the demo's folder into the library's `_Archive` folder
  (A8), with Restore; **Content to review** helps the team archive or confirm
  old demos in bulk (A6). Permission: Maintain content.
- **Share feedback** on a demo's action bar and **Get help** in the sidebar
  (A2), sent to each segment's owners (Admin → Report owners); demos without an
  Owner go to their segment's owners. No email in v1.
- **PTC Only** (was "Internal"): a PTC Only demo is never customer facing.
- **Create DemoBoard** only for people on Elio's Consensus licence list
  (Admin → Users & groups → Consensus licences). Administrators without a
  licence do not see it either.
- **Related demos** at the foot of a demo's page (A13), picked automatically or
  by hand.
- Hub activity: pick a creator to see their most used demos. Tiles show dates,
  a table view with CSV export, the Dashboard (Library and Usage tabs),
  freshness, data-update time.
- Hidden: Request New Asset, the Value Roadmap tab, the sidebar feedback link,
  the SCO segment (its one demo keeps its value).
- **GXC videos** (10/29): a separate library "GXC Video" that only "View GXC
  videos" sees (Administrators always; Team Member once; partners never).
  Without it a GXC video does not exist on the Hub, its link included.
  Downloads are switched off by default (Admin → Content access).
- Admin: menu down the left, an icon per tab; Overview links to the Brightcove
  migration page.

## Facts that shape the swap

- **Each slot has its own data share** (`portaldata` for production,
  `portaldatastaging` for staging; the mount is a slot setting). Nothing set on
  staging exists on production: groups, Featured, the Consensus licence list,
  Report owners, feedback, archive marks, the Admin log, usage history.
- **Sticky (slot) settings stay with the slot:** the SSO settings (AUTH_MODE,
  OIDC_*, SECRET_KEY, HTTPS_ONLY, AUTH_CURATOR_EMAILS, CUSTOM_DOMAIN), the
  BRIGHTCOVE_* settings, and `HUB_TASKS_LIST` on staging (empty, so trials
  there do not reach the team's list). **Everything else moves with the code.**
- **New settings since v2026.3.123:** `GRAPH_GXC_LIBRARY` and
  `MIGRATION_GXC_LIBRARY`, both defaulting to "GXC Video". Nothing to set.
- **Fewer permissions (2026-10-30), 12 shown under four headings.** Edit
  metadata, Manage content access, Review content, Archive content and See
  archived content are one, **Maintain content**; Run Brightcove migration is
  part of **Run sync & migration**; Request new asset is hidden. A group holding
  any old one holds the new one. Removed permissions (Create without review,
  Request content access change) drop out of every group.
- **Partners hold at most View the Hub, Preview, Download and Request new
  asset**, whatever group they are in: never PTC Only, GXC, Hub activity,
  Maintain content or anything administrative.
- **Permissions are given once, by group name**, the first time production's
  `access.json` is read by the new code: Maintain content and View GXC videos
  to the group named **"Team Member"** (Administrators have everything). The
  name must match (case does not matter); a group renamed later does not get
  them again.
- `sync.MAPPING_VERSION` is 5 in the new code (3 on production): **the first
  SharePoint sync on production rebuilds the mirror in full** (Demo Owner,
  product version, thumbnails, assumed values). Until it has run, production
  shows those fields empty.
- `_Archive` exists in Demo Catalog, Demo Video and GXC Video (checked
  2026-10-29, all empty). Archive refuses in a library without one.

## Before the swap

1. **Archive test on staging** (Seb's High item, with Liwei): archive the
   oldest, never-used demo; check in SharePoint that its folder moved into
   `_Archive` and kept its permissions; restore it from Admin → Content review
   and check it is back at the library root and listed again.
2. **No migration is running** — `/migration` on both slots shows no active run.
3. **Staging is the build you want**: `https://dev-tmh.ptcxc.com/api/version`
   shows the expected version; sign in and spot-check Home, a demo page, Hub
   activity and the Admin page.
4. **Settings by name** (Cloud Shell; there is no az CLI on the workstation):
   ```bash
   az webapp config appsettings list -g Technical-Marketing-Hub_RG -n Technical-Marketing-Hub \
     --query "[].[name,slotSetting]" -o table
   az webapp config appsettings list -g Technical-Marketing-Hub_RG -n Technical-Marketing-Hub \
     --slot staging --query "[].[name,slotSetting]" -o table
   ```
   - `HUB_ADMIN_EMAILS` on staging names the permanent administrators (it moves
     to production).
   - The SSO, BRIGHTCOVE and staging's `HUB_TASKS_LIST` settings are slot
     settings.
   - `UPLOAD_LIBRARY_OVERRIDES` is empty on both slots.
5. **Production's team group is still named "Team Member"** (Admin → Users &
   groups on `tmh.ptcxc.com`; 26 members on 2026-10-29). Do not rename it
   before the swap.
6. **Back up production `owned/`** (Azure Portal → storage account → file share
   `portaldata` → `owned/` → download). It is the only data a sync cannot
   rebuild; the swap does not touch it, this is just the safety net.

## The swap

7. Azure Portal → Technical-Marketing-Hub → Deployment slots → **Swap**
   staging → production. Note the time.

## Immediately after (first five minutes)

8. **Both slots enforce sign-in.** Anonymously:
   - `https://tmh.ptcxc.com/` and `https://dev-tmh.ptcxc.com/` → 302 to `/login`;
   - `/api/assets` on both → 401.
   Then sign in to production: the Microsoft page shows production's client
   id (starts `c965ef60`) and comes back to `tmh.ptcxc.com`. Staging's starts
   `5cc8e937`.
9. **Redeploy the current commit to staging.** After a swap, staging runs the
   old code (v2026.3.123) against staging's newer data. Rerun the last deploy so
   both slots run the same build:
   ```bash
   gh run rerun $(gh run list --repo SebBergner/Technical-Marketing-Hub --limit 1 \
     --json databaseId -q '.[0].databaseId') --repo SebBergner/Technical-Marketing-Hub
   ```
   Then `https://dev-tmh.ptcxc.com/api/version` shows the new version again.
10. `https://tmh.ptcxc.com/api/version` shows the new version.

## On production, in order

11. **Admin → Users & groups.** Team Member now has Maintain content and View
    GXC videos; Administrators has every permission. If Team Member lacks them,
    tick them by hand. Check no other group holds more than it should under the
    new, broader Maintain content.
12. **Admin → Overview → Sync SharePoint now**, then **Sync Consensus now**.
    The SharePoint run is a full rebuild this once (MAPPING_VERSION 5); expect
    it to take longer. Afterwards:
    - Sync history shows every part succeeded: Demo Catalog, Demo Video, GXC
      Video, pages, VMs, partner downloads;
    - Content dashboard totals close to staging's;
    - a few demo pages show Demo Owner and product version where SharePoint
      has them.
13. **Automatic sync**: Overview → on, two times a day (if not already).
14. **Consensus licences** (Users & groups): upload Elio's CSV again (October
    2026 version, 263 people, 19 partners). Without it nobody sees Create
    DemoBoard.
15. **Report owners**: name each segment's owners and General's. Without them
    every feedback lands in General and nobody is told.
16. **GXC**: anyone besides Team Member and Administrators who should see GXC
    videos goes into a group with View GXC videos (PTC addresses only), and the
    same people into the SharePoint GXC group. Downloads stay off unless decided
    otherwise (Admin → Content access).
17. **Home page tab**: Featured demos and the two display options (production
    has its own; re-pick if wanted).
18. **Left from before review was removed**: Admin → Content review lists
    uploads that were waiting for review (Publish or leave), and Content access
    still shows open access requests to approve or reject. List them for Liwei.
19. **API tokens** stay per slot: production's existing tokens keep working;
    tokens made on staging do not.
20. **Spot checks**: search and filters; a demo page (Edit on the Details card,
    Share feedback, Related demos, Create DemoBoard for a licensed person); Hub
    activity with a creator picked; Admin → Sign-ins → Admin log shows your sync
    and group changes; a partner test account (if you have one) cannot open
    `/admin` and sees no GXC video.
21. **Tell Elio, Seb and Serge**; Serge sends the announcement.

## If something is wrong

- **Swap back** (same Swap button). Production returns to v2026.3.123 with its
  own share; files only the new code reads (`consensus_licenses.json`,
  `support_reports.json`, ...) are ignored by the old code and are there again
  on the next swap forward.
- A demo archived after the swap sits in `_Archive` in SharePoint. The old code
  was never run against `_Archive`: restore such demos before swapping back.
- Settings are not rolled back by a swap or a redeploy; undo a setting change
  by hand.
- Code-only rollback of a slot: `gh workflow run "Build and deploy Python app to
  Azure Web App - Technical-Marketing-Hub" --ref <sha> --repo SebBergner/Technical-Marketing-Hub`
  (deploys to staging).
