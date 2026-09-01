# Demo Request intake — SharePoint list specification

What to create on **EXT-TDD** before wiring the Hub's "Request a New Asset"
form to it. Every column here maps to a control that already exists on that
form, so nothing needs designing twice.

Today the form saves nothing: `submitAssetRequest()` hides the form and shows
a success card, with no request made. This list is where the answers go.

---

## Create the list

New → List → Blank list. Name it **Demo Requests**. Show in site navigation:
yes.

Delete nothing from the default `Title` column — SharePoint requires it. Set
it to hold a one-line summary of the request; the form can compose that from
asset type and product.

## Columns

| Display name | Internal name | Type | Choices / notes |
|---|---|---|---|
| Title | `Title` | Single line | Required by SharePoint. Auto-composed, e.g. "Video — Windchill" |
| Request ID | `RequestID` | Single line | Enforce unique values. Written by the Hub |
| Status | `Status` | Choice | New · Triaged · Scoped · In production · Delivered · Declined. Default **New** |
| Asset type | `AssetType` | Choice | Video · LDK |
| Products | `Products` | Choice, **multi-select** | See the product note below |
| Brief | `Brief` | Multiple lines, plain text | The "Quick brief" free text |
| Narrative angle | `NarrativeAngle` | Choice | Value proposition-led · Features & functions-led · Mix of both |
| Desired length | `DesiredLength` | Choice | < 1 min · 1–3 min · 3–5 min · 5–10 min · 10+ min · Not sure |
| Customer involvement | `CustomerInvolvement` | Choice | None · Customer footage · Customer story |
| Named customer | `NamedCustomer` | Single line | Only meaningful when the above is not None |
| Distribution channels | `DistributionChannels` | Choice, **multi-select** | Social (LinkedIn / YouTube) · Web (PTC.com) · eStore · Share with a prospect · Share with an existing customer · Internal sales enablement · Event / trade show · Internal Hub only · Push to PTC Velocity |
| Content depth | `ContentDepth` | Choice | Teaser · Overview · Explainer · Walkthrough. Derived from the channels, editable |
| Needed by | `NeededBy` | Date only | |
| Compelling event | `CompellingEvent` | Single line | "product launch, trade show, exec review" |
| Starting materials | `StartingMaterials` | Choice, multi-select | Have materials · Team has creative liberty |
| Requester | `Requester` | Person or Group | Not a text field — see below |
| Requester team | `RequesterTeam` | Single line | |
| Notes | `Notes` | Multiple lines, plain text | |
| Delivered asset | `DeliveredAsset` | Hyperlink | Filled at the end; the link back to what was produced |
| Triage notes | `TriageNotes` | Multiple lines | For the team, not the requester |

**Multiple lines: choose "Plain text", not "Enhanced rich text".** Rich text
arrives through Graph as HTML and would have to be stripped on the way into
the Hub.

**Requester as a Person column, not text.** The form asks for a name and an
email as free text, which means two people can spell the same person three
ways and nothing can be grouped by requester. A Person column resolves against
Entra ID, gives a working mailto, and lets a view filter to "mine". The Hub
already knows who is signed in, so it can fill this without asking.

---

## Two things worth changing while you are at it

**1. The product list is wrong.** The form offers Windchill, Creo, ServiceMax,
Codebeamer and "Other". The catalogue has **19** product families, and three
of the biggest are missing from that list: ThingWorx (111 assets), Mathcad
(43) and Arbortext (15). Anyone wanting a ThingWorx video has to choose
"Other", so the single most useful field for routing a request is the one most
likely to be useless.

Fill the choices from the catalogue instead: Creo, Windchill, ThingWorx,
Codebeamer, Mathcad, Arbortext, ServiceMax, PTC Modeler, Integrity, Jetstream,
Orbit, Kepware, Connected Work Cell, Digital Performance Management, Vuforia,
Servigistics — and keep **Other** for what has no family yet.

**2. Nothing records what happens next.** The form captures a request well and
then has nowhere to say it was accepted, who is doing it, or what came out.
`Status`, `TriageNotes` and `DeliveredAsset` above are that missing half; they
are what turns a form into a queue. Without them the list is a suggestion box.

---

## Views to add

- **Triage** — filter `Status = New`, sorted oldest first. The working view.
- **In flight** — `Status` is Triaged, Scoped or In production, grouped by
  Status.
- **By product** — grouped by `Products`, to see where demand actually is.
- **Due soon** — `NeededBy` within the next 30 days and `Status` not
  Delivered. This is the one that catches a trade-show deadline in time.

## Permissions

Everyone in the org: **Contribute** (add items, edit their own). TDD team:
**Edit**. Nobody should be able to change another person's request, but the
team must be able to triage.

## Notify

List → Automate → Rules → *notify someone when a new item is created*. Send to
the TDD team. Built-in and enough; a request nobody sees for a week is the
failure mode this list exists to prevent.

---

## What the Hub needs afterwards

Two things, neither of which is written yet:

1. `POST /api/requests` — validates against `AssetRequestCreate` (which
   already exists in `backend/models.py`), writes to this list through Graph,
   and keeps a copy under `owned/requests.jsonl` so a Graph outage cannot lose
   a submission.
2. `submitAssetRequest()` in index.html — currently a no-op that shows a
   success card. It must call the endpoint and only claim success when the
   write succeeded.

Note the write direction. Everything else the Hub touches in SharePoint is a
read-only mirror; this list is the one place the Portal *originates* data, so
it is Portal-owned and SharePoint is the store of record for it. It must never
be rebuilt by a sync.

Requires `Sites.Selected` with **write** on EXT-TDD. The current grant is
read-only, so ask for the write grant at the same time.
