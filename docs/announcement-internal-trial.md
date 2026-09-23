# Internal trial announcement

The email inviting the immediate team to use the Hub, kept here because it was
written once, needed again a week later, and could not be found — it existed
only in a chat transcript.

**It is a template, not a record.** The figures and the version number below
were true when it was last checked and will not stay true. Run the checks in
*Before sending* and edit, rather than sending it as it stands.

| | |
|---|---|
| Audience | the immediate team, not the wider Marketing / Solution Consulting org |
| Sent by | Elio |
| Prompted by | Seb, 2026-09-18: *"I think we have a good stage where we should start using the technical Marketing Hub internally in the team"* |
| Revised | 2026-09-23, after Elio and Seb's review: the phased rollout, the internal-review framing, and the old sites staying up |
| Last verified | 2026-09-23, production on v2026.2.42 |

---

## Before sending

Quick checks, because every one of these has been wrong at some point:

```bash
P=https://technical-marketing-hub-c8gxg4fagycjh5dz.eastus-01.azurewebsites.net
curl -s "$P/api/version"                                    # the number in the mail
curl -s "$P/api/assets?limit=1" | head -c 120               # the asset count
curl -s "$P/api/graph/status"; curl -s "$P/api/consensus/status"   # last sync dates
```

- [ ] The **version number** quoted in the mail matches `/api/version`.
- [ ] The **asset count** is still about right.
- [ ] Both sources synced recently — a fortnight-old catalogue undercuts the
      "now live and ready to use" framing.
- [ ] The **Share feedback** button still points at the current form.
- [ ] The **duplicate check** on Request New Asset is still the real one.
      It was a placeholder returning invented figures until 2026-09-22, and
      the mail now sends people to it — check a product returns plausible
      matches before promising that it does.

---

## The email

**Subject: Introducing the Technical Marketing Hub — try it out and tell us what you think**

Hi team,

We'd like to introduce the **Technical Marketing Hub** — a new home for our
demo content, now live and ready to use:

🔗 **https://technical-marketing-hub-c8gxg4fagycjh5dz.eastus-01.azurewebsites.net**

**This is an internal review.** Only our team has been invited so far, and
we're sharing it before it's finished on purpose: it isn't perfect yet, and
your feedback now is what will shape it before it goes any wider.

The Hub brings the Demo Library, Demo Video Gallery, and VM pages together in
one catalogue covering Videos, Live Demo Kits (LDKs), Video Demo Kits (VDKs),
CAD Datasets, and Virtual Machines (to be added) — pulled from SharePoint and
Consensus so you don't have to remember which system has what. It's about
1,100 assets today. The existing sites aren't going anywhere for now, so
nothing you rely on changes while we test.

A few things worth trying:

- **Browse by Product** in the left sidebar, or filter by Asset Type, Segment,
  Stage, and Language across the top
- **Search** — it covers titles and descriptions across both sources at once
- Open any asset's detail page for the full file list, previews, and a
  one-click **Download Kit**
- On a Consensus demo, the tags on the detail page are clickable — they filter
  the whole catalogue, which is a quick way to find related material
- Use **Request New Asset** if something you need isn't in the catalogue yet —
  it checks the catalogue for similar demos before you ask for a new one

**Telling us what you think is the point of this round.** There's a
**Share feedback** button at the bottom of the left sidebar — it opens our
feedback form in a new tab. What's useful, what's missing, what's confusing:
all of it is worth sending.

If you hit something that looks broken, the **version number next to the PTC
logo** (bottom-left, e.g. v2026.2.42) tells us which build you were on —
including it makes the report much easier to act on.

Two things to expect:

- Content updates happen through a periodic manual sync today, so a brand-new
  upload in SharePoint or Consensus may take a little while to appear.
- Some assets are missing metadata like Stage or Segment, so those filters
  won't catch everything yet. That's a content gap we're working through, not
  a bug — though do tell us if a specific demo is hard to find.

**What happens next**

We're rolling the Hub out in phases:

1. **GXC** — this internal review, starting now
2. **The wider Marketing organization** — next, and this phase will also bring
   single sign-on (SSO)
3. **PTC** more broadly
4. **Partners**, last

Each phase builds on what we learn in the one before, so what you tell us now
shapes every step after it.

Thanks for helping us get this right,
[Elio / signature]

---

## Notes, not for the email

### The link is not access-controlled

Platform sign-in is not enabled — `/.auth/me` returns 404, meaning App Service
Authentication is off entirely. Anyone with the URL can read the catalogue.
Fine for an internal mail; do not describe it as restricted.

This is why the mail says **"only our team has been invited"** and not "only
our team has access", which is how Seb put it in review (2026-09-23). The
first is true; the second will be once SSO is on. Strengthen the wording then,
not before.

### Request New Asset — resolved 2026-09-22

For a while this draft deliberately left it out. The **Check Demo Database for
Similar Content** button was a placeholder that returned hard-coded matches
with invented usage figures under real colleagues' names for Windchill, and a
fabricated all-clear for every other product — not something to point testers
at.

Production now runs the real version (verified on v2026.2.42: a Windchill
check returns 68 genuine matches with real dates and play counts), so the
bullet is back in the list above. Kept here because it explains why the
feature is worth naming in the mail at all: it answers "has someone already
built this", which is the question the form exists to stop people answering
by guesswork.

### What is left out on purpose

The Admin page, Share-to-Consensus and comments. Each is either behind the
admin sign-in or not built, and naming them would send people hunting for
things that are not there. The rule this follows: an announcement should
undersell what exists rather than describe what is planned.

### The phased rollout

From Seb, 2026-09-23: GXC first, then the Marketing organization, then PTC,
and partners last. SSO arrives with the second phase. The mail names the order
but no dates, deliberately — none were agreed, and a date in an announcement
reads as a commitment.

Update the numbered list as each phase happens, rather than writing a new
mail from scratch: the list is the part a later reader will want current.

### The old sites stay up

Elio, 2026-09-23: the Demo Library, Demo Video Gallery and VM pages are not
being shut down for now. So the mail says the Hub *brings them together*, not
that it *replaces* them — the earlier "It replaces the separate…" wording
would have told people to stop using pages that are still the fallback.
Restore "replaces" when they are actually retired.

### Virtual Machines are listed but empty

The catalogue holds 441 videos, 280 CAD datasets, 213 LDKs, 157 VDKs — and
**zero virtual machines** (checked 2026-09-22). The site itself is honest
about it: the sidebar shows "Virtual Machines 0", greyed out and unclickable,
with the tooltip *"No virtual machines in the catalogue yet"*. Post-Sale gets
the same treatment for the same reason.

An earlier draft of this mail listed Virtual Machines among what the
catalogue covers without qualification, which the site then contradicts on
screen. The mail now says "Virtual Machines (to be added)" — Liwei's wording
in the draft that went to Elio, shorter than the sentence it replaced and
equally honest.

Drop "(to be added)" once VMs are indexed.

### The feedback form is shared with AMP

Testers pick which product they are commenting on. Worth a sentence from Elio
if that is not obvious to the team.
