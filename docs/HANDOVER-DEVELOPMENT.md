# Development Handover — TDD Portal / Technical Marketing Hub

**Written 2026-09-03 for a successor developer or AI assistant with no prior
context on this project.** Everything here was verified against the working
tree and the live data on that date; where a number appears, it was measured,
not estimated. Where something is unverified, it says so.

> 中文导读：本文档是**开发**交接。第 1 节是必读的“别踩这些坑”；第 2 节是数据流；
> 第 4 节是每个文件的作用；第 9 节是待办清单（按可以立刻动手的顺序排列）。
> 部署相关的一切在 `docs/HANDOVER-DEPLOYMENT.md`。

Companion documents, all current:

| Document | What it holds |
|---|---|
| `docs/HANDOVER-DEPLOYMENT.md` | git state, Azure state, what still has to be created |
| `docs/ARCHITECTURE.md` (922 lines) | the reasoning behind each decision, in the order it was made, with the measurements |
| `README.md` | how to run it, how to wire each integration |
| `docs/demo-request-list.md` | the SharePoint list contract for the intake form |

`ARCHITECTURE.md` is the long-form record and is **not** superseded by this
file. Read this one to start working; read that one before changing a
decision, because most of them were made against a measurement that is written
down there.

---

## 0. What the product is, in one paragraph

PTC's Technical Demo Development team publishes demo content across four
disconnected systems — SharePoint (the demo kits), Consensus (buyer-facing
recorded demos), Brightcove (video hosting) and Seismic. There is no single
place to search it. The Hub is a **federated catalogue**: it indexes those
systems and dispatches to them, and it stores no content of its own.
SharePoint stays the system of record. Today the catalogue serves **807
assets** — 369 from SharePoint, 438 from Consensus.

Two people outside the codebase shape it:

- **Sebastian Bergner (Seb)** — owner. Set the "no Azure SQL" and "Consensus
  is a first-class entry" decisions. Owns the product family list and the
  Value Roadmap concept. GitHub repo is under his account.
- **Elio** — owns the front-end design (`index.html`, branch
  `Elio-UI-Development`) and owns Consensus content. His mock-up is the visual
  source of truth; our integration is layered on top of it, deliberately
  non-invasively (see §5).

---

## 1. The rules that must not be broken

These are not style preferences. Each one is here because breaking it already
cost real data or real time on this project.

### 1.1 The mirror / owned split

```
DATA_DIR/
  mirror/          rebuildable cache. Sync REPLACES these wholesale.
    sharepoint.json      455 rows
    consensus.json       491 rows
    seed.json            empty (only used with no credentials)
  owned/           Portal-authored. Sync must NEVER touch these.
    identity.json        241 KB — stable asset id <-> source item. IRREPLACEABLE.
    curation.json        editors' picks and rails
    stats.json           view / share / download counters
    share_events.jsonl   audit log of DemoBoards sent
    sync_state.json      delta token + fingerprints
    segments.json        editorial copy for landing pages (DOES NOT EXIST YET)
    requests.jsonl       local copy of intake submissions
```

Put a human-authored value in `mirror/` and the next sync destroys it
**silently, weeks later**. `replace_source_rows()` in
`backend/repositories/json_repo.py` is the **only** sanctioned mirror writer,
and the `AssetRepository` ABC in `backend/repositories/base.py` is structured
so that a sync run physically cannot reach the owned-data methods.

`identity.json` has no second copy anywhere. It pins a stable slug to a source
item so a link shared in March still resolves in December. Losing it breaks
every link ever shared and every curation reference.

Two bugs already paid for here, both 2026-08-26:

- Mirror rows are **partitioned by source system**. Two sources describing the
  same asset produce duplicate ids — the seed plus the first Graph sync gave
  907 rows for 455 assets.
- `identity.source_system` means *who provides this now*, not who created the
  row. Getting that wrong retired 288 assets that had merely moved between
  sources.

### 1.2 Never invent data to fill a gap

The project's house rule, and it is enforced in code in several places:

- `/api/segments` returns `null` for a missing description rather than a
  plausible sentence, and the UI renders "No description written yet".
- `view_count` stays `None` for SharePoint assets rather than being faked —
  measured 2026-08-31: **0 of 455** SharePoint assets have any view count.
- `show_placeholder_counts` exists as a config flag so the mock-up's
  aspirational sidebar numbers can be shown for a stakeholder demo, and it
  defaults to `False`.
- Elio's mock-up markup is **never shown, not even for one frame** (§5.3).

The reason is concrete: Elio's hardcoded sidebar claimed Creo had 24 demos
against a real 382. Placeholder data is indistinguishable from real data to
anyone who has not read the source.

### 1.3 A shrinking sync is a bug until proven otherwise

`replace_source_rows(..., allow_shrink=False)` raises `WouldShrinkMirror` if
the incoming row count is below 50 % of the current one
(`_SHRINK_FLOOR = 0.5`). This exists because a Graph delta sync rewrote the
mirror from a **partial page** — 455 assets became 308, 147 were lost, and it
reported success. Fixed in commit `5399903`; the guard and a regression test
that fails against the old code went in with it.

Similarly `WouldDowngrade` prevents a Consensus V1 sync from overwriting a
richer V2 sync, which would silently strip every tag from the catalogue.

### 1.4 Divested products are excluded at one funnel, not at each call site

PTC no longer owns ThingWorx, Kepware, Vuforia and six others (decision
2026-09-02, `DIVESTED_PRODUCTS` in `backend/services/taxonomy.py`). Those
assets must not appear **anywhere** in the Hub, including the 5 that also tag a
retained product.

The filter lives in exactly one place per repository — `_load_mirror()` in
`json_repo.py` — so search, filters, browse, rails, facets and a saved
permalink all inherit it. When this was first implemented, `get(asset_id)` in
`sql_repo.py` bypassed it: the one route that needs no search or filter, a
saved link, was the one that leaked. A test now covers it. **If you add a read
path, route it through the funnel.**

Note the deliberate limit: exclusion is on **product tags**, not on prose. Four
assets mention a divested product only in their description and are kept —
product tags are PTC's own judgement, descriptions are prose.

### 1.5 Measure before you claim

Every number in the codebase's comments has a date attached because the
project has been burned by inference. Some examples worth knowing:

| Claim that was wrong | What measurement showed |
|---|---|
| "most SharePoint assets have thumbnails" | **0 of 455** have any |
| "SharePoint and Consensus hold the same catalogue" | only 4 of 637 Consensus demos mention LDK or VDK; title matching yields ~6 pairs |
| "titles are unique" | three separate demos are called "Benefits of Mathcad Prime" |
| "`title` is what Consensus searches by" | it searches `internalTitle`, a pipe-delimited convention |
| "`marketing/createlink` is idempotent" | it is not, and created links cannot be listed back |

---

## 2. How data flows

```
  Microsoft Graph                Consensus V2 (read)      Consensus V1 (write)
  Sites.Selected, app-only       Bearer JWT               org api_key/secret
        │                              │                        │
        │ delta or full enumeration    │ 1005 demos, tags        │ createsenddemo
        ▼                              ▼                        │ createlink
  graph/sync.py                  consensus_sync.py              │ userInfo
        │                              │                        │
        │  Asset objects                │                        │
        └──────────┬───────────────────┘                        │
                   ▼                                            │
        replace_source_rows(assets, source_system)              │
                   │  resolves stable ids via owned/identity.json
                   ▼                                            │
        DATA_DIR/mirror/<source>.json                           │
                   │                                            │
                   │  _load_mirror()  ← divestment filter here  │
                   ▼                                            │
        JsonAssetRepository  ── AssetQuery ──▶ /api/assets       │
                   │                                            │
                   ▼                                            │
        static/hub-api.js  ──── rewrites Elio's index.html ──────┘
```

**Sync is manual.** There is no scheduler, cron or background task anywhere in
the codebase — confirmed again 2026-09-03. `POST /api/graph/sync` and
`POST /api/consensus/sync` are the only way the mirror refreshes. Liwei
accepted this for the PoC; see §9.

The two sources cost very different amounts, which is why they want different
frequencies when a scheduler is added:

- **SharePoint has a delta token** (`owned/sync_state.json`), so an unchanged
  check is nearly free. Hourly is fine.
- **Consensus has no delta** and re-pulls everything each time. Once or twice
  daily.

---

## 3. Data model

`backend/models.py` — Pydantic v2. The central type is `Asset`; `AssetSummary`
is what list endpoints return.

Fields worth understanding rather than guessing at:

| Field | Meaning and trap |
|---|---|
| `id` | our stable slug, from `owned/identity.json`. **Not** the source id. Every shared link is keyed on it |
| `source` | `"sharepoint"` \| `"consensus"` \| `"seed"` |
| `title` | display name, **not unique** |
| `internal_title` | what Consensus actually lists and searches by: `Role-Based Demonstration \| Mathcad Prime \| Capabilities Playlist \| Select a Role`. The Consensus query URL must use this, not `title` |
| `products` | the specific module, e.g. `Windchill PDMLink`. SharePoint's full taxonomy, 41 values |
| `product_families` | derived, 19 values. The filter that reaches **both** platforms |
| `segment` | CAD / PLM / ALM / SLM / IoT (+ SCO, 1 asset). For Consensus this is derived from the `internalTitle` pipe convention, which only **64 %** of demos follow |
| `customer_facing` | **field exists, data does not.** 96–100 % `True`, i.e. a default rather than a signal. Do not build a filter on it until it has a real source |
| `external_views` | Consensus only (472 of 491 have it). SharePoint has none |
| `resources[]` | the files inside the asset folder. `size_bytes`, `duration_seconds`, `width`, `height` all come free from the Graph children listing |
| `main_video` | the resource the asset's own duration comes from |
| `consensus_uuid` | the join to Consensus, where one exists |

### 3.1 The two-level product taxonomy

This confused people twice, so: there are **two** family concepts and they
answer different questions.

- **`product_families`** — 19 derived families, computed by
  `family_of()` from prefixes and a small alias table. Used as a *secondary
  filter*: "narrow where I am".
- **`umbrella_families`** — the **8 curated families** Seb gave in the
  2026-09-02 review, used by the left-nav *browse* affordance: "take me
  somewhere".

```python
PRODUCT_FAMILIES = ("Creo", "Codebeamer", "Windchill", "PTC Jetstream",
                    "IPE", "ServiceMax", "PTC Orbit", "Servigistics")
HIDDEN_FAMILIES  = ("Onshape", "Arena")          # on Seb's list, no content yet
FAMILY_ROLLUP    = {"Mathcad": "Creo", "Arbortext": "Windchill",
                    "PTC Modeler": "Codebeamer",
                    "Jetstream": "PTC Jetstream", "Orbit": "PTC Orbit"}
```

Live umbrella counts, 2026-09-03: Creo 422 · Windchill 209 · Codebeamer 99 ·
ServiceMax 13 · PTC Jetstream 6 · PTC Orbit 6 · Servigistics 1 · **IPE 0**.

IPE is on the list deliberately with nothing behind it — demos are being made
now. It renders as an empty family, honestly.

`Jetstream`/`Orbit` in `FAMILY_ROLLUP` are **not** rollups; they are the same
product spelled two ways. Seb's list carries the `PTC ` prefix and SharePoint's
Product column does not. Without those two entries both families read zero
while 6 assets each sit in the catalogue.

### 3.2 Faceted search with self-exclusion

`repo.facets(query)` counts each dimension over **every filter except its
own**. Without this, a dropdown can be entered but never left: pick Type=Video
and every other Type shows 0, so the control is a trap. Implemented in both
repositories with three tests that were proven to fail against the old code
(commit `6457196`).

---

## 4. Code map

```
app.py                       FastAPI app, router registration, lifespan seeding,
                             RevalidatingStatic (see §4.1), / and /debug
backend/
  config.py                  every setting, all env-driven. Read this first.
  models.py                  Pydantic domain types
  tables.py                  SQLAlchemy tables (only for storage_backend="sql")
  db.py, deps.py             session + repository construction
  auth.py                    Easy Auth header parsing, roles, security warnings
  seed.py                    452-asset xlsx snapshot loader (fallback only)
  repositories/
    base.py                  AssetQuery + the AssetRepository ABC — start here
    json_repo.py             THE production backend. Divestment funnel,
                             facet self-exclusion, shrink guard, request store
    sql_repo.py              retained + tested, not used. Proves the abstraction
  services/
    taxonomy.py              the whole vocabulary problem: families, segments,
                             Consensus tag classification, divestment
    sharepoint_mapping.py    driveItem -> Asset, filename signal extraction
    relevance.py             search scoring
    consensus_match.py       SharePoint <-> Consensus matching (mostly moot, §1.5)
    proposals.py             metadata proposals awaiting a curator
  integrations/
    graph/client.py          MSAL app-only token, Graph calls, ETag handling
    graph/sync.py            delta + full enumeration
    graph/writeback.py       accepted proposals -> SharePoint, never overwrites
    graph/requests_list.py   the Demo Requests list contract (verified)
    consensus.py             V1 client. Auth is a BODY object, everything POST
    consensus_v2.py          V2 client. Bearer JWT, tags, read-only
    consensus_oauth.py       V2 OAuth. BLOCKED — see §7.2
    consensus_sync.py        builds Assets from either API version
    sync_report.py           what a sync did, in words
  routers/                   see §4.2
static/
  hub-api.js                 2271 lines. The entire front-end integration
  css/orion.css              Elio's stylesheet
  debug.html                 plain data inspector, ours, cannot collide with Elio's
index.html                   Elio's file, 2.5 MB. See §5
tests/                       365 pass, 2 skip
```

### 4.1 `RevalidatingStatic`

`app.py` subclasses `StaticFiles` to send `Cache-Control: no-cache` on every
static response. Without it the browser applied heuristic freshness and served
a stale `hub-api.js` for minutes — which cost real debugging time here, and
would cost Elio the same on every edit. `no-cache` is not `no-store`: the
response is still cached and still ETag-revalidated, so an unchanged file is a
304 and costs nothing.

### 4.2 API surface

```
GET  /                          Elio's UI
GET  /debug                     data inspector
GET  /health

GET  /api/assets                the main query. AssetQuery as query params
GET  /api/assets/{id}
POST /api/assets/{id}/view

GET  /api/taxonomy              facets for the filter bar
GET  /api/taxonomy/video-levels
GET  /api/taxonomy/rails

GET  /api/segments              landing pages: derived + editorial, kept apart
GET  /api/segments/{key}

POST /api/requests              intake form, JSON
POST /api/requests/with-files   intake form, multipart (needs python-multipart)
GET  /api/requests/unsynced     ones that never reached SharePoint

GET  /api/consensus/status
GET  /api/consensus/probe       userInfo + one search, prints live field names
                                beside our mapping. RUN THIS FIRST with new creds
GET  /api/consensus/search
GET  /api/consensus/reconcile
POST /api/consensus/sync
POST /api/share/consensus       creates a DemoBoard
GET  /api/consensus/oauth/status | /start | /callback
POST /api/consensus/oauth/revoke

GET  /api/graph/status
GET  /api/graph/verify
POST /api/graph/sync
GET  /api/graph/writeback/backlog
POST /api/graph/writeback

GET  /api/curation/summary
POST /api/curation/propose
GET  /api/curation/proposals
POST /api/curation/proposals/{asset_id}/{field}/{decision}

GET  /api/auth/me               read the "warnings" array — it names what is wrong
GET  /api/debug/backend         which repo, which integrations, security warnings
```

Interactive docs at `/docs` (FastAPI generates them).

---

## 5. The front-end, and why it is shaped this way

### 5.1 The non-invasive integration contract

`index.html` is **Elio's file**, arriving from `origin/Elio-UI-Development`
essentially unchanged. Our integration is **one `<script>` tag** plus a small
hoisted `<style>` block. `static/hub-api.js` then takes over the DOM: it
replaces card content, rewrites the nav, takes over the filter controls and
adds the modals.

This is deliberate. It means merging Elio's next revision stays trivial. **Keep
it that way** — resist the urge to restructure his markup.

### 5.2 `index.html` has no `<head>`

Verified: `h.find("</head>")` returns `-1`. The markup begins immediately, and
the main `<style>` block sits at byte offset **2,548,153** while the sidebar
markup is at **72,310**.

This is not a curiosity, it is a trap that already cost two failed fixes. A CSS
rule that hides something must **precede the markup it hides**, or the browser
parses and paints that markup and only reaches the rule 2.5 MB later. Anything
you add that must apply before first paint goes in the hoisted block at the top
of the file, immediately after `<title>`. There is a comment there saying so.

### 5.3 The mock-up must never flash

Elio's markup ships static demo cards and a hardcoded product nav (with real
PTC product logos and invented counts like "1,204 views") so his file stands
alone in a browser. Both are hidden from the first frame:

```css
#mainThread { display: none; }
body.hub-ready #mainThread { display: block; }
.orion-side__body { visibility: hidden; }
body.hub-ready .orion-side__body { visibility: visible; }
```

`hub-api.js` adds `body.hub-ready` only when real content is in place, and
`bootFailed()` shows an explicit failure message if the catalogue never
arrives. There is **no timer reveal** — an earlier version had one, and Liwei's
ruling was explicit: a blank screen or a loading spinner is fine, the mock-up
is not, not even for a frame.

Two notes for whoever changes this:

- Hiding `#mainThread` alone is not enough. `.orion-side__body` is where the
  placeholder is most convincing.
- The brand lockup and PTC mark sit **outside** `.orion-side__body` on purpose,
  so the column keeps its shape and nothing jumps when it appears.

### 5.4 Card interaction model (settled 2026-09-02 with Elio)

Three doors on every card:

| Target | Action |
|---|---|
| Play button | popup `<iframe>` modal playing the **Consensus marketing preview** |
| Title | the asset detail page, routed on `#/asset/<id>` |
| Platform logo | the source platform: SharePoint `web_url`, or the Consensus library searched by `internal_title` |

Consensus sends no `X-Frame-Options` or `frame-ancestors`, so the iframe works.
The marketing view is reached by rewriting the demo's own link:

```javascript
function marketing_view(link) {          // backend/integrations/consensus_sync.py
  return link.replace("preview=sales", "preview=marketing");
}
```

**Why not `marketing/createlink`?** It was tested against the live API. It is
**not idempotent** (every call creates another link) and created links **cannot
be listed back**, so caching them would mean an unbounded, unauditable pile of
links in Consensus. `?preview=marketing` is free, needs no storage and gives
the same view. Elio's two requirements were: use the marketing view, not the
sales preview (which shows ugly "Viewer 1" usernames and lets customers get a
raw preview link), and use a chrome-less popup rather than a new tab. Both are
met. The trade-off Liwei explicitly accepted: no per-view tracking, and a
watermark.

### 5.5 Notable `hub-api.js` internals

| Symbol | Note |
|---|---|
| `SHARE_BUTTON_HIDDEN = true` | the DemoBoard share flow is built and works, but is hidden pending the Easy Auth decision (§7.1). Flip to `false` once auth is on |
| `paintCover()` | generates a coloured cover with the product mark for the **455 assets with no thumbnail**. Earlier version used title initials, which collided ("NOV" ×3) |
| `consensusUrl()` | must use `a.internal_title \|\| a.title` — see §3 |
| `buildFamilyNav()` | rewrites `.orion-side__body`. Counts were deliberately **removed** from Browse-by-Product (see §8.2) |
| `rescoreSelect()` | keeps facet counts honest as filters change |
| `clampDescription()` | Consensus descriptions run to 1194 characters and made tiles absurdly tall |
| `autocomplete="off"` | on the search box, because the browser restored stale text across navigation |
| `MAX_ATTACHMENT_BYTES` | 4 MB, matching `requests_list.py`. Keep the two in step |

---

## 6. Integration specifics that will bite you

### 6.1 Microsoft Graph

- **`Sites.Selected` is a two-step grant.** The app registration permission
  alone grants nothing; a site-level grant is also required. The symptom of
  missing step 2 is a perfectly valid token returning 403 on every call.
- Azure lists **two** different APIs each exposing a permission named
  `Sites.Selected`. The **Microsoft Graph** one is required. Granting the
  SharePoint one looks identical in the portal and does nothing.
- The site host is **`ptccloud`**, not `ptc`:
  `https://ptccloud.sharepoint.com/sites/EXT-TDD`.
- An asset is a **top-level folder in `Demo Catalog` carrying a Demo Type**.
  295 top-level folders carry no Demo Type and are therefore not assets; 167 of
  those are CAD model folders, legitimately a different content type. The
  remaining ~128 need a PM decision (§9).
- The description lives in **`DocumentSetDescription`**, not the read-only
  `Description`. 94 % coverage.
- `size` and the `video` facet (duration, width, height) come **free** in the
  children listing the sync already makes. Graph reports duration in
  **milliseconds**; everything else in this codebase is seconds.
- **Write access is confirmed** (2026-08-31, re-verified 2026-09-02) by a
  non-destructive probe: a PATCH with a deliberately wrong `If-Match` returned
  **412, not 403**, and Graph checks authorisation before preconditions.
  Nothing was modified. The grant itself cannot be listed —
  `GET /sites/{id}/permissions` needs `Sites.FullControl.All` — so **this probe
  is how to re-check it**. `scripts/Check-GraphAccess.ps1` and
  `scripts/check_graph.py` are the tools.
- **v1.0 cannot write list-item attachments.** That is why intake attachments
  go to `Documents/Demo Requests` in the document library instead.

> **Standing instruction from Liwei, still in force:** do not make **any**
> modification to SharePoint while testing. Probes must be non-destructive.

### 6.2 Consensus — two APIs, both needed

|  | V1 | V2 |
|---|---|---|
| Auth | org `api_key` + `api_secret` **in the request body** | Bearer JWT |
| Methods | everything POST | REST |
| Acting user | `auth.user_email` selects it | the authorising person |
| Has tags | no | **yes** |
| Can write | **yes** — DemoBoards, links | no, read-only scopes |
| Status | healthy | running on a **hand-copied token** |

The OpenAPI spec declares **no `securitySchemes`** and every path uses
`security: []`, because auth is a body object. Response shape is
`{"data": {"items": [...], "paging": {...}}, "status": 200}` with the error
status **inside the body**, so an HTTP 200 can carry a failure.

Both APIs run side by side: V2 for indexing (it is the only source of tags,
`usage` view counts and `updateDate`), V1 for sharing and thumbnails.

**Field names that are not what you would guess** (each cost a 400):

- `share_to` items key on **`contact_email`**, not `email`. `first_name` and
  `last_name` work; `contact_first_name` etc. are **silently ignored**.
- A demo's id is always `uuid`. Its URL is `previewLink`, not `url`.
- Paging is `limit` (max 500) / **`page`**, with `nextPage` in the response.
- `createsenddemo` **requires `organization`** — the customer the DemoBoard is
  for. Keep `isTest: true` when exercising it.
- V2 requires an **undocumented `platform: developer-platform` header**, absent
  from both the OpenAPI spec and the OAuth guide. Without it a valid token is
  rejected as "Token header is invalid".

**`isPublic` is the quality boundary.** Of 637 demos, the 146 with
`isPublic=false` are customer-specific boards (Schneider Electric, Thales
Canada, GE Appliances, Siemens Energy), POCs and meeting recordings — **0 of
146 have a folder**, and indexing them would be a confidentiality risk. Only
the **491 public** demos are indexed. Do not relax this.

**`auth.user_email` semantics, verified read-only 2026-09-02:** `info/userInfo`
with a colleague's address returns *their* profile, and an address with no
Consensus account returns **401** rather than quietly falling back to the
configured account. It either acts as the right person or it fails — which is
the property the whole attribution design rests on.

### 6.3 Testing integrations without credentials

`httpx.MockTransport` is used throughout, with **the spec's own example
payloads** — `tests/test_consensus_http.py` and `tests/test_graph.py`. This is
how a breaking rename is caught: `demo.url` → `demo.preview_link` passed a
green suite once because there were no router-level tests. There are now
(`test_consensus_api.py`, `test_graph_api.py`).

---

## 7. Known blockers, with their causes

### 7.1 Easy Auth is unconfigured — and it gates more than it looks

`AUTH_MODE` defaults to `disabled`, which hands every caller a clearly
labelled dev principal with full rights. That is correct locally. Deployed with
Graph credentials present and auth still disabled, **an anonymous visitor can
create SharePoint list items and upload files**. `auth.py` detects exactly this
and reports it in the startup log, `/api/auth/me` and `/api/debug/backend` —
but **a warning is not a guard. Nothing refuses the request.**

The knock-on effect is the reason this is a blocker rather than a nicety.
Consensus V1 has no per-user login: the org credentials act as whoever
`auth.user_email` names, and the only trustworthy source of an address is Easy
Auth. Letting the requester type their own would let anyone send a DemoBoard in
a colleague's name — worse than the status quo. So:

> **No Entra app registration → every DemoBoard sent from the Hub is attributed
> to one person, and the per-recipient tracking a DemoBoard exists for is
> meaningless.**

This is why `SHARE_BUTTON_HIDDEN = true`. Seb attempted the registration and
lacked permission via "Create new"; the Azure error suggests "Provide the
details of an existing app registration", which is the path to try next.

### 7.2 Consensus V2 OAuth is broken on their side

Two independently created credential sets, five encodings, one real
authorisation code — all `invalid_client`. **Their client secret is issued as a
bcrypt hash.** A support ticket is open with no reply.

Also structural: there is **no `client_credentials` grant** — the token
endpoint answers "only authorization_code, refresh_token" — so no daemon flow
exists. A human authorises once and the app refreshes forever, meaning the sync
runs as *that person*. Two consequences when it is fixed: use a shared or
service account, and store the rotating refresh token somewhere durable (which
makes the Azure Files task more urgent, not less).

Meanwhile `CONSENSUS_V2_TOKEN` is a token copied by hand from
`https://app.goconsensus.com/api/v2/docs/portal/`. It is short-lived and tied
to Liwei's login. **When it lapses, the sync falls back to V1 — still working,
but with no tags at all**, which is the one thing V2 was adopted for. The
`WouldDowngrade` guard now catches this rather than letting it happen silently.
Treat a sudden loss of tags as this expiring, not as a bug.

### 7.3 Things that look like data but are not

- **`customer_facing`** — 96–100 % `True`. A default, not a signal. The
  meeting asked for a customer-facing vs internal-only tag; it needs a source
  before it can be a filter.
- **Value Roadmap** — 0 of 946 assets have one. Seb was to show how AMP does
  it. A placeholder renders today, by agreement.
- **Most Viewed for SharePoint** — 0 of 455 have any view count. A "Most
  Viewed" rail today would rank Consensus items only and silently omit every
  SharePoint one. Either label it "Most viewed on Consensus" or hold the rail.
- **78 Consensus assets have no segment and no product family.** They appear
  in search but live on no page. Same root cause as the naming-convention gap
  below.

### 7.4 Open questions awaiting a person

- **For Elio.** Consensus `segment` is derived from the `internalTitle` pipe
  convention (`PLM | Windchill | PLM Overview | Walkthrough | 12:55`). **64 %
  carry it, 36 % do not**, and the gap is almost entirely the *PTC NEXT Spring
  2026 localised block* — the same demo in Japanese / Italian / German /
  French / Chinese, whose folder is the language name. Can it be backfilled,
  and is it enforced for new uploads? If yes, segment coverage goes from 64 %
  toward ~95 % **with no code change**. Elio owns that content, so it is his
  call.
- **For the PM.** The ~128 untyped SharePoint folders (~110 videos): missing
  attribute, or deliberately out of catalogue?
- **For Consensus support.** The bcrypt client secret, and the undocumented
  `platform` header.
- **Unanswered.** Is there a **UUID-addressable Consensus library URL**? Today
  the platform button searches by `internal_title`, and a title is not an
  identifier — three demos share one.
- **Vocabulary.** Elio's markup says `IPL`; the data says `IoT` and `SCO`.
  Page titles currently come from the data. Which is official?
- **Brightcove / Seismic.** Access and API existence still unconfirmed.

---

## 8. Decisions already made — do not re-open without cause

### 8.1 No Azure SQL

Seb's call, superseding an earlier plan. Storage is file-backed JSON behind the
`AssetRepository` interface; at ~950 assets, loading into memory beats a
database round trip, and there is nothing to provision. `SqlAssetRepository` is
**retained and runs the same parametrised tests**, which is what actually
proves the abstraction rather than asserting it. `storage_backend` switches
between them.

### 8.2 No counts on Browse-by-Product

Liwei's call, 2026-09-02. The umbrella and derived family counts legitimately
disagreed (379 vs 422 for Creo, because the lookup hit `product_families`
first), and with self-exclusion applied, clicking Codebeamer sent Creo to 0 —
factually correct and completely confusing. Numbers removed; the nav is now
navigation.

### 8.3 Segment landing pages, not product filter toggles

Liwei's proposal, refined across the 2026-09-02 meeting. The left nav *goes
somewhere*; the filter bar *narrows what you have*. Six segment pages instead
of nineteen product pages. Editorial content deliberately shrunk to a short
description plus an owner contact — release announcements have a shelf life
measured in weeks and reach people through the demo itself and by email.

`/api/segments` keeps derived and editorial content **strictly apart**: derived
is recomputed per request from the same repository call the filters use, so a
page can never promise a number the grid then fails to deliver.

The search box offers whichever category the query names — a segment gets a
link to its page, a family gets "show all N", a type gets a filter. One
mechanism. This also avoids a silent failure: **ThingWorx genuinely split 64
IoT / 44 PLM**, so routing a product name to a segment page would have hidden
44 assets.

### 8.4 Asset requests originate in SharePoint

This is the **one** place the Portal originates data, so SharePoint is its
store of record and **no sync may rebuild it**. Everything else is a read-only
mirror. Local-first: `requests.jsonl` is written before the Graph call, so a
failed write loses nothing. `/api/requests/unsynced` reports the backlog.

The dev principal must **never** override a real submitted address — it did
once, silently replacing `liwchen@ptc.com` with `dev@localhost`. Guarded by
`not user.is_dev_principal`.

Full column spec, views and permissions: `docs/demo-request-list.md`.

### 8.5 Write-back never overwrites

Accepted metadata proposals are pushed to SharePoint only into empty fields,
and the operation says out loud what it did. See `graph/writeback.py` and
`ARCHITECTURE.md` §"write-back never overwrites".

---

## 9. Backlog, in the order it can be picked up

### Ready now, no dependencies

1. **Fill in `owned/segments.json`.** Every segment page renders "No
   description written yet" and "no owner recorded". That is the designed
   state, but it is only defensible while somebody is about to fill it in. Six
   segments: CAD (402), PLM (250), ALM (102), IoT (78), SLM (35), SCO (1). No
   deploy needed:

   ```json
   { "PLM": { "blurb": "...",
              "owner": {"name": "...", "email": "..."},
              "updated_by": "...", "updated_at": "2026-09-03" } }
   ```

   Settle while filling it in: SCO has one asset, and the agreed rule is that a
   page needs an *owner*, not a count — if nobody owns SCO it should stop being
   a page.

2. **Scheduled sync.** Promised in the meeting, still manual. Shape: an Azure
   timer (WebJob or Function) calling the two sync endpoints, plus a manual
   button in `/debug` for troubleshooting. Respect the different costs (§2).

3. **View All Requests table** (asked for by Serge). Filterable by requester,
   status and expected delivery. Note §8.4: SharePoint is the store of record,
   so this reads the list, it does not read `requests.jsonl`. Also note the
   open item in `docs/demo-request-list.md` — the list has no `Status`,
   `TriageNotes` or `DeliveredAsset` columns yet, and without them it is a
   suggestion box rather than a queue.

4. **Admin area** for uploads and settings. Scoped in the meeting, not
   started.

### Blocked on a person

5. **Customer-facing vs internal-only tag** — blocked on a data source (§7.3).
6. **Value Roadmap indexing** — blocked on Seb's AMP walkthrough.
7. **Turning the share button on** — blocked on Easy Auth (§7.1).
8. **Consensus tags surviving long-term** — blocked on Consensus support (§7.2).

### Cleanup noticed but not done

9. `docs/deploying.md` had a stale `CONSENSUS_VIEWER_URL_TEMPLATE` value
   (`?preview=sales`); the code now defaults to `?preview=marketing`. Corrected
   in this handover pass — mentioned so the discrepancy is not rediscovered as
   a bug.

---

## 10. Working conventions in this repo

Worth matching, because the codebase is consistent about them and the
consistency is load-bearing for a project whose main risk is silent wrongness.

- **Commit messages state the fact, not the activity.** `fix: a Graph delta
  sync was rewriting the mirror from a partial page`, not `fix sync bug`.
- **Every comment with a number carries the date it was measured.** If you
  cannot date it, do not assert it.
- **A regression test must be proven to fail against the old code** before it
  counts as covering the bug. Several tests in `test_repository.py` were
  written that way and say so.
- **Fail loudly with a named error** rather than guessing at an unavailable
  contract. `ConsensusSchemaUnknown` did exactly this and it is why the V1
  rewrite was cheap.
- **Restart the server rather than trusting `--reload`** after changing mirror
  field shapes. Stale-process false failures cost time here at least three
  times.
- **Sweep for secret values before every commit.** `.env` is gitignored;
  `.env.example` is committed and must never carry a real value.
- **Gather the spec before building the integration.** The Consensus V1 client
  was written twice because the first version was built on guessed
  conventions; nearly every guess was wrong.

### Running it

```bash
python -m pytest tests/ -q
```

```bash
python -m uvicorn app:app --reload --port 8000
```

Local Python is 3.12.10; the Azure workflow builds on 3.13. No configuration is
needed for a fresh clone — with no credentials it seeds a 452-asset xlsx
snapshot and prints, loudly, that the data is stale. **Once credentials exist
the seed is the wrong answer**, so `app.py`'s lifespan makes seeding
conditional on the sources being *unreachable*, not on the catalogue being
empty. That distinction is there because deleting `data/runtime` used to
silently resurrect stale data alongside a live sync, and it cost two real bugs.

Current state: **365 tests pass, 2 skipped** (both skips are conditional and
correct — one needs a KEPServerEX asset that divestment removed, one is
JSON-repo-specific).
