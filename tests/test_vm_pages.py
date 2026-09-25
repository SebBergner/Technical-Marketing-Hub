"""VM pages: parsing, sealing credentials, relations, storage and the one door.

The fixtures are built by hand in the shape the real pages have (measured
2026-09-23: text web parts, Button, Quick links, File and media, Highlighted
content). No real credential appears anywhere in this file -- the secrets
below are made up, and each test that checks for leaks looks for them by
value, which is what would actually matter if one escaped.
"""
from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

import backend.oidc
from app import app
from backend.auth import APP_SERVICE_MARKER, AuthMode
from backend.config import settings
from backend.deps import get_repo
from backend.integrations.graph import vm_pages
from backend.integrations.graph.vm_pages import (
    Catalogue, build_vm_assets, parse_page, parse_supports_query, products_in_title,
    segment_in_title, version_in_title,
)
from backend.models import AssetType
from backend.repositories.base import AssetQuery
from backend.repositories.json_repo import JsonAssetRepository

OS_PASSWORD = "Zq7-made-up-OSpw"
DEMO_PASSWORD = "made_up_demo_1"
ADMIN_PASSWORD = "not-a-real-admin-pw"
SECRETS = (OS_PASSWORD, DEMO_PASSWORD, ADMIN_PASSWORD)

SITE = "/sites/EXT-TDD"


def text_part(html: str) -> dict:
    return {"@odata.type": "#microsoft.graph.textWebPart", "innerHtml": html}


def standard_part(title: str, texts: dict | None = None, links: dict | None = None,
                  properties: dict | None = None) -> dict:
    return {"@odata.type": "#microsoft.graph.standardWebPart", "data": {
        "title": title, "properties": properties or {},
        "serverProcessedContent": {
            "searchablePlainTexts": [{"key": k, "value": v} for k, v in (texts or {}).items()],
            "links": [{"key": k, "value": v} for k, v in (links or {}).items()],
        }}}


def layout(*parts) -> dict:
    return {"horizontalSections": [{"columns": [{"webparts": list(parts)}]}]}


ACD_LAYOUT = layout(
    text_part(
        "<p>This environment contains ACD 7.2.1 with Snowmobile data.</p>"
        "<h2>Live Demo Server</h2>"
        "<p>Usernames: tech, owner</p>"
        f"<p>Demo password: {DEMO_PASSWORD}</p>"
        "<p>Please view the Admin Credentials section for more.</p>"
        "<h2>Local VM Setup Steps</h2>"
        "<ul><li>Log into VM OS</li><li>username: Administrator</li>"
        f"<li>password: {OS_PASSWORD}</li><li>run ipconfig</li></ul>"
        f'<p><a href="ftp://ftp.example.ptc.com/acd.zip">Download from FTP</a></p>'
        f'<p><a href="{SITE}/Demo%20Catalog/Release%20Notes">All release notes</a></p>'
        "<h2>Installed Software</h2>"
        "<table><tr><th>Software</th><th>Version</th></tr>"
        "<tr><td>SQL Server</td><td>2019</td></tr></table>"
        "<h2>Admin Credentials</h2>"
        "<table><tr><th>Application</th><th>Username</th><th>Password</th></tr>"
        f"<tr><td>ACD</td><td>insadmin</td><td>{ADMIN_PASSWORD}</td></tr></table>"),
    standard_part("Button", {"label": "Create environment from PTC Cloud Portal template"},
                  {"linkUrl": "https://portal.ptc.io/ProvPortal/publicTemplates.action"}),
    standard_part("Quick links",
                  {"items[0].title": "Built from", "items[1].title": "Setup steps"},
                  {"baseUrl": SITE,
                   "items[0].sourceItem.url": f"{SITE}/SitePages/Virtual%20Machines/Windchill-13.aspx",
                   "items[1].sourceItem.url": "#local-vm-setup-steps"}),
    standard_part("File and media", {"title": "Release notes"},
                  {"serverRelativeUrl": f"{SITE}/Demo%20Catalog/Release%20Notes/ACD%207.2.1.pdf"}),
    standard_part("Highlighted content", properties={"query": {"advancedQueryText":
        'Path: "https://x/SitePages/Demo%20Catalog" \n'
        '(title:"Snowmobile - Arbortext Content Delivery - LDK") AND (Filetype:aspx) AND WORDS(LDK)'}}),
)


def public_json(parsed) -> str:
    return json.dumps([s.model_dump() for s in parsed.sections])


# ───────────────────────────────────────────────────────── parsing a page
def test_a_page_becomes_sections_in_reading_order():
    parsed = parse_page(ACD_LAYOUT)
    headings = [s.heading for s in parsed.sections]
    assert headings == [None, "Live Demo Server", "Local VM Setup Steps",
                        "Installed Software", "Admin Credentials"]
    assert parsed.sections[0].blocks[0].text.startswith("This environment contains")
    software = parsed.sections[3].blocks[0]
    assert software.kind == "table"
    assert software.rows == [["Software", "Version"], ["SQL Server", "2019"]]


def test_section_ids_are_unique_even_when_headings_repeat():
    parsed = parse_page(layout(text_part("<h2>Notes</h2><p>a</p><h2>Notes</h2><p>b</p>")))
    ids = [s.id for s in parsed.sections]
    assert len(ids) == len(set(ids))


def test_links_inside_text_survive_as_links_not_markup():
    setup = next(s for s in parse_page(ACD_LAYOUT).sections if s.heading == "Local VM Setup Steps")
    links = [l for b in setup.blocks for l in b.links]
    assert [(l.label, l.kind) for l in links] == [("Download from FTP", "download"),
                                                  ("All release notes", "demo_folder")]


def test_web_parts_become_actions_documents_and_relations():
    parsed = parse_page(ACD_LAYOUT)
    assert [(a.kind, a.url) for a in parsed.actions] == [
        ("cloud_portal", "https://portal.ptc.io/ProvPortal/publicTemplates.action")]
    assert [name for name, _ in parsed.documents] == ["ACD 7.2.1.pdf"]
    assert any("Windchill-13.aspx" in u for u in parsed.link_urls)
    assert parsed.supports_titles == ["Snowmobile - Arbortext Content Delivery - LDK"]


# ───────────────────────────────────────────────────── sealing credentials
def test_no_known_secret_survives_into_the_public_sections():
    public = public_json(parse_page(ACD_LAYOUT))
    for secret in SECRETS:
        assert secret not in public, secret


def test_every_secret_is_kept_where_a_signed_in_person_can_reach_it():
    secrets = json.dumps(parse_page(ACD_LAYOUT).secrets)
    for secret in SECRETS:
        assert secret in secrets, secret


def test_a_credentials_heading_seals_its_whole_section():
    parsed = parse_page(ACD_LAYOUT)
    creds = next(s for s in parsed.sections if s.heading == "Admin Credentials")
    assert creds.sealed
    assert all(b.sealed and not b.text and not b.rows for b in creds.blocks)
    assert creds.id in parsed.secrets["sections"]


def test_a_password_line_is_sealed_and_its_neighbours_are_not():
    setup = next(s for s in parse_page(ACD_LAYOUT).sections if s.heading == "Local VM Setup Steps")
    texts = [(b.text, b.sealed) for b in setup.blocks]
    assert ("username: Administrator", False) in texts
    assert ("run ipconfig", False) in texts
    assert sum(1 for _, sealed in texts if sealed) == 1


def test_mentioning_credentials_is_not_the_same_as_containing_one():
    """Sealing greedily is the rule, but a sentence pointing at the admin
    section is not itself secret, and hiding it would hide the pointer."""
    live = next(s for s in parse_page(ACD_LAYOUT).sections if s.heading == "Live Demo Server")
    visible = [b.text for b in live.blocks if not b.sealed]
    assert "Please view the Admin Credentials section for more." in visible


def test_a_table_whose_header_names_a_password_is_sealed_whole():
    """Under a neutral heading on purpose. The first version of this test used
    "Accounts overview", which the heading rule seals by itself -- so it
    passed with the header rule removed, and tested nothing (2026-09-23)."""
    parsed = parse_page(layout(text_part(
        "<h2>Services</h2>"
        "<table><tr><th>Service</th><th>User</th><th>Pass</th></tr>"
        "<tr><td>db</td><td>sa</td><td>hunter2-made-up</td></tr></table>")))
    assert "hunter2-made-up" not in public_json(parsed)


def test_a_secret_in_a_link_label_is_sealed_too():
    parsed = parse_page(layout(text_part(
        '<h2>Access</h2><p><a href="https://x.ptc.com">password is abc-made-up</a></p>')))
    assert "abc-made-up" not in public_json(parsed)


def test_the_first_pass_catches_everything_on_its_own(caplog):
    """The second pass is a backstop. If it ever has to act on real-shaped
    input, the first pass has a gap -- and the leak tests above would still
    pass, because the backstop covered for it. This is the test that notices."""
    with caplog.at_level("WARNING", logger="backend.integrations.graph.vm_pages"):
        parse_page(ACD_LAYOUT)
    assert "survived the first pass" not in caplog.text


def test_the_backstop_seals_what_the_first_pass_missed():
    from backend.models import VmBlock, VmSection
    sections = [VmSection(id="s", heading="Notes",
                          blocks=[VmBlock(kind="p", text=f"password {OS_PASSWORD}")])]
    secrets = {"sections": {}, "blocks": {}}
    assert vm_pages._assert_nothing_leaks(sections, secrets) == 1
    assert sections[0].blocks[0].sealed and sections[0].blocks[0].text is None
    assert OS_PASSWORD in json.dumps(secrets)


def test_the_count_of_sealed_things_is_public_so_the_ui_can_say_so():
    assert parse_page(ACD_LAYOUT).sealed_count == 3        # 2 lines + 1 section


# ─────────────────────────────────────────────── what a title can tell us
@pytest.mark.parametrize("title, version", [
    ("Windchill 13.1.4.1 - Virtual Machine", "13.1.4.1"),
    ("ALM (CB 3.3.0 RVS 13.5 Modeler 10.3 PV 7.3.0) - Virtual Machine", None),
    ("3rd Party CAD - PTC ONLY - Virtual Machine", None),
])
def test_a_version_only_when_the_title_has_exactly_one(title, version):
    assert version_in_title(title) == version


def test_products_come_from_the_title_or_not_at_all():
    known = {"Arbortext Content Delivery", "Windchill PDMLink", "Codebeamer"}
    assert products_in_title("Arbortext Content Delivery (ACD) 7.2.1", known)[0] == \
        "Arbortext Content Delivery"
    assert "Windchill" in products_in_title("Windchill 13.1.4.1 - Virtual Machine", known)
    assert "Codebeamer" in products_in_title("ALM (CB 3.3.0 RVS 13.5) - VM", known)
    assert products_in_title("3rd Party CAD - PTC ONLY - Virtual Machine", known) == []


def test_a_segment_only_when_the_title_says_it():
    assert segment_in_title("ALM (CB 3.3.0) - Virtual Machine") == "ALM"
    assert segment_in_title("Windchill 13.1.4.1 - Virtual Machine") is None


def test_a_supports_query_naming_a_slice_becomes_a_filter():
    titles, filters = parse_supports_query('(Segment:"PLM") AND (Filetype:aspx) AND WORDS(LDK)')
    assert titles == []
    assert [(f.label, f.segment, f.type) for f in filters] == [("Every PLM LDK", "PLM", AssetType.LDK)]


# ───────────────────────────────────────────── building assets from pages
CATALOGUE = [
    {"id": "snowmobile-acd-ldk", "type": "ldk", "title": "Snowmobile - Arbortext Content Delivery - LDK",
     "products": ["Arbortext Content Delivery"],
     "web_url": "https://x/Demo Catalog/Snowmobile - Arbortext Content Delivery - LDK"},
    {"id": "snowmobile-editor-ldk", "type": "ldk", "title": "Snowmobile - Authoring In Arbortext Editor LDK v.2.0",
     "products": ["Arbortext Editor"], "web_url": "https://x/Demo Catalog/Snowmobile - Authoring"},
    {"id": "snowmobile-creo-ldk", "type": "ldk", "title": "Snowmobile - Creo Design LDK",
     "products": ["Creo Parametric"], "web_url": "https://x/Demo Catalog/Snowmobile - Creo"},
    {"id": "snowmobile-x", "type": "ldk", "title": "Snowmobile - Another One", "products": ["Creo Parametric"],
     "web_url": "https://x/Demo Catalog/Snowmobile - Another"},
    {"id": "release-notes", "type": "ldk", "title": "Release Notes", "products": [],
     "web_url": "https://x/Demo Catalog/Release Notes",
     "resources": [{"name": "ACD 7.2.1.pdf", "item_id": "ITEM-RN-1", "kind": "document"}]},
]


def vm_page(pid: str, title: str, modified: str, url_name: str, description: str = "") -> dict:
    return {"id": pid, "title": title, "lastModifiedDateTime": modified, "description": description,
            "webUrl": f"https://ptccloud.sharepoint.com{SITE}/SitePages/Virtual%20Machines/{url_name}",
            "lastModifiedBy": {"user": {"displayName": "Someone"}}}


def build(pages, layouts=None):
    return build_vm_assets(pages, layouts or {}, {}, Catalogue.build(CATALOGUE))


def test_relations_carry_how_we_know_them():
    pages = [vm_page("p1", "ACD 7.2.1 with Snowmobile Demo Data", "2026-09-15T00:00:00Z", "ACD.aspx"),
             vm_page("p2", "Windchill 13 - Virtual Machine", "2026-09-09T00:00:00Z", "Windchill-13.aspx")]
    assets, _, result = build(pages, {"p1": ACD_LAYOUT})
    acd = next(a for a in assets if a.title.startswith("ACD"))
    assert [(r.title, r.via) for r in acd.vm.related_vms] == [("Windchill 13 - Virtual Machine", "page")]
    vias = {r.asset_id: r.via for r in acd.vm.related_demos}
    assert vias["snowmobile-acd-ldk"] == "supports"
    assert vias.get("snowmobile-editor-ldk") == "inferred"       # same dataset, same family
    assert "snowmobile-creo-ldk" not in vias                     # same dataset, other family
    assert "release-notes" not in vias                           # documents, not a demo


def test_a_document_the_catalogue_mirrors_can_be_previewed_in_the_hub():
    assets, _, result = build([vm_page("p1", "ACD 7.2.1", "2026-09-15T00:00:00Z", "ACD.aspx")],
                              {"p1": ACD_LAYOUT})
    doc = assets[0].vm.documents[0]
    assert (doc.asset_id, doc.item_id) == ("release-notes", "ITEM-RN-1")
    assert result.documents_previewable == 1


def test_of_two_pages_with_one_title_the_newer_is_kept():
    pages = [vm_page("old", "ACD 7.2.0.5", "2024-07-12T00:00:00Z", "a.aspx"),
             vm_page("new", "ACD 7.2.0.5", "2026-09-15T00:00:00Z", "b.aspx")]
    assets, _, result = build(pages)
    assert [a.source_item_id for a in assets] == ["new"]
    assert result.duplicates_dropped == 1


def test_a_description_carrying_a_password_is_dropped():
    assets, _, _ = build([vm_page("p1", "VM", "2026-01-01T00:00:00Z", "v.aspx",
                                  description=f"Default password {OS_PASSWORD}")])
    assert assets[0].description is None


def test_a_description_sharepoint_cut_short_is_completed_from_the_page():
    cut = "This environment contains ACD 7.2.1 with Snow"
    assets, _, _ = build([vm_page("p1", "ACD 7.2.1", "2026-09-15T00:00:00Z", "ACD.aspx",
                                  description=cut)], {"p1": ACD_LAYOUT})
    assert assets[0].description == "This environment contains ACD 7.2.1 with Snowmobile data."
    # One the page does not continue is left as the author wrote it.
    assets, _, _ = build([vm_page("p1", "ACD 7.2.1", "2026-09-15T00:00:00Z", "ACD.aspx",
                                  description="Something else")], {"p1": ACD_LAYOUT})
    assert assets[0].description == "Something else"


def test_a_button_whose_text_is_its_own_address_gets_a_readable_label():
    url = "https://portal.ptc.io/ProvPortal/publicTemplates.action"
    parsed = parse_page(layout(standard_part("Button", {"label": url}, {"linkUrl": url})))
    assert [(a.label, a.kind) for a in parsed.actions] == [("Open the PTC Cloud Portal", "cloud_portal")]


def test_a_vm_is_not_marked_customer_facing_and_says_when_it_is_ptc_only():
    assets, _, _ = build([vm_page("p1", "3rd Party CAD - PTC ONLY - Virtual Machine",
                                  "2026-06-05T00:00:00Z", "cad.aspx")])
    assert assets[0].customer_facing is False
    assert assets[0].vm.ptc_only and assets[0].tags == ["PTC only"]


def test_a_page_that_cannot_be_parsed_is_reported_not_fatal(monkeypatch):
    def boom(_):
        raise ValueError("unexpected canvas")
    monkeypatch.setattr(vm_pages, "parse_page", boom)
    assets, _, result = build([vm_page("p1", "VM", "2026-01-01T00:00:00Z", "v.aspx")])
    assert assets == [] and result.errors


# ──────────────────────────────────────────────────── storage and search
@pytest.fixture()
def repo(tmp_path):
    store = JsonAssetRepository(str(tmp_path))
    from backend.models import Asset
    store.replace_source_rows([Asset(**{k: v for k, v in r.items() if k != "resources"},
                                     resources=r.get("resources") or [])
                               for r in CATALOGUE], "sharepoint")
    assets, secrets, _ = build_vm_assets(
        [vm_page("p1", "ACD 7.2.1 with Snowmobile Demo Data", "2026-09-15T00:00:00Z", "ACD.aspx")],
        {"p1": ACD_LAYOUT}, {}, Catalogue.build(CATALOGUE))
    store.replace_source_rows(assets, "vm_pages")
    store.replace_vm_secrets(secrets)
    return store


def vm_id(repo):
    return repo.list(AssetQuery(types=["vm"])).items[0].id


def test_secrets_are_stored_outside_the_mirror_the_catalogue_reads(repo):
    mirror = os.path.join(repo.mirror_dir, "vm_pages.json")
    private = os.path.join(repo.mirror_dir, "private", "vm_credentials.json")
    public = open(mirror, encoding="utf-8").read()
    for secret in SECRETS:
        assert secret not in public
        assert secret in open(private, encoding="utf-8").read()
    # The private file is not read as catalogue rows.
    # (Release Notes is in CATALOGUE but never listed -- see test_listing.py.)
    assert repo.list(AssetQuery(limit=100)).total == len(CATALOGUE) - 1 + 1


def test_the_detail_carries_the_page_but_never_a_secret(repo):
    asset = repo.get(vm_id(repo))
    assert asset.vm and asset.vm.sections
    dumped = asset.model_dump_json()
    for secret in SECRETS:
        assert secret not in dumped


def test_search_reaches_a_vms_public_text_but_not_its_secrets(repo):
    assert repo.list(AssetQuery(text="SQL Server", types=["vm"])).total == 1
    for secret in SECRETS:
        assert repo.list(AssetQuery(text=secret)).total == 0, secret


def test_a_demo_knows_which_vms_run_it(repo):
    ldk = repo.get("snowmobile-acd-ldk")
    assert [(u.title, u.via) for u in ldk.used_by_vms] == [
        ("ACD 7.2.1 with Snowmobile Demo Data", "supports")]


def test_list_responses_stay_light(repo):
    """The page content is detail-only; a grid of 1,000 cards must not carry it."""
    summary = repo.list(AssetQuery(types=["vm"])).items[0]
    assert "vm" not in summary.model_dump()


# ────────────────────────────────────────────────────────── the one door
@pytest.fixture()
def client(repo):
    app.dependency_overrides[get_repo] = lambda: repo
    try:
        with TestClient(app, base_url="http://localhost", follow_redirects=False) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_repo, None)


def test_a_developer_on_a_laptop_sees_them(client, repo, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", AuthMode.DISABLED.value)
    monkeypatch.delenv(APP_SERVICE_MARKER, raising=False)
    body = client.get(f"/api/vms/{vm_id(repo)}/credentials").json()
    assert OS_PASSWORD in json.dumps(body) and ADMIN_PASSWORD in json.dumps(body)


def test_auth_left_off_on_app_service_does_not_publish_them(client, repo, monkeypatch):
    """The one misconfiguration that would otherwise hand every password to
    anyone with the URL: AUTH_MODE=disabled on Azure."""
    monkeypatch.setattr(settings, "auth_mode", AuthMode.DISABLED.value)
    monkeypatch.setenv(APP_SERVICE_MARKER, "technical-marketing-hub")
    assert client.get(f"/api/vms/{vm_id(repo)}/credentials").status_code == 401


def test_easyauth_without_a_signed_in_person_does_not_show_them(client, repo, monkeypatch):
    """Today's Azure configuration: easyauth mode, platform sign-in off."""
    monkeypatch.setattr(settings, "auth_mode", AuthMode.EASYAUTH.value)
    assert client.get(f"/api/vms/{vm_id(repo)}/credentials").status_code == 401


class _FakeMsal:
    def initiate_auth_code_flow(self, scopes, redirect_uri=None, **_):
        return {"state": "s", "nonce": "n", "code_verifier": "v" * 43,
                "redirect_uri": redirect_uri, "scope": scopes,
                "auth_uri": "https://login.microsoftonline.com/t/authorize"}

    def acquire_token_by_auth_code_flow(self, flow, params):
        return {"id_token_claims": {"oid": "o-1", "tid": "t", "name": "Person"}}


def test_someone_signed_in_sees_them(client, repo, monkeypatch):
    for name, value in {"auth_mode": AuthMode.OIDC.value, "oidc_tenant_id": "t",
                        "oidc_client_id": "c", "oidc_client_secret": "s",
                        "oidc_redirect_uri": "", "custom_domain": ""}.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(backend.oidc, "_msal_app", lambda: _FakeMsal())
    assert client.get(f"/api/vms/{vm_id(repo)}/credentials").status_code == 401
    client.get("/login")
    client.get("/auth/callback", params={"code": "c", "state": "s"})
    body = client.get(f"/api/vms/{vm_id(repo)}/credentials").json()
    assert OS_PASSWORD in json.dumps(body)


def test_a_non_vm_asset_has_no_credentials(client, repo, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", AuthMode.DISABLED.value)
    monkeypatch.delenv(APP_SERVICE_MARKER, raising=False)
    assert client.get("/api/vms/snowmobile-acd-ldk/credentials").status_code == 404


def test_the_ordinary_detail_endpoint_never_carries_them(client, repo, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", AuthMode.DISABLED.value)
    monkeypatch.delenv(APP_SERVICE_MARKER, raising=False)
    body = client.get(f"/api/assets/{vm_id(repo)}").text
    for secret in SECRETS:
        assert secret not in body


# ──────────────────────────────────────────────── riding along with the sync
def test_a_vm_sync_failure_does_not_fail_the_catalogue_sync(monkeypatch):
    from backend.routers import graph as graph_router

    class Client:
        def resolve_site(self, url):
            return object()

    def boom(*_):
        raise RuntimeError("pages API unavailable")
    monkeypatch.setattr(vm_pages, "sync_vm_pages", boom)
    outcome = graph_router._sync_vm_pages(Client(), repo=None)
    assert outcome == {"ok": False, "error": "pages API unavailable"}
