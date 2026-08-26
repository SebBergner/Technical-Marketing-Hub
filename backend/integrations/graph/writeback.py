"""Push accepted metadata proposals into SharePoint columns.

This closes the enrichment loop:

    Consensus match -> proposal -> human accepts -> **write-back** -> sync

Write-back is the only place the Portal writes to a system of record, and the
only outbound side effect in the codebase that a user cannot undo from inside
the app. Everything unusual here follows from that.

Why it does not simply PATCH every accepted proposal
----------------------------------------------------
An accepted proposal says "this value was right when a human looked at it".
That was possibly days ago, and SharePoint has a second writer — its own UI.
So each item is re-read immediately before writing, and three outcomes are
distinguished that a blind PATCH would collapse into one:

  * the column is already the proposed value  -> nothing to do, mark it done
  * the column is empty                       -> write it
  * the column holds something *different*    -> STOP, report it, write nothing

That last case is the whole reason this care exists. A blind write would
destroy a value somebody typed by hand, silently, and SharePoint's version
history would blame the application rather than anyone who could explain it.

The ETag closes the remaining gap: even the moment between our read and our
write is guarded, so a simultaneous edit fails loudly instead of being lost.

Column names are asked for, not guessed
---------------------------------------
Reading tolerates several plausible internal names (see `sync.COLUMNS`).
Writing cannot — one name is sent, and the wrong one fails on every item. So
the real internal name is resolved from the list's own column definitions
before anything is written, and a missing column aborts the run rather than
producing 450 identical failures.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from backend.integrations.graph.client import (
    GraphClient, GraphConcurrentEdit, GraphError, GraphFieldUnknown,
    GraphPermissionError, SiteRef,
)
from backend.integrations.graph.sync import COLUMNS, SOURCE_SYSTEM, _field
from backend.models import ProposalState
from backend.repositories.base import AssetQuery

log = logging.getLogger(__name__)

#: Portal fields this job knows how to push. Deliberately a allow-list rather
#: than "whatever a proposal names": a proposal field is data, and data must
#: not be able to choose which SharePoint column gets written.
WRITABLE_FIELDS = ("consensus_uuid",)

#: Cap on one run, so a first run against a live site cannot touch the whole
#: catalogue before anyone has seen the result.
DEFAULT_LIMIT = 50


class Outcome:
    """What happened to one proposal. Values are stable — the UI groups on them."""
    WOULD_WRITE = "would_write"          # dry run only
    WRITTEN = "written"
    ALREADY_CORRECT = "already_correct"  # SharePoint already had it
    CONFLICT = "conflict"                # SharePoint has a DIFFERENT value
    NOT_SYNCED = "not_synced"            # no Graph item id — sync has not run
    MISSING = "missing"                  # item gone from SharePoint
    FAILED = "failed"

    #: Outcomes that mean the proposal is finished and can leave the backlog.
    RESOLVED = (WRITTEN, ALREADY_CORRECT)


@dataclass
class ItemResult:
    asset_id: str
    field: str
    outcome: str
    proposed_value: str | None = None
    current_value: str | None = None
    asset_title: str | None = None
    detail: str | None = None

    def as_dict(self) -> dict:
        return {
            "asset_id": self.asset_id, "asset_title": self.asset_title,
            "field": self.field, "outcome": self.outcome,
            "proposed_value": self.proposed_value,
            "current_value": self.current_value, "detail": self.detail,
        }


@dataclass
class WritebackResult:
    dry_run: bool = True
    considered: int = 0
    columns: dict[str, str] = field(default_factory=dict)
    items: list[ItemResult] = field(default_factory=list)
    aborted: str | None = None

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for item in self.items:
            out[item.outcome] = out.get(item.outcome, 0) + 1
        return out

    def as_dict(self) -> dict:
        counts = self.counts()
        return {
            "dry_run": self.dry_run,
            "considered": self.considered,
            "columns": self.columns,
            "counts": counts,
            "aborted": self.aborted,
            # Conflicts are the ones a human must look at, so they are not
            # left to be found by scrolling a 50-row list.
            "conflicts": [i.as_dict() for i in self.items
                          if i.outcome == Outcome.CONFLICT],
            "items": [i.as_dict() for i in self.items],
        }


def _looks_like_a_graph_id(source_item_id: str | None) -> bool:
    """Tell a Graph driveItem id from the seed importer's path.

    The xlsx importer stored `sites/EXT-TDD/Demo Catalog/<name>` because it had
    no real ids to record. Graph ids contain no slashes. Writing needs a real
    id, so the difference decides whether an asset is writable at all.
    """
    return bool(source_item_id) and "/" not in source_item_id


def resolve_column(client: GraphClient, drive_id: str, portal_field: str) -> str:
    """Ask SharePoint what the column is really called.

    Matches our candidate names against both the internal name and the display
    name, ignoring case and spaces, because `Demo Type`, `DemoType` and
    `Demo_x0020_Type` are all the same column seen from different angles.
    """
    def normalise(value: str) -> str:
        return (value or "").replace("_x0020_", "").replace(" ", "").lower()

    definitions = client.list_columns(drive_id)
    by_name: dict[str, str] = {}
    for definition in definitions:
        internal = definition.get("name")
        if not internal:
            continue
        by_name.setdefault(normalise(internal), internal)
        by_name.setdefault(normalise(definition.get("displayName", "")), internal)

    for candidate in COLUMNS.get(portal_field, (portal_field,)):
        match = by_name.get(normalise(candidate))
        if match:
            return match

    wanted = COLUMNS.get(portal_field, (portal_field,))[0]
    raise GraphFieldUnknown(
        f"the library has no column matching {portal_field!r} (looked for "
        f"{', '.join(COLUMNS.get(portal_field, ()))!r}). Add a single-line text "
        f"column named {wanted!r} to the Demo Catalog library in SharePoint, then "
        f"re-run. Nothing was written."
    )


def write_back(client: GraphClient, repo, changed_by: str, dry_run: bool = True,
               limit: int = DEFAULT_LIMIT, site: SiteRef | None = None,
               drive_name: str | None = None) -> WritebackResult:
    """Push accepted proposals to SharePoint.

    Defaults to a dry run. That is not timidity: this is the one operation that
    modifies a corporate system of record, the matcher that generated these
    values produced confident false positives before it was tightened, and a
    dry run costs one extra call per item to find that out safely.

    Returns per-item outcomes rather than raising, because a partial success is
    the normal case — one conflicted item must not stop the other forty-nine.
    """
    from backend.config import settings

    site = site or client.resolve_site()
    drive = client.find_drive(site.site_id, drive_name or settings.graph_list_name)
    if drive is None:
        raise ValueError(
            f"no drive named {drive_name or settings.graph_list_name!r} on {site.web_url}")

    result = WritebackResult(dry_run=dry_run)
    pending = _accepted_proposals(repo, limit)
    result.considered = len(pending)
    if not pending:
        return result

    # Resolve every column up front. A missing column fails identically for
    # every item, so discovering it on item 1 of 50 and stopping is the
    # difference between one clear error and fifty confusing ones.
    try:
        for portal_field in sorted({p.field for p in pending}):
            result.columns[portal_field] = resolve_column(client, drive.drive_id, portal_field)
    except GraphFieldUnknown as exc:
        result.aborted = str(exc)
        return result

    assets = {a.id: a for a in repo.list(AssetQuery(limit=5000)).items}

    for proposal in pending:
        try:
            item = _write_one(client, repo, drive.drive_id, proposal,
                              assets.get(proposal.asset_id),
                              result.columns[proposal.field], changed_by, dry_run)
        except GraphPermissionError as exc:
            # Reads worked (we got this far), so this is a read-only grant. It
            # will fail identically for every remaining item — same reasoning
            # as the missing column above: stop, and say what to ask IT for.
            result.aborted = (
                f"{exc} Reads are working, so the per-site grant exists but is "
                f"read-only. Ask IT to raise it to 'write' on this site. "
                f"{len(result.items)} item(s) were processed before this.")
            return result
        result.items.append(item)

    log.info("graph write-back (%s): %s",
             "dry run" if dry_run else "live", result.counts())
    return result


def _accepted_proposals(repo, limit: int) -> list:
    """Accepted but not yet written — the write-back backlog.

    Only fields on the allow-list, so an unexpected proposal field can never
    steer a write at a column nobody intended.
    """
    page = repo.list_proposals(state=ProposalState.ACCEPTED.value, limit=max(limit, 1) * 4)
    eligible = [p for p in page.items
                if p.field in WRITABLE_FIELDS and p.proposed_value]
    return eligible[:limit]


def _write_one(client: GraphClient, repo, drive_id: str, proposal, asset,
               column: str, changed_by: str, dry_run: bool) -> ItemResult:
    out = ItemResult(asset_id=proposal.asset_id, field=proposal.field,
                     outcome=Outcome.FAILED, proposed_value=proposal.proposed_value,
                     asset_title=proposal.asset_title or (asset.title if asset else None))

    if asset is None:
        out.outcome = Outcome.MISSING
        out.detail = "the asset is no longer in the catalogue"
        return out

    source_item_id = getattr(asset, "source_item_id", None)
    if not _looks_like_a_graph_id(source_item_id):
        out.outcome = Outcome.NOT_SYNCED
        out.detail = (
            f"this asset came from the spreadsheet import, not from Graph "
            f"(source_item_id={source_item_id!r}), so there is no SharePoint item to "
            f"write to. Run POST /api/graph/sync first.")
        return out

    # Re-read now. The proposal was accepted at some earlier point and
    # SharePoint has its own editors; acting on the older picture is exactly
    # how a hand-typed value gets destroyed.
    try:
        list_item = client.get_list_item(drive_id, source_item_id)
    except GraphPermissionError:
        raise                       # not about this item — let the run abort
    except GraphError as exc:
        out.detail = f"could not read the item before writing: {exc}"
        return out

    if list_item is None:
        out.outcome = Outcome.MISSING
        out.detail = "the item no longer exists in SharePoint — re-sync the catalogue"
        return out

    fields = list_item.get("fields") or {}
    current = _field(fields, proposal.field)
    current = str(current).strip() if current is not None else None
    out.current_value = current

    if current and current == proposal.proposed_value:
        out.outcome = Outcome.ALREADY_CORRECT
        out.detail = "SharePoint already holds this value"
        if not dry_run:
            repo.mark_proposal_written(proposal.asset_id, proposal.field)
        return out

    if current:
        out.outcome = Outcome.CONFLICT
        out.detail = (
            f"SharePoint holds {current!r} but the accepted proposal is "
            f"{proposal.proposed_value!r}. Nothing was written — someone set this "
            f"after the proposal was reviewed, so a human has to choose.")
        return out

    if dry_run:
        out.outcome = Outcome.WOULD_WRITE
        out.detail = f"would set {column} = {proposal.proposed_value!r}"
        return out

    try:
        client.update_list_item_fields(
            drive_id, source_item_id, {column: proposal.proposed_value},
            etag=list_item.get("eTag"))
    except GraphConcurrentEdit as exc:
        out.outcome = Outcome.CONFLICT
        out.detail = f"changed in SharePoint between our read and our write: {exc}"
        _record(repo, proposal, current, changed_by, Outcome.CONFLICT, str(exc))
        return out
    except GraphPermissionError:
        # A read-only grant, not a bad item. Nothing was written, so there is
        # nothing to record; the run aborts and reports it once.
        raise
    except GraphError as exc:
        out.detail = str(exc)
        _record(repo, proposal, current, changed_by, Outcome.FAILED, str(exc))
        return out

    # Attribution: the person who accepted the value, not whoever ran the job.
    # App-only writes show up in SharePoint as the application, so this log is
    # the only place the real author survives.
    _record(repo, proposal, current, changed_by, Outcome.WRITTEN, None)
    repo.mark_proposal_written(proposal.asset_id, proposal.field)

    # The value is NOT written into the mirror here. SharePoint owns it now, and
    # it returns through normal sync. Writing it locally would put a value in
    # the mirror that no sync produced — the exact drift the split prevents.
    out.outcome = Outcome.WRITTEN
    out.detail = f"set {column} = {proposal.proposed_value!r}"
    return out


def _record(repo, proposal, old_value: str | None, ran_by: str,
            status: str, error: str | None) -> None:
    author = proposal.decided_by or ran_by
    note = f" (pushed by {ran_by})" if proposal.decided_by and proposal.decided_by != ran_by else ""
    repo.record_metadata_edit(
        asset_id=proposal.asset_id, field=proposal.field,
        old_value=old_value, new_value=proposal.proposed_value,
        changed_by=f"{author}{note}", write_status=status, error=error,
    )


def backlog(repo) -> dict[str, Any]:
    """What a write-back run would consider, without calling Graph at all."""
    pending = _accepted_proposals(repo, limit=10_000)
    assets = {a.id: a for a in repo.list(AssetQuery(limit=5000)).items}
    writable = [p for p in pending
                if _looks_like_a_graph_id(
                    getattr(assets.get(p.asset_id), "source_item_id", None))]
    return {
        "accepted_awaiting_writeback": len(pending),
        "writable_now": len(writable),
        "blocked_until_synced": len(pending) - len(writable),
        "fields": sorted({p.field for p in pending}),
        "source_system": SOURCE_SYSTEM,
    }
