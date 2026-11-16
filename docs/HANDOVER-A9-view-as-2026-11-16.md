# A9 "View as a group": handover for the development plan (2026-11-16)

For the Claude session that will write the **development plan** for A9. Plan only: do not
write code. Liwei comes back to the implementing session afterwards with your plan.
Read this page, then `docs/BACKLOG.md` section **A9** (search "A9. View as"), then the code
listed under "Where to look".

Working rules (same as every session on this project; details in `docs/HANDOVER-DEVELOPMENT.md`):
- Reply to Liwei in **Chinese**; only code, commits and files are English.
- Ask the open questions before coding. Push only when Liwei says "Push to staging".
- SharePoint and staging are read-only unless Liwei says otherwise in that session.
- Never invent numbers or behaviour: read the code and say what you checked.

## 1. Why now

Liwei has one account. He cannot see what a non-GXC person, a partner, a Team Member or a
plain "PTC employee" sees. Questions of the same kind keep coming back (GXC visibility,
PTC Only, partner limits, My Hub). The 10/28 order put A9 last because it was meant to check
**My Hub as a partner sees it**; My Hub is live since 11/13, so that reason is met.
Liwei decided on 2026-11-16 to build A9 next, before the other low-priority items.

## 2. What is already decided

From BACKLOG A9 (10/21, 10/28) and Liwei's yes on 2026-11-16:

- **Entry**: Admin -> Users & groups, a button "View the Hub as this group" on **every** group
  (including groups created later). Only this entry; no other.
- **Unit = a group, not a person.** Hub permissions are computed per group, so previewing a group
  is enough and exposes no individual's data.
- **No personal state is carried into the preview**: no personal GXC link grants, no favourites or
  playlists of the real person. The preview shows the group's own permissions only.
- **Effective permissions = the group's permissions intersected with the real user's.**
  A preview can lower, never raise.
- **Read-only for the whole preview**: every write is refused (upload, archive, edit metadata,
  send a request, feedback, favourites, playlists, notes, sync, admin changes).
- **Not counted in usage**: not as a partner, not as the real person (views, searches, downloads,
  recently viewed, welcome pop-up, sign-in records).
- **Who may use it**: Manage users & groups.
- **Audit**: starting and ending a preview are written to the Admin log.
- **Banner** on every page while previewing: "Viewing as <group> - Exit".
- No test accounts from IT (10/26 decision).

## 3. What View as cannot test (say so in the plan and in the UI help text)

- **GXC personal links (B10)**: grants are written when a person first opens a link, and a preview
  is read-only. The A -> B -> C chain, revoke cascade and "GXC group only" 404 with a link still need
  a real non-GXC PTC account (BACKLOG B10 "待测"). View as can only show the **listing** side:
  that a non-GXC group does not see GXC in lists, counts, filters, home, search.
- SharePoint's own permissions (a partner pasting a SharePoint link).
- Real partner sign-in (Entra guest, `external` claim). A "Partners" preview is simulated.

## 4. Where to look (verified 2026-11-16; re-check line numbers)

- `backend/access.py`: `groups_of(user)` (membership; groups with `auto` = "members" or "guests"
  are decided by `user.is_partner`), `permissions_of(user)` (union of group permissions, partner
  capped by `PARTNER_NEVER`, dev principal gets `ALL - _ADMIN_ONLY`), `Perm` enum, `_audit`,
  `audit_log`.
- `backend/auth.py`: `CurrentUser` dataclass (`is_partner`, `can(...)`, `can_curate`,
  `token_permissions`), `get_current_user`. This is the natural single place to make the
  "effective user" differ from the real one; find where `can()` calls `permissions_of`.
- `backend/deps.py`: `get_repo(user)`: the one place that hides GXC (via `Perm.VIEW_GXC`) and
  personal-link grants. Archived, hidden, PTC Only and partner filtering also read through the
  repository; confirm each one is driven by the effective user, not by something read directly
  from the session.
- Usage recording (`services/usage.py`, search and view events), `welcome.py`, recently viewed /
  `owned/me/*`, `record_sign_in`: all must be silent during a preview.
- Frontend: Admin Users & groups (`static/js/admin/`), the Hub shell and top bar
  (`static/js/hub/`), how the Hub learns its permissions (`/api/auth/me` or similar) so the UI
  hides buttons.
- Tests: `tests/` uses `easyauth_headers`, which gives every user oid-123; use a distinct
  `X-MS-CLIENT-PRINCIPAL-ID` when testing per-person data. `tests/conftest.py` guards against real
  SharePoint writes; keep it that way.

## 5. Questions the plan must answer

1. **How is "the preview" carried per request?** A signed server-side session value (not a query
   string or a header the browser can set freely), set and cleared by two admin endpoints. It must
   survive page loads and must end at sign-out.
2. **Where is the single choke point** that swaps real user -> effective user so every route,
   `get_repo`, `can()` and the front end's permission list agree? List every route family that reads
   identity some other way (direct session, `object_id`, `email`) and how each is handled.
3. **How are writes refused centrally** (one middleware or dependency on non-GET, plus the few GETs
   with side effects such as view/usage recording and `record_sign_in`) rather than per route?
   Include API tokens and background jobs: not affected.
4. **Intersection details**: previewing "Administrators" as a non-admin gives only the overlap;
   previewing a group the real user is not in; partners group (`auto = guests`) must apply
   `PARTNER_NEVER` and the partner white-list as the real partner would, even though the real user
   is PTC staff (`is_partner` is decided from the account, so the effective user needs an explicit
   override). Same for the "members" group.
5. **What the front end does**: banner, Exit, hiding buttons by effective permissions, Admin
   entry points while previewing (the Admin page itself: allowed only if the effective permissions
   allow it, and the Exit control must always work).
6. **Test plan**: unit tests for the intersection, partner override, write refusal, no usage
   written, audit entries; a route sweep similar to the 10/30 security check (call routes as the
   preview and compare with the same group's real behaviour); a manual checklist for Liwei on
   staging (non-GXC group sees no GXC anywhere; Partners group sees only the white-list; My Hub as
   Partners; write attempts are refused with a clear message).
7. **Edge cases**: previewing a group that has zero permissions; deleting the previewed group
   mid-preview; two browser tabs; session expiry; `HUB_ADMIN_EMAILS` bootstrap admins.
8. **Size and order of work**: BACKLOG estimates 1.5-2 days. Break it into steps that can each be
   run locally and verified, with the riskiest piece (the choke point) first.

## 6. Out of scope

- Previewing a single person; test accounts; simulating SharePoint permissions; any change to
  what the groups may do; GXC personal-link chain testing (see section 3).

## 7. Deliverable of the planning session

A plan document (suggest `docs/A9-view-as-plan.md`, local until Liwei says commit) with:
the chosen mechanism and why, the file-by-file change list, the step order, the test plan, the
Liwei manual checklist, risks, and any question you still need Liwei to answer. Short enough to
read in one sitting. Then Liwei returns to the implementing session.

## 8. State at handover

- Branch `liwei-backend-dev`, in sync with origin, nothing of ours uncommitted except the untracked
  local docs and this file. Production v2026.3.211 (11/13), staging the same build.
- B10 is built (steps 1 and 2 and "GXC group only"); BACKLOG title updated 2026-11-16 (uncommitted
  edit). Still open: a real non-GXC account test, and marking the 3 Lamborghini videos "GXC group
  only" on production (marks are per slot).
- Other pending items are listed in the Hub status memory
  (`C--Work-TDD-Hub-technical-marketing-hub/memory/project_status_2026_11_08.md`) and BACKLOG.
