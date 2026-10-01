# Migrating Consensus content to SharePoint: notes (discussion only)

Status: **discussion, nothing built.**
- Recorded 2026-09-30 after the Brightcove Gallery migration finished (see
  `brightcove-migration-plan.md`).
- Liwei expects the team to ask for "the same migration for Consensus". These notes say what is
  known, what blocks it and what to ask first.

## Measured (2026-09-30 ~22:15 EDT, read-only, Consensus V1 `demo/search`)

| Fact | Value |
|---|---|
| Demos in the tenant | 658 (498 public, 160 not; none archived) |
| Demo `type` | `single` 523 · `standard` 124 · `advanced` 6 · `flow` 5 |
| Shown in the Hub today | 441: public demos only, minus divested products |
| Fields a demo returns | title, internalTitle, type, language, isPublic/isArchived/isPublished, createdAt, uuid, description, draft, previewLink, folderInfo, highSpot, creatorData, previewThumbs, tours (empty on all) |
| A downloadable video file URL | **none** in what we read |

V2 returns the tags the Hub uses (segment, product, funnel stage, industry) but no images and no
`previewLink` (`backend/integrations/consensus_sync.py`, `media_from_v1`).

## Why it is harder than Brightcove

1. **Getting the video files is the blocker.**
   - Brightcove's CMS API lists each video's MP4 renditions with signed URLs, so the migration
     streams Brightcove → SharePoint.
   - Nothing we call on Consensus returns a file. Possible routes, none verified:
     - ask Consensus (support, or the full API reference) whether an export or media endpoint
       exists — we only use a few endpoints;
     - find the source files: the producers' masters, or the same video already on Brightcove;
     - export by hand from the Consensus UI, then migrate as local files. The migration tool
       already accepts a local path in the manifest's `source` column.
2. **Not every demo is one video.**
   - `single` (523) is most likely one video, and so one MP4.
   - `standard` / `advanced` / `flow` (135) are probably interactive demos: several videos, with
     chapters and branching chosen by the viewer. **This is assumed from the type names, not
     verified.**
   - A file copy loses the interactivity. They would be split into several videos, or left in
     Consensus.
3. **Consensus is more than storage.**
   - The Hub relies on it for "Open Demo" (the Consensus player) and "Create DemoBoard" (sharing
     as yourself, with licence checks).
   - It also relies on Consensus's own engagement reporting.
   - Copying files to SharePoint replaces none of these.

## The question to answer first: what is the goal?

| Goal | What it means |
|---|---|
| Retire Consensus (e.g. licence cost) | Full migration, plus a replacement for sharing, tracking and the interactive demos. The largest by far. |
| A central copy / backup in SharePoint | Consensus stays for sharing; only blocker 1 remains. |
| One place to find everything | Already done: Consensus demos are indexed in the Hub. |

## What can be reused if files are obtainable

- The whole Brightcove pipeline:
  - sheet → manifest → preview/validation → pilot → batches, run from `/migration`;
  - parallel, resumable uploads;
  - Demo Video as the target library, indexed by the Hub (`video_sync.py`).
- New work:
  - a Consensus source (like `BrightcoveSource`);
  - de-duplication against the videos already migrated from Brightcove;
  - a decision on how a Consensus demo maps to folders and files.
- Consensus already carries the Hub's tags (segment, product, stage), which the Brightcove sheet
  had to add by hand.

## Next steps (no code)

1. Ask the team which goal this is.
2. Ask Consensus whether video files can be exported by API, and what the `standard`,
   `advanced` and `flow` types contain.
3. Sample a few `single` demos:
   - can their source files be obtained?
   - how many are already in Demo Video from Brightcove?
