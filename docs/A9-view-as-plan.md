# A9 "View the Hub as this group": development plan (2026-11-16)

Plan only, no code. Written from `docs/HANDOVER-A9-view-as-2026-11-16.md`, BACKLOG A9 and a read
of the code on branch `liwei-backend-dev` (ec16239) on 2026-11-16. Line numbers are from that read.
"Checked" means I read the code; "to confirm" means the sweep in step 1 must check it.

## 1. The mechanism in one paragraph

A preview is one key in the existing signed session cookie (`request.session["view_as"]`), set by
`POST /api/admin/view-as` and removed by `POST /api/admin/view-as/exit`. On every request,
`backend.auth.principal_from_request()` (the single function every identity check already goes
through, see section 2) builds the real user as today and, when the session holds a valid preview,
returns an **effective user** instead: a `CurrentUser` with no personal identity (no email, username,
object id or curator roles), `is_partner` set explicitly from the group, and permissions = the
group's permissions intersected with the real user's. One middleware makes the whole preview
read-only. Usage, activity and My Hub writes are skipped where they happen. The front end learns
about the preview from `/api/auth/me` and shows the banner.

Why this shape:
- **Session, not a header or query string.** SessionMiddleware signs the cookie with `SECRET_KEY`
  (`app.py:160`), so the browser cannot forge or edit it. It survives page loads. Sign-out
  (`oidc.logout`, `request.session.clear()`, `oidc.py:346`) and a new sign-in
  (`auth_callback` clears the session, `oidc.py:311`) end it for free.
- **Swap in `principal_from_request`, not in `get_current_user`.** `require_perm` (admin_auth.py:161),
  the sign-in gate (oidc.py:371/381/420), the Admin log (admin_log.py:316), `/api/admin/session`
  (admin.py:64) and the reports reviewer (reports.py:119) call `principal_from_request` directly, not
  the FastAPI dependency. Swapping one level lower covers all of them at once.
- **No personal identity on the effective user.** Every personal lookup in the code is keyed by
  email / username / object id (checked: `my_hub.user_key`, `disclaimer.key_of`, `welcome.key_of`,
  `gxc_shares.may_be_granted`/`may_share`, `me.py` requests, `reports.py:134/197` "mine",
  `uploads.py:89` "mine", `consensus_licenses.is_licensed`, `activity.note_request`). With those
  blank they find nothing, so no personal state leaks in and none is written, without touching
  each route. The few places where "blank" would break the page are handled explicitly (section 4).

## 2. The choke point and everything that reads identity

`principal_from_request(request)` in `backend/auth.py:324` becomes:
1. `real = _real_principal(request)` (today's body, unchanged).
2. If `real` came from an API token, or there is no `view_as` in the session: return `real`.
3. Validate the preview: `view_as.oid == session_user(request)["oid"]` (the person who started it),
   the group still exists, the real user still has Manage users & groups. If any fails, drop
   `view_as` from the session and return `real` (section 7).
4. Return `effective_user(real, group)`, cached in `request.state` for the rest of the request
   (it is called 3-6 times per request today; `admin_log._who` builds a new `Request(scope)`, which
   shares `scope["state"]`, so the cache holds there too).

Every other way identity is read, and what happens to it:

| Where | Reads | Handling |
|---|---|---|
| `get_current_user`, all routers using it (assets, me, uploads, requests, support, disclaimer, taxonomy, vms, auth/me) | `principal_from_request` | Covered by the swap. |
| `admin_auth.require_perm` / `_actor` | `principal_from_request` + `has_admin_session` | Covered; **plus** ignore the shared Admin password cookie during a preview, otherwise `_actor` (admin_auth.py:188) would let `admin-session` raise permissions. |
| `admin_log._who` (admin_log.py:309) | same + `has_admin_session` | Same fix; actor written as the real person (below). |
| `admin.session_state` (admin.py:53) | same + `has_admin_session` | Same fix: during a preview it reports only the effective user, never `via: password`. |
| `oidc.require_sign_in` (oidc.py:353) | `session_user` (is there a session) + `principal_from_request` | `session_user` stays real (a session exists); the permission check uses the effective user. `activity.note_request` is skipped in a preview. |
| `oidc.login` (oidc.py:221) | `session_user` | Only "already signed in?"; unaffected. |
| `deps.get_repo` (deps.py:39) | `user.can(VIEW_GXC)`, `gxc_shares.granted_ids(user.email)` | Effective user: GXC by group permission; `may_be_granted` is False (no email), so no personal grants. |
| API tokens (`_principal_from_token`) | Bearer header | Returned before the session is looked at: never previewed. |
| Background jobs (auto_sync, migration runner, insights, `build_repo(gxc=True)`) | no request | Unaffected. |

**Actor in logs.** `_actor`, `_who` and `require_perm`'s `hub_actor` build `user:<email>`; the
effective user has no email. A helper `actor_of(user)` returns `user:<real email> as <group name>`
during a preview and today's string otherwise; the three places use it.

Archived, hidden, PTC Only and partner filtering: `_locked_for` (assets.py:188) reads
`user.can(Perm.INTERNAL)`, `can(PREVIEW/DOWNLOAD)` (checked). Archived/hidden visibility and the
listing filters: **to confirm** in step 1 that each reads `user.can(...)`/`is_partner` from the
`CurrentUser` and nothing from the session directly (a grep of `request.session`/`session_user`
on 2026-11-16 found only auth.py and oidc.py, so this is expected to hold).

## 3. Writes refused centrally

New middleware `view_as.read_only`, added in `app.py` right after `admin_log.middleware` (so it
runs inside SessionMiddleware and the sign-in gate, outside the Admin log). When the session holds a
valid preview:
- `GET`, `HEAD`, `OPTIONS`: pass, except the GETs that write (below).
- `POST /api/admin/view-as/exit`: pass (Exit must always work).
- **Telemetry, dropped silently** (answer 204, route not called): `POST /api/assets/search-event`,
  `POST /api/assets/{id}/view`, `POST /api/assets/{id}/consensus-preview`, `POST /api/welcome/seen`,
  `POST /api/welcome/shown`. These are fire-and-forget from the page; a 403 would only add console
  errors. A16 (feature usage, BACKLOG) is built **before** A9 (Liwei, 2026-11-16), so its
  feature-event endpoint is on this list from the start; check its exact path in the code then.
- **Everything else**: 403 JSON `{"detail": "Read-only: you are viewing the Hub as <group>. Exit
  the preview to make changes.", "view_as": true}` and header `X-Hub-View-As: read-only`.
  This covers upload, archive, metadata, access, still-current, thumbnails, related, requests,
  New Asset Inquiry, support reports, favourites, playlists, notes, disclaimer accept, sync,
  migration, all `/api/admin/*` changes and the admin password login.

GETs with side effects (checked 2026-11-16):
- `GET /files/{id}/download|play|preview` (assets.py:597/629/651) write a usage event through
  `_record` (assets.py:320). `_record` returns early in a preview. The file still opens: a preview
  must show whether the group can open it.
- `GET /api/consensus/oauth/start` and `/callback` store Consensus tokens: refused by the
  middleware during a preview (listed by path).
- `gxc_shares.tokens_for` / `token_for` create a person's code on a GET (`_new_code_for`,
  gxc_shares.py:173); not reached, because `may_share` is False without an email.
- Opening a GXC personal link writes a grant: not reached, `may_be_granted` is False. **To confirm**
  in step 1 by reading the link-opening route.
- `record_sign_in` (access.py and activity.py): only in `auth_callback`, which clears the session
  first, so it can never run inside a preview.

Not affected: API tokens (no session preview), background jobs.

Refused attempts are not written to the Admin log (the guard sits outside it). Only start and
exit are, as decided.

## 4. The effective user

`access.effective_permissions(real, group)` (pure, unit-tested):

```
base    = set(group["permissions"])                  # Administrators: ALL (as _normalise keeps it)
partner = group["auto"] == "guests"
if partner: base -= PARTNER_NEVER                     # as permissions_of() does for a real partner
return frozenset(base & real.permissions)             # real.permissions already has its own caps
```

- `CurrentUser` gains `view_as: dict | None` (`{"group_id", "group_name"}`), `real: CurrentUser |
  None` and `partner_as: bool | None`. `is_partner` returns `partner_as` when it is set (needed
  because the effective user has no email, and the real email is PTC). `permissions` returns
  `effective_permissions(...)` when `view_as` is set. `as_dict()` adds `view_as` (group name and
  the real person's name, for the banner).
- **Partners** (`auto = "guests"`): `partner_as = True`; `PARTNER_NEVER` applied, so the result can
  only be inside `PARTNER_ALLOWED` (view, preview, download, request).
- **PTC employees** (`auto = "members"`): `partner_as = False`.
- **Administrators** as a non-admin with Manage users: only the overlap (e.g. no Maintain content if
  the real user lacks it). A bootstrap admin (`HUB_ADMIN_EMAILS`) has ALL as the real user, so the
  overlap is the group.
- **A group the real user is not in**: allowed; the intersection is still with the real user's own
  permissions.
- **Hand-made groups**: `partner_as = False`, permissions together with PTC employees (section 12, 1).
- Curator settings (`AUTH_CURATOR_*`) do not reach the effective user: its roles are empty.
- Dev principal (local `AUTH_MODE=disabled`): real permissions are `ALL - _ADMIN_ONLY`
  (access.py:473), so a local preview never shows the Admin page's own two. It may start a
  preview locally (section 12, 2), even though it lacks Manage users & groups.

Places where blank identity needs explicit handling (checked):
- `/api/me`, `/api/me/favorites`, `/api/me/playlists`: `me._key` raises 401 when `user_key` is
  None (me.py:38), which would look like a sign-out. `my_hub.user_key` returns a fixed
  `preview:<group_id>` key for the effective user, and `my_hub`/`playlists` read it as empty
  without touching disk. My Hub as Partners then shows its partner layout with empty lists.
- `/api/auth/me`: `consensus_licensed` is False in a preview (a licence is personal).
- Disclaimer and welcome: `key_of` returns None, so `required` is False; neither pops up. Correct.
- New Asset Inquiry prefill (`permissions.js`) uses `user.name/email`: blank in a preview; the
  submit is refused anyway.

## 5. Front end

- **Admin -> Users & groups** (`static/js/admin/users.js`, `renderGroups` at :344 and the group
  detail): a "View the Hub as this group" button on every group's detail, shown when the page's
  permissions include `manage_users`. It posts `{group_id}` and opens `/`. One help line under it:
  "Read-only. Shows what this group's permissions allow, with none of your own favourites, playlists
  or GXC links. It cannot test GXC personal links, SharePoint's own permissions or a real partner
  sign-in."
- **Banner** (new `static/js/view-as.js`, loaded by `index.html`, `admin.html`,
  `content-health.html`, `migration.html`): asks `/api/auth/me`; when `user.view_as` is set,
  inserts a fixed bar "Viewing as <group> - Exit" above everything. Exit posts to
  `/api/admin/view-as/exit`, then goes to `/admin` (Users & groups tab).
- **One place for the refusal message**: the same script wraps `window.fetch`; a 403 with
  `X-Hub-View-As: read-only` shows a short toast with the server's text. Buttons stay visible, so
  the preview shows what the group would be offered, and clicking one says why nothing happens.
- **Hiding by permission**: already driven by `/api/auth/me` permissions and `is_partner`
  (`static/js/hub/permissions.js`), so it follows the effective user without change. Other pages
  that read `/api/auth/me` (`hub/nav.js`, `hub/vm.js`, `content-health/main.js`) likewise.
- **Admin page during a preview**: `/api/admin/session` answers for the effective user. Without
  View Admin it shows the password form; the form's POST is refused, and the banner's Exit is above
  it. With View Admin it shows only the tabs the effective permissions allow.
- **"No access to the Hub" page** (oidc.py:387, a group without View the Hub): during a preview its
  action is "Exit preview" (a small form posting to the exit endpoint) instead of "Sign out".

## 6. File-by-file change list

| File | Change |
|---|---|
| `backend/view_as.py` (new) | Session key, `start(request, real, group)`, `stop(request)`, `current(request, real)` validation, `effective_user`, `actor_of`, the read-only middleware and its path lists. |
| `backend/auth.py` | `CurrentUser` fields and `is_partner`/`permissions`/`as_dict`; `principal_from_request` split into `_real_principal` + swap + per-request cache. |
| `backend/access.py` | `effective_permissions(real, group)`; a `group_by_id` lookup. |
| `backend/admin_auth.py` | `_actor` ignores the password cookie in a preview; actor via `actor_of`. |
| `backend/admin_log.py` | `_who` same; two `ACTIONS` entries ("Started viewing the Hub as a group", "Stopped viewing as a group"); category "Users & groups" (already matches `/api/admin/access`; add `view-as` to that regex). |
| `backend/routers/admin.py` | `POST /api/admin/view-as` (Manage users & groups, real person only, sets `hub_target` = group name), `POST /api/admin/view-as/exit` (no permission, needs an active preview); `session_state` as in section 2. |
| `backend/oidc.py` | Skip `activity.note_request` in a preview; Exit on the no-access page. |
| `backend/routers/assets.py` | `_record` returns early in a preview. |
| `backend/services/my_hub.py`, `backend/services/playlists.py` | `preview:` key reads as empty, never written. |
| `backend/routers/auth.py` | `consensus_licensed` False in a preview. |
| `app.py` | Add the read-only middleware after `admin_log.middleware`. |
| `static/js/view-as.js` (new), the four HTML pages, CSS | Banner, Exit, fetch toast. |
| `static/js/admin/users.js` | The button and help line. |
| `tests/test_view_as.py` (new) | Section 8. |

## 7. Edge cases

- **Group with zero permissions**: no View the Hub, so the Hub answers the no-access page (with
  Exit). `/admin` stays reachable (`_NOT_HUB_PREFIXES`), banner and Exit work there.
- **Group deleted mid-preview**: the next request finds no group, drops `view_as`, writes one Admin
  log line "Preview ended: group deleted" (actor = real person) and continues as the real user.
  The banner disappears on the next page load.
- **Group's permissions changed mid-preview**: picked up on the next request (`load_state` is
  mtime-cached), which is what a real member would see.
- **Real user loses Manage users & groups mid-preview**: same as deleted: preview ends.
- **Two browser tabs**: one cookie, so both tabs are in the preview; the other tab shows the banner
  on its next load, and its writes are refused with the message. Exit in one ends both. Documented
  in the help line, not prevented.
- **Session expiry / sign-out**: idle and absolute expiry drop the session user; `view_as` without
  a matching `oid` is ignored, and the next sign-in clears the session. Sign-out clears it.
- **Shared Admin password session**: cannot start a preview (no person), and is ignored while one
  is active.
- **Starting a preview while in one**: refused by the read-only guard (only Exit passes).
- **Hand-made group of partners** (e.g. a partner-only group): previewed as PTC staff
  (`partner_as = False`), so it can show more than a real partner member gets. Stated in the help
  text; Partners is the group to preview for the partner view.
- **GXC cards in a preview of a GXC group**: listed, but without personal share tokens
  (`may_share` False). Sharing is a write anyway.

## 8. Test plan

Unit (`tests/test_view_as.py`):
- `effective_permissions`: Administrators as a non-admin = overlap; group the user is not in;
  Partners capped to `PARTNER_ALLOWED` even if the group was given more; PTC employees; zero
  permissions; dev principal; bootstrap admin.
- `is_partner` override both ways; `as_dict` carries `view_as`.
- Choke point: in a preview, `get_current_user`, `require_perm`, `get_repo` (GXC on/off) and
  `/api/auth/me` all agree; an API token request in the same test client is not previewed.
- Session: start needs Manage users & groups (403 otherwise); admin password session cannot start;
  forged `view_as` with another `oid` is ignored; logout ends it; deleted group ends it.
- Audit: start and exit each add one Admin log entry with actor `user:<real> as <group>` and the
  group as target; a refused write adds none.
- Read-only: every non-GET route in `app.routes` (enumerated, not hand-listed) returns 403 with the
  header during a preview, except exit and the telemetry list (204); the OAuth GETs refused.
- No usage written: snapshot every file under `DATA_DIR` (path + hash) before a scripted preview
  session (search, open demo, play, preview, download, My Hub, welcome) and compare after: only
  the session cookie changes; in particular no usage event, `activity.json`, `my_hub`, welcome,
  disclaimer or `gxc_shares` change.

Sessions in tests: sign in through the fake MSAL in `tests/test_oidc.py` (`FakeMsal`, `sign_in`),
extended so each sign-in can name its email and `external` flag (distinct oids per person).
`easyauth_headers` gives everyone oid-123 and is not used for these. `conftest.py`'s SharePoint
write guard stays as it is.

Route sweep (like the 10/30 security check): for every GET route with sample ids, call it
(a) signed in as a real partner and (b) as a PTC admin previewing Partners; then (a) a real plain PTC
employee (no GXC) and (b) an admin previewing PTC employees. Compare status codes and bodies with
identity fields removed. Any difference is a bug or must be explained in the test.

## 9. Liwei's manual checklist (local first, then staging after "Push to staging")

1. Admin -> Users & groups: every group, including a newly created one, has the button.
2. View as PTC employees: no GXC anywhere (Home, search, filters and their counts, lists, demo
   page, My Hub, Hub activity); PTC Only demos open.
3. View as Partners: only view / preview / download; PTC Only files locked; no GXC; no New Asset
   Inquiry; "Share Internally" renamed as for partners; My Hub shows the partner layout, empty.
4. View as Team Member: Maintain controls visible; clicking Save / Archive / Upload shows the
   read-only message and nothing changes.
5. Favourites star, playlist, feedback, request: refused with the message.
6. Admin page while viewing a group without View Admin: no Admin content; Exit works.
7. Exit: back to the real account; Admin log shows the start and the end with the group.
8. Hub activity / usage the next day: nothing from the preview session, under any name.
9. Sign out while previewing, sign in again: no banner.

## 10. Order of work (each step runs and is verified locally)

| Step | What | Verified by | Size |
|---|---|---|---|
| 1 | Effective user, intersection, partner override, the swap in `principal_from_request`, actor helper, password-cookie fix. Confirm the "to confirm" items in sections 2 and 3. **Riskiest; first.** | Unit tests; full existing suite green (nothing changes without a preview). | 0.5 d |
| 2 | Start/exit endpoints, session validation, Admin log entries. | Tests: start, exit, forged oid, deleted group, logout. | 0.25 d |
| 3 | Read-only middleware, telemetry drop, `_record`, `note_request`, My Hub key. | Route enumeration test; `DATA_DIR` snapshot test. | 0.25 d |
| 4 | Route sweep vs real partner / real employee. | Sweep test. | 0.25-0.5 d |
| 5 | Front end: button, help line, banner, Exit, toast, no-access page. | Local run in the browser, checklist 1-7. | 0.5 d |

About 1.75-2 days, in line with BACKLOG's 1.5-2.

## 11. Risks

- **A route that reads identity some other way later.** Mitigated by putting the swap below every
  current caller and by the route-enumeration tests, which pick up new routes automatically.
- **The password cookie raising a preview**: easy to miss; covered by a dedicated test.
- **Blank identity causing a 401 or 500 somewhere** (as `me._key` would): the route sweep calls
  every GET in a preview and fails on 401/500.
- **Cache of the effective user across requests**: cached only in `request.state`, never in a
  module-level cache, so one person's preview cannot reach another request.
- **Partner simulation is not a real partner**: SharePoint and the guest sign-in are not tested;
  said in the help text and in section 3 of the handover.

## 12. Decided (Liwei, 2026-11-16: all three as recommended)

1. **A hand-made group (e.g. Team Member) is previewed together with PTC employees**, because a
   real Team Member is always also in PTC employees. The group's permissions are the union of the
   two, then intersected with the real user's as in section 4. The banner says "Viewing as Team
   Member (with PTC employees)". Partners and PTC employees are previewed on their own.
   Consequence for section 4: for a hand-made group, `base = group perms | PTC employees perms`.
2. **Local development**: the local dev principal (`AUTH_MODE=disabled`) may start a preview, so it
   can be tried locally. It never runs in production (`security_warnings`). The shared Admin
   password session still cannot.
3. **Write buttons stay visible** in a preview; clicking one answers with the read-only message.
