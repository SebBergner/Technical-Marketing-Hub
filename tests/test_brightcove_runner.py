"""The Brightcove migration CLI's write path, against a mocked Graph.

Pinned here are the Phase 0 findings that fail SILENTLY when got wrong
(docs/brightcove-migration-plan.md §9): the content type goes on the listItem,
not in fields; the note field takes "Label|Guid", never "-1;#..."; hidden
columns need `hidden` in $select; term paging must not loop forever. Also the
order that makes a re-run safe: the Brightcove ID is written only after the
video is in.
"""
from __future__ import annotations

import itertools
import json
import os

import httpx
import pytest

from backend.config import settings
from backend.integrations.graph import migration_writer as w
from backend.integrations.graph.client import GraphClient
from backend.services import brightcove_runner as run

SITE_URL = "https://ptccloud.sharepoint.com/sites/EXT-TDD"
SITE_ID = "site-1"
DRIVE, LIST = "drive-test", "list-test"
DEMO_CT = "0x0120D520-demo-test"
NOTE = "gd5821201d3e49e6b7226b0306116d32"
CREO, WC = "0f90d5b6-creo", "245d9426-wc"


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    for name in ("graph_tenant_id", "graph_client_id", "graph_client_secret"):
        monkeypatch.setattr(settings, name, "")
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "migration_brightcove_library", "Gallery_Brightcove")


#: Options the fake library offers for the choice columns added for the sheet.
FAKE_OPTIONS = {"HubProducts": ["Windchill", "Creo", "Creo Parametric", "Codebeamer"],
                "VideoType": ["Technical Overview", "Technical Walkthrough", "Presenter Support",
                              "Technical Teaser", "Other"],
                "VideoSubtype": ["Feature", "Solution", "Customer", "Release", "N/A"],
                "Gallery": ["PTC Gallery", "GXC Gallery"]}


def columns(hidden_requested: bool, video=True):
    cols = [{"name": n, "displayName": n} for n in w.REQUIRED_COLUMNS
            if n not in ("Demo_x0020_Type", "Segment") and n not in FAKE_OPTIONS]
    cols += [{"name": n, "displayName": n, "choice": {"choices": o}} for n, o in FAKE_OPTIONS.items()]
    cols.append({"name": "Demo_x0020_Type", "displayName": "Demo Type", "choice": {
        "choices": ["Live Demo Kit", "Virtual Demo Kit"] + (["Video"] if video else [])}})
    cols.append({"name": "Segment", "displayName": "Segment", "choice": {
        "choices": ["ALM", "AR", "CAD", "IoT", "PLM", "SCO", "SLM"]}})
    if hidden_requested:           # Graph's real behaviour: no `hidden` in $select, no hidden columns
        cols.append({"name": NOTE, "displayName": "Product_0", "hidden": True})
    return cols


class FakeGraph:
    """Records every request; serves just enough of Graph for the write path."""

    def __init__(self, library="Gallery_Brightcove_Test", existing=(), video=True):
        self.library, self.existing, self.video = library, list(existing), video
        self.calls: list[tuple[str, str, object]] = []
        self.ids = itertools.count(1)       # thread-safe: parallel runs use this fake

    def handler(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        body = json.loads(request.content) if request.content else None
        self.calls.append((method, path, body))
        if path.endswith("/drives"):
            return httpx.Response(200, json={"value": [{"id": DRIVE, "name": self.library}]})
        if path.endswith(f"/drives/{DRIVE}/list"):
            return httpx.Response(200, json={"id": LIST})
        if path.endswith(f"/lists/{LIST}/columns"):
            wants_hidden = "hidden" in (request.url.params.get("$select") or "")
            return httpx.Response(200, json={"value": columns(wants_hidden, self.video)})
        if path.endswith(f"/lists/{LIST}/contentTypes"):
            return httpx.Response(200, json={"value": [
                {"id": DEMO_CT, "name": "Demo", "documentSet": {"shouldPrefixNameToFile": True}}]})
        if path.endswith(f"/drives/{DRIVE}/root/children") and method == "GET":
            return httpx.Response(200, json={"value": self.existing})
        if path.endswith(f"/drives/{DRIVE}/root/children") and method == "POST":
            return httpx.Response(201, json={"id": f"folder-{next(self.ids)}", "name": body["name"],
                                             "webUrl": f"{SITE_URL}/x"})
        if path.endswith("/createUploadSession"):
            return httpx.Response(200, json={"uploadUrl": "https://upload.example/session-1"})
        if path.endswith("/listItem") and method == "GET":
            return httpx.Response(200, json={"id": "3", "@odata.etag": '"etag-1"'})
        if path.endswith("/listItem") and method == "PATCH":
            return httpx.Response(200, json={"id": "3"})
        if path.endswith("/listItem/fields"):
            return httpx.Response(200, json=body)
        if "/sites/" in path:
            return httpx.Response(200, json={"id": SITE_ID, "webUrl": SITE_URL})
        return httpx.Response(404)

    def client(self) -> GraphClient:
        return GraphClient(tenant_id="t", client_id="c", client_secret="s", site_url=SITE_URL,
                           transport=httpx.MockTransport(self.handler),
                           token_provider=lambda: "x.e30.sig")


class FakeUploader:
    """An upload session: accepts chunks, can start at an offset, can be gone."""

    def __init__(self, size: int, start_at: int = 0, gone: bool = False):
        self.size, self.received, self.gone = size, start_at, gone
        self.puts: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers, "never send our token to the upload URL"
        if self.gone:
            return httpx.Response(404)
        if request.method == "GET":
            return httpx.Response(200, json={"nextExpectedRanges": [f"{self.received}-"]})
        rng = request.headers["content-range"]
        self.puts.append(rng)
        start = int(rng.split()[1].split("-")[0])
        assert start == self.received, f"chunk {rng} does not continue at {self.received}"
        self.received += len(request.content)
        if self.received >= self.size:
            return httpx.Response(201, json={"id": "file-1", "name": "clip.mp4", "size": self.size})
        return httpx.Response(202, json={"nextExpectedRanges": [f"{self.received}-"]})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def target(fake: FakeGraph) -> w.LibraryTarget:
    return w.LibraryTarget.resolve(fake.client(), fake.library)


TERMS = w.TermIndex({"creo parametric": ("Creo Parametric", CREO),
                     "windchill aerospace & defense": ("Windchill Aerospace ＆ Defense", WC)})


# ─────────────────────────────────────────────────────────────── the target
def test_the_demo_catalog_is_never_a_target():
    with pytest.raises(w.MigrationTargetError, match="never a migration target"):
        w.LibraryTarget.resolve(FakeGraph().client(), "Demo Catalog", allow_production=True)


def test_the_production_library_needs_an_explicit_flag():
    fake = FakeGraph(library="Gallery_Brightcove")
    with pytest.raises(w.MigrationTargetError, match="production"):
        w.LibraryTarget.resolve(fake.client(), "Gallery_Brightcove")
    assert fake.calls == [], "refused before a single request"
    assert w.LibraryTarget.resolve(fake.client(), "Gallery_Brightcove",
                                   allow_production=True).drive_id == DRIVE


def test_resolve_asks_for_hidden_columns_and_finds_the_note_field():
    t = target(FakeGraph())
    assert (t.product_note_field, t.demo_content_type_id) == (NOTE, DEMO_CT)
    assert "PLM" in t.segment_choices


def test_a_library_without_the_video_choice_is_not_ready():
    with pytest.raises(w.MigrationTargetError, match='"Video" choice'):
        target(FakeGraph(video=False))


# ─────────────────────────────────────────────────────────────── terms
def test_term_paging_stops_when_a_page_repeats():
    """Measured 2026-09-28: page 1 holds every term, then an endless
    nextLink repeats the same few. A plain loop hung for 23 minutes."""
    served = []

    def handler(request):
        served.append(1)
        return httpx.Response(200, json={
            "value": [{"id": "t1", "labels": [{"name": "Creo Parametric"}]}],
            "@odata.nextLink": "https://graph.microsoft.com/v1.0/sites/s/termStore/sets/x/terms?p=2"})

    client = GraphClient(tenant_id="t", client_id="c", client_secret="s", site_url=SITE_URL,
                         transport=httpx.MockTransport(handler), token_provider=lambda: "x.e30.sig")
    index = w.TermIndex.load(client, SITE_ID, "set-1")
    assert len(served) == 2
    assert index.get("creo parametric ") == ("Creo Parametric", "t1")


def test_the_note_value_never_carries_the_minus_one_prefix():
    assert w.note_value([("Creo Parametric", CREO), ("Windchill PDMLink", WC)]) == \
        f"Creo Parametric|{CREO};Windchill PDMLink|{WC}"


def test_a_label_matches_after_normalising_but_the_stored_label_is_written():
    assert TERMS.get("Windchill Aerospace & Defense") == ("Windchill Aerospace ＆ Defense", WC)


# ─────────────────────────────────────────────────────────────── manifest
#: The manifest header these tests' rows are written in. Pinned here rather
#: than taken from run.COLUMNS, which grows as columns are added.
BASE_HEADER = ("brightcove_id", "title", "description", "segments", "products", "customer_facing",
               "contains_audio", "original_publish_date", "gallery_url", "source", "filename")


def write_manifest(tmp_path, rows, header=BASE_HEADER):
    path = tmp_path / "m.csv"
    lines = [",".join(header)] + [",".join(r) for r in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def row(bcid="111", title="Polaris AR", segments="PLM;CAD", products="Creo Parametric",
        cf="no", audio="yes", date="2019-05-14", source="clip.mp4", filename=""):
    return [bcid, title, "A demo", segments, products, cf, audio, date,
            "https://gallery.example/111", source, filename]


def test_a_manifest_reports_every_problem_without_stopping(tmp_path):
    path = write_manifest(tmp_path, [
        row(),
        row(bcid="222", title="Second", cf="", date="14/05/2019"),
        row(bcid="111", title="Duplicate"),
        row(bcid="333", title="Fourth", source="notes.txt"),
    ])
    records = run.load_manifest(path)
    run.validate(records, ["ALM", "CAD", "PLM"], TERMS)
    assert records[0].problems == []
    assert "customer_facing is empty" in records[1].problems
    assert any("YYYY-MM-DD" in p for p in records[1].problems)
    assert any("repeats row 2" in p for p in records[2].problems)
    assert any("not a video" in p for p in records[3].problems)


def test_different_videos_with_one_title_get_their_publish_date(tmp_path):
    """Liwei, 2026-09-30: a shared title is told apart by the upload date on
    the end. V29 (2) had 3 such pairs. Case-insensitive, like SharePoint."""
    records = run.load_manifest(write_manifest(tmp_path, [
        row(bcid="1", title="Creo Simulation Live", date="2024-02-16"), row(bcid="2", title="Other"),
        row(bcid="3", title="creo simulation live", date="2026-06-05")]))
    run.validate(records, ["PLM", "CAD"], TERMS)
    assert records[0].title == "Creo Simulation Live (2024-02-16)"
    assert records[2].title == "creo simulation live (2026-06-05)"
    assert records[0].problems == records[1].problems == records[2].problems == []
    assert records[1].title == "Other"


def test_the_same_date_too_adds_the_brightcove_id(tmp_path):
    records = run.load_manifest(write_manifest(tmp_path, [
        row(bcid="1", title="Twin", date="2024-02-16"), row(bcid="2", title="Twin", date="2024-02-16")]))
    run.validate(records, ["PLM", "CAD"], TERMS)
    assert [r.title for r in records] == ["Twin (2024-02-16) (1)", "Twin (2024-02-16) (2)"]
    assert all(r.problems == [] for r in records)


def test_one_video_twice_is_not_renamed_but_reported(tmp_path):
    records = run.load_manifest(write_manifest(tmp_path, [row(bcid="1", title="Same"),
                                                          row(bcid="1", title="Same")]))
    run.validate(records, ["PLM", "CAD"], TERMS)
    assert records[1].title == "Same"
    assert any("repeats row 2" in p for p in records[1].problems)
    assert any("same folder name" in p for p in records[0].problems)


def test_current_is_written_only_where_the_library_has_the_column(tmp_path):
    header = BASE_HEADER + ("current",)
    records = run.load_manifest(write_manifest(tmp_path, [row() + ["no"], row(bcid="2") + ["maybe"]],
                                               header=header))
    assert records[0].current is False
    assert any("current 'maybe'" in p for p in records[1].problems)
    assert "Current_x0020_Version" not in run.fields_for(records[0])
    assert run.fields_for(records[0], {"current": "Current_x0020_Version"})["Current_x0020_Version"] is False


def test_unknown_values_are_reported_not_forced(tmp_path):
    records = run.load_manifest(write_manifest(tmp_path, [
        row(segments="PLM;Robotics", products="Creo Parametrics")]))
    run.validate(records, ["PLM", "CAD"], TERMS)
    assert any("'Robotics'" in p for p in records[0].problems)
    assert any("'Creo Parametrics'" in p for p in records[0].problems)


def test_the_plan_sorts_new_existing_conflict_and_invalid(tmp_path):
    records = run.load_manifest(write_manifest(tmp_path, [
        row(bcid="1", title="New One"), row(bcid="2", title="Already Here"),
        row(bcid="3", title="Name Taken"), row(bcid="4", title="Bad", cf="maybe")]))
    status = run.plan(records, existing={"2": {}}, names_in_use={"name taken"})
    assert status == {"1": "new", "2": "existing", "3": "conflict", "4": "invalid"}


# ─────────────────────────────────────────────────────────────── the write path
def test_one_video_end_to_end_in_the_proven_order(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x" * 700_000)
    records = run.load_manifest(write_manifest(tmp_path, [row(source=str(video))]))
    fake, up = FakeGraph(), FakeUploader(size=700_000)
    t = target(fake)
    log = run.BatchLog.new("upload", t.name, "m.csv", planned=1)
    fake.calls.clear()

    run.migrate_one(fake.client(), t, TERMS, records[0], log, uploader=up.client(),
                    chunk_size=320 * 1024, say=lambda _: None)

    writes = [(m_, p.rsplit("/", 2)[-2:], b) for m_, p, b in fake.calls if m_ != "GET"]
    create, content_type, session, fields, note = writes
    assert create[2]["@microsoft.graph.conflictBehavior"] == "fail"
    assert content_type[0] == "PATCH" and content_type[2] == {"contentType": {"id": DEMO_CT}}
    assert session[1][-1] == "createUploadSession"
    # metadata strictly after the upload, and the Brightcove ID only there
    assert fields[2]["BrightcoveID"] == "111"
    assert fields[2]["Segment@odata.type"] == "Collection(Edm.String)"
    assert fields[2]["Customer_x0020_Facing"] is False
    assert "Product" not in fields[2]
    assert note[2] == {NOTE: f"Creo Parametric|{CREO}"}
    assert up.puts == ["bytes 0-327679/700000", "bytes 327680-655359/700000",
                       "bytes 655360-699999/700000"]
    assert log.item("111")["status"] == "done"
    assert json.load(open(log.path))["counts"] == {"done": 1}


def test_an_interrupted_upload_resumes_where_graph_left_off(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x" * 700_000)
    records = run.load_manifest(write_manifest(tmp_path, [row(source=str(video))]))
    fake, up = FakeGraph(), FakeUploader(size=700_000, start_at=327_680)
    t = target(fake)
    log = run.BatchLog.new("upload", t.name, "m.csv", planned=1)
    log.set_item("111", status="uploading", folder_id="folder-9",
                 upload_url="https://upload.example/session-1")
    fake.calls.clear()

    run.migrate_one(fake.client(), t, TERMS, records[0], log, uploader=up.client(),
                    chunk_size=320 * 1024, say=lambda _: None)

    assert not [c for c in fake.calls if c[1].endswith("/root/children")], "no second folder"
    assert up.puts[0].startswith("bytes 327680-")
    assert log.item("111")["status"] == "done"


def test_an_expired_session_starts_again_rather_than_failing(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x" * 1000)
    records = run.load_manifest(write_manifest(tmp_path, [row(source=str(video))]))
    fake = FakeGraph()
    t = target(fake)
    gone, fresh = FakeUploader(1000, gone=True), FakeUploader(1000)
    calls = {"n": 0}

    def handler(request):             # first session gone, the new one works
        calls["n"] += 1
        return (gone if calls["n"] == 1 else fresh).handler(request)

    log = run.BatchLog.new("upload", t.name, "m.csv", planned=1)
    log.set_item("111", status="uploading", folder_id="folder-9",
                 upload_url="https://upload.example/old")
    run.migrate_one(fake.client(), t, TERMS, records[0], log,
                    uploader=httpx.Client(transport=httpx.MockTransport(handler)),
                    say=lambda _: None)
    assert any(p.endswith("/createUploadSession") for _, p, _ in fake.calls)
    assert log.item("111")["status"] == "done"


def test_the_batch_log_is_what_the_migration_page_reads(tmp_path):
    from backend.services import brightcove_migration as bc
    log = run.BatchLog.new("upload", "Gallery_Brightcove_Test", "m.csv", planned=476)
    log.set_item("111", status="done")
    log.set_item("222", status="failed", error="boom")
    log.finish()
    listed = bc.list_batches()[0]
    assert listed["counts"] == {"done": 1, "failed": 1}
    assert bc.plan_total([listed]) == 476
    assert os.path.dirname(log.path) == bc.batches_dir()


# ─────────────────────────────────── the columns added for Seb's sheet (§13)
CHOICES = {"Segment": ("ALM", "CAD", "PLM"),
           "HubProducts": ("Windchill", "Creo", "Creo Parametric", "Codebeamer"),
           "VideoType": ("Technical Overview", "Technical Walkthrough", "Presenter Support",
                         "Technical Teaser", "Other"),
           "VideoSubtype": ("Feature", "Solution", "Customer", "Release", "N/A"),
           "Gallery": ("PTC Gallery", "GXC Gallery")}
FULL = ("brightcove_id", "title", "segments", "hub_products", "customer_facing", "video_type",
        "video_subtype", "named_customer", "gallery", "gallery_section", "long_description", "source")


def test_new_columns_are_validated_against_the_librarys_own_options(tmp_path):
    path = write_manifest(tmp_path, [
        ["1", "Good", "PLM", "Windchill;Creo Parametric", "yes", "Technical Overview", "Feature",
         "Vestas", "PTC Gallery", "PLM - All", "Long text", "c.mp4"],
        ["2", "Bad", "PLM", "Windchill AI;creo", "yes", "Other/Unclear", "Feature",
         "", "Partner Gallery", "", "", "c.mp4"],
    ], header=FULL)
    records = run.load_manifest(path)
    run.validate(records, CHOICES, TERMS)
    good, bad = records
    assert good.problems == []
    assert any("'Windchill AI' is not a HubProducts option" in p for p in bad.problems)
    assert any("'creo' is not a HubProducts option" in p for p in bad.problems), "case matters"
    assert any("'Other/Unclear' is not a VideoType option" in p for p in bad.problems)
    assert any("'Partner Gallery' is not a Gallery option" in p for p in bad.problems)


def test_product_terms_come_from_hub_products_only_where_a_term_matches_exactly(tmp_path):
    records = run.load_manifest(write_manifest(tmp_path, [
        ["1", "T", "PLM", "Windchill;Creo Parametric", "yes", "", "", "", "", "", "", "c.mp4"]],
        header=FULL))
    run.validate(records, CHOICES, TERMS)
    assert records[0].products == ["Creo Parametric"]      # "Windchill" is no term (§13)


def test_the_new_columns_are_written_in_the_shapes_sharepoint_takes(tmp_path):
    records = run.load_manifest(write_manifest(tmp_path, [
        ["1", "T", "PLM", "Windchill;Creo", "no", "Presenter Support", "Customer", "Hill Helicopters",
         "GXC Gallery", "Hill Helicopters", "The long one.", "c.mp4"]], header=FULL))
    f = run.fields_for(records[0])
    assert f["HubProducts@odata.type"] == "Collection(Edm.String)"
    assert f["HubProducts"] == ["Windchill", "Creo"]
    assert (f["VideoType"], f["VideoSubtype"], f["NamedCustomer"], f["Gallery"],
            f["GallerySection"], f["LongDescription"]) == (
        "Presenter Support", "Customer", "Hill Helicopters", "GXC Gallery", "Hill Helicopters",
        "The long one.")


def test_folder_names_are_safe_and_keep_what_sharepoint_allows():
    assert w.safe_folder_name("Windchill Aerospace & Defense: Overview") == \
        "Windchill Aerospace & Defense - Overview"
    assert w.safe_folder_name("Co-Create 3D: Part 2") == "Co-Create 3D - Part 2"
    assert w.safe_folder_name("PLM / CAD Demo?") == "PLM - CAD Demo"
