# TDD Portal — Architecture

Revision 5, 2026-08-20. Easy Auth with viewer/curator roles is in place ahead of any write
path. Section 2a records what the SharePoint site actually contains.

---

## 1. What changed, and what it costs us

Graph access flips the single most consequential constraint in the design: **inbound integration goes
from push to pull.** Nearly everything downstream simplifies.

| | Previous (Power Automate push) | Now (Graph pull) |
|---|---|---|
| How data arrives | They call us | **We call them** |
| Recovering lost data | Wait for the next flow run | **Re-sync on demand** |
| Change detection | Hand-rolled snapshot + size guards | **Native `delta` queries** |
| Deletions | Only via full snapshot diff | **Reported natively** |
| Thumbnails / files | Had to be pushed to Blob | **Fetched on demand** |
| Metadata direction | Read-only mirror | **Read *and* write** |
| Library schema setup | Manual clicking in SharePoint | **Provisioned in code** |
| Ingest auth | Shared secret on a public endpoint | **Outbound OAuth, no inbound endpoint** |
| Power Automate | Required | **Not needed** |

Two of those are worth dwelling on.

**The mirror becomes a true cache.** Previously, pushed data was not re-pullable — if the database was
lost, the catalogue was gone until the next scheduled flow. That forced real durability requirements
onto mirrored data. Now the mirror can be rebuilt from Graph at any time, so it is a cache with a known
rebuild path. Only Portal-owned data is genuinely irreplaceable.

**We no longer expose an inbound write endpoint.** The push design needed a publicly reachable
`/api/ingest` guarded by a shared key. That endpoint is now gone entirely. Strictly better.

### What this does *not* change

Be clear-eyed about this, because it is easy to over-read the win:

1. ~~The metadata still does not exist.~~ **SUPERSEDED — see section 2a.** Measured 2026-08-14:
   the Demo Catalog has managed columns at 100% coverage on all 452 assets. The real gap is
   `consensus_uuid`, absent entirely — 98% of the catalogue cannot be shared externally.
2. **The Portal is still an index, not a content store.** Nothing here justifies copying content in.
3. **Mirror and owned data must still never share a row.** Sync still overwrites the mirror wholesale.
4. **Consensus is still the fastest path to real data** — its credentials are already in hand, while
   Graph is pending IT.
5. **Value Roadmap still has no source system.** Still a new pipeline, still sequenced last.

### What it costs us

Write access is not free. It introduces three obligations that did not exist before:

- **Authentication becomes mandatory, not optional.** An unauthenticated app that can write to a
  corporate SharePoint site is indefensible. Easy Auth must ship *before* any write path does.
- **Concurrency has to be handled.** Two writers (the Portal and SharePoint's own UI) means optimistic
  concurrency via ETags, not last-write-wins.
- **Attribution is lost unless we rebuild it.** App-only writes appear in SharePoint as the application,
  not the person. If we want to know who changed a label, we have to record it ourselves.

---

## 2. Upstream consolidation — SharePoint as the single read source

*Sebastian Bergner's proposal, 2026-08-13. Adopted, with two refinements.*

The obvious design fans out at read time: the app calls SharePoint for metadata, Consensus for the
demo UUID, Brightcove for the playback ID. Every page view depends on three services being up.

The better design consolidates **upstream**. Enrichment runs as scheduled background jobs that write
their findings into SharePoint columns. The app then reads exactly one source.

```
   BEFORE — fan-out on the read path        AFTER — consolidation upstream
   ────────────────────────────────         ─────────────────────────────────────
                                             filename parser ─┐
   App ─┬─► SharePoint                       Consensus API ───┼─► SharePoint columns
        ├─► Consensus    ← must be up        Brightcove API ──┘   (+ human correction)
        └─► Brightcove   ← must be up                     │
                                                          ▼
                                              Graph delta sync → Azure SQL → API → UI
```

**Why this is materially better**

1. **Failure isolation.** Consensus down? The Portal is unaffected — it reads a UUID already stored in a
   SharePoint column rather than asking Consensus at render time.
2. **Humans can repair data without a deploy.** A wrong auto-matched UUID is fixed by editing one cell.
3. **It is inspectable.** Open the SharePoint list and you see exactly what the Portal will show.
4. **Smaller credential surface on the read path.**
5. **It costs nothing extra** — the curated library is being built anyway; these are just more columns.

### Refinement 1 — the work moves off the read path, it does not disappear

Something still has to put the Consensus UUID in that column. Either a person pastes it (does not scale,
goes stale) or a background job writes it — which still requires the Consensus client, just on a daily
schedule rather than per request.

And **actions stay live**: when a user clicks "share to Consensus", that call happens in real time. So
the Consensus client survives, but demoted from the *read* path to the much smaller *action* path.

This also resolves a wrinkle in the earlier design. Enrichment writing into SharePoint — rather than
straight into our database — means enriched values arrive through normal sync and land in the mirror
legitimately. No special case, no violation of the mirror/owned split. The data flow becomes one line.

> **Contingency:** if IT grants `read` only, enrichment cannot write to SharePoint. Fall back to holding
> those values in a Portal-owned `asset_enrichment` table, joined at query time — the read path stays
> single-source, but humans lose the ability to correct values in SharePoint.

### Revision 3 — no Azure SQL. File-backed index instead.

*Sebastian Bergner's call, 2026-08-13. Adopted.*

Azure SQL is dropped. The Portal keeps a **file-backed server-side index** and SharePoint stays the
centre of gravity, so there is no database to provision, secure or pay for. At this catalogue's size
(hundreds to low thousands) loading into memory and filtering in Python is faster than a database
round trip, so nothing is lost.

The repository abstraction absorbed this in one new class — `JsonAssetRepository`. Models, routers,
services, matching and every test were untouched. `SqlAssetRepository` is retained and **both run the
same parametrised test suite**, which is what actually proves the abstraction holds.

The mirror/owned split is now *physically visible*, an improvement on SQL where it was a convention:

```
<DATA_DIR>/
  mirror/<source_system>.json   rebuildable cache — sync replaces wholesale
  owned/identity.json           stable slug <-> source id        ← irreplaceable
  owned/curation.json           editor's picks, rails
  owned/roadmap.json            AI-derived index
  owned/stats.json              view / share counters
  owned/share_events.jsonl      distribution log (append-only)
  owned/requests.jsonl          intake submissions               ← irreplaceable
```

#### The one thing this must not be allowed to forget

**App Service local disk is ephemeral.** It does not survive a restart, a redeploy, or scale-out.
Every `git push` wipes it. That is harmless for `mirror/` — re-sync and it is back — but everything
under `owned/` **cannot be reconstructed from SharePoint**:

| Lost | Consequence |
|---|---|
| `owned/requests.jsonl` | Submitted asset requests gone permanently |
| `owned/identity.json` | Every previously shared link stops resolving |
| `owned/roadmap.json` | Re-index cost paid again |
| `owned/stats.json` | View counts reset; "Most Viewed" empties |

`DATA_DIR` is therefore configurable, and the deployment decision is deliberately deferred:

- **now** — local `data/runtime`, fine while the catalogue is seed data;
- **before real users submit anything** — point `DATA_DIR` at an **Azure Files mount**. Pennies a
  month, not a database, and it survives redeploys and is shared across instances.

`GET /api/debug/backend` reports `storage_is_durable` so this cannot be silently forgotten.

Second constraint, documented rather than solved: writes assume **one instance**. `os.replace` makes
each write atomic so a file is never left corrupt, but two processes doing read-modify-write can lose
an update. Fine for a single instance; scale-out needs a real store.

### Decision — authentication is App Service Easy Auth, with two roles

*Implemented 2026-08-20, ahead of any write path, as section 1 requires.*

Entra ID sign-in is handled by the platform; the app receives identity as
`X-MS-CLIENT-PRINCIPAL-*` headers.

**Those headers are only as trustworthy as the gate in front of them.** Anything
that can reach the app without passing through Easy Auth can set them itself.
That is not theoretical: it happens when Easy Auth is left on "allow
unauthenticated", when a container port is exposed directly, or when a proxy in
front forgets to strip inbound `X-MS-*`.

So the headers are honoured **only** when `AUTH_MODE=easyauth` is set
explicitly. The default ignores them, which means a forged header on an
unconfigured machine grants nothing.

The residual risk is the inverse — deploying to App Service and never setting
`AUTH_MODE`, silently making every caller a curator. `security_warnings()`
detects exactly that (App Service always sets `WEBSITE_SITE_NAME`) and it
surfaces in `/api/auth/me`, `/api/debug/backend` and a startup log line. It is
not allowed to be quiet.

| Role | May |
|---|---|
| `viewer` | read the catalogue, share externally |
| `curator` | additionally decide metadata proposals and trigger a Graph sync |

Curator comes from an Entra ID group listed in `AUTH_CURATOR_GROUPS`, or an app
role named `curator`. With neither configured **nobody** can curate — failing
closed, so a half-finished setup cannot accidentally grant write access.

### Refinement 2 — SharePoint is the authority, not the query engine

Do **not** query SharePoint live per request. Graph is a poor fit for what this UI does:

- hundreds of milliseconds per call, and it throttles;
- weak multi-field faceted filtering;
- no useful full-text relevance ranking;
- sorting, counts and "most viewed" all become awkward.

So: **SharePoint is the single source of truth; Azure SQL is the local read index.** That is exactly the
mirror table already specified — it simply carries more columns now, because the enriched values are in
SharePoint before sync ever runs.

### Decision — asset requests go to a SharePoint list

*Liwei Chen, 2026-08-20. Closes an open question carried since the requirements doc.*

The requirements doc left "where should submitted requests be stored — SharePoint list,
Smartsheet, a database?" explicitly undecided. Answer: **a dedicated SharePoint list or form**,
built once Entra ID / Graph write access lands.

This is consistent with SharePoint as the centre of gravity, and it removes a durability risk
rather than adding one:

- `owned/requests.jsonl` is no longer needed. Requests are governed, retained and backed up by
  IT like any other corporate list, instead of living on an ephemeral App Service disk.
- The remaining genuinely irreplaceable Portal-owned data shrinks to `owned/identity.json`
  (stable slugs) and `owned/roadmap.json` (AI index). Both are small, and the roadmap is
  recomputable at a cost.
- `DATA_DIR` should still point at durable storage before production, but losing it would no
  longer destroy anyone's submitted request.

`POST /api/requests` is therefore **deferred** until Graph write exists, rather than built now
against a store we would immediately migrate away from. The `AssetRequest` model and
`asset_request` table stay as the shape the SharePoint list should mirror.

### Move, don't copy

When populating the curated library, **move** items rather than copying them. Copies diverge, double
storage, and create ambiguity about which one is authoritative. Retire the old location instead.

---

## 2a. What the SharePoint site actually contains

Measured 2026-08-14 from Site Contents plus a full 9,166-row item export. This section exists
because two earlier design decisions rested on guesses that turned out to be wrong.

**Host is `ptccloud.sharepoint.com`, not `ptc.sharepoint.com`.** Site: `/sites/EXT-TDD`.

### Correction 1 — the metadata already exists

It was previously recorded that SharePoint had "essentially no structured metadata — files in
folders plus naming conventions", which made human labelling the project's critical path. That is
**wrong**. The Demo Catalog carries managed columns, and coverage on the asset folders is complete:

| Column | Coverage on the 452 asset folders |
|---|---|
| Name, Demo Type, Segment, Language, Product, Owned By | **100%** |
| Product Version | 98% |
| Description | 81–93% |

So no filename parser is needed for product / type / segment / language — they are real columns.
The backfill effort is far smaller than assumed, and it is no longer the critical path.

### Correction 2 — the real gap is the Consensus join key

A live cross-match of all 452 catalogue folders against 636 published Consensus demos:

```
matched            6
portal_only      446      ← 98% cannot be shared externally
consensus_only   632
```

`consensus_uuid` is absent from SharePoint entirely. **That** is the gap worth automating, not
the taxonomy.

### Libraries and lists on the site

| Name | Type | Items | Relevance |
|---|---|---|---|
| **Demo Catalog** | Document library | 9,166 | Primary source — 452 assets |
| **Virtual Machine Catalog** | Document library | 139 | **Second asset source.** The mockup claimed 14 VMs; there are 139 |
| Seismic | Document library | 148 | Relates to PTC Velocity — role unconfirmed |
| Site Assets / Documents / Style Library / Form Templates | Document library | 2,244 / 87 / 0 / 0 | Site plumbing, not content |
| Product Filter | List | 5 | Only 5 rows, but Product has 20+ values — so not the Product lookup. Purpose unconfirmed |
| VM/Demo Issue Tracking | List | 187 | Existing tracker; may overlap with the intake form |
| VM - Related Demos | List | 1 | VM↔demo link table, effectively empty |
| Site Pages / Wiki | Page library | 549 / 16 | The current portal pages |

**There is no Video library.** Videos live as files inside demo folders.

### The structural rule that defines an asset

Demo Catalog = 1,367 folders + 7,799 files. Only **452 folders carry Demo Type**, and **all 452 sit
at depth 0**, directly under Demo Catalog. The other 915 folders are internal structure (Dataset,
Video, Documentation, Models…), nesting up to 6 levels deep.

> **An asset is a top-level folder in Demo Catalog. Everything beneath it is a resource.**

Clean, unambiguous, and it needs no heuristics.

Column values on *files* must be ignored: files show Language 98% and Product 65%, but those are
inherited column defaults, not authored metadata.

### Contents of an asset folder

| | Value |
|---|---|
| Assets containing ≥1 video | **396 / 452 (87%)** |
| Videos per asset | min 1, median 2, **max 94** |
| Files per asset | min 1, median 4, **max 1440** |
| Video files total | 1,319 (`.mp4` 1,279, `.m4v` 40) |

Other extensions: `.docx` 638, `.zip` 522, `.pptx` 485, `.rar` 314, plus ~3,400 files ending
`.1` `.2` `.3` — Creo's versioned CAD format (`part.prt.1`), not user-facing.

**110 videos sit under no asset folder** — they live in top-level folders that carry no Demo Type,
such as `Creo+ 12.0 Technical PM Videos`. Those are invisible to the rule above; needs a decision.

### Consequence for the data model

`Asset` needs a `resources[]` layer, and `playback_url` resolves to a chosen video resource:

```
Asset (= top-level folder)
  └── resources[]   video · guide (.docx/.pptx) · dataset (.zip) · CAD (.creo/.prt.N)
```

With a median of 2 videos and a maximum of 94, **"which video represents this asset" is a real
question**, not an implementation detail. 142 assets have exactly one; the rest need a rule or a
human choice.

### Video filenames carry far weaker signals than the mockup suggested

Across all 1,219 videos inside asset folders:

| Signal | Hits |
|---|---|
| `overview` | 140 |
| `audio` | 52 |
| `facing` | 44 |
| `customer` | 25 |
| `no audio` | 18 |
| `teaser`, `narrat` | **0** |

The mockup's tidy titles (`Tech Walkthrough No Audio — Manufacturing Part 3`) are **not
representative** of real filenames. An earlier plan to derive `content_depth`,
`has_narrated_audio` and `customer_facing` from filenames was based on that curated sample and
would not have worked at this hit rate.

### Data quality issues to fix at ingest

1. **Segment delimiters are inconsistent** — `IoT,PLM` (comma) and `CAD;#SLM` (SharePoint
   multi-value) both appear. 11 rows affected; naive filtering would silently miss them.
2. **Full-width ampersands** — `Windchill Aerospace ＆ Defense` uses U+FF06, not `&`. Three
   product names affected. Breaks exact matching and looks wrong in the UI.
3. **Product is a lookup**, serialised `30;#Creo Parametric`. Must be parsed. 14 rows multi-product.
4. **Description exists three times** — `Description` strips newlines; `Description2` keeps them and
   has the best coverage (93%). Use `Description2`, discard the others.
5. **407 / 452 names carry a `v.N` suffix**, many also repeating the Demo Type (`… LDK v.1`).
   Strip both for display titles.


---

## 3. System shape

```
┌──────────────────────────────────────────────────────────────────────┐
│  PRESENTATION — vanilla JS, no build step                            │
│  home · search · video preview · demo gallery · request intake       │
│  · metadata curation UI  (new)                                       │
└───────────────────────────────┬──────────────────────────────────────┘
                                │  REST /api      Easy Auth (Entra ID)
┌───────────────────────────────▼──────────────────────────────────────┐
│  APPLICATION — FastAPI on Azure App Service                          │
│                                                                      │
│    routers  ──►  services  ──►  repositories  ──►  Azure SQL         │
│                     │                                                │
│                     └──────►  integrations (outbound only)           │
└──────┬───────────────────────────────────────────────────────────────┘
       │
       │  READ PATH — one source
       ├─► Microsoft Graph      site-scoped, read + write   [pending IT]
       │
       │  ENRICHMENT JOBS — scheduled, write into SharePoint
       ├─► Consensus API        UUID match                  [live today]
       ├─► Brightcove CMS       playback ID match           [unconfirmed]
       │
       │  ACTION PATH — live, user-initiated
       ├─► Consensus API        generate DemoBoard link     [live today]
       └─► Seismic / Velocity   add to Digital Sales Room   [API unknown]

  Every arrow points outward. The app initiates every call it makes.
```

The **service layer is not optional**. "Share to Consensus" alone touches three stores: read the asset
from the catalogue, check it has a `consensus_uuid`, call Consensus, record a share event, bump a
counter. That orchestration belongs in neither a router nor a repository.

---

## 4. Data classes

Unchanged in principle, but the durability implications shift now that the mirror is rebuildable.

| Class | Contents | If lost | Backup need |
|---|---|---|---|
| **A — Mirror** | `asset_source` | Re-sync from Graph | None |
| **B — Portal-owned** | identity, curation, roadmap, stats, requests, audit | **Gone forever** | Real backups |
| **C — Delegated** | Consensus links, Velocity rooms | Nothing stored | n/a |

**`asset_identity` is the table that protects you.** It maps a stable slug to
`(source_system, source_item_id)`. Titles change and files move; the slug never does, so every link ever
shared keeps resolving. Lose that table and every shared URL in circulation dies. It is small, it is
irreplaceable, and sync must never touch it.

---

## 5. Database schema

Two groups, one schema, never interleaved. The application reads through a joining view so the split
stays invisible above the repository layer.

```sql
-- ══════════ MIRROR — rebuildable cache, wholesale replaced by sync ══════════
CREATE TABLE asset_source (
  asset_id            NVARCHAR(80)   NOT NULL PRIMARY KEY,
  source_system       NVARCHAR(20)   NOT NULL,          -- 'sharepoint'
  source_item_id      NVARCHAR(100)  NOT NULL,
  etag                NVARCHAR(100)  NULL,              -- for If-Match on write-back
  title               NVARCHAR(400)  NOT NULL,
  file_name           NVARCHAR(400)  NULL,
  folder_path         NVARCHAR(1000) NULL,
  web_url             NVARCHAR(1000) NULL,
  drive_item_id       NVARCHAR(100)  NULL,              -- for downloadUrl / thumbnails
  asset_type          NVARCHAR(20)   NULL,              -- video | ldk | vdk | vm | wiki
  products            NVARCHAR(400)  NULL,              -- JSON array
  funnel_stage        NVARCHAR(30)   NULL,
  content_depth       NVARCHAR(20)   NULL,              -- teaser|overview|explainer|walkthrough
  language            NVARCHAR(10)   NULL,
  has_narrated_audio  BIT            NULL,
  customer_facing     BIT            NULL,
  named_customer      NVARCHAR(200)  NULL,
  industry            NVARCHAR(200)  NULL,
  consensus_uuid      NVARCHAR(60)   NULL,
  brightcove_id       NVARCHAR(60)   NULL,
  duration_seconds    INT            NULL,
  status              NVARCHAR(20)   NULL,              -- draft | published | retired
  uploaded_at         DATETIME2      NULL,
  modified_at         DATETIME2      NULL,
  synced_at           DATETIME2      NOT NULL
);

-- ══════════ PORTAL-OWNED — sync is never allowed to touch these ══════════
CREATE TABLE asset_identity (
  asset_id       NVARCHAR(80)  NOT NULL PRIMARY KEY,    -- stable slug, assigned once
  source_system  NVARCHAR(20)  NOT NULL,
  source_item_id NVARCHAR(100) NOT NULL,
  first_seen_at  DATETIME2     NOT NULL,
  retired_at     DATETIME2     NULL,                    -- soft delete; slug never reused
  CONSTRAINT uq_identity_source UNIQUE (source_system, source_item_id)
);

CREATE TABLE sync_state (                               -- delta cursor lives here
  source_system   NVARCHAR(20) NOT NULL PRIMARY KEY,
  delta_token     NVARCHAR(MAX) NULL,
  last_run_at     DATETIME2 NULL,
  last_success_at DATETIME2 NULL,
  last_error      NVARCHAR(MAX) NULL,
  items_seen      INT NULL
);

CREATE TABLE metadata_proposal (                        -- drives the curation UI
  asset_id       NVARCHAR(80)  NOT NULL,
  field          NVARCHAR(60)  NOT NULL,
  proposed_value NVARCHAR(400) NULL,
  confidence     DECIMAL(3,2)  NULL,
  origin         NVARCHAR(30)  NOT NULL,   -- filename | consensus | brightcove | manual
  state          NVARCHAR(20)  NOT NULL,   -- pending | accepted | rejected | written
  decided_by     NVARCHAR(200) NULL,
  decided_at     DATETIME2     NULL,
  PRIMARY KEY (asset_id, field)
);

CREATE TABLE metadata_edit (                            -- app-only writes hide the human
  id                   BIGINT IDENTITY PRIMARY KEY,
  asset_id             NVARCHAR(80)  NOT NULL,
  field                NVARCHAR(60)  NOT NULL,
  old_value            NVARCHAR(400) NULL,
  new_value            NVARCHAR(400) NULL,
  changed_by           NVARCHAR(200) NOT NULL,          -- real user, from Easy Auth
  written_to_source_at DATETIME2     NULL,
  write_status         NVARCHAR(20)  NOT NULL,          -- pending | ok | conflict | failed
  error                NVARCHAR(MAX) NULL
);

CREATE TABLE asset_curation (
  asset_id       NVARCHAR(80) PRIMARY KEY,
  is_editor_pick BIT NOT NULL DEFAULT 0,
  rail_name      NVARCHAR(80) NULL,
  rail_order     INT NULL,
  notes          NVARCHAR(MAX) NULL
);

CREATE TABLE asset_value_roadmap (
  asset_id     NVARCHAR(80) PRIMARY KEY,
  description  NVARCHAR(MAX) NULL,
  drivers      NVARCHAR(MAX) NULL,        -- JSON
  capabilities NVARCHAR(MAX) NULL,        -- JSON
  indexed_at   DATETIME2 NULL,
  model        NVARCHAR(60) NULL
);

CREATE TABLE asset_stats (
  asset_id NVARCHAR(80) PRIMARY KEY,
  views INT NOT NULL DEFAULT 0, downloads INT NOT NULL DEFAULT 0,
  launches INT NOT NULL DEFAULT 0, shares INT NOT NULL DEFAULT 0
);

CREATE TABLE share_event (
  id BIGINT IDENTITY PRIMARY KEY,
  asset_id NVARCHAR(80) NOT NULL,
  channel  NVARCHAR(20) NOT NULL,         -- consensus | velocity
  target_ref NVARCHAR(200) NULL,
  shared_by  NVARCHAR(200) NULL,
  created_at DATETIME2 NOT NULL
);

CREATE TABLE asset_request (              -- the one genuinely irreplaceable table
  id UNIQUEIDENTIFIER PRIMARY KEY,
  submitted_at DATETIME2 NOT NULL,
  requester    NVARCHAR(200) NOT NULL,
  payload         NVARCHAR(MAX) NOT NULL, -- full intake form, JSON
  recommendations NVARCHAR(MAX) NULL,     -- derived tiers, JSON
  status NVARCHAR(20) NOT NULL DEFAULT 'new'
);
```

> **The rule, restated:** a sync run may `DELETE`/`INSERT` freely in `asset_source` and touch nothing
> else. If a human-authored value ever lands in `asset_source`, the next sync destroys it. Enforce this
> in the repository layer, not by convention — a single `SqlAssetRepository.replace_source_rows()` that
> is the *only* code path allowed to write that table.

---

## 6. Graph integration

### Authentication

Client credentials (app-only) via MSAL. No signed-in user, so no delegated permissions.

```
POST https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token
  client_id={CLIENT_ID}  client_secret={SECRET}
  scope=https://graph.microsoft.com/.default
  grant_type=client_credentials
```

Cache the token in memory and refresh on expiry — MSAL's `ConfidentialClientApplication` does this for
you. **Credentials are read only in `integrations/graph/client.py`.** Nowhere else in the codebase
touches them.

### The permission model, and its one trap

`Sites.Selected` is a two-step grant:

1. Admin consents to the `Sites.Selected` application permission. **This grants access to nothing.**
2. An admin grants the app a role on a specific site:
   `POST /v1.0/sites/{siteId}/permissions` with `roles: ["write"]`.

**Step 2 is very easy for IT to miss**, because step 1 looks like the whole job in the Azure portal UI.
The symptom is a clean token followed by `403` on every site call — which reads like a code bug and can
burn a day. If that happens, do not debug the client: go straight back to IT and ask them to confirm
the site-level grant.

Verify with `GET /v1.0/sites/{siteId}/permissions` as the first thing you do after receiving credentials.

### Endpoints in use

| Purpose | Call |
|---|---|
| Resolve site | `GET /sites/{host}:/sites/{path}` |
| Find library | `GET /sites/{siteId}/lists` |
| Full read | `GET /sites/{siteId}/lists/{listId}/items?$expand=fields` |
| **Incremental** | `GET /sites/{siteId}/lists/{listId}/items/delta` |
| File details | `GET /sites/{siteId}/drive/items/{itemId}` |
| Thumbnail | `GET /sites/{siteId}/drive/items/{itemId}/thumbnails` |
| Stream URL | `driveItem["@microsoft.graph.downloadUrl"]` — short-lived, pre-authenticated |
| **Write back** | `PATCH /sites/{siteId}/lists/{listId}/items/{itemId}/fields` + `If-Match: {etag}` |
| Provision library | `POST /sites/{siteId}/lists` with a `columns` definition |

### Sync algorithm

```
1. Load delta_token from sync_state.
2. No token?  →  full enumeration, then store the token the final page returns.
3. Token?     →  call /items/delta; on HTTP 410 Gone, discard the token and do a full pass.
4. For each changed item:
     - resolve or create asset_identity  → gives a stable asset_id
     - upsert asset_source
     - items marked @removed  → set asset_identity.retired_at, delete the asset_source row
5. Persist the new delta token, last_success_at, items_seen.
6. On failure, record last_error and leave the previous token intact.
```

Three things that will bite otherwise:

- **410 Gone.** Delta tokens expire. Handle it, or sync silently stops working.
- **429 throttling.** Graph throttles. Honour `Retry-After` with exponential backoff. Never busy-retry.
- **`$expand=fields` on `delta`.** Support here is worth verifying in a spike before building on it. If
  it does not behave, fall back to using delta purely for change *detection*, then batch-fetch the
  fields for the changed IDs.

Run it on a timer (hourly is plenty). Graph change notifications can come later if anyone actually
wants near-real-time; the delta loop is self-healing either way.

### Write-back rules

1. **Optimistic concurrency.** Always `If-Match` with the stored ETag. On `412`, re-read, show the user
   what changed, ask again. Never blind-overwrite.
2. **Portal writes only labels.** Metadata columns on that one library. Never file content, never
   deletion, never any other site.
3. **Audit every write** to `metadata_edit` with the real user from Easy Auth, *before* calling Graph —
   because app-only writes are indistinguishable in SharePoint's own history.
4. **Write-through, then re-read.** Update SharePoint first, then refresh the mirror row from the
   response. Never let the mirror drift ahead of the source.
5. **SharePoint stays the system of record.** The Portal is a *better editing surface* for it — not a
   competing store.

---

## 7. The metadata problem, and why write access changes the plan

Graph does not create metadata. But write access replaces a clumsy workflow with a good one.

**Before:** parse filenames → export a spreadsheet → humans edit the spreadsheet → bulk-import to
SharePoint. Slow feedback, an offline artifact to babysit, an import step that can fail halfway.

**Now:**

```
  Graph sync ─────► inventory in asset_source
                          │
     ┌────────────────────┼────────────────────┐
     ▼                    ▼                    ▼
 filename parser   Consensus match    Brightcove match (if API)
     └────────────────────┼────────────────────┘
                          ▼
                 metadata_proposal  (value + confidence + origin)
                          │
                          ▼
        Curation UI in the Portal — accept / correct / reject,
        pre-filled, sorted by lowest confidence first
                          │
                          ▼
     PATCH back to SharePoint  ·  audit to metadata_edit
                          │
                          ▼
              SharePoint is now authoritative
```

Same amount of human judgement, far less friction around it — one screen, keyboard-driven, immediate
feedback, resumable, and progress is measurable (`n of m fields confirmed`).

The proposal sources are already validated against your own real titles:

```
Tech Walkthrough No Audio — Manufacturing Part 3
└─ content type ─┘└ audio:no ┘   └─ topic ──┘└ series ┘

Windchill AI Parts Rationalization Overview — Chinese
└ product ┘                        └ depth ┘  └ lang:zh ┘
```

Product, content type, language, narrated-audio, named customer, series position — most of the schema is
recoverable from strings you already have. Treat parser output as a *proposal with a confidence score*,
never as truth.

**Provisioning is now code too.** With write access, `POST /sites/{siteId}/lists` creates the library and
its Choice columns from a definition in the repo. The taxonomy becomes reviewable, diffable and
repeatable instead of a sequence of clicks nobody wrote down.

---

## 8. Video playback — now unblocked

This was the outstanding blocker on the preview page. Graph resolves it, with a caveat.

`@microsoft.graph.downloadUrl` is a short-lived pre-authenticated URL. The app can hand it to a browser
and the video plays **without the viewer needing SharePoint permissions** — the app's identity did the
authorising.

But SharePoint is not a CDN. No adaptive bitrate, no transcoding, and it throttles under load. Fine for
a handful of internal viewers; poor for a large library with real concurrency.

So implement playback as a **strategy, resolved per asset**:

```python
def resolve_playback(asset):
    if asset.brightcove_id:
        return brightcove_playback_url(asset.brightcove_id)   # preferred: CDN, ABR, player
    if asset.drive_item_id:
        return graph_download_url(asset.drive_item_id)        # works today; short-lived
    return None                                               # honest empty state
```

This unblocks the preview page immediately and still lets Brightcove take over per-asset as IDs get
populated. The earlier recommendation stands — **Brightcove keeps delivery, the Portal takes discovery** —
but it is no longer a prerequisite for shipping.

Cache the Graph URL for less than its lifetime and resolve it at play time, not at list time.

---

## 9. Security

Write access to a corporate SharePoint site raises the bar. Non-negotiables:

- **Easy Auth (Entra ID) ships before any write path.** This reverses the earlier "defer auth" decision.
  Read-only over a mockup made deferral fine; write access does not.
- **Credentials in Key Vault**, surfaced via App Service `@Microsoft.KeyVault(...)` references — or drop
  the secret entirely and use the App Service managed identity, which is better and has nothing to rotate.
- **Never in the repo, never in git history.** Add `.env` to `.gitignore` before the first secret exists.
- **Diarise secret expiry.** Client secrets expire and it always surprises someone. Managed identity
  avoids this problem outright.
- **Never log tokens**, and scrub `Authorization` headers from error reporting.
- **Roles.** Once auth exists, separate curators (may write metadata) from consumers (search and share).
  Entra ID groups, checked in the service layer.

---

## 10. Backend structure

```
app.py                          # factory, static mount, router registration
backend/
  config.py                     # pydantic-settings: SQL conn, GRAPH_*, CONSENSUS_*
  db.py                         # SQLAlchemy engine + session
  models.py                     # Pydantic API models
  tables.py                     # SQLAlchemy tables (mirror / owned, clearly separated)
  deps.py                       # get_current_user (Easy Auth), get_repo, require_role
  repositories/
    base.py                     # AssetRepository ABC + AssetQuery + Page
    sql_repo.py                 # the only writer of asset_source
  integrations/
    graph/
      client.py                 # MSAL token, httpx session, 429 backoff  ← only place creds are read
      sites.py                  # site / list resolution + permission self-check
      sync.py                   # delta loop
      writeback.py              # PATCH fields with If-Match
      provisioning.py           # create library + columns from a repo-held definition
    consensus.py                # protocol + Stub + Http impls
    brightcove.py
    velocity.py
  services/
    catalog.py  curation.py  sharing.py  playback.py  proposals.py
  routers/
    assets.py taxonomy.py share.py requests.py curation.py admin.py health.py
static/  css/ js/ img/
data/seed/                      # seed catalogue, for local dev and Phase 0
scripts/                        # extract_seed.py, one-off maintenance
tests/
```

`AssetQuery` stays an object rather than kwargs, so filters translate down into SQL rather than loading
the catalogue into memory. Client-side filtering in the gallery is fine at current scale; the server
supports identical facets from day one so the switch is a one-function change.

---

## 11. Build sequence

Phases 0 and A **depend on nothing from IT** — start today, in parallel with the access request.

| Phase | Depends on | Deliverable |
|---|---|---|
| **0 — Foundation** | nothing | Split `index.html` into files; extract the 19 base64 JPEGs (2.6 MB → ~180 KB); Pydantic models; Azure SQL + tables; REST API over seed data; hash routing |
| **A — Consensus** | *(credentials in hand)* | Real `ConsensusClient`; replace the faked `EXISTING_ASSET_MATCHES`; two-way reconciliation report |
| **B — Graph read** | IT | `graph/client.py`, permission self-check, site/list resolution, full enumeration, then delta + `sync_state`. **Real inventory visible in the Portal.** |
| **C — Auth** | B | Easy Auth, `get_current_user`, curator vs consumer roles. **Gate: must land before D.** |
| **D — Provision** | B, C | Create the curated library and its Choice columns via Graph, from a definition in the repo |
| **E — Curation** | D | Filename parser + Consensus matcher → `metadata_proposal`; curation UI; write-back with `If-Match`; `metadata_edit` audit |
| **F — Real catalogue** | E | Home, gallery and preview driven by real data; playback strategy; sidebar counts from live facets |
| **G — Extras** | F | Value Roadmap pipeline; request triage; analytics; Velocity integration |

**Riskiest step is F**, not B — it replaces the largest block of hand-written markup and is where visual
regressions hide. Screenshot the mockup before Phase 0 and diff against it after 0, E and F. The contract
for this work is *"it looks identical, but the data is real."*

**Phase E is the long pole in wall-clock time**, because it is gated on human review, not on code.

---

## 12. Open items

| Item | Owner | Blocks |
|---|---|---|
| Graph app registration (`Sites.Selected` + site-level `write`) | IT | B onward |
| Confirm exact SharePoint site URL / site ID | Seb | B |
| ~~Which Azure subscription owns the app~~ | **resolved** | `AZURE-PTC-CXC` / `b10a7da9-9267-43c9-ab54-7245298b5f83`, App Service `Technical-Marketing-Hub` (Linux, Python 3.13, East US), RG `Technical-Marketing-Hub_RG` |
| Brightcove CMS API access | you | a 4th proposal source; better playback |
| Seismic API for Digital Sales Rooms | open | Velocity automation stays manual until answered |
| Correct expansion of "VDK" — the sidebar currently says *Video Demo Kits* | you | taxonomy, external docs |
| The mockup has a fifth type, **Wiki**, absent from the requirements doc | you | `AssetType` enum |
| Value Roadmap: authoritative guidance, or exploratory aid? | you | accuracy bar for G |

Two carried-over engineering items, unchanged: the deploy workflow uses a `publish-profile` secret where
the stated intent was OIDC federated login; and `gunicorn` is in `requirements.txt` with no visible
startup command — confirm App Service runs
`gunicorn -w 4 -k uvicorn.workers.UvicornWorker app:app`.
