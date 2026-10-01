# Download Kit as one zip — notes for a decision

Status: **discussion only, nothing built** (Liwei, 2026-10-01). To be decided
with Seb and Elio.

## The ask

On a SharePoint demo's detail page, "Download Kit" today only opens the
asset's folder page on SharePoint, where the person presses SharePoint's own
"Download" to get a zip. The ask: one click on the Hub downloads every file in
the folder as a single zip.

## Why SharePoint's own zip cannot be used

- SharePoint's folder "Download" zips through an internal service that needs a
  short-lived authorisation the SharePoint page creates for the signed-in user
  in the browser. A link from the Hub cannot create it.
- Tried 2026-09-10: linking to `_layouts/15/download.aspx?SourceUrl=<folder>`
  returned "File Not Found" on the live tenant; that endpoint takes a single
  file, not a folder or Document Set (see the comment on the Download Kit
  button in `static/hub-api.js`).
- Microsoft Graph has no "zip this folder" operation.

## What is possible: the Hub builds the zip

On click, the server lists the folder through Graph (app credentials, read
only), reads each file from SharePoint and writes it into a zip that streams
straight to the browser. Nothing is stored on the server.

- Files are stored, not recompressed (videos are already compressed). That is
  fast and lets the exact zip size be known up front, so the browser shows
  real progress.
- Every file in the folder goes in, including the CAD parts the detail page
  counts but does not list (55 kits have such files).
- Recorded as a download in the usage log, like single-file downloads.
- Read-only towards SharePoint.

## Sizes (measured 2026-10-01, local mirror, listed files only)

| | |
|---|---|
| Kits with listed files | 729 |
| Median kit | 0.06 GB |
| 90th percentile | 0.36 GB |
| Over 2 GB | 6 kits |
| Over 4 GB | 1 kit (What's New in Creo 11.0 - PM Technical Videos - LDK v.1, 4.24 GB) |
| Bobcat - Intelligent Product Lifecycle | 3.73 GB, 9 files |

Unlisted CAD parts are not in these figures, so real totals are somewhat
higher for those 55 kits.

## Costs and risks

- **All bytes pass through the App Service**: in from SharePoint, out to the
  person. That uses the plan's bandwidth and CPU; which plan tier the app runs
  on was not checked. Several people downloading large kits at once could
  slow the rest of the site.
- **No resume**: a dropped connection on a 3–4 GB kit means starting again
  (SharePoint's own download has the same limitation).
- A short wait before the download starts, while the folder is listed.

## Proposal if it goes ahead

1. "Download Kit" downloads the zip directly.
2. A small "Open in SharePoint" link keeps today's behaviour.
3. Optional size cap — e.g. above 2 GB, point to SharePoint instead (6 kits
   today).

## Decisions needed

1. Build it at all?
2. A size cap, and if so, where?
