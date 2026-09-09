# Development Handover — TDD Portal / Technical Marketing Hub

**Written 2026-09-03, substantially revised 2026-09-08, appended 2026-09-09**
(new §9 subsection recording five unscoped asks from an Elio review — no
other section changed) for a successor
developer or AI assistant with no prior context on this project. Everything
here was verified against the working tree and the live data as of the
revision date; where a number appears, it was measured, not estimated. Where
something is unverified, it says so. Five feature commits landed between the
two dates (Load More, file download and preview, Servigistics/IPE/Language
nav work, LDK duration hiding, the Preview button redesign) — §4.2, §5.5,
§5.6 and §8.6 are new or substantially rewritten as of this revision; §8.3
was corrected because the design it originally described (segment landing
pages) was later reverted, before this document's previous revision, and had
gone uncorrected until now.

> 中文导读：本文档是**开发**交接，2026-09-08 做过一次大幅修订。第 1 节是必读的
> "别踩这些坑"；第 2 节是数据流；第 4 节是每个文件的作用；§5.6 是这次新加的
> 文件下载/预览功能；§8.6 是这次新加的显示层改名/隐藏/配色决定；第 9 节是
> 待办清单（已按最新进度更新，几项旧的"待办"已经上线）。
> 部署相关的一切在 `docs/HANDOVER-DEPLOYMENT.md`（同样已同步更新）。

Companion documents, all current as of 2026-09-08:

| Document | What it holds |
|---|---|
| `docs/HANDOVER-DEPLOYMENT.md` | git state, Azure state, the routine deploy process, what's still open |
| `docs/GUIDE-zh-push-and-deploy.md` | Chinese step-by-step for Liwei's own future pushes |
| `docs/ARCHITECTURE.md` (922 lines) | the reasoning behind each decision, in the order it was made, with the measurements |
| `README.md` | how to run it, how to wire each integration |
| `docs/demo-request-list.md` | the SharePoint list contract for the intake form |

Also check this session's saved memory (`tdd-portal-*` and
`product-landing-pages-proposal` files) for context that is genuinely too
fresh or too small to belong in a document — most recently, an exact
agreement with Seb on how Value Roadmap data will eventually arrive
(`tdd-portal-value-roadmap-amp`) and a scoped next task for the file-preview
modal (`tdd-portal-file-preview-properties-table`, now **done** as of §5.6).

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
| `resources[]` | the files inside the asset folder. `size_bytes`, `duration_seconds`, `width`, `height`, `item_id`, `created_at`, `created_by`, `modified_at`, `modified_by` all come free from the Graph children listing -- no extra call for any of them. `item_id` is what §5.6's download/preview endpoints resolve at click time; the four date/name fields feed the preview modal's Properties table |
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
  somewhere". Backend still counts all 8; the nav shows 7 of them and calls
  one by a different name — Servigistics is hidden and IPE reads "PTC Ignite"
  at the display layer only, added 2026-09-08. See §8.6, not this section, for
  that: nothing here changed.

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
GET  /api/assets/{id}/files/{item_id}/download   302 to a fresh Graph download_url()
GET  /api/assets/{id}/files/{item_id}/preview    302 to a fresh GraphClient.preview() (§5.6)

GET  /api/taxonomy              facets for the filter bar
GET  /api/taxonomy/video-levels
GET  /api/taxonomy/rails

GET  /api/segments              derived + editorial, kept apart -- still works,
                                but no longer linked from the nav (§8.3)
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

**The preview mode has flipped twice, and it is currently `sales`, not
`marketing`.** Both are reached by rewriting the demo's own link, in
`sales_view()` (`backend/integrations/consensus_sync.py`, renamed from
`marketing_view()` on the second flip):

```javascript
function sales_view(link) {              // backend/integrations/consensus_sync.py
  return link.replace("preview=marketing", "preview=sales");
}
```

History: Elio's original two requirements (2026-09-02) were to use the
marketing view rather than the sales preview (which shows ugly "Viewer 1"
usernames and lets customers get a raw preview link), and a chrome-less popup
rather than a new tab — see `openPreview()`. On 2026-09-08, after reviewing
the Hub with Seb, Elio asked to revert: `marketing` "performed poorly" in
practice, no further detail given, taken at face value. The popup mechanism
is unaffected, only the query string changed back.

**Why not `marketing/createlink`?** Tested against the live API, both times.
It is **not idempotent** (every call creates another link) and created links
**cannot be listed back**, so caching them would mean an unbounded,
unauditable pile of links in Consensus. Rewriting the query string on the real
`previewLink` is free, needs no storage, and survives either direction of this
flip with a one-line change.

**The value is hardcoded in three independent places** — `config.py`'s
`consensus_viewer_url_template` default, `consensus_sync.py`'s `sales_view()`,
and `hub-api.js`'s `previewUrl()` — because the frontend has no way to read a
server setting today. Missing one of the three on the first flip is exactly
how a change like this ships half-done. If this parameter moves a third time,
worth exposing it through an endpoint the frontend already calls (`/api/taxonomy`
or similar) rather than fixing three files again.

### 5.5 Notable `hub-api.js` internals

| Symbol | Note |
|---|---|
| `SHARE_BUTTON_HIDDEN = true` | the DemoBoard share flow is built and works, but is hidden pending the Easy Auth decision (§7.1). Flip to `false` once auth is on |
| `paintCover()` | generates a coloured cover with the product mark for the **455 assets with no thumbnail**. Earlier version used title initials, which collided ("NOV" ×3) |
| `consensusUrl()` | must use `a.internal_title \|\| a.title` — see §3 |
| `buildFamilyNav()` | rewrites `.orion-side__body` fresh on every load from `facets.umbrella_families` — Elio's own static markup for this group is never shown, only 4 of its 8 sample items even exist there. Skips `HIDDEN_UMBRELLAS`, relabels via `UMBRELLA_DISPLAY` (§8.6). Counts were deliberately **removed** from Browse-by-Product (see §8.2) |
| `UMBRELLA_DISPLAY` / `HIDDEN_UMBRELLAS` | the display-layer rename/hide for umbrella families (IPE → "PTC Ignite", Servigistics hidden) — see §8.6. The backend never learns of either; both are presentation only |
| `HIDDEN_SEGMENTS = ["IoT"]` | same pattern, older and separately introduced (before this doc's 09-03 revision, undocumented until now): IoT held 78 assets before the divested-products cut (§1.4) and 1 after, so it is filtered out of the Segment dropdown at the `fillSelect("hubFilterSegment", ...)` call site. The segment itself and its data are untouched -- this hides one dropdown option, nothing else |
| `rescoreSelect()` | keeps facet counts honest as filters change |
| `clampDescription()` | Consensus descriptions run to 1194 characters and made tiles absurdly tall |
| `autocomplete="off"` | on the search box, because the browser restored stale text across navigation |
| `MAX_ATTACHMENT_BYTES` | 4 MB, matching `requests_list.py`. Keep the two in step |
| `loadMoreState` / `RESULT_LIMIT` | the grid fetches 200 at a time (the API's own ceiling) and appends more on click — added 2026-09-08 after a filter down to "showing 200 of 422" had no way to reach the rest. See §5.6 is unrelated to this; look here in `renderFileList`'s neighbourhood instead |
| `addLanguageTag()` | a corner badge on the thumbnail (not `.asset-card__meta` — that flex row has no wrap and silently clips whatever does not fit, which is exactly what happened to this tag before it moved). Skips English on purpose: 727 of 808 assets are English, a badge on 90% of the grid is noise, not signal |
| `asset.type === "ldk"` gates on `toCardData()`'s `duration` and `openAssetDetail()`'s `vpDuration` | an LDK's duration number is the recording's own length, not how long the live demo actually runs — Seb's review, 2026-09-08. Hidden for LDK, shown for everything else |

### 5.6 File download and preview (added 2026-09-08)

Two new endpoints on `backend/routers/assets.py`, both redirecting rather
than proxying bytes, both resolving fresh on every call rather than caching
anything — the same reasoning `GraphClient.download_url()`'s docstring
already gave for video preview, extended to cover every file in a folder:

```
GET /api/assets/{asset_id}/files/{item_id}/download   -> 302 to Graph's download_url()
GET /api/assets/{asset_id}/files/{item_id}/preview     -> 302 to GraphClient.preview()
```

Both share `_require_listed_file()` (item_id must belong to a resource
actually on that asset — otherwise the endpoint doubles as "fetch any file in
the Demo Catalog by id") and `_demo_catalog_drive()` (resolve site + drive,
same two calls `sync_catalogue()` already makes).

`AssetResource` grew five fields for this, all free from the same driveItem
the sync already lists — no extra Graph call for any of them:
`item_id`, `created_at`, `created_by`, `modified_at`, `modified_by`. All are
`None` on a resource synced before the relevant field existed; the frontend
falls back to plain text or omits the row rather than showing a gap.

**Two constraints, found by testing rather than documented anywhere, that any
future preview work needs to respect:**

1. **The iframe must not carry `referrerpolicy="no-referrer"`.** SharePoint's
   `embed.aspx` viewer (what `GraphClient.preview()` returns) renders
   completely blank without a referrer, with no error on either side of the
   frame boundary. Found by comparing the identical URL opened standalone
   (worked) against the same URL in an iframe with that attribute (blank) —
   the Consensus iframe two sections up needs the opposite, so this is a
   real, easy mistake to copy forward.
2. **Word and PowerPoint files never render inside any iframe on this app,
   full stop — no header on our side changes it.** Confirmed by opening the
   identical `/preview` URL as a top-level navigation (renders Word Online
   correctly, every time) versus in an iframe (blank, no console error on
   either side). This is Office Online's own anti-framing behaviour, the same
   category of defence that stops a WOPI-based editor being embedded
   somewhere a user might mistake for the real SharePoint. Consequence:
   `MODAL_PREVIEWABLE_KINDS = ["video", "image"]` get the in-modal viewer with
   Prev/Next; the "document" kind gets a plain `target="_blank"` link instead,
   pointed at the identical `/preview` URL — a preview before download either
   way, just not inside the app's own chrome for Office files.

The preview modal's Properties table (redesigned 2026-09-08 to match a
screenshot Seb shared of AMP, PTC's own video-analysis tool, per the
`tdd-portal-file-preview-properties-table` memory) shows Language (the
**asset's**, not the file's — `AssetResource` has no per-file language),
Type, Duration, Resolution, Size, Created, Created by, Last modified, Modified
by. Rows with no value are omitted, not shown blank. AMP's own panel also has
a Workfront ID and a Style Template row; neither has a source on this side,
so neither exists here — don't invent one.

The per-row Preview button itself was redesigned the same day from an
icon-only grey button (Liwei: "太过不明显", too easy to miss) to a PTC-green
pill with the word "Preview". The fill colour on hover is pinned to `#00890B`
literally rather than the theme-following `--orion-indigo` token — that
token is `#40AA1D` in dark mode, which carries white text at only 3.01:1,
fine for the idle text/border at this size but not enough once the whole
background goes green. Same pinned value `.play-btn`/`.btn-primary-sm` already
use for the identical reason (§8.6 has the fuller contrast history).

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

### 8.3 Segment landing pages — shipped, then deliberately removed

Liwei's original proposal, from the 2026-09-02 meeting: the left nav *goes
somewhere*; the filter bar *narrows what you have*. Six segment pages instead
of nineteen product pages, editorial content shrunk to a short description
plus an owner contact.

**This shipped, then Seb, Elio and Serge each independently said in a later
review to navigate by product instead** — commit `5f1dded` replaced the
segment nav with the umbrella Browse-by-Product nav §3.1 describes, and
`renderSegmentHeader()` in `hub-api.js` now unconditionally hides the segment
header with a comment recording exactly this. **If you find "six segment
pages" described as the current nav anywhere — an older doc, your own memory
of this project, a stale comment — it is describing this since-reverted
design, not what ships today.**

`/api/segments` **still exists** and still serves derived + editorial content,
kept strictly apart the way it always was — nothing links to it from the nav
any more, but the endpoint itself was not removed, and nothing stops it being
reattached to a UI later if segments come back into favour. See §9 for why
filling in `owned/segments.json` is consequently no longer the priority it
once was.

The search-suggestion mechanism this section originally justified — "a
segment gets a link to its page, a family gets 'show all N'" — checked
against the current code rather than assumed: `suggestionsFor()` has **no
segment branch at all** any more. `baselineFacets.segments` is referenced
exactly once in `hub-api.js` today, to keep the Segment filter dropdown's own
counts honest (`rescoreSelect`) — not for suggestions, not for a nav, not for
a page. Segments are a plain filter now, nothing more.

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

### 8.6 Display-layer renames stay display-layer (2026-09-08)

Two unrelated asks from the same Elio/Seb review, both resolved the same way:
change what a person reads, never what the backend or a query string calls
the thing.

**Servigistics hidden, IPE relabelled "PTC Ignite."** Both are umbrella
families in `PRODUCT_FAMILIES` (`backend/services/taxonomy.py`) and the
backend never hears about either change — `taxonomy.py`, the `umbrella_facet`
values, and the `?umbrella=` query string all still say "IPE". The frontend's
`UMBRELLA_DISPLAY` (value → label) and `HIDDEN_UMBRELLAS` (values hidden
outright) sit in `hub-api.js` and translate at render time, in
`buildFamilyNav()` (nav), the `fillSelect("hubFilterProduct", ...)` call site
(dropdown), and `suggestionsFor()`'s umbrella branch (search). Hiding
Servigistics is a **business decision, not a data one** — it still has an
asset, unlike IPE, which is kept visible at zero on the deliberate logic that
its demos are being made now and dimming it would report a plan as a fault.
**Known residual:** the Request-a-New-Asset form's product pills
(`fillProductPills()`) are a separate code path from all three of the above
and still offer "Servigistics" — flagged when found, not fixed, since it was
outside what was actually asked.

**VDK's display expansion flip-flopped once, worth knowing if it moves
again.** Checked directly against live SharePoint (`Demo_x0020_Type`, every
value in the column enumerated, not sampled): the only two values are
"Live Demo Kit" and "Virtual Demo Kit" — "Video Demo Kit" appears nowhere in
the actual data. Liwei confirmed with Elio directly that "Video Demo Kit" is
still the term to show regardless, with an explicit instruction: if fixing
the wording would touch internal logic, touch only the wording. So the hero
subtitle and the "VDKs" nav item's subtitle read "Video Demo Kits" — display
text only. `TYPE_MAP`, `AssetType.VDK`, the `"vdk"` filter value, and every
place SharePoint's own Demo Type column is read all still say "Virtual Demo
Kit" internally and are untouched. If someone asks again which is "correct",
both answers are true at once on purpose: the data is verified as saying
Virtual, the page is instructed to say Video.

**Two shades of PTC green, and which goes where is measured, not chosen by
eye.** Elio's file has a real dark theme, and no single green clears WCAG AA
on both of its grounds: `#40AA1D` (the brand's primary) carries white text at
3.01:1 on white and 5.51:1 on the dark surface `#1c1f23`; `#00890B` (the
brand's secondary) is the exact reverse, 4.58:1 and 2.94:1. So `--orion-indigo`
(the token name stays, only its value changed, since eighteen of Elio's rules
already reference it) follows the theme — secondary green in light mode,
primary in dark — while anything that fills a shape and puts **white text**
on it (`.play-btn`, `.btn-primary-sm`, the Preview pill's hover state) is
pinned to the literal `#00890B` in both themes rather than following the
token, because the primary green fails white text specifically in dark mode.
Get this backwards — as the first attempt did, hoisting the whole override
block above Elio's own `:root` — and the page does not flash the wrong colour
for a beat, it stays wrong everywhere: two `:root` rules setting the same
custom property resolve by source order, later wins, regardless of which one
is "supposed" to be more specific. Proved in the browser before shipping
either direction, both times.

---

## 9. Backlog, in the order it can be picked up

*(Revised 2026-09-08 — several items below were "ready now" on 2026-09-03 and
have since shipped: Load More, file download and preview, the Servigistics/
IPE/Language nav work, LDK duration hiding. This list is what remains.)*

### New asks — Elio review, 2026-09-09 (not yet scoped)

Five requests from Liwei's 2026-09-09 meeting with Elio. None has an
implementation plan yet — recorded here in the order Liwei raised them, so
they are not lost before the next scoping pass. Each links back to what is
already known from earlier sections rather than starting from nothing.

1. **Add a Comment feature.** Where a comment is stored was explicitly **not**
   decided in the meeting — on an asset, on a resource, backed by a
   SharePoint list, or `owned/` — and needs a follow-up discussion before this
   is scoped. Whatever the answer, §1.1 applies directly: a comment is
   Portal-authored data, so it belongs in `owned/` (a new file, e.g.
   `owned/comments.jsonl`, following the `share_events.jsonl` append-only
   pattern) or in a SharePoint list on the §8.4 model — never in `mirror/`,
   since a sync must never be able to destroy it.

2. **Bring CAD datasets and VM assets into the Hub as first-class content.**
   Today the Hub only surfaces Video, LDK and VDK. Two things already
   measured are directly relevant and worth re-reading before scoping this
   (`ARCHITECTURE.md` §2a):
   - SharePoint has a **second document library, "Virtual Machine Catalog,"
     with 139 items** — a completely separate library from Demo Catalog. The
     old mock-up only ever claimed 14 VMs.
   - `Asset.resources[]` already models `dataset` (.zip) and CAD
     (`.creo`/`.prt.N`) as a resource *kind nested inside* an asset folder —
     that is not the same thing as a VM or a CAD dataset being its own
     browsable asset. This needs the same kind of definitional call §2a made
     for Demo Catalog ("an asset is a top-level folder carrying a Demo
     Type") — applied to a library that has never been enumerated this way.

3. **Surface LDK "Supporting Documents" on the asset detail page.** ~~Liwei's
   working guess was~~ **Measured 2026-09-09 against the live site via Graph**
   (read-only `GET`s with the existing app-only credentials; nothing written)
   — the mechanism is more specific, and less finished, than a guess would
   have suggested:

   - The two example URLs Liwei supplied are **Site Pages**, not Demo Catalog
     folder metadata. `SitePages` is a real Graph-addressable list
     (`GET /sites/{siteId}/lists/Site Pages`, id `8b8e848f-…`) that is
     **excluded from `GET /sites/{siteId}/lists`'s own enumeration** (it
     carries a `system` facet) but is directly addressable by name — worth
     remembering if a future Graph call silently "can't see" it. Its 549
     items (§2a of `ARCHITECTURE.md`) are one profile page per LDK/VM, each
     with its own metadata columns (`Demo_x0020_Type`, `Product`, `Segment`,
     `Priority`, `Availability`, a `Preview` thumbnail, etc.) — `CanvasContent1`
     is empty on both pages checked, so these are **not** modern drag-and-drop
     canvas pages; whatever assembles the page's own layout is a shared
     template outside anything Graph v1.0 exposes.
   - There **is** a purpose-built link between the two catalogues: the
     **Virtual Machine Catalog** library has a `Supported Demos` column —
     confirmed via its column definition to be a multi-value **Lookup**
     pointing at `Title` in the `Site Pages` list. This is clearly the schema
     "Supporting Demo Environment" is meant to read. **It is entirely
     unpopulated: 0 of 139 VM Catalog items have any value in it** (full
     population, not a sample).
   - The reverse direction also exists and is equally unused in practice:
     Demo Catalog **files** (not just the top-level asset folder) carry a
     `Required Virtual Machine Link` hyperlink field. Sampled 30 asset
     folders / 136 files: present on only **3 of 136**, and all three point
     at the generic Virtual Machine Catalog **library root**, never a
     specific VM. A `SetVMLink` field (present on 50 of 136, ~37%) turned out
     to be a link to a SharePoint Designer/Nintex **workflow status page**
     (`wrkstat.aspx?...WorkflowInstanceName=...`, reported "Stage 1" on the
     two sampled) — i.e. there is an actual workflow meant to populate the
     real per-asset VM link, and on this evidence it does not appear to be
     completing. Graph does not expose workflow internals, so this could not
     be investigated further from here.
   - **What is genuinely rich and already free:** a `Demo Category` choice
     column set **per file** (not per asset), present on 125 of 136 sampled
     files (92%), with values README · Setup · Battlecard · CAD Data ·
     Datasheet · Demo Data · Outline · Picks · Presentation · Preview Video ·
     Talk Track · VM Software BOM · Webcast Recording · Video · Audio · Cover
     Sheet · TBD. This is the same Graph children listing the sync already
     performs (§3, the way `resources[]` fields are free today) — no extra
     call needed. There is no LDK-level "Documentation" subfolder to speak
     of — the one asset folder inspected in depth was flat (a .pptx, an
     .mp4, two .docx).
   - **Correction, same day, after Liwei checked a live page directly.** The
     `Supported Demos` = 0/139 finding above is real but was measured against
     the wrong VM — Liwei pasted the actual rendered content of
     `.../Virtual Machines/Windchill-13.1.4.1---Virtual-Machine.aspx`, and its
     "Supported Demos" section lists **~70 real LDK/VDK entries, each with a
     person's name and a date** (e.g. "Jetstream VDK V.1 — Aug 25, 2026 —
     Thompson, Scott"), spanning 2024 through 2026. So the feature is live
     and populated for at least this VM — the earlier "unused infrastructure"
     conclusion does not hold in general and should not be repeated as
     written above.
   - Chasing this down further **the Virtual Machine Catalog document
     library has no folder for "Windchill 13.1.4.1" at all** — its newest
     Windchill folder is `Windchill 13.0.1.1 Rev 1.0`, from 2024. Its own
     `Supported Demos` lookup column is real but appears to belong to a
     library that has stopped receiving new VM folders, while the "Virtual
     Machines" folder under **Site Pages** is the one still being kept
     current. Practical consequence for new-ask item 2 (VM ingestion): the
     139-item Virtual Machine Catalog library **cannot be treated as the
     current VM inventory** — Site Pages' `Virtual Machines/` folder needs to
     be the source, or at least cross-checked against it, or newer VMs like
     this one are invisible to the Hub.
   - The Site Pages list itself was checked column-by-column (82 columns) and
     **has no `Supported Demos` (or similarly named) column at all** — so
     the ~70-row list on the live page is not a field stored on that page's
     own item either. Checked and ruled out as the source: `VM - Related
     Demos` (still 1 row, unchanged since 2026-08-14), `VM/Demo Issue
     Tracking` (a bug tracker — "Reported/Fixed In - VM/Demo" columns, not a
     supported-demos log). Graph's drive full-text search
     (`/drives/{id}/root/search(q=...)`) was tried as a shortcut to locate
     whatever field actually names "13.1.4.1" and **returned HTTP 500 on
     every query, including a trivial one** — this app registration or this
     drive does not support that endpoint, so a brute-force text search is
     not available from here either.
   - **Net position: the real mechanism is still not identified**, and
     evidence now points at something the Graph endpoints tried so far don't
     surface at all — most likely a search-index-backed web part (PnP Modern
     Search / Content Search Web Part) reading a field this investigation
     has not found yet, or a log-like list not yet spotted in the site's
     `/lists` enumeration. Two ways to close this, neither tried yet: (a) the
     classic SharePoint `_api/web/...` REST API can read a page's actual web
     part configuration, but needs a SharePoint-audience token, which this
     app's Graph-scoped credentials do not have; (b) simply asking Elio, who
     commissioned this content and very likely knows whether it is a
     Power Automate flow, a Nintex workflow, or a custom web part.
   - **What still stands from the first pass, unaffected by this
     correction:** `Demo Category` remains a real, populated, per-file
     column (125/136 sampled, free in the same Graph call the sync already
     makes) and is still the practical, buildable basis for a "Supporting
     Documents" section on our own detail page — that recommendation does
     not depend on ever resolving the "Supported Demos" mystery above, which
     is a separate, harder problem (VM-to-demo linkage) worth keeping
     distinct from "show me this asset's supporting files."
   - **Second correction, same day, from screenshots of the reverse
     direction.** Liwei also showed the LDK's own page —
     `SitePages/Demo Catalog/Snowmobile - Windchill Risk and Reliability.aspx`
     — which carries the *reciprocal* widget, "View Supporting Demo
     Environment", showing **VMs that support this LDK** (not the other way
     round). Its "See all" page listed exactly 4 cards: `Windchill 13.1.4.1`,
     `13.1.2.0`, `13.0.1.1`, `11.1 M020-CPS08` — all Virtual Machines, in
     **exact descending-Modified order** (Aug 2026 → Nov 2025 → Aug 2024 →
     Jul 2024). Checked this LDK's own Site Page fields: `Product Group` =
     Windchill, `Segment` = PLM — matching every one of the 4 VMs shown. That
     is consistent with a **computed, not stored**, relationship: a
     Highlighted-Content-style web part filtering the Virtual Machines pages
     by the current page's own `Product Group` (and/or `Segment`), sorted by
     `Modified` descending, capped at 4 — which would explain why no stored
     join field was ever found, on either side.
   - **That hypothesis does not fully survive contact with the other
     direction, though.** The VM's own ~70-row "Supported Demos" list (first
     correction, above) spans product families that are not all "Windchill"
     — Jetstream, MedDev, FAD, EHT, Creo View, Snowmobile — which a
     same-Product-Group filter would not produce. The VM's own description
     ("Modular VM with almost all Windchill modules… **contains many other
     products as well**") suggests it may genuinely be manually associated
     with a broad, curated set of demos rather than computed — meaning the
     two directions ("VMs I need" vs "demos I support") may not be the same
     mechanism at all, or the real filter is broader than Product Group
     (e.g. Segment alone, or a manually maintained set for this specific
     general-purpose VM). Also checked and ruled out this round:
     `LayoutWebpartsContent` (a real column on Site Pages, for header-zone
     web parts) is also `None` on this LDK's page, same as `CanvasContent1`
     — though see the caveat directly below before trusting that "None".
   - **A caution about trusting any "None"/absent field from this
     investigation.** The 13.1.4.1 page's real, ~70-entry `Supported Demos`
     did not merely read as an empty value — the field was **entirely
     absent from the `fields` dict**, not present as a null. That is
     independent evidence that Graph's `$expand=fields` can silently drop a
     large/complex field rather than error on it, so `CanvasContent1` and
     `LayoutWebpartsContent` reading as absent on these pages is **not
     proof** they are actually empty — they could be large enough to hit the
     same silent-drop behaviour. Nothing above should be read as "this page
     definitely isn't a modern canvas page" — only as "Graph would not show
     us that content either way."
   - **Confirmed, same day, from the web part's own configuration pane.**
     Elio did not know how this was built, so Liwei opened the LDK page in
     Edit mode and read the "Highlighted content" web part's own settings
     directly (no code, no Graph — just the page's Edit UI). It is a
     **Custom query (KQL)**, not the basic Filter mode:
     ```
     Path:"https://ptccloud.sharepoint.com/sites/EXT-TDD/SitePages/Virtual Machines"
       (Segment:"PLM") AND (Filetype:aspx)
     ```
     Sort: **Most recent** (Modified, descending — matches the observed card
     order exactly). Layout: Carousel, 1 item shown at a time on the small
     widget; "See all" runs the identical query with no cap, which is why it
     returned exactly the 4 (or ~70, on the VM's reciprocal page) matching
     pages. This fully resolves the apparent contradiction between the two
     directions above: **the filter is on `Segment`, not `Product Group`** —
     PLM is a broad segment that legitimately spans Jetstream, MedDev, FAD,
     EHT, Creo View etc. alongside Windchill, which is exactly the mixed set
     the VM's own ~70-row list showed. There is no stored join field, no
     curated list, and no per-item relationship anywhere — every earlier
     attempt to find one came up empty because there genuinely isn't one.
   - **The reciprocal widget confirmed too, from the VM page's own web part.**
     The "Supported Demos" widget on the `Windchill 13.1.4.1` VM page is the
     same Highlighted Content / Custom Query pattern, mirrored:
     ```
     Path:"https://ptccloud.sharepoint.com/sites/EXT-TDD/SitePages/Demo Catalog"
       (Segment:"PLM") AND (Filetype:aspx) AND WORDS(LDK)
     ```
     `Path` points at the `Demo Catalog` Site Pages folder instead of
     `Virtual Machines`, same literal `Segment:"PLM"`, same most-recent sort
     — plus one extra term, `AND WORDS(LDK)`, not present on the LDK page's
     own query. That addition does not appear to be strictly enforced by the
     live results, though: the VM's own ~70-row list's very first entry was
     "Jetstream **VDK** V.1", which should not match a literal `WORDS(LDK)`
     requirement — most likely because KQL's `WORDS()` matches a page's full
     indexed body/description text, not just its title, so a VDK page whose
     own text happens to mention "LDK" slips through. Not worth chasing
     further; the core three-part recipe (Path scope, Segment literal,
     most-recent sort) is what matters and is now confirmed on both sides.
   - **One fragility worth recording, not for us to fix:** `"PLM"` appears in
     the query text as a **literal string**, not a token bound to the page's
     own Segment field (a true page-property binding renders as a
     `{Segment}`-style placeholder in this same box, which is not what is
     here). So each Site Page's copy of this web part was very likely
     stamped with a hardcoded literal at creation/provisioning time, and
     nothing keeps it in sync if that page's own Segment value is edited
     afterwards. Not our bug to fix, but worth knowing if a page's supporting
     content ever looks stale or wrong on the SharePoint side.
   - **What this means for building it in our own Hub:** the relationship is
     fully computable from data we can already have — no dependency on Seb or
     Elio producing a curated mapping. Once new-ask item 2 (bringing VM
     assets into the Hub) is scoped and VM Site Pages are ingested with their
     own `Segment` field, "Supporting Demo Environment" on our own detail
     page is: **same `Segment`, opposite content type (a Video/LDK/VDK asset
     shows VM assets and vice versa), sorted by most recently modified** —
     the same three ingredients SharePoint's own web part uses, computed
     properly (bound live to each asset's actual current Segment) rather than
     copied as a stale literal the way SharePoint's own copy is. This is a
     genuinely good outcome: it turns out to need no new data source at all,
     only the VM ingestion work item 2 already calls for.

4. **Seb will pursue SSO** (an Entra ID app registration for real sign-in).
   This is not a new blocker — it is the same one already tracked as §7.1.
   Seb's earlier attempt via "Create new" app registration failed for lack of
   permission, and the portal's own error suggested "provide the details of
   an existing app registration" as the path to try instead (§4a of
   `docs/HANDOVER-DEPLOYMENT.md`). If this succeeds, it unblocks the curator
   role, the Share button, and — per this new ask — real per-user
   attribution generally, not only Consensus DemoBoard ownership.

5. **Admin area needs per-demo usage tracking with real analytics**, not just
   uploads/settings (this expands backlog item 2 below, not a separate item).
   Relevant existing infrastructure: `owned/stats.json` already counts
   `views` / `downloads` / `launches` / `shares` per asset (`backend/models.py`,
   `backend/repositories/json_repo.py`) but nothing in the UI surfaces it yet.
   Per §7.3, this cannot be built as one honest number across sources: **0 of
   455 SharePoint assets have any view count**, while Consensus's
   `external_views` covers 472 of 491. Any usage dashboard either has to scope
   itself per-source (e.g. "Most viewed on Consensus") or explicitly show "no
   data" for SharePoint-only assets — inventing a number here is exactly what
   §1.2 exists to prevent.

### V2 scope — bringing VM and CAD data into the Hub (planned 2026-09-09)

Elaborates new-ask item 2 above into an actual plan, now that item 3's
investigation answered the dependency it had on VM assets existing. CAD
datasets and VM environments are **two separate pieces of work with very
different difficulty** — worth sequencing and possibly shipping separately
rather than as one "V2" story.

#### CAD datasets — the easy half, cheap and well-defined

Measured 2026-09-09 across all 751 top-level Demo Catalog folders by their
SharePoint `ContentType`, correcting the rougher §6.1 estimate ("167 CAD
model folders, ~128 need a PM decision"):

| ContentType | Folders |
|---|---|
| `Demo` (today's LDK/VDK/Video assets) | 456 |
| `CAD Model` | **280** |
| `Folder` (genuinely uncategorized — the real "needs a PM decision" set) | 15 |

**280, not 167** carry the real, distinct `CAD Model` content type — sampled
one (`Adirondack Chair`, a flat folder with just a `.zip` and a `.rar`) and
it has its own honest metadata, nothing invented: `Title`, `Description`
("Complete assembly and drawings for a wooden Adirondack chair."),
`CAD_x0020_Product` (free text, e.g. "ProENGINEER Wildfire" — not the
managed-metadata `Product` term Demo folders use), `Product_x0020_Version`,
`Product_x0020_Maintenance_x0020_Release`, a thumbnail `Image`, Created/
Modified. **No `Segment` and no managed `Product` term** on the one sampled
— so a CAD Model asset cannot honestly be filtered by Segment or product
family the way a Demo can, only browsed/searched by name and its free-text
CAD product.

Only 15 folders are genuinely unclassified now — a far smaller open question
than the old ~128 figure suggested, and worth re-raising with the PM with
the corrected number.

**Confirmed 2026-09-09 as exactly what Elio meant**, via a screenshot of
SharePoint's own `Demo Catalog/Forms/CAD Model Gallery.aspx` view (a
pre-built library view filtered to `ContentType = CAD Model`) — it renders
precisely `Name`, `Product Version`, `CAD Product`, `Description` per card,
matching the fields measured above with nothing extra. Full-population
field coverage across all 280: `Image` 280/280, `CAD_x0020_Product` 280/280,
`Description` 280/280, `Product_x0020_Version` 276/280. One caveat found by
comparing the two: the gallery screenshot showed one card ("Aerospace
Data") rendering a **generic file icon instead of a real thumbnail**, yet
its `Image` field holds a well-formed-looking path
(`/sites/EXT-TDD/SiteAssets/CAD Model/Aerospace Data.png`) — so "100% of
items have an `Image` value" is not the same claim as "100% of thumbnails
actually resolve," and at least one does not. Worth spot-checking a handful
of the 280 image URLs for a real 404 rate before promising thumbnails will
always render, rather than assuming the field's presence is sufficient —
same lesson as the SharePoint-assets-have-no-thumbnails finding in §1.5.

**Shipped locally 2026-09-09** (not yet pushed — see the deploy freeze note
below). Two bugs found and fixed while wiring it up, both worth knowing if
this is touched again:

1. **`Image` is a library-wide computed default, not a real-thumbnail
   signal.** Measured: it is textually populated on *all* 456 Demo folders
   too, always following the pattern
   `/sites/EXT-TDD/SiteAssets/CAD Model/<title>.png` — a real uploaded file
   sits behind it for at least some CAD Models (confirmed against Elio's own
   gallery view) but, as far as tested, none of the Demo folders. It is
   therefore mapped as its own `cad_thumbnail` column, used only for CAD
   Model assets — folding it into the shared `thumbnail_url` lookup put a
   guaranteed-broken image path on every Demo card and silently suppressed
   their generated colour cover (`paintCoverInto()` skips its fallback
   whenever `thumbnail_url` is set at all, trusting it to be real).
2. **The column value is a site-relative path** (`/sites/EXT-TDD/SiteAssets/…`),
   never a full URL — unlike the `{"Url": ...}` shape other hyperlink
   columns return. Handed straight to the page it resolves against
   whichever origin is serving the Hub (localhost while developing, the
   Azure app once deployed) instead of SharePoint, and always 404s.
   `sharepoint_mapping.absolutize_url()` now prepends the scheme+host from
   `settings.graph_site_url`.
3. **Resolved by preload-and-fall-back, deliberately not by routing through
   Graph.** Unlike `download_url()`/`preview()`, which are Graph's own
   pre-authenticated *per-click* redirects, this thumbnail renders for
   *every card in a grid at once* — confirmed working in Liwei's own
   already-authenticated Chrome, and confirmed silently failing (the CSS
   background-image never even completes a request) in an unauthenticated
   browser context. Re-resolving through Graph's `/thumbnails` endpoint per
   page view was considered and rejected: that call pattern is once-per-click
   for preview/download, but would be **once per card per page load** here —
   up to 200 Graph calls a page, a real throttling risk that download/preview
   never carry, for an audience (PTC's own TDD team) that is realistically
   always signed into M365 already. Caching a Graph-resolved thumbnail URL at
   sync time was also rejected: those URLs expire, and sync is manual and can
   go a long time between runs (§2), so a stored one would likely be stale by
   the time anyone loads the page.

   Shipped instead, in `hub-api.js`'s `paintCoverInto()`: preload the
   thumbnail with `new Image()` before trusting it, and on `onerror` fall
   back to the exact same generated colour cover already used for an asset
   with no `thumbnail_url` at all (`renderCoverMark()`, split out from
   `paintCoverInto()` so both paths render identically). Zero added
   server-side cost either way — the browser's own cache serves the probe
   from the same request Elio's card markup already fired, so success costs
   nothing extra, and failure degrades to an existing, already-correct visual
   rather than a blank tile. If a real need for unauthenticated viewing ever
   materialises, the properly durable fix would be downloading the thumbnail
   *bytes* once at sync time into `DATA_DIR` and serving them ourselves — no
   expiry, no per-view Graph cost, no dependence on the viewer's own session
   — but that is real implementation work, not justified today.

Implementation shape: add a new `AssetType` (e.g. `cad_model`), extend the
asset-definition funnel (currently `_load_mirror()`/the sync's
"has a Demo Type" rule) to also admit `ContentType == "CAD Model"` folders,
and map the CAD-specific fields above. Do **not** confuse this with the
already-covered per-file `Demo Category == "CAD Data"` tag found on files
*inside* existing Demo/LDK folders (§9 item 3's investigation) — that is a
resource-level tag on content that is already in the catalogue today; this
section is about the 280 **standalone** CAD-only folders that are not in the
catalogue at all yet.

#### VM environments — the harder half, real design decisions needed

Two candidate sources were found, and **they disagree**, which is itself the
main finding:

- **Virtual Machine Catalog** document library — 139 folders, each with real
  files (e.g. a release-notes PDF, a getting-started guide) and its own
  `Supported Demos` lookup column (§9 item 3). But it appears **abandoned**:
  its newest Windchill entry is `Windchill 13.0.1.1 Rev 1.0`, created 2024.
- **Site Pages / Virtual Machines** — the "profile page" library. Confirmed
  still actively maintained into 2026 (`Windchill 13.1.4.1`, last modified
  Aug 2026) — with **no corresponding folder in the VM Catalog library at
  all**. This is the one that is current.

`ARCHITECTURE.md` §2a called the VM Catalog library "a second asset source"
without knowing about this split — that framing is now known incomplete,
not wrong exactly, but two-and-a-half years stale for the newest VMs. **Site
Pages/Virtual Machines should be the source of record for VM ingestion**,
not the VM Catalog library alone; the VM Catalog library is worth keeping
around only to pull real files (release notes, getting-started guides) for
the older VMs that still have a matching folder there.

VM content is structurally unlike a Demo asset: mostly instructional text
(FTP server addresses, credential naming conventions, a Cloud Portal
template name) rather than files the Hub could preview or download the way
it does for SharePoint files today. Recommendation, consistent with the
Hub's own identity as "an index that dispatches, storing no content of its
own" (§0): index a VM as **metadata + a link back to the real SharePoint
page** — title, description, product/version/availability, a thumbnail,
`Segment` — rather than trying to reproduce the FTP/Cloud Portal flow inside
the Hub.

Two things need an actual decision before coding, not just a plan:

1. **`AssetType.VM` already exists in `backend/models.py`, unused since it
   was added** — this is the type to activate, not a new one to invent.
2. **Identity/mirror partitioning** (§1.1): does a VM asset get
   `source_system="sharepoint"` (still Graph-sourced, just a different
   library/shape) or its own value? Whichever is chosen, follow the existing
   discipline exactly — the project has already paid once for getting
   `source_system` semantics wrong (§1.1's 2026-08-26 incident, 288 assets
   wrongly retired).

Once VM assets exist with their own `Segment` field, "Supporting Demo
Environment" (§9 item 3) becomes buildable exactly as scoped there — same
`Segment`, opposite content type, sorted by most recently modified, bound
live rather than copied as a stale literal. That feature has no further
dependency beyond this section landing.

**Suggested sequencing:** CAD Model ingestion first — the data is clean,
the rule is a one-line `ContentType` check, and there is no open design
question. VM ingestion second, and worth a short conversation with Seb
first specifically about the VM Catalog library looking abandoned — that is
likely news to him too, not something to silently work around in code.

### Ready now, no dependencies

1. **`View All Requests` table** (asked for by Serge). Filterable by
   requester, status and expected delivery. Note §8.4: SharePoint is the
   store of record, so this reads the list, it does not read
   `requests.jsonl`. Also note the open item in `docs/demo-request-list.md`
   — the list has no `Status`, `TriageNotes` or `DeliveredAsset` columns yet,
   and without them it is a suggestion box rather than a queue.

2. **Admin area** for uploads and settings. Scoped in the meeting, not
   started.

3. **`fillProductPills()` still offers "Servigistics"** on the
   Request-a-New-Asset form (§8.6) — a residual gap in a code path separate
   from the nav/dropdown hiding, noticed but out of scope when that shipped.

4. ~~**Fill in `owned/segments.json`.**~~ **No longer the priority it was** —
   segments have no nav entry point any more (§8.3), so nobody currently
   reaches a segment page to read the description on it. `/api/segments`
   still works and this is still worth doing if segments ever get a UI home
   again, but it is not blocking anything today the way it looked like it
   would on 2026-09-03.

### Blocked on a person

5. **Customer-facing vs internal-only tag** — blocked on a data source (§7.3).
6. **Value Roadmap indexing.** Not blocked on *finding* the approach any
   more — Seb confirmed 2026-09-08 it will arrive as **a JSON file per demo
   folder**, written by AMP, read like any other resource in the sync, not an
   API integration. Still blocked on Seb actually producing and handing off
   that JSON for the catalogue's ~950 assets. See the
   `tdd-portal-value-roadmap-amp` memory for the full detail, including one
   still-open question (does AMP analyse per video or per asset folder —
   matters for where the data attaches) that needs confirming when the
   handoff happens, not assumed from this note.
7. **Turning the share button on** — blocked on Easy Auth (§7.1), which is
   itself blocked on the curator-role gap now documented in
   `docs/HANDOVER-DEPLOYMENT.md` §1.
8. **Consensus tags surviving long-term** — blocked on Consensus support (§7.2).

### Scheduled sync — now blocked twice over, not once

**Not built**, as it has been throughout — an Azure timer (WebJob or
Function) calling the two sync endpoints, hourly for SharePoint (it has a
delta token) and once or twice daily for Consensus (it does not), plus a
manual button in `/debug`. But building it is no longer sufficient by
itself: as of 2026-09-08 the sync endpoints require the curator role
(`require_curator` in `backend/routers/graph.py` and `consensus.py`), and
nobody holds it on the deployed app (`AUTH_CURATOR_GROUPS` is empty). A timer
built today would need a service principal with that role, which does not
exist yet either. Until then, data on Azure only ever updates by hand — see
`docs/HANDOVER-DEPLOYMENT.md` §5a for exactly how that is currently done.

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
