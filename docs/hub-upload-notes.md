# Uploading through the Hub: notes (discussion only)

Status: **discussion, nothing built.**
- Recorded 2026-09-30 / 10-01 with Liwei, after the Brightcove Gallery migration
  (`brightcove-migration-plan.md`).
- Consensus is out of scope here: its demos are built differently (`consensus-migration-notes.md`).

## The idea

A Hub page where a signed-in user uploads a video and fills in its metadata.
- The Hub then creates the item in SharePoint (and optionally in Brightcove).
- The Hub's index picks the item up.

## Is it wanted?

Yes, it is already a requirement:
- **HLR-B4** (Serge, P2, "Missing"): upload a new asset through TMH, stored in SharePoint.
- The HLR also recommends a process rule: *every new video goes into SharePoint first; the
  Gallery and Consensus are distribution copies.* This page is how that rule would be followed.
- Serge's mockup has an "Add Asset" entry
  (`Highlevel/Gallery_to_TMH_Import_Playbook.html`).

## What already exists and was proven by the migration (2026-09-30, 155 videos)

- **SharePoint write path** (`backend/integrations/graph/migration_writer.py`): document set,
  chunked resumable upload session, metadata written last, Product through the note field.
- **Live vocabularies:** the library's choice options (Segment, Hub Products, Video Type, Video
  Subtype, Gallery) are read live from the library (`LibraryTarget.choices`). A form built on
  them cannot drift from SharePoint, and validation is the same as the migration's.
- **Video file naming** `<demo>_<Video Type>.mp4`, and duplicate-title handling (date suffix).
- **Hub indexing of the Demo Video library** (`backend/integrations/graph/video_sync.py`).
- **Job tracking** with resumable state (the migration's batch log and `/migration` page).

## Design points

1. **Bytes should not pass through the Hub server.**
   - The Hub asks Graph for an upload session. The browser uploads the file in chunks straight
     to that pre-authenticated URL. The Hub then writes the metadata.
   - This keeps large videos off App Service, and avoids its request limits.
   - **To verify first:** that a browser may PUT to the upload-session URL cross-origin (CORS).
     Not tested yet.
2. **Brightcove (optional, phase 2).**
   - Brightcove can pull a video from a URL (Dynamic Ingest). Give it the SharePoint file's
     short-lived download URL, so the user uploads once.
   - **To confirm:**
     - **The ingest permission.** The credential is known to have video write permissions; the
       ingest permission itself was not checked. The migration client is deliberately GET-only.
     - **Placement.** How a video is placed so it appears in the right Gallery (folder, playlist,
       tags): Gallery configuration is unknown to us.
     - **Ingest is asynchronous.** The Brightcove ID is written back to SharePoint's
       `BrightcoveID` once processing finishes.
3. **One job per upload.** Each upload has a job record with its states:
   - file in SharePoint;
   - metadata written;
   - Brightcove ingested.

   A failed step is visible and retryable, like the migration's batches.
4. **Who may upload.**
   - Signed-in (SSO) users with a role: curator, or a new contributor role.
   - The shared Admin credential must not write to SharePoint (`backend/admin_auth.py`).
   - Production has no SSO yet, so the page is staging-only until it does.
5. **Review before it is listed.**
   - New uploads could land as "pending review". A curator would check Customer Facing, the tags
     and any internal-only content before the Hub lists them.
   - Recommended, because the Hub is used to share with customers.
6. **Visible at once.** After an upload, re-index that one item, rather than waiting for the
   twice-daily automatic sync.

## Suggested phases

1. **Videos into SharePoint (Demo Video):** the metadata form and a review step. These combine
   existing capabilities, so this is the lowest risk.
2. **"Also publish to the Brightcove Gallery"** as an option, once point 2's questions are
   answered.
3. **Later:**
   - editing an uploaded item in the Hub;
   - uploading multi-file kits (LDK/VDK), which have a more complex structure.

## Decisions needed before building

1. **Does new content still go to Brightcove?** If the Gallery stays as the public player, phase 2
   matters; if Brightcove is being retired, phase 2 is dropped.
2. Who may upload, whether uploads are reviewed, and who reviews.
3. Is phase 1 videos only?
