"""Demo request intake.

The endpoint that originates data rather than reflecting it, so the things
worth holding still are about not losing a submission and not lying about
where it got to.

Graph is never called here: `build_fields` is the part with the awkward
shapes, and it is pure.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from backend.integrations.graph.requests_list import build_fields
from backend.models import AssetRequest, AssetType


def make(**kw) -> AssetRequest:
    base = dict(asset_type=AssetType.VIDEO, id="REQ-1",
                submitted_at="2026-09-01T00:00:00Z", status="new")
    base.update(kw)
    return AssetRequest(**base)


def test_multi_choice_columns_carry_the_type_as_a_sibling_key():
    """Verified against the live list on 2026-09-01.

    Graph wants `"Col@odata.type": "Collection(Edm.String)"` NEXT TO the
    value. Nesting it inside the value, which is the shape the docs suggest
    elsewhere, returns 400 invalidRequest — and so does a bare list.
    """
    fields = build_fields(
        make(distribution_channels=["eStore", "Event / trade show"],
             starting_materials=["Have materials"]),
        request_id="REQ-1")

    assert fields["DistributionChannels@odata.type"] == "Collection(Edm.String)"
    assert fields["DistributionChannels"] == ["eStore", "Event / trade show"]
    assert fields["StartingMaterials@odata.type"] == "Collection(Edm.String)"


def test_multi_value_text_columns_are_joined_not_listed():
    """Products was managed metadata and is single-line text now, so a list
    would be written as its Python repr if it were passed straight through."""
    fields = build_fields(make(products=["Windchill", "ThingWorx"]),
                          request_id="REQ-1")
    assert fields["Products"] == "Windchill; ThingWorx"
    assert isinstance(fields["Products"], str)


def test_the_title_says_what_the_request_is():
    """SharePoint shows Title as the item's name. An id there would make the
    list unreadable at a glance, and blank is not allowed."""
    fields = build_fields(make(products=["Creo"]), request_id="REQ-1")
    assert "VIDEO" in fields["Title"] and "Creo" in fields["Title"]


def test_every_request_starts_unclaimed():
    assert build_fields(make(), request_id="REQ-1")["Status"] == "New"


def test_customer_involvement_is_mapped_to_words_a_reader_understands():
    """"footage" and "story" are the form's internal values, not labels."""
    for internal, shown in [("none", "None"), ("footage", "Customer footage"),
                            ("story", "Customer story")]:
        fields = build_fields(make(customer_involvement=internal), request_id="R")
        assert fields["CustomerInvolvement"] == shown


def test_a_date_only_column_still_needs_an_instant():
    fields = build_fields(make(needed_by=date(2026, 10, 15)), request_id="R")
    assert fields["NeededBy"] == "2026-10-15T00:00:00Z"


def test_blank_answers_are_left_out_rather_than_written_as_empty():
    """A column the requester skipped should keep the list's own default, not
    be stamped with an empty string that looks like a deliberate answer."""
    fields = build_fields(make(products=["Creo"]), request_id="R")
    for absent in ("Brief", "NamedCustomer", "CompellingEvent", "Notes"):
        assert absent not in fields


def test_the_request_survives_sharepoint_being_unreachable(tmp_path):
    """The local append happens first and independently, so an outage costs
    visibility and never the submission."""
    from backend.repositories.json_repo import JsonAssetRepository

    repo = JsonAssetRepository(str(tmp_path))
    record = make(products=["Creo"])
    repo.save_request(record)

    assert [r.id for r in repo.unsynced_requests()] == ["REQ-1"]

    repo.mark_request_synced("REQ-1", "42")
    assert repo.unsynced_requests() == []

    rows = [json.loads(l) for l in
            (tmp_path / "owned" / "requests.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1, "marking synced must rewrite the line, not append a second"
    assert rows[0]["sharepoint_item_id"] == "42" and rows[0]["synced"] is True


def test_the_store_is_append_only_across_submissions(tmp_path):
    from backend.repositories.json_repo import JsonAssetRepository
    repo = JsonAssetRepository(str(tmp_path))
    for n in range(3):
        repo.save_request(make(id=f"REQ-{n}", products=["Creo"]))
    assert len(repo.unsynced_requests()) == 3


# ───────────────────────────────────────────────────────────── attachments
def test_a_filename_can_never_become_a_path():
    """A name is a name here, never a path. The only reason one would contain
    a separator is to try to be one."""
    from backend.integrations.graph.requests_list import safe_attachment_name

    for hostile in ["../../etc/passwd", r"..\..\windows\system32\x.txt",
                    "/absolute/brief.docx", "....//brief.docx"]:
        clean = safe_attachment_name(hostile)
        assert "/" not in clean and "\\" not in clean
        assert not clean.startswith(".")


def test_sharepoint_illegal_characters_are_replaced_not_passed_on():
    from backend.integrations.graph.requests_list import safe_attachment_name
    clean = safe_attachment_name('a"b*c:d<e>f?g|h#i%j.txt')
    assert not any(ch in clean for ch in '"*:<>?|#%')


def test_an_empty_name_still_yields_a_usable_one():
    from backend.integrations.graph.requests_list import safe_attachment_name
    assert safe_attachment_name("") == "attachment"
    assert safe_attachment_name("...") == "attachment"


def test_executables_are_refused_whatever_they_claim_to_be():
    """An intake form open to the whole org, writing into a shared library, is
    a distribution channel for whatever it will store."""
    from backend.integrations.graph.requests_list import attachment_rejection

    for name in ["payload.exe", "run.BAT", "script.ps1", "installer.msi",
                 "thing.jar", "x.sh"]:
        assert attachment_rejection(name, 100), f"{name} should be refused"

    for name in ["brief.docx", "screens.png", "deck.pptx", "notes.md", "a.pdf"]:
        assert attachment_rejection(name, 100) is None, f"{name} should be allowed"


def test_the_size_limit_is_the_one_graph_can_actually_take():
    """Graph's simple upload tops out at 4 MB; past that it needs a resumable
    session. Refusing with a reason beats a truncated file nobody notices."""
    from backend.integrations.graph.requests_list import (
        MAX_ATTACHMENT_BYTES, attachment_rejection)

    assert attachment_rejection("big.mp4", MAX_ATTACHMENT_BYTES + 1)
    assert attachment_rejection("ok.mp4", MAX_ATTACHMENT_BYTES) is None
    assert attachment_rejection("empty.txt", 0), "an empty file is a mistake"
