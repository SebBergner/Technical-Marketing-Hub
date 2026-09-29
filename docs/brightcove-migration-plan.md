# Brightcove Gallery → SharePoint migration: plan and starting facts

*Written 2026-09-28 (Liwei Chen, with Claude) as the brief for the session that builds it. Nothing
here is built yet. Facts marked "measured" were read that day, read-only, from EXT-TDD. Nothing in
SharePoint was changed.*

## 1. The ask

Serge, Elio and Seb want the Brightcove Gallery videos (the PLM, CAD and GXC galleries, about 476
unique videos and 39.4 h of runtime) moved into SharePoint. The mechanism:

- **Seb provides a sheet**: one row per video, with its metadata and tags.
- **A tool reads the sheet** and downloads each video from Brightcove.
- **The tool uploads each video into the Demo Catalog** as something the Hub already indexes, so it
  becomes searchable in TMH as a VDK or video.

> **Decision, 2026-09-28 (Liwei), which supersedes the Demo Catalog as the target:**
>
> - **`Gallery_Brightcove`** (EXT-TDD) is the **permanent home** of the migrated videos. It was
>   first set up as the Phase 0 test library.
> - The library holds **only Brightcove content**. The migration **does not write to the Demo
>   Catalog**.
> - The Hub will **index `Gallery_Brightcove` as well as the Demo Catalog**. The design of that is
>   still to be decided (§10). Until it is built, the library is invisible in the Hub.
> - Status reporting lives on a separate page, `/migration`. It uses the admin sign-in, is not
>   linked from the main page or `/admin`, and is written for managers. Other future migrations go
>   there too.
>
> Two consequences follow. The spike items in the library (§9) must be dealt with before the Hub
> indexes it. And a separate place to test future write-path changes is needed (§10).

**Context:**

- `C:\Work\TDD Hub\Highlevel\TMH_High_Level_Requirements.md`: especially HLR-A1–A10, B2, B5, C1,
  C2, D4 and decisions D1–D8.
- `C:\Work\TDD Hub\Highlevel\Gallery_to_TMH_Import_Playbook.html`: Serge's mockup import and its
  field mapping. Treat it as a requirements prototype, not as code to adopt.

**Scope boundary.** This is the *file* migration (requirement HLR-B5). The quicker "metadata-only
gallery source" (HLR-A1: searchable, links back to the Gallery) is a separate, smaller piece and
may be wanted first, for the 2026-10-06 executive review.

## 2. What the Hub needs to see

The SharePoint sync (`backend/integrations/graph/sync.py`, `build_assets`) turns a **top-level
folder** of the Demo Catalog library into an asset only when:

- its **Demo Type** is one of `sharepoint_mapping.TYPE_MAP`: `Live Demo Kit` → `ldk`,
  `Virtual Demo Kit` → `vdk`; **or**
- its ContentType is `CAD Model`.

Everything else is skipped. Real demos are folders of the **"Demo" content type**, which is a
document set. The asset id is `slugify(folder name)`, kept stable in `owned/identity.json`. A
folder rename therefore produces a **new** asset id and breaks earlier shared links, so choose
folder names carefully the first time.

Columns the sync reads are listed in `sync.py` `COLUMNS`. Files inside the folder become
`resources`, and `derive_video_facts` picks the main video.

## 3. Measured on 2026-09-28

Read-only (GET only) against EXT-TDD. First pass in the morning; re-checked at 13:18 EDT, which
added the corrections and new rows marked **(13:18)**. The test library row is from 13:41 EDT.

| Fact | Value | How to re-check |
|---|---|---|
| App permission | `Sites.Selected` (app-only token). Re-checked 13:18. | `GraphClient.granted_roles()` |
| Write on EXT-TDD | **Granted.** Confirmed 2026-08-31 and 2026-09-02 by a PATCH with a wrong `If-Match`, which returned 412, not 403. The grant is site-scoped, so it should cover new libraries on EXT-TDD too; not yet confirmed by a write there. | `scripts/check_graph.py`; docs/HANDOVER-DEVELOPMENT.md |
| Site permission listing | Not readable (403): it needs FullControl | — |
| Quota | 536.6 GB used, **536.3 GB remaining**, 1073.7 GB total, state normal. **(13:18)** Every library on the site reports identical numbers, so this is the **site** quota, shared by all libraries, not a Demo Catalog quota. | `GET /sites/{id}/drives?$select=name,quota` |
| Demo Type choices | `AR Experience`, `Live Demo Kit`, `Virtual Demo Kit`. **No "Video".** The stale twin `Demo_x0020_Type0` has the same choices. Re-checked 13:18. | `list_columns` |
| Segment choices | ALM, AR, CAD, IoT, PLM, SCO, SLM (multi-select, check boxes). Re-checked 13:18. | `list_columns` |
| Product, Tags | **Managed metadata** (term store); Graph returns `{Label, TermGuid, WssId}`. **(13:18)** Graph v1.0 does not return a `term` facet on these column definitions, even with `$select=term`, so the bound term set cannot be read from the column. | children listing with `listItem($expand=fields)` |
| **Term store (13:18)** | **Readable** with `Sites.Selected`: 11 term groups are listed. The Product term `Creo Parametric` (`0f90d5b6-792f-41a7-a520-0cc787d285af`, seen on folder "AAX LDK v.1") is in **Extranet / "PTC Product"** (set `505d8d92-dc55-422c-8f3c-a52cbaadf259`, 207 top-level terms). It is not in PTC Corporate Terms' "Product", "PTC Product" or "Product Groups". Only one term was checked, so the binding is likely but not proven. | `GET /sites/{id}/termStore/groups`, `…/sets/{set}/terms/{term}` |
| **Hidden note fields (13:18)** | `Product_0` = `gd5821201d3e49e6b7226b0306116d32`, `Tags_0` = `a42378fcf8ee4c86a9e0031012c55048`. Both are hidden and **not read-only**. `TaxCatchAll` exists. These are the Demo Catalog's internal names; another library has its own. | `GET /sites/{id}/lists/{list}/columns` (paged; 240 columns) |
| Managed metadata write, prior evidence | 2026-09-01, Demo Requests list: writing a multiterm column directly returned **500 on every payload shape** (`requests_list.py`, notes on `Products`). The note field route above was tested on the test library on 2026-09-28 and works; see §9. | — |
| **"Demo" content type (13:18)** | A **document set** (id prefix `0x0120D520`, group "TDD", `shouldPrefixNameToFile: true`). Allowed child types: Demo Content, Document, Linked Content. Its columns include Product, Demo Type, Segment, Language, DocumentSetDescription, Product Version, ConsensusUUID. Customer Facing, Contains Audio and Keywords are library columns, **not** part of the content type. | `GET /sites/{id}/lists/{list}/contentTypes`, `…/{ct}/columns` |
| Text / boolean / date columns | `DocumentSetDescription`, `Keywords`, `Product_x0020_Version` (text); `Customer_x0020_Facing`, `Contains_x0020_Audio` (boolean); `Review_x002F_Expiry_x0020_Date` (date) | `list_columns` |
| **Brightcove ID column** | **Does not exist** in the Demo Catalog (re-checked 13:18). `COLUMNS["brightcove_id"]` finds nothing, so `brightcove_id` is empty on every asset. There is no Gallery URL column either. | `list_columns` |
| Publish / recorded date column | **None usable.** **(13:18)** `FirstPublishedDate` exists, but it is read-only and in the `_Hidden` group, so it cannot carry the Brightcove date. The Hub's `uploaded_at` for SharePoint assets is the folder's `lastModifiedDateTime`. | `sync.py` lines 214 and 230 |
| Existing upload code | `requests_list.upload_attachment` does a simple `PUT …:/content`. Its comment says simple upload is capped at 4 MB; current Graph docs say about 250 MB. Neither limit is measured here, and videos need **upload sessions** either way. | — |
| **Test library** | `Gallery_Brightcove` on EXT-TDD (list id `8c476c7e-757c-4b38-b8bc-4bacd837a854`), created 2026-09-28 17:25 UTC. **State at 14:54 EDT**, after the site owner's setup: content types enabled; "Demo" document set added (list content type id `0x0120D52000FEDB7DCF37384140B521A0BC11FDAED200EC138D1ABA147F43B4FC5E6C202EF9D8`); `Demo_x0020_Type` (the site column, with a library-only `Video` choice added); `Segment` (list column, the same 7 choices as production, not required); Product **multi-valued**, as in production; `BrightcoveID` (text), `OriginalPublishDate` (date only), `GalleryURL` (text); Customer Facing and Contains Audio (the TDD site columns). Product's note field has the same name as in the Demo Catalog (`gd5821201d3e…`); `TaxCatchAll` exists. No Language column: the sync then defaults to `en`. *History:* at 13:41 it had no content types and an extra `DemoType` text column (default `"Video"`). That column was removed because the sync accepts `DemoType` as a Demo Type name. | `GET /drives/{id}/list`, `/sites/{id}/lists/{list}/columns`, `…/contentTypes` |
| **Site vs list columns (13:51)** | The **site** "Demo" content type carries only Product, Product Version, DocumentSetDescription and Required Virtual Machine. In the Demo Catalog, **Demo Type, Segment and Language are list-only columns**, added to the library and not to the site content type, so adding "Demo" to another library does not bring them. The **site** column "Demo Type" (`Demo_x0020_Type`, group "Custom Columns", id `dd3264c9…`) is the one that appears in the Demo Catalog as the **stale twin `Demo_x0020_Type0`**; the live `Demo_x0020_Type` there is list-only. The same pattern holds for Customer Facing and Contains Audio: the TDD site columns are the `…0` twins. There is no Segment site column. Product is the same site column in both places (id `0d582120-1d3e-49e6-b722-6b0306116d32`; its note field name `gd5821201d3e…` is derived from that id). | `GET /sites/{id}/contentTypes/{ct}/columns`, `/sites/{id}/columns`, `/sites/{id}/lists/{list}/columns` |
| Gallery facts (Serge's catalog) | 537 rows / 476 unique videos; 17 carry a Brightcove deletion tag; 40 are below 720p; 103 are from before 2019; GXC is password-protected and has a "Lamborghini – PTC Internal Only" category | the playbook |

## 4. Gaps to close before any upload

1. **A test library.** This is a hard rule: never modify the production Demo Catalog while
   developing or testing (see memory "Project guardrails"). The site owner creates a test library
   on EXT-TDD, or a sandbox site with a Sites.Selected write grant, holding the same "Demo" content
   type and columns.
2. **New columns (site owner):** `Brightcove ID` (text), `Original Publish Date` (date) and
   `Gallery URL` (hyperlink or text).
3. **Demo Type for a single video.** Decide between reusing `Virtual Demo Kit` and adding a
   `Video` choice. A new choice needs one line in `TYPE_MAP`, plus a label if it should read
   differently from Consensus videos.
4. **Date semantics in the Hub.** Without step 2 and a Hub change to prefer `Original Publish Date`
   over `lastModifiedDateTime`, all migrated videos appear as uploaded today and flood "Latest
   Uploads".

## 5. Design outline

**Where it runs.** A **CLI tool in `scripts/`**, run from a workstation. It is not an App Service
endpoint: runs take hours, and App Service has request timeouts and instance restarts. Later it
can become a scheduled job.

**Phases, each gated by the one before:**

0. **Spike, on the test library only.** Using Graph alone:
   - (a) create a top-level folder of the **Demo document-set content type**;
   - (b) set choice, text and boolean columns;
   - (c) set the managed-metadata **Product** column;
   - (d) upload a file over 1 GB with an upload session;
   - (e) have a Hub sync pointed at the test library pick it up as an asset.

   **Done 2026-09-28. Every step passed on the test library, with Graph only. Results, exact
   calls and the Hub changes found are in §9.** The planning notes that follow are kept as
   written. Known hard parts: Graph v1.0 has no direct "create document set" call, and no direct
   way to write managed metadata by label. Candidate workarounds are the hidden note field
   (`<Field>_0` = `-1;#Label|TermGuid`; the working format turned out to be `Label|TermGuid`, see
   §9) and building a label→TermGuid map from existing items. Avoid SharePoint REST: app-only REST
   needs a **certificate** credential, and we have a client secret.
1. **Sheet contract and validator.**
   - Required columns (draft, confirm with Seb): Brightcove ID; Title; Description; Product
     (must match term labels); Segment; Language; Demo Type; Customer-Facing; Internal-only;
     Original Publish Date; Download URL (or rely on the Brightcove API); Gallery URL; Tags.
   - Validate every value against the live choices and terms.
   - **Dry-run report:** new, existing, conflict, invalid and skipped rows, with no writes.
2. **Migration tool.**
   - Idempotent, keyed by Brightcove ID.
   - **Streams** each download into a Graph upload session, without holding a whole file in
     memory.
   - Resumable, with a state file per run.
   - Handles 429 and `Retry-After`.
   - Works in batches, with a batch log listing every folder and item id it created.
   - **Never deletes and never overwrites a value a person changed since the last run** (keep
     last-written values in the state).
   - Optional per video: the poster image (and setting `Preview Image URL`), and captions.
3. **Hub changes.**
   - `TYPE_MAP` for the new type.
   - Read the three new columns.
   - Set `uploaded_at` from Original Publish Date.
   - A "Watch in Gallery" link, the distribution link in HLR-B2.
   - De-duplicate against Consensus videos and existing VDK folders that hold the same video
     (HLR-A5).
4. **Pilot in production:** about 10 videos, reviewed by a person, then batches.

**Folder naming.** Use a stable, human title (the sheet's Title) and never embed dates or version
noise that is likely to change. Renames break Hub links.

## 6. Risks

- **Audience.** "EXT-TDD" may include external or partner users. Confirm the site membership
  before uploading GXC internal-only material, for example Lamborghini. It may need a restricted
  library, or to be excluded.
- **Brightcove access.** Gallery download URLs may be signed or expire, and GXC needs a password.
  The durable path is a Brightcove CMS API credential; find out who owns the account. Gallery
  renditions may be transcodes rather than masters.
- **Managed metadata.** A Product label that no existing item uses has no known TermGuid unless
  the term store is readable.
- **Duplicates.** The same video may already exist as a VDK folder's mp4 or as a Consensus asset.
  Match by Brightcove ID, then by title, duration and product; flag uncertain matches, never merge
  them automatically.
- **Divested products.** ThingWorx, Vuforia and Kepware videos are hidden by the Hub anyway
  (`taxonomy.DIVESTED_PRODUCTS`). Decide whether to upload them at all.
- **Rollback.** A wrong mapping discovered after a batch. The batch log makes it reversible.
  Deleting in production is a destructive action and needs Liwei's explicit go-ahead each time.
- **Volume.** Estimated 40–120 GB, assuming 1–3 GB per hour at 1080p. **Unmeasured**: measure it
  with HEAD `Content-Length` once the sheet has URLs.

## 7. Decisions pending (owner)

| # | Decision | Owner |
|---|---|---|
| 1 | Sheet format and a 5–10 row sample | Seb |
| 2 | Test library; the three new columns; a "Video" Demo Type or not | SharePoint site owner / Elio |
| 3 | Brightcove access route (download URLs or API credential), and GXC | Brightcove account owner |
| 4 | Scope: all 476 or a cut-off; divested products; below-720p videos; deletion-tagged videos | Elio / Serge / Christine |
| 5 | Internal-only content: where it goes, or whether it is excluded | Elio / Serge |
| 6 | Folder naming convention | Elio / Seb |
| 7 | Policy when a gallery video already exists in TMH (Consensus or VDK) | Elio / Seb |

## 8. Standing rules that apply

- Never modify SharePoint while testing. Use the test library. Production writes go only through
  the reviewed pilot and batches, with Liwei's go-ahead.
- `mirror/` is rebuilt by sync; `owned/` is never touched by it (`replace_source_rows` is the only
  mirror writer).
- No secrets in code, docs, logs or chat.
- Pushes to `main` deploy to the **staging** slot. Commit or push only when Liwei asks. Never
  prompt a swap.
- Before claiming a number, measure it and give the date.

## 9. Phase 0 spike results (2026-09-28)

Run 14:01–14:54 EDT by Claude with Liwei, against the **test library `Gallery_Brightcove` only**.
The Demo Catalog was only read. The spike scripts were throwaway and are not in the repo. Every
write went through one guard that refuses any URL outside the test drive or list, and every
created id was logged. Nothing was deleted.

### What works, with the exact Graph calls

| Step | Result | Call that works | Calls that do not |
|---|---|---|---|
| (a) Demo document set | ✅ | 1. `POST /drives/{d}/root/children` with `{"name", "folder": {}, "@microsoft.graph.conflictBehavior": "fail"}`. 2. `PATCH /drives/{d}/items/{id}/listItem` with `{"contentType": {"id": "<list CT id>"}}`. The result's `webUrl` is `_layouts/15/DocSetHome.aspx?id=…`, the same as real Demo folders in the Demo Catalog; plain folders do not get that URL. | `PATCH …/listItem/fields {"ContentTypeId"}` → **403** "Field 'ContentTypeId' is read-only". `PATCH …/fields {"ContentType": "Demo"}` → **200 but no change** (a silent failure). `POST /lists/{l}/items` with a content type → **400** "Files and folders should only be added to a DocumentLibrary via the OneDrive API". |
| (b) Choice, text, boolean, date | ✅ 8 of 8 read back identical | `PATCH /drives/{d}/items/{id}/listItem/fields` with `If-Match`. Multi-choice needs `"Segment@odata.type": "Collection(Edm.String)"`. Date as `"2019-05-14T00:00:00Z"`. | — |
| (c) Product (managed metadata) | ✅ single and multi-valued | PATCH the **hidden note field** (`gd5821201d3e49e6b7226b0306116d32` = `Product_0`). Single value: `"Label\|TermGuid"`. Multiple values: `"Label1\|Guid1;Label2\|Guid2"`. SharePoint then fills `Product` (with a `WssId`) and `TaxCatchAll`. | Writing `Product` directly → **400** "Invalid request", whether as a list, an object, or together with the note field. Note value `"-1;#Label\|Guid"` → **200, `Product` stays empty**. Multi-value note `"-1;#L1\|G1;#-1;#L2\|G2"` → **200, mangles the note and leaves `Product` unchanged**. Both `-1;#` forms are silent failures. |
| (d) Large upload | ✅ | `POST /drives/{d}/items/{folderId}:/{name}:/createUploadSession` with `{"item": {"@microsoft.graph.conflictBehavior": "fail"}}`, then `PUT` 10 MiB chunks (32 × 320 KiB) to `uploadUrl` with `Content-Range` and **no** `Authorization` header. Resume with `GET uploadUrl` → `nextExpectedRanges`. | — |
| (e) Hub pickup | ⚠️ needs Hub changes, see below | Real `delta` + `_with_fields` + `build_assets`, read-only, with no `replace_source_rows`. | — |

### Measured numbers

- **Test file:** `Polaris AR.mp4`, 4,690,525,319 bytes. Stopped on purpose after 30 chunks
  (314,572,800 bytes), then resumed and finished at 14:22:29: HTTP 201, size identical.
- **Integrity:** the local QuickXorHash matched SharePoint's `K1ngEVBNzavrVFMCw2k6r4l3YiQ=`.
- **Throughput from this workstation:** 5.4 MB/s for the first 300 MB, then 4.4 MB/s (4.38 GB
  in 16.7 min). At that rate the unmeasured 40–120 GB estimate would take about 2.5–8 hours.
- **Session expiry:** `expirationDateTime` is renewed as chunks arrive. It moved from 18:19Z
  to 18:36Z during the upload.
- **Video facet:** absent in the completion response, present about 44 s later (483 s,
  1440×1080). The tool must not treat a missing duration right after upload as an error.
- **File name:** not prefixed with the document-set name, despite `shouldPrefixNameToFile: true`.

### Other findings

- **Term store paging never ends.** `GET /termStore/sets/{set}/terms` returns all 207 terms on
  page 1, then an endless `@odata.nextLink` that repeats the same 7 terms each page. The first
  attempt hung for 23 minutes. `GraphClient._paged` has no guard against this. Any term lookup
  must dedupe by id and stop when a page adds nothing new.
- **Hidden columns need `hidden` in `$select`.** Measured 2026-09-28 22:13 EDT on
  `Gallery_Brightcove_Test`: `/lists/{id}/columns` returned 52 columns without it and 163 with
  it. The difference includes Product's note field (`Product_0`). Without `hidden`, a readiness
  check wrongly reports the note field missing, and a library comparison sees no note field on
  either side and calls them identical.
- **Term labels.** There is no plain "Windchill" term, only products such as
  "Windchill PDMLink". Some labels contain a **full-width ampersand** (`Windchill Aerospace ＆
  Defense`), which `clean_text` normalises on read. Writes must use the term's exact label, so
  the sheet validator should match after normalisation but write the stored label.
- The Demo Catalog uses 42 distinct Product labels (read 2026-09-28). This is the fallback
  label→TermGuid source if the term store ever becomes unreadable.
- A file uploaded into the document set showed Product on the file itself afterwards, possibly
  through document-set shared columns. The cause was not verified. It does not affect the Hub,
  which reads only top-level folder fields.

### Hub changes the spike proved necessary (Phase 3)

1. **`TYPE_MAP` has no `Video`.** As deployed, the test library yields **0 assets**. With
   `"Video": "video"` added in-process only (`AssetType.VIDEO` already exists), it yields 1
   asset, and title, description, Brightcove ID, Segment and rails, main video and duration are
   all correct.
2. **`parse_lookup` mishandles a single-valued managed metadata column.** Graph returns a dict,
   not a list, and it was stored as the string `"{'Label': …}"`. Production Product is
   multi-valued (a list), so it does not trigger today, but the fix is one branch.
3. **`Customer Facing` is not read.** Written as false, the Hub showed `customer_facing: true`,
   because the Hub derives it from file names and defaults to true. **This blocks HLR-A9**:
   internal-only GXC videos would appear customer-facing. `Contains Audio` is not read either.
4. **`uploaded_at` is the folder's last-modified date** (2026-09-28), not `OriginalPublishDate`
   (2019-05-14). This confirms gap 4 in §4 and blocks HLR-A8 and D4.

**All four were fixed on branch `feature/brightcove-migration` on 2026-09-28 (not yet committed).**

- **What changed:** `TYPE_MAP` gained `Video`; `parse_lookup` now accepts a bare dict;
  `Customer_x0020_Facing` and `Contains_x0020_Audio` overrule the filename rule when they are
  set (`apply_stated_flags`); `OriginalPublishDate` is preferred for `uploaded_at`.
- **Proof of zero impact:** the same production snapshot (10,506 items, captured 16:17 EDT) was
  built before and after the change. Both runs gave 738 assets with **0 field differences**.
- **On the test library:** the spike folder now becomes a `video` asset with
  `customer_facing: false`, `has_narrated_audio: true`, `uploaded_at: 2019-05-14` and
  `products: ["Creo Parametric"]`.
- **Tests:** 532 pass, 3 skipped (523 before).

### Items left in the test library

These were deliberately not deleted:

- `Polaris AR (spike test)`: a Demo document set with all fields written and
  `Polaris AR.mp4` inside.
- `Spike CT by name`: a plain Folder, which proved the name-based content-type write does
  nothing.
- `Spike CT by contentType`: a Demo document set with Product = Creo Parametric and
  Windchill PDMLink (from the multi-value test).

### Document-set shared columns (measured 2026-09-28 16:52 EDT)

A file uploaded into `Polaris AR (spike test)` showed Product and Demo Type, but not Segment.
Liwei then set Segment on it by hand. This is not a gap in the migration: the Demo document set
pushes only its **shared columns** down to the files inside it.

| Library | Shared columns on the "Demo" content type |
|---|---|
| Demo Catalog | `Product_x0020_Version`, `Demo_x0020_Type0` (the stale twin), `Product`, `Product_x0020_Maintenance_x0020_Release` |
| Gallery_Brightcove | `Product_x0020_Version`, `Demo_x0020_Type`, `Product` |

In the Demo Catalog, across the 108 files directly inside 25 Demo folders:

- **Product** is on 108 of 108, always equal to the folder's value.
- **Segment** and **`Demo_x0020_Type`** are on none.

So files inside demos never carry Segment in production either. The Hub reads only the top-level
folder's fields, which means file-level values do not affect it. If Segment should appear on
files too, the site owner can add it to the shared columns of this library's Demo content type
(library level, not the site content type). That is better than writing it twice from the tool.

## 10. Open design points (2026-09-28)

1. **Hub indexing of `Gallery_Brightcove`.**
   - A second library needs its own delta token, its own shrink guard, and a rule for asset-id
     collisions with the Demo Catalog.
   - **Decided 2026-09-28 (Liwei): a separate source** (for example `source = "gallery"`), not
     merged into `sharepoint`. It keeps the Demo Catalog's mirror and guards untouched.
   - Not built yet.
   - **Future requirement, recorded 2026-09-28 (Liwei), not to be built now:** ordinary users
     should eventually see only *demos*, with **no source tags or platform badges** (SharePoint /
     Gallery / Consensus) on cards, filters or detail pages. Which source holds what is **admin
     knowledge only**, shown on `/admin` (and `/migration`).
     - This pulls against HLR-C1 (a source label on cards and in filters), so HLR-C1 should be
       re-read in that light before it is built.
     - It would also remove the platform badges the main page shows today, which is a visible
       main-page change.
     - Until it is scheduled, adding the gallery source should not add a new user-facing badge
       beyond what the existing badge code does for an unknown source. Check what that is before
       building.
2. **The spike items.** `Polaris AR (spike test)` (with its 4.7 GB video), `Spike CT by name` and
   `Spike CT by contentType` were in what is now the production library.
   - **Removed 2026-09-28 22:06 EDT at Liwei's request.** They were deleted by id, each re-checked
     against its name and creator (the Technical Marketing Hub app) first, and each returned
     HTTP 204.
   - `Gallery_Brightcove` was then empty.
   - The items sit in the site recycle bin, restorable for about 93 days and counting towards the
     site quota until then. The recycle bin was not emptied.
3. **Where write-path changes are tested now.** The library that was the test library is the real
   home.
   - **Decided 2026-09-28 (Liwei):** a separate test library, which Liwei creates that evening.
     `Gallery_Brightcove` stays the production home and is not used for tests from then on.
   - **Created 2026-09-28: `Gallery_Brightcove_Test`.**
     - It was built by hand. "New library → From existing library" refused, with "This list has
       a dependency on another list with a template type that is not supported". The likely
       cause is the `Required Virtual Machine` lookup to the Virtual Machine Catalog, which the
       site Demo content type brings in; managed metadata was not ruled out.
     - A read-only comparison at 21:57 EDT left three differences to fix, all on Segment: its
       display (drop-down, where it must be check boxes, since a demo can have several), a
       default of `ALM`, and Segment also sitting on the Document content type.
     - Product Version is **optional** in the Demo content type of both libraries. It was
       required in `Gallery_Brightcove` until Liwei changed it that evening.
     - **After Liwei's fixes, the comparison at 22:00 EDT reported the two libraries IDENTICAL
       in everything the migration depends on.** That covers the watched columns (type,
       required, choices and their display, date format, default), the note fields, and each
       content type's columns and required flags. For the Demo document set it also covers the
       shared columns, the allowed content types and file-name prefixing.
     - **From this point every write-path test targets `Gallery_Brightcove_Test` only.**
   - The test library must match `Gallery_Brightcove` exactly: content types, the `Video`
     choice, the Segment choices and required flags, multi-valued Product, the three new
     columns, and the shared columns. Verify this read-only by comparing the two before any
     write.
   - At 20:49 EDT, `Gallery_Brightcove` itself still differed from the Demo Catalog in two ways.
     Segment is **required inside the Demo content type** (it is optional in the Demo Catalog),
     and Segment is **part of the Document content type** (it is not in the Demo Catalog), which
     is why files show an empty Segment.
4. **The CLI's run log.** The `/migration` page reads
   `DATA_DIR/owned/migration/brightcove/batches/*.json` (fields: `batch_id`, `mode`, `started_at`,
   `finished_at`, `planned`, `counts`). The CLI runs on a workstation, so the logs have to reach
   the deployment's data directory somehow, for example by the CLI posting them to an admin
   endpoint. Decide this with the CLI.

## 11. The migration CLI (Phase 2 skeleton, 2026-09-28)

`scripts/migrate_brightcove.py`, run from a workstation:

| Command | Writes to SharePoint? | What it does |
|---|---|---|
| `check --library L` | no | Confirms L is fit to write to: the Demo document set, the `Video` choice, every column written, and the Product note field. Loads the Product terms. Counts the demos already migrated. |
| `dry-run --library L --manifest M` | no | Validates every row against the live Segment choices and Product terms (HLR-A7), plans new / existing / conflict / invalid (HLR-A4), and logs the run. |
| `run --library L --manifest M [--limit N]` | yes | Asks for the library's name to be typed, then migrates the `new` rows. |
| `resume <batch id>` | yes | Finishes whatever a run left unfinished, using its batch log. |

**Safety**

- The Demo Catalog is refused outright.
- The production library (`MIGRATION_BRIGHTCOVE_LIBRARY`) is refused without
  `--allow-production`.
- An existing Brightcove ID is **skipped, never updated** (HLR-A6).
- Nothing is deleted.

**Order per video**

1. Create the folder.
2. Set the Demo content type.
3. Upload the video (streamed, 10 MiB chunks, resumable).
4. Write the metadata.
5. Write Product through the note field.

The Brightcove ID is written last, so a folder that has one is complete.

**Batch log**

- One JSON file per run in `DATA_DIR/owned/migration/brightcove/batches/`, rewritten after every
  step.
- `/migration` shows only the runs against its own library, so a test run's `planned` never
  becomes the production progress bar.

**Manifest**

A CSV in our own format; see `backend/services/brightcove_runner.py`. The columns are
`brightcove_id, title, description, segments, products, customer_facing, contains_audio,
original_publish_date, gallery_url, source, filename`. Seb's sheet will be converted into it
(Phase 1).

**Measured 2026-09-28 22:12–22:17 EDT, read-only**

- `check` passes on `Gallery_Brightcove_Test` (207 Product terms, 0 demos).
- It refuses `Gallery_Brightcove` without the flag, and refuses `Demo Catalog` even with it.
- A 2-row sample dry-run planned 1 new and flagged the other row's bad date, unknown segment
  and unknown product.
- No write run has been made yet.

**Not built yet**

- The adapter for Seb's sheet.
- The Brightcove download route (`source` takes a local path or URL today).
- Getting batch logs from the workstation onto the deployment (§10, item 4).
- Updating existing videos in place.
- Poster images and captions.

## 12. Brightcove API access (measured 2026-09-29 09:15–09:17 EDT, read-only)

**Credentials.** `BRIGHTCOVE_CLIENT_ID` and `BRIGHTCOVE_CLIENT_SECRET` (in `.env`, never in the repo)
obtain an OAuth token from `https://oauth.brightcove.com/v4/access_token` (client credentials, valid
300 s).

**Account ID: `2088006836001`.** It is not a secret. The token's `permissions` claim (base64 of
zlib-compressed JSON) lists every permission against that one account, so the ID needs no one to
supply it.

**Permissions.** The credential can **write** Brightcove (`BC_VIDEO_WRITE`, `BC_PLAYLIST_WRITE`,
`BC_EXPERIENCE_WRITE` and more), so the migration must only ever make read calls with it. The
permissions it needs are all present:

- `BC_VIDEO_READ` and `BC_VIDEO_LIST`: list and read videos;
- `BC_VIDEO_CLEAR_SOURCES_READ`: download URLs for the video files;
- `BC_ANALYTICS_READ`.

There is no permission for **digital masters**.

**Findings**

- **The account holds 3,132 videos** (`/counts/videos`), far more than the 476 gallery videos. The
  newest was created that morning and is not a gallery video. **The migration is driven by the
  sheet's Brightcove IDs, never by listing the account.**
- **A video record** has `name`, `description`, `long_description`, `published_at`, `created_at`,
  `duration` (ms), `tags`, `custom_fields`, `images` (poster and thumbnail), `text_tracks`
  (captions), `reference_id`, `original_filename`, `state`, `has_digital_master` and
  `digital_master_id`.
- **Sources** (`/videos/{id}/sources`) are HLS and DASH manifests plus **MP4 renditions** (H.264
  1920×1080 and 1280×720, and an audio-only MP4). Each rendition has its **byte size** and a
  **signed URL**, in both http and https variants; treat the URLs as credentials and never log
  them.
  - **The volume can therefore be measured exactly** by summing the chosen rendition's `size`
    over the sheet's IDs. That replaces the 40–120 GB guess in §6.
  - One sample: 1080p, 108.8 s, 26,820,377 bytes. That is one video, not a basis for a total.
- **The MP4s are Brightcove's transcodes, not the uploaded masters.** Masters would need a
  digital-master permission this credential lacks. Renditions or masters is a decision for
  Serge and Elio (risk "Brightcove access", §6).

**Network: Zscaler TLS inspection on the workstation.**

- Brightcove's domains (`oauth.brightcove.com`, `cms.api.brightcove.com`) reach Liwei's machine
  re-signed by "Zscaler Intermediate Root CA". Python's certifi bundle does not trust that
  (`CERTIFICATE_VERIFY_FAILED`); Windows does, through IT's "Zscaler Root CA" (thumbprint
  `0D23EE8F…F0C5`).
- `graph.microsoft.com` is **not** inspected (normal DigiCert chain). That is why Graph always
  worked.
- The test used certifi plus that one root, exported read-only from the Windows store.
  **Verification was never switched off.**
- A permanent answer is still to choose; see the reply of 2026-09-29. App Service in Azure sits
  behind no Zscaler and needs none of this.

### Brightcove as the source, and the first end-to-end test (2026-09-29)

**Built**

- `backend/integrations/brightcove.py` is a **read-only** client: it has no method that can send
  anything but GET, and a test pins that.
- `backend/integrations/tls.py` makes outbound HTTPS trust the operating system's certificates
  (`truststore`, added to `requirements.txt`). That settles the Zscaler problem, and verification
  stays on.
- An empty `source` in a manifest now means "download from Brightcove by ID".
- `enrich` fills whatever the sheet left blank from Brightcove: title, description,
  `published_at` as the original publish date, the file name, and the rendition size. A value the
  sheet does give always wins.
- The download is **streamed straight into the SharePoint upload session**, with no local file.
  A fresh signed URL is fetched on every start or resume, because the URLs expire.
- The dry-run prints the total volume to upload.

**Facts seen in the public playlist `PLM_Gallery_Featured` (6 videos; read 09:32 EDT)**

- **Tags carry gallery membership** (`plm_gallery`, `ptc_gallery`, `plm_gallery_featured`, …) and
  **Serge's deletion flag `z_for_deletion_1`**.
- **2 of the 6 are `INACTIVE`.** The manifest check rejects inactive videos.
- **The best MP4 varies by age:** 540p for the 2017 videos, 720p or 1080p for later ones. This is
  the "below 720p" group in the playbook.
- The account has 229 playlists, including `PLM_Gallery_*`, `Creo_Showcase_*`, `AR_Gallery_*`
  and **`gxc_internal`**.

**End-to-end test** into `Gallery_Brightcove_Test` only, authorised by Liwei; run 09:33 EDT, 27 s

- **Video:** `5679317223001` "Change Management" (public, 125 s, 540p). The manifest gave only
  the ID, `PLM`, `Windchill PDMLink` and `customer_facing=yes`.
- **Result read back:**
  - a Demo document set with Demo Type `Video`, Segment `PLM`, Product `Windchill PDMLink`
    (WssId 184), the Brightcove ID, OriginalPublishDate 2017-12-13, Customer Facing true, and
    Brightcove's description;
  - the file is **20,319,119 bytes, identical to Brightcove's rendition size**, and SharePoint
    derived a video facet (960×540, 124.7 s).
- **The Hub mapping** turns it into a `video` asset with `uploaded_at` 2017-12-13,
  customer-facing, and a duration of 125 s.
- **Re-planning the same manifest** gives `existing`: nothing would be uploaded twice.
- `GalleryURL` stayed empty because Brightcove does not know a video's gallery page. The sheet
  has to supply it if it is wanted (HLR-B2).
- 20 MB is too small to measure throughput. The first real batch will measure it.

## 13. Seb's sheet, first look (Gallery Consolidation **V29**, analysed 2026-09-29 10:29 EDT, read-only)

V29 is not final; the final version is expected on 2026-09-30. Only aggregates were printed.

**Shape**

- 48 worksheets: a Legend and one sheet per gallery section (`<section> (<gallery>)`).
- Two layouts:
  - **17 columns** (IPL, PLM, CAD, SLM, ALM, PTC NEXT 2026): Section, Id, Video Title, Proposed
    Title, Delete? (IPL: Archive?), Short Description, Long Description, Tags (Brightcove's),
    Proposed Tags, Published Date, Age (Days), Flags, Duration, Video Type, Type Rationale,
    Subtype, Subtype Rationale.
  - **7 columns** (GXC and customer sheets): Section, Id, Video Title, Delete?, Short and Long
    Description, Tags.
  - Many customer sheets are still empty.
- The last row of each sheet is a total; the adapter ignores any row without a numeric Id.

**Counts**

- 443 Brightcove IDs, all distinct: **no video is on two sheets**, and there are no keep/delete
  conflicts.
- **Keep: 260.** PTC Gallery 207, GXC Gallery 52, and 1 on the `Volvo (Retired)` sheet.
  **Delete or archive: 183.**
- The Legend's "TOTAL 184" matches the kept rows of the six 17-column sheets.

**Brightcove, for the 260 kept IDs**

- All 260 were found, all are `ACTIVE`, and all have an MP4.
- Best rendition: 1080p ×240, 720p ×8, 540p ×9, and 3 at odd heights (940, 1028, 1072).
- **Total runtime 20.7 h. Total size of the best renditions 33.53 GB**, which replaces the
  40–120 GB guess in §6. That is about **2.1 h of upload** at the 4.4 MB/s measured on
  2026-09-28.

**What the sheet does not have** (the manifest needs these)

- **No Segment column at all.**
- **No Customer Facing column at all.** HLR-A9 requires it explicitly for every video.
- **83 of the kept rows** (GXC and customer sheets) have no Video Type, no Subtype and no
  Proposed Tags yet.

**Products ("Proposed Tags")**

- The kept rows use 266 tags, 31 of them distinct. **Only 7 distinct tags match a SharePoint
  Product term**: Codebeamer, ServiceMax, Creo Parametric, Creo+, Creo Illustrate, Arbortext
  Content Delivery and Onshape, plus ThingWorx, which is **divested**.
- The biggest ones do not match: **"Windchill" ×82 and "Creo" ×55**. The term set
  (Extranet / "PTC Product", **flat, 207 terms, no hierarchy**) has no family-level terms and
  none of the newer products either (Creo Simulation Live, Windchill AI, PTC Orbit, Jetstream,
  PTC Modeler, Windchill Navigate, …). "Pure Variants" exists as `pure::variants`.
- **Customer names are mixed into Proposed Tags**: Vestas ×9, Bobcat ×9, Hill_Helicopters ×7,
  QuidelOrtho ×3. They belong in Named Customer (HLR-C2), not in Product.

**Other signals**

- **Audio.** 81 kept titles say "Audio" or "No Audio" (46 and 35), which maps to Contains Audio.
  179 say nothing.
- **Video Type (kept):** Technical Overview 106, Technical Walkthrough 40, Presenter Support 20,
  Other/Unclear 11. **Subtype:** Feature 66, Solution 45, Customer 31, N/A 31, Release 4.
- **Titles.** 110 kept rows have a Proposed Title. The adapter should prefer it over the
  Brightcove title.
- **Descriptions.** Both a Short (under 250 characters) and a Long description are given. The Hub
  has one description field today.

**Decisions, 2026-09-29 (Liwei)**

1. **Products: a new multi-choice column `HubProducts` ("Hub Products")** in `Gallery_Brightcove`
   and the test library, holding the Hub's own product vocabulary. The Hub will read it for the
   gallery source. The managed-metadata Product column is filled only where a label matches a
   term exactly.
   - Choices use the Hub's spellings (`taxonomy.py`): `PTC Jetstream`, not "Jetstream";
     `PTC Orbit`.
   - **ThingWorx is not a choice**, because it is divested.
   - Customer names found in Proposed Tags go to `NamedCustomer`, not to products.
2. **Segment** will be added to the sheet in the final version (2026-09-30).
3. **Customer Facing** will be added to the sheet in the final version.
4. **Scope is the Delete? / Archive? column only.** A row not marked for deletion is migrated.
   That includes Attract Loops, `Volvo (Retired)` and anything else unticked.
   - ThingWorx-tagged videos would still be hidden by the Hub's divestment rule.

**New columns** (Liwei creates them in both libraries; internal names first, no spaces):
`HubProducts` (multi-choice, check boxes), `VideoType` (choice), `VideoSubtype` (choice),
`NamedCustomer` (text), `Gallery` (choice: PTC Gallery / GXC Gallery), `GallerySection` (text)
and `LongDescription` (multi-line text). `DocumentSetDescription` takes the Short Description.

**Library rename, 2026-09-29.** Seb and Elio want the library to hold demo videos beyond Brightcove,
named **"Demo Video"**.

- Renaming only changes the display name; the URL stays `Gallery_Brightcove`. The old library is
  now displayed as "Demo Video_tobedelete" (empty).
- New libraries are to be created as `DemoVideo` and `DemoVideoTest`, then renamed to "Demo Video"
  and "Demo Video Test", so the URLs carry no `%20`.
- **Creating a library through Graph is refused: `POST /sites/{id}/lists` returns 403 "Access
  denied"** (measured 11:10 EDT). The app's Sites.Selected role is `write`, which covers items and
  fields, not lists; that would need `manage` or `fullcontrol`. Nothing was created.
- On the empty `DemoVideoTest` (created by hand by Liwei) Graph also refused, with 403, adding the
  site content type (`contentTypes/addCopy`) and creating a list column (`POST …/lists/{id}/columns`)
  (11:25 EDT). **With the `write` role, every schema change is refused.** Only content (folders,
  files, field values) can be written. Library configuration is therefore manual, and the
  read-only comparison verifies it.

**"Demo Video" (URL `DemoVideo`), configured by hand by Liwei, 2026-09-29**

- A read-only check against the spec at 12:06 EDT found it complete: the columns, choices,
  displays, no defaults, the Demo content type (Product Version and Segment optional) and the
  document-set shared and allowed types all match.
- Product is multi-valued; Liwei confirmed this in the UI, since Graph does not expose the setting.
- The custom columns also sit on the Document content type. This is harmless and left as is for
  now.
- `migration_brightcove_library` now defaults to "Demo Video", so the CLI's production guard
  covers it.
- **VideoType choices, deliberately (Liwei):** Technical Overview, Technical Walkthrough,
  Presenter Support, **Technical Teaser**, **Other**. The sheet's "Other/Unclear" maps to
  "Other".
- **Decision (Liwei): tests run on "Demo Video" itself for now, not on a test library.**
  - This is acceptable while the Hub does not index the library.
  - Test items appear on `/migration` and must be removed before go-live: from the batch logs,
    and with Liwei's go-ahead for each delete.
  - `DemoVideoTest` stays empty.

### Sheet adapter and the first write into "Demo Video" (2026-09-29)

**Built**

- `scripts/migrate_brightcove.py from-sheet --sheet <xlsx> --out <csv>` (`backend/services/gallery_sheet.py`)
  converts Seb's workbook into a manifest. It rereads nothing from SharePoint.
- The write path now handles the seven new columns. Every choice value is validated against the
  library's live options, exactly and case-sensitively.
- The managed-metadata Product is derived from Hub Products only where a term matches exactly.
- `check` and `dry-run` may read the production library; `run` and `resume` still need
  `--allow-production`.

**V29 through it (12:11 EDT)**

- 260 rows converted and 183 left out (ticked Delete?/Archive?).
- The Proposed-Tags tokens read as customers were exactly Vestas, Bobcat, Hill Helicopters and
  QuidelOrtho.
- The dry-run against "Demo Video" found **every row invalid for one reason only: customer_facing
  is empty**; that column arrives in the final sheet.
- The only other finding is `ThingWorx` on 2 rows. It is not a Hub Products option, because it is
  divested, so it is reported and not silently dropped.
- All 31 product spellings, the video types ("Other/Unclear" mapped to "Other"), the subtypes and
  the galleries validate.

**First write into "Demo Video"** (a test; authorised; 12:11–12:13 EDT)

- **Video:** `6371368960112` "Vestas: Engineering (Presenter Support)", 212.9 MB.
- **Test-only values:** Customer Facing = no (the Presenter Support rule) and Segment = PLM, ALM,
  CAD (from its products). These were set for the test because the sheet does not have them yet.
- **Read back correct:**
  - HubProducts = Windchill, Codebeamer, Creo, and Product = **Codebeamer only** (the one exact
    term);
  - NamedCustomer Vestas, VideoType Presenter Support, VideoSubtype N/A, Gallery PTC Gallery,
    GallerySection Vestas;
  - both descriptions, Contains Audio false, OriginalPublishDate 2025-04-11;
  - the file is **212,861,617 bytes, identical to the Brightcove rendition**.
- **Throughput, end to end** (Brightcove download streamed into the SharePoint upload):
  **97 s → 2.2 MB/s**. That is half the 4.4 MB/s of the upload alone. At that rate the 33.53 GB
  of V29 would take **about 4.3 h**. This is one video; a first batch will confirm it, and 2–4
  parallel streams may help (§5, not built).
- `/migration` counted products from the managed-metadata column and showed only "Codebeamer".
  Fixed: this library's products are read from Hub Products.
- **The test item stays in "Demo Video"** and must be removed before go-live, with Liwei's
  go-ahead.

**Rendition choice, decided 2026-09-29 (Liwei):** **at most 1080p; where there is no 1080p, the
highest there is** (`BrightcoveClient.MAX_HEIGHT`). If every rendition is taller than 1080p, the
smallest of them is taken. Masters are not used. In V29 the choice changes nothing: the tallest
kept rendition is 1080p.

## 14. Running the migration from /migration (built 2026-09-29)

**Decisions (Liwei, 2026-09-29)**

1. **Who may start a run: an SSO curator, or the shared admin sign-in.** The page uses
   `admin_or_curator`, like the sync buttons.
   - A curator is recorded as themselves.
   - The shared admin sign-in must type an operator name, which the batch log keeps.
   - This is a deliberate, temporary exception to `admin_auth.py`'s "the shared credential never
     writes to SharePoint"; the exception is documented there too. **When production has SSO,
     starting becomes curator-only.**
2. **Where a run executes: inside the Hub server, in a background thread**, on exactly one
   deployment: staging, with `MIGRATION_RUNNER_ENABLED=true`.
3. **Rendition:** at most 1080p; otherwise the highest there is (§13).

**The page flow**

1. **Upload** the workbook (.xlsx, at most 20 MB). It is kept under
   `owned/migration/brightcove/sheets/<id>/` and converted to a manifest.
2. **Preview**, computed in the background (about 60 s for V29's 260 videos), read-only against
   SharePoint and Brightcove:
   - the migration's scope, what is ready now, what needs fixing, what is already in the library
     and what was left out;
   - volume, runtime and an estimated time;
   - Segment, Hub Products, Video Type, Gallery, customer and audience shares, over the whole scope;
   - problems grouped by reason, each with its rows, and a CSV export for the sheet's owner.
3. **Start**: a pilot (the first 10) or all. The library name must be typed; an operator name is
   also needed when signed in with the admin account.
4. **Progress**, polled every 3 s: bytes, videos, the rate and time left, the current video, each
   video's state, and pause (after the current video) and resume.

**Robustness on App Service**

- **One run at a time**, across every gunicorn worker, through an `O_EXCL` lock on the share (the
  `auto_sync` pattern). A heartbeat keeps it fresh; a lock unrefreshed for 15 minutes is taken
  over.
- **A restart resumes** an unfinished, un-paused page run on startup, from its batch log.
- **Pausing is a separate marker file**, because the click can reach another worker.
- **A preview that a restart interrupted** (still "running" after 2 minutes without progress) is
  recomputed when next opened.
- **A video that reached the library between preview and run** is skipped as "already there".
- **The page's "planned" total** comes from the newest workbook, not from the newest run.

**Verified locally (12:44–12:48 EDT, runs off)**

- The V29 upload previewed as: scope 260, ready 0, needing fixes 260 (all for Customer Facing),
  left out 183, 33.5 GB, 20 h 43 min, about 4.2 h. Products: Windchill 82, Creo 55,
  Codebeamer 39, ServiceMax 10. Galleries: PTC 207, GXC 52. These match §13.
- The self-healing preview was exercised.
- No console errors. The run panels are covered by `tests/test_migration_jobs.py`
  (584 tests pass in all).

**Staging needs** (App Service, Configuration)

- `BRIGHTCOVE_ACCOUNT_ID=2088006836001`, `BRIGHTCOVE_CLIENT_ID` and `BRIGHTCOVE_CLIENT_SECRET`.
- `MIGRATION_RUNNER_ENABLED=true`. **Tick "Deployment slot setting"** so it stays on staging.
- **Always On** must be on for the staging slot, or App Service unloads the app while a run is
  going.
- `openpyxl` and `truststore` arrive through `requirements.txt` on the next deploy.
