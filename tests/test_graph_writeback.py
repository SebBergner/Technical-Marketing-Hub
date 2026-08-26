"""Write-back: accepted proposals -> SharePoint columns.

This is the only code in the Portal that changes a system of record, so the
tests are weighted towards what it must REFUSE to do rather than what it does.
The one that matters most is `test_an_existing_different_value_is_never_
overwritten` — everything else is bookkeeping by comparison.

No credentials involved: `httpx.MockTransport` plus an injected token provider
covers the whole path, including the failure modes we cannot produce on demand
against a live tenant (a concurrent edit, a missing column, a read-only grant).
"""
from __future__ import annotations

import json

import httpx
import pytest

from backend.integrations.graph.client import (
    GraphClient, GraphConcurrentEdit, GraphFieldUnknown,
)
from backend.integrations.graph.writeback import (
    Outcome, backlog, resolve_column, write_back,
)
from backend.models import (
    Asset, AssetType, MetadataProposal, ProposalOrigin, ProposalState,
)
from backend.repositories.json_repo import JsonAssetRepository

SITE_URL = "https://ptccloud.sharepoint.com/sites/EXT-TDD"
SITE_ID = "ptccloud.sharepoint.com,guid-1,guid-2"
DRIVE_ID = "drive-abc"
ITEM_ID = "01ABCDEFGHIJKLMNOP"          # Graph driveItem id: no slashes
UUID = "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0"
CURATOR = "liwchen@ptc.com"


# ───────────────────────────────── fake tenant ─────────────────────────────
def make_handler(*, columns=("ConsensusUUID",), current=None, etag="etag-1",
                 patch_status=200, patch_body=None, item_found=True, seen=None):
    """A minimal SharePoint that answers the four calls write-back makes."""
    seen = seen if seen is not None else {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path

        if path.endswith(f"/sites/{SITE_URL.split('/sites/')[1]}") or ":/sites/" in path:
            return httpx.Response(200, json={
                "id": SITE_ID, "displayName": "EXT-TDD", "webUrl": SITE_URL})

        if path.endswith(f"/sites/{SITE_ID}/drives"):
            return httpx.Response(200, json={
                "value": [{"id": DRIVE_ID, "name": "Demo Catalog"}]})

        if path.endswith(f"/drives/{DRIVE_ID}/list"):
            return httpx.Response(200, json={
                "id": "list-1",
                "columns": [{"name": c, "displayName": c} for c in columns]})

        if path.endswith(f"/items/{ITEM_ID}/listItem"):
            if not item_found:
                return httpx.Response(404, json={})
            fields = {"Title": "A Kit"}
            if current:
                fields["ConsensusUUID"] = current
            return httpx.Response(200, json={
                "id": "7", "eTag": etag, "fields": fields})

        if path.endswith(f"/items/{ITEM_ID}/listItem/fields"):
            seen["method"] = request.method
            seen["if_match"] = request.headers.get("if-match")
            seen["body"] = json.loads(request.content)
            return httpx.Response(patch_status, json=patch_body or {"ConsensusUUID": UUID})

        return httpx.Response(404, json={"error": {"message": f"unexpected {path}"}})

    return handler, seen


def client_for(handler) -> GraphClient:
    return GraphClient(tenant_id="t", client_id="c", client_secret="s",
                       site_url=SITE_URL, transport=httpx.MockTransport(handler),
                       token_provider=lambda: "fake-token")


@pytest.fixture()
def repo(tmp_path):
    store = JsonAssetRepository(str(tmp_path))
    store.replace_source_rows([
        Asset(id="a-kit", type=AssetType.LDK, title="A Kit", source_item_id=ITEM_ID),
        # Imported from the spreadsheet, so its "id" is a path, not a Graph id.
        Asset(id="seeded", type=AssetType.LDK, title="Seeded",
              source_item_id="sites/EXT-TDD/Demo Catalog/Seeded"),
    ], "sharepoint")
    return store


def accept(repo, asset_id="a-kit", value=UUID, by="elio@ptc.com"):
    repo.save_proposals([MetadataProposal(
        asset_id=asset_id, asset_title=asset_id, field="consensus_uuid",
        proposed_value=value, confidence=0.9, origin=ProposalOrigin.CONSENSUS,
        evidence="strong title match")])
    repo.decide_proposal(asset_id, "consensus_uuid", ProposalState.ACCEPTED.value, by)


def outcomes(result) -> dict[str, str]:
    return {i.asset_id: i.outcome for i in result.items}


# ══════════════════════════ the refusal that matters ═══════════════════════
def test_an_existing_different_value_is_never_overwritten(repo):
    """Someone typed a UUID into SharePoint after the proposal was reviewed.

    Overwriting it would destroy a human's work silently, and because app-only
    writes are attributed to the application, SharePoint's version history
    would not even name a person to ask. Refusing is the whole point.
    """
    accept(repo)
    handler, seen = make_handler(current="a-different-uuid-typed-by-hand")

    result = write_back(client_for(handler), repo, CURATOR, dry_run=False)

    assert outcomes(result) == {"a-kit": Outcome.CONFLICT}
    assert "body" not in seen, "no PATCH may be sent when a value already exists"
    assert "a-different-uuid-typed-by-hand" in result.items[0].detail

    # And the proposal stays accepted, so it comes back for a human to resolve
    # rather than quietly vanishing from the backlog.
    stored = repo.list_proposals(state="accepted").items
    assert [p.asset_id for p in stored] == ["a-kit"]


def test_a_concurrent_edit_between_read_and_write_is_a_conflict(repo):
    """The ETag closes the last gap: an edit landing in the split second
    between our read and our write must fail, not win a race."""
    accept(repo)
    handler, _ = make_handler(patch_status=412)

    result = write_back(client_for(handler), repo, CURATOR, dry_run=False)

    assert outcomes(result) == {"a-kit": Outcome.CONFLICT}
    assert repo.list_proposals(state="written").total == 0
    assert repo.metadata_edits()[0]["write_status"] == Outcome.CONFLICT


# ══════════════════════════════ the happy path ═════════════════════════════
def test_an_empty_column_is_written_with_the_etag(repo):
    accept(repo)
    handler, seen = make_handler(etag="etag-7")

    result = write_back(client_for(handler), repo, CURATOR, dry_run=False)

    assert outcomes(result) == {"a-kit": Outcome.WRITTEN}
    assert seen["method"] == "PATCH"
    assert seen["body"] == {"ConsensusUUID": UUID}
    assert seen["if_match"] == "etag-7", "a write without If-Match can clobber"


def test_writing_marks_the_proposal_written_without_losing_who_accepted_it(repo):
    accept(repo, by="elio@ptc.com")
    handler, _ = make_handler()

    write_back(client_for(handler), repo, changed_by=CURATOR, dry_run=False)

    written = repo.list_proposals(state="written").items
    assert len(written) == 1
    assert written[0].decided_by == "elio@ptc.com", \
        "the job runner must not overwrite who authorised the value"
    assert written[0].written_at is not None


def test_the_audit_trail_names_the_person_not_the_application(repo):
    """App-only Graph writes appear in SharePoint as the app, so this log is
    the only surviving record of who was actually responsible."""
    accept(repo, by="elio@ptc.com")
    handler, _ = make_handler()

    write_back(client_for(handler), repo, changed_by=CURATOR, dry_run=False)

    entry = repo.metadata_edits()[0]
    assert "elio@ptc.com" in entry["changed_by"]
    assert CURATOR in entry["changed_by"], "who ran the job is still worth keeping"
    assert entry["old_value"] is None and entry["new_value"] == UUID
    assert entry["write_status"] == Outcome.WRITTEN


def test_the_written_value_is_not_copied_into_the_mirror(repo):
    """SharePoint owns it now; it must arrive back through sync.

    Writing it locally would put a value in the mirror that no sync produced —
    which is precisely the drift the mirror/owned split exists to prevent.
    """
    accept(repo)
    handler, _ = make_handler()

    write_back(client_for(handler), repo, CURATOR, dry_run=False)

    assert repo.get("a-kit").consensus_uuid is None


# ═════════════════════════════════ dry run ═════════════════════════════════
def test_dry_run_is_the_default_and_writes_nothing(repo):
    accept(repo)
    handler, seen = make_handler()

    result = write_back(client_for(handler), repo, CURATOR)     # no dry_run given

    assert result.dry_run is True
    assert outcomes(result) == {"a-kit": Outcome.WOULD_WRITE}
    assert "body" not in seen
    assert repo.list_proposals(state="accepted").total == 1


def test_dry_run_still_reports_conflicts(repo):
    """The point of a dry run is to surface trouble before writing, so a
    conflict must show up there rather than only on the live run."""
    accept(repo)
    handler, _ = make_handler(current="something-else")

    result = write_back(client_for(handler), repo, CURATOR, dry_run=True)

    assert outcomes(result) == {"a-kit": Outcome.CONFLICT}
    assert result.as_dict()["conflicts"], "conflicts are surfaced separately"


# ═══════════════════════════════ preconditions ═════════════════════════════
def test_a_missing_column_aborts_before_touching_any_item(repo):
    """A column that does not exist fails identically for all 450 items.

    Stopping on the first discovery turns fifty confusing failures into one
    clear instruction.
    """
    accept(repo)
    handler, seen = make_handler(columns=("Title", "Segment"))

    result = write_back(client_for(handler), repo, CURATOR, dry_run=False)

    assert result.aborted and "ConsensusUUID" in result.aborted
    assert result.items == []
    assert "body" not in seen


def test_the_real_internal_column_name_is_used_not_our_guess(repo):
    """SharePoint mangles names it generated itself. Writing needs the exact
    one, so it is read from the list rather than assumed."""
    accept(repo)
    handler, seen = make_handler(columns=("Consensus_x0020_UUID",))

    result = write_back(client_for(handler), repo, CURATOR, dry_run=False)

    assert result.columns == {"consensus_uuid": "Consensus_x0020_UUID"}
    assert seen["body"] == {"Consensus_x0020_UUID": UUID}


def test_columns_are_matched_by_display_name_too():
    handler, _ = make_handler(columns=())

    def with_display(request):
        if request.url.path.endswith(f"/drives/{DRIVE_ID}/list"):
            return httpx.Response(200, json={"columns": [
                {"name": "OData__x0043_UUID", "displayName": "Consensus UUID"}]})
        return handler(request)

    assert resolve_column(client_for(with_display), DRIVE_ID,
                          "consensus_uuid") == "OData__x0043_UUID"


def test_an_asset_that_never_came_from_graph_is_skipped_with_a_reason(repo):
    """Spreadsheet-imported assets carry a path, not a Graph id. There is
    nothing to PATCH until a sync has run."""
    accept(repo, asset_id="seeded")
    handler, seen = make_handler()

    result = write_back(client_for(handler), repo, CURATOR, dry_run=False)

    assert outcomes(result) == {"seeded": Outcome.NOT_SYNCED}
    assert "/api/graph/sync" in result.items[0].detail
    assert "body" not in seen


def test_an_item_deleted_in_sharepoint_is_reported_not_crashed(repo):
    accept(repo)
    handler, _ = make_handler(item_found=False)

    result = write_back(client_for(handler), repo, CURATOR, dry_run=False)

    assert outcomes(result) == {"a-kit": Outcome.MISSING}


def test_a_value_already_correct_in_sharepoint_leaves_the_backlog(repo):
    """Someone filled it in by hand. That is a success, not a conflict, and
    the proposal should stop appearing in the backlog."""
    accept(repo)
    handler, seen = make_handler(current=UUID)

    result = write_back(client_for(handler), repo, CURATOR, dry_run=False)

    assert outcomes(result) == {"a-kit": Outcome.ALREADY_CORRECT}
    assert "body" not in seen, "no need to write a value that is already there"
    assert repo.list_proposals(state="written").total == 1


# ═════════════════════════════ scope and safety ════════════════════════════
def test_only_accepted_proposals_are_written(repo):
    """Pending means nobody has looked at it, and rejected means somebody
    said no. Neither may reach SharePoint."""
    repo.save_proposals([
        MetadataProposal(asset_id="a-kit", field="consensus_uuid",
                         proposed_value=UUID, origin=ProposalOrigin.CONSENSUS),
    ])
    handler, seen = make_handler()

    result = write_back(client_for(handler), repo, CURATOR, dry_run=False)

    assert result.considered == 0 and "body" not in seen


def test_a_proposal_for_an_unlisted_field_is_ignored(repo):
    """A proposal's field name is data. Data must not be able to choose which
    SharePoint column gets written."""
    repo.save_proposals([MetadataProposal(
        asset_id="a-kit", field="title", proposed_value="Renamed",
        origin=ProposalOrigin.MANUAL)])
    repo.decide_proposal("a-kit", "title", ProposalState.ACCEPTED.value, CURATOR)
    handler, seen = make_handler()

    result = write_back(client_for(handler), repo, CURATOR, dry_run=False)

    assert result.considered == 0 and "body" not in seen


def test_the_limit_caps_one_run(repo):
    """A first live run must not be able to touch the whole catalogue."""
    repo.replace_source_rows(
        [Asset(id=f"kit-{n}", type=AssetType.LDK, title=f"Kit {n}",
               source_item_id=ITEM_ID) for n in range(4)], "sharepoint")
    for n in range(4):
        accept(repo, asset_id=f"kit-{n}")

    result = write_back(client_for(make_handler()[0]), repo, CURATOR, limit=2)

    assert result.considered == 2
    assert len(result.items) == 2


def test_one_bad_item_does_not_stop_the_others(repo):
    """A partial success is the normal case for a bulk write."""
    repo.replace_source_rows([
        Asset(id="a-kit", type=AssetType.LDK, title="A Kit", source_item_id=ITEM_ID),
        Asset(id="seeded", type=AssetType.LDK, title="Seeded",
              source_item_id="sites/EXT-TDD/Demo Catalog/Seeded"),
    ], "sharepoint")
    accept(repo, asset_id="a-kit")
    accept(repo, asset_id="seeded")
    handler, _ = make_handler()

    result = write_back(client_for(handler), repo, CURATOR, dry_run=False)

    assert outcomes(result) == {"a-kit": Outcome.WRITTEN, "seeded": Outcome.NOT_SYNCED}


# ═════════════════════════════════ backlog ═════════════════════════════════
def test_backlog_separates_writable_from_blocked_without_calling_graph(repo):
    accept(repo, asset_id="a-kit")
    accept(repo, asset_id="seeded")

    report = backlog(repo)
    assert report["accepted_awaiting_writeback"] == 2
    assert report["writable_now"] == 1
    assert report["blocked_until_synced"] == 1


def test_a_read_only_grant_aborts_instead_of_failing_every_item(repo):
    """403 on PATCH after reads succeeded means the grant is read-only. That
    fails identically for all 450 items, so it stops the run and names the fix."""
    repo.replace_source_rows(
        [Asset(id=f"kit-{n}", type=AssetType.LDK, title=f"Kit {n}",
               source_item_id=ITEM_ID) for n in range(3)], "sharepoint")
    for n in range(3):
        accept(repo, asset_id=f"kit-{n}")
    handler, _ = make_handler(patch_status=403)

    result = write_back(client_for(handler), repo, CURATOR, dry_run=False)

    assert result.aborted and "read-only" in result.aborted
    assert len(result.items) == 0, "it must stop, not grind through the rest"


# ═══════════════════════════════ client level ══════════════════════════════
def test_the_client_names_the_setup_fix_for_an_unknown_column():
    def handler(request):
        return httpx.Response(400, json={"error": {
            "message": "Field 'ConsensusUUID' is not recognized."}})

    with pytest.raises(GraphFieldUnknown, match="check_graph.py"):
        client_for(handler).update_list_item_fields(DRIVE_ID, ITEM_ID, {"x": "1"})


def test_412_is_its_own_error_so_callers_can_treat_it_as_an_outcome():
    """A concurrent edit is a legitimate result, not a fault, and callers need
    to tell it apart from a genuine failure."""
    with pytest.raises(GraphConcurrentEdit, match="changed in SharePoint"):
        client_for(lambda r: httpx.Response(412, json={})).update_list_item_fields(
            DRIVE_ID, ITEM_ID, {"x": "1"}, etag="stale")
