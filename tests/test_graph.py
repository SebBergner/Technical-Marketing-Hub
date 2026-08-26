"""Graph client and catalogue sync, exercised without credentials.

`httpx.MockTransport` plus an injected token provider means the whole path —
auth handling, throttling, paging, delta, the Sites.Selected diagnosis, sync
and write-back — is covered before IT delivers anything. When credentials do
arrive the remaining unknowns are the real column internal names, and nothing
else.

Payload shapes follow the Graph v1.0 reference for driveItem and listItem.
"""
from __future__ import annotations

import base64
import json

import httpx
import pytest

from backend.integrations.graph.client import (
    DeltaTokenExpired, GraphAuthError, GraphClient, GraphError, GraphPermissionError,
)
from backend.integrations.graph.sync import build_assets

SITE_URL = "https://ptccloud.sharepoint.com/sites/EXT-TDD"
SITE_ID = "ptccloud.sharepoint.com,guid-1,guid-2"
DRIVE_ID = "drive-abc"


def fake_token(roles=("Sites.Selected",)) -> str:
    """A JWT-shaped token carrying a roles claim.

    Shaped like the real thing because the client reads `roles` off it to tell
    "no permission consented" apart from "wrong site URL" — the two look
    identical from outside, and a shapeless token would skip that path.
    """
    def seg(obj):
        raw = base64.urlsafe_b64encode(json.dumps(obj).encode()).decode()
        return raw.rstrip("=")
    return f'{seg({"alg": "RS256"})}.{seg({"aud": "https://graph.microsoft.com", "roles": list(roles)})}.sig'


def client_for(handler, roles=("Sites.Selected",)) -> GraphClient:
    return GraphClient(
        tenant_id="t", client_id="c", client_secret="s", site_url=SITE_URL,
        transport=httpx.MockTransport(handler),
        token_provider=lambda: fake_token(roles),
    )


def folder(name, demo_type="Live Demo Kit", item_id=None, path="", **fields):
    payload = {
        "id": item_id or f"id-{name}",
        "name": name,
        "folder": {"childCount": 3},
        "webUrl": f"{SITE_URL}/Demo%20Catalog/{name}",
        "lastModifiedDateTime": "2025-07-21T10:00:00Z",
        "parentReference": {"path": f"/drives/{DRIVE_ID}/root:{path}"},
    }
    columns = {"Segment": "CAD", "Language": "English",
               "Product": "30;#Creo Parametric", **fields}
    if demo_type:
        columns["DemoType"] = demo_type
    payload["listItem"] = {"fields": columns}
    return payload


def file_item(name, path):
    return {
        "id": f"file-{name}",
        "name": name,
        "file": {"mimeType": "video/mp4"},
        "parentReference": {"path": f"/drives/{DRIVE_ID}/root:{path}"},
    }


# ─────────────────────────────────────────────────────────────────── auth
def test_bearer_token_is_attached():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"id": SITE_ID, "displayName": "TDD"})

    client_for(handler).resolve_site()
    assert seen["auth"] == f"Bearer {fake_token()}"


def test_401_is_reported_as_an_auth_problem():
    with pytest.raises(GraphAuthError):
        client_for(lambda r: httpx.Response(401, json={})).resolve_site()


# ──────────────────────── the Sites.Selected two-step trap (the big one)
def test_403_says_the_site_grant_is_probably_missing():
    """A valid token plus 403 on everything is the signature of step 2 being
    skipped. The error must say so, or a day gets lost debugging our code."""
    with pytest.raises(GraphPermissionError) as exc:
        client_for(lambda r: httpx.Response(403, json={})).resolve_site()

    message = str(exc.value)
    assert "Sites.Selected" in message
    assert "sites/{siteId}/permissions" in message


def test_verify_access_separates_bad_credentials_from_missing_grant():
    def bad_token():
        raise GraphAuthError("invalid_client: secret expired")

    client = GraphClient(tenant_id="t", client_id="c", client_secret="s",
                         site_url=SITE_URL,
                         transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
                         token_provider=bad_token)
    result = client.verify_access()
    assert result["token"]["ok"] is False
    assert "tenant id" in result["diagnosis"]
    assert "site" not in result, "must not continue past a token failure"


def test_verify_access_names_the_missing_consent_when_the_token_has_no_roles():
    """Measured on the real tenant 2026-08-26: IT created the app and issued a
    secret, but never added the Sites.Selected permission. The token is valid
    and every call 401s, which reads as a bad secret. Only the empty roles
    claim says otherwise, so the check must not blame the site URL."""
    result = client_for(lambda r: httpx.Response(401, json={}), roles=()).verify_access()

    assert result["token"]["ok"] is True
    assert result["granted_permissions"] == []
    assert "NO application permissions" in result["diagnosis"]
    assert "Grant admin consent" in result["diagnosis"]
    assert result["site"]["error"] == "not attempted",         "no point calling the site — it cannot succeed"


def test_granted_roles_survives_a_token_it_cannot_parse():
    """Never let introspection break a run; an unreadable token just reports
    nothing rather than raising."""
    client = GraphClient("t", "c", "s", token_provider=lambda: "not-a-jwt")
    assert client.granted_roles() == []


def test_verify_access_diagnoses_a_forbidden_site():
    result = client_for(lambda r: httpx.Response(403, json={})).verify_access()
    assert result["token"]["ok"] is True
    assert result["site"]["ok"] is False
    assert "step 2" in result["diagnosis"]


def test_verify_access_reports_read_only_when_write_is_absent():
    def handler(request):
        if request.url.path.endswith("/permissions"):
            return httpx.Response(200, json={"value": [{"roles": ["read"]}]})
        return httpx.Response(200, json={"id": SITE_ID, "displayName": "TDD",
                                         "webUrl": SITE_URL})

    result = client_for(handler).verify_access()
    assert result["permissions"]["roles"] == ["read"]
    assert "write-back will not" in result["diagnosis"]


def test_verify_access_confirms_a_full_grant():
    def handler(request):
        if request.url.path.endswith("/permissions"):
            return httpx.Response(200, json={"value": [{"roles": ["write"]}]})
        return httpx.Response(200, json={"id": SITE_ID, "webUrl": SITE_URL})

    assert "Fully configured" in client_for(handler).verify_access()["diagnosis"]


# ────────────────────────────────────────────────────────────── resolution
def test_site_url_is_parsed_into_a_graph_lookup():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        return httpx.Response(200, json={"id": SITE_ID, "displayName": "TDD"})

    site = client_for(handler).resolve_site()
    assert seen["path"] == "/v1.0/sites/ptccloud.sharepoint.com:/sites/EXT-TDD"
    assert site.site_id == SITE_ID


def test_find_drive_matches_by_name_case_insensitively():
    def handler(request):
        return httpx.Response(200, json={"value": [
            {"id": "d1", "name": "Documents"},
            {"id": DRIVE_ID, "name": "Demo Catalog"}]})

    client = client_for(handler)
    assert client.find_drive(SITE_ID, "demo catalog").drive_id == DRIVE_ID
    assert client.find_drive(SITE_ID, "Nope") is None


# ─────────────────────────────────────────────────────── paging & throttling
def test_next_link_is_followed():
    pages = [
        {"value": [{"id": "1"}], "@odata.nextLink": f"{'https://graph.microsoft.com/v1.0'}/page2"},
        {"value": [{"id": "2"}]},
    ]
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json=pages[len(calls) - 1])

    drives = client_for(handler).list_drives(SITE_ID)
    assert len(calls) == 2 and len(drives) == 2


def test_429_is_retried_honouring_retry_after(monkeypatch):
    monkeypatch.setattr("backend.integrations.graph.client.time.sleep", lambda _: None)
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(429, headers={"Retry-After": "1"}, json={})
        return httpx.Response(200, json={"id": SITE_ID})

    assert client_for(handler).resolve_site().site_id == SITE_ID
    assert len(calls) == 3


def test_403_is_never_retried(monkeypatch):
    """A permission failure is a state, not a transient fault."""
    monkeypatch.setattr("backend.integrations.graph.client.time.sleep", lambda _: None)
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(403, json={})

    with pytest.raises(GraphPermissionError):
        client_for(handler).resolve_site()
    assert len(calls) == 1


# ──────────────────────────────────────────────────────────────────── delta
def test_delta_collects_pages_and_returns_the_token():
    pages = [
        {"value": [{"id": "a"}],
         "@odata.nextLink": "https://graph.microsoft.com/v1.0/next"},
        {"value": [{"id": "b"}],
         "@odata.deltaLink": "https://graph.microsoft.com/v1.0/d?token=NEXT123"},
    ]
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json=pages[len(calls) - 1])

    page = client_for(handler).delta(DRIVE_ID)
    assert [i["id"] for i in page.items] == ["a", "b"]
    assert page.delta_token == "NEXT123"


def test_expired_delta_token_raises_so_the_caller_resyncs():
    """410 Gone is normal. Swallowing it makes sync silently stop working."""
    with pytest.raises(DeltaTokenExpired):
        client_for(lambda r: httpx.Response(410, json={})).delta(DRIVE_ID, token="old")


# ──────────────────────────────────────────────────────────────── write-back
def test_update_fields_sends_if_match():
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["if_match"] = request.headers.get("if-match")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ConsensusUUID": "uuid-1"})

    client_for(handler).update_fields(
        SITE_ID, "list-1", "item-1", {"ConsensusUUID": "uuid-1"}, etag="etag-9")

    assert seen["method"] == "PATCH"
    assert seen["if_match"] == "etag-9"
    assert seen["body"] == {"ConsensusUUID": "uuid-1"}


def test_412_explains_the_concurrent_edit():
    """SharePoint's own UI is a second writer; a stale overwrite must fail loudly."""
    with pytest.raises(GraphError, match="changed in SharePoint"):
        client_for(lambda r: httpx.Response(412, json={})).update_fields(
            SITE_ID, "l", "i", {"x": 1}, etag="stale")


def test_download_url_is_extracted():
    def handler(request):
        return httpx.Response(200, json={
            "id": "v1", "@microsoft.graph.downloadUrl": "https://cdn/tmp/video.mp4"})

    assert client_for(handler).download_url(DRIVE_ID, "v1") == "https://cdn/tmp/video.mp4"


# ────────────────────────────────────── sync mapping (the structural rule)
def test_only_top_level_folders_with_a_demo_type_become_assets():
    items = [
        folder("AAX LDK v.1"),
        folder("Nested Thing", path="/AAX LDK v.1"),        # depth > 0
        folder("No Type Here", demo_type=None),             # missing Demo Type
    ]
    assets, result = build_assets(items)

    assert [a.title for a in assets] == ["AAX LDK v.1"]
    assert result.skipped_no_demo_type == 1


def test_files_are_attributed_to_their_top_level_folder():
    items = [
        folder("AAX LDK v.1"),
        file_item("AAX Demo Video.mp4", "/AAX LDK v.1"),
        file_item("guide.docx", "/AAX LDK v.1/Documentation"),
        file_item("part.prt.1", "/AAX LDK v.1/Dataset/Models"),
    ]
    assets, result = build_assets(items)
    asset = assets[0]

    assert result.resources == 3
    assert asset.resource_count == 3
    assert asset.video_count == 1
    # CAD counted but not listed — 42% of the real catalogue is version files.
    assert asset.resource_counts["cad"] == 1
    assert not [r for r in asset.resources if r.kind.value == "cad"]
    assert asset.main_video == "AAX Demo Video.mp4"


def test_files_under_a_folder_with_no_demo_type_are_orphans():
    """295 top-level folders lack a Demo Type; their files must not be
    silently attached to some other asset."""
    items = [folder("Real Asset"), file_item("stray.mp4", "/Creo+ 12.0 PM Videos")]
    _, result = build_assets(items)
    assert result.orphan_files == 1
    assert result.resources == 0


def test_columns_map_through_shared_logic():
    items = [folder("Kit v.1", Product="30;#Creo Parametric;#42;#Windchill PDMLink",
                    Segment="IoT,PLM", Language="Chinese (People's Republic of China)")]
    asset = build_assets(items)[0][0]

    assert asset.products == ["Creo Parametric", "Windchill PDMLink"]
    assert asset.segment == "IoT"
    assert asset.rails == ["PLM"]          # extra segments become rails
    assert asset.language == "zh"


def test_customer_facing_comes_from_the_video_filenames():
    items = [
        folder("Kit A"),
        file_item("Kit A Demo - Internal Only.mp4", "/Kit A"),
        folder("Kit B", item_id="id-KitB"),
        file_item("Kit B Demo - Customer Facing.mp4", "/Kit B"),
    ]
    by_title = {a.title: a for a in build_assets(items)[0]}
    assert by_title["Kit A"].customer_facing is False
    assert by_title["Kit B"].customer_facing is True


def test_deleted_items_are_ignored():
    items = [folder("Gone"), {"id": "x", "name": "Gone", "folder": {},
                              "deleted": {"state": "deleted"},
                              "parentReference": {"path": f"/drives/{DRIVE_ID}/root:"}}]
    assets, _ = build_assets(items)
    assert len(assets) == 1
