"""Personal GXC links (B10 step 2, Liwei 2026-11-02/03).

Outside the GXC group a PTC person opens a GXC video only through someone's
personal link, which grants it to them -- the page and files open, nothing
lists it. Partners never. Every open through another person's link is
recorded; revoking a person's links ends every access that came through
them, down the chain.
"""
from __future__ import annotations

import json

from backend import access, gxc_shares
from tests.test_auth import easyauth_headers
from tests.test_gxc import ADMIN, MEMBER, PARTNER, STAFF, client, ids, repo  # noqa: F401

OTHER = "other@ptc.com"
VIDEO = "gxc-lamborghini"


def page(client, who, token=None, asset_id=VIDEO):
    params = {"s": token} if token else {}
    return client.get("/api/assets/" + asset_id, params=params, headers=easyauth_headers(who))


def own_token(client, who):
    r = page(client, who)
    assert r.status_code == 200, r.text
    return r.json()["share_token"]


def test_the_gxc_group_gets_a_personal_token_that_stays_the_same(client):
    a = own_token(client, MEMBER)
    assert a and len(a) == gxc_shares.TOKEN_LENGTH
    assert own_token(client, MEMBER) == a
    assert own_token(client, ADMIN) != a, "one per person"
    assert MEMBER.split("@")[0] not in a
    cards = client.get("/api/assets", headers=easyauth_headers(MEMBER)).json()["items"]
    assert next(c for c in cards if c["id"] == VIDEO)["share_token"] == a, "card links too"


def test_outside_the_group_only_a_working_link_opens_it(client):
    a = own_token(client, MEMBER)
    assert page(client, STAFF).status_code == 404
    forged = a[:-1] + ("a" if a[-1] != "a" else "b")
    assert page(client, STAFF, forged).status_code == 404
    assert page(client, STAFF, a, asset_id="bobcat").status_code == 200, "not a GXC video"
    r = page(client, STAFF, a)
    assert r.status_code == 200
    body = r.json()
    assert body["gxc_link_only"] and body["web_url"] is None, "no Open in SharePoint"
    assert body["share_token"] and body["share_token"] != a, "their own token now"
    assert page(client, STAFF).status_code == 200, "the grant stands without a token"


def test_a_granted_video_is_listed_nowhere(client):
    page(client, STAFF, own_token(client, MEMBER))
    assert ids(client, STAFF) == {"bobcat"}
    assert ids(client, STAFF, q="Lamborghini") == set()
    assert ids(client, STAFF, published=["2026"]) <= {"bobcat"}
    related = client.get("/api/assets/bobcat/related", headers=easyauth_headers(STAFF)).json()
    assert VIDEO not in json.dumps(related)
    r = client.get(f"/api/assets/{VIDEO}/files/I-1/download", follow_redirects=False,
                   headers=easyauth_headers(STAFF))
    assert r.status_code != 404, "its files are reachable, as its page is"


def test_partners_never_even_with_a_link(client):
    assert page(client, PARTNER, own_token(client, MEMBER)).status_code == 404


def test_links_chain_and_every_open_is_recorded(client):
    a = own_token(client, MEMBER)
    b = page(client, STAFF, a).json()["share_token"]
    assert page(client, OTHER, b).status_code == 200
    page(client, ADMIN, a)                     # the GXC group: recorded, nothing granted
    opens = gxc_shares.opens()
    assert [(o["who"], o["via"], o["granted"]) for o in opens] == [
        (STAFF, MEMBER, True), (OTHER, STAFF, True), (ADMIN, MEMBER, False)]
    assert page(client, MEMBER, a).status_code == 200
    assert len(gxc_shares.opens()) == 3, "opening your own link is not an open"


def test_revoking_ends_everything_that_came_through_the_links(client):
    a = own_token(client, MEMBER)
    b = page(client, STAFF, a).json()["share_token"]
    page(client, OTHER, b)
    out = gxc_shares.revoke(MEMBER, VIDEO, "user:" + ADMIN)
    assert {(g["who"], g["via"]) for g in out["grants_revoked"]} == {(STAFF, MEMBER), (OTHER, STAFF)}
    assert page(client, STAFF).status_code == 404
    assert page(client, OTHER).status_code == 404
    assert page(client, OTHER, b).status_code == 404, "the middle link died with its grant"
    assert page(client, STAFF, a).status_code == 404, "the revoked link itself"
    fresh = own_token(client, MEMBER)
    assert fresh != a
    assert page(client, STAFF, fresh).status_code == 200, "a new link from them works"


def test_revoking_everything_a_person_sent(client):
    a = own_token(client, MEMBER)
    page(client, STAFF, a)
    gxc_shares.revoke(MEMBER, None, "user:" + ADMIN)
    assert page(client, STAFF).status_code == 404
    assert own_token(client, MEMBER) != a


def test_leaving_the_group_keeps_the_links_working(client):
    a = own_token(client, MEMBER)
    group = next(g for g in access.load_state()["groups"] if g["name"] == "GXC")
    access.update_group(group["id"], "test", members=[PARTNER])
    assert page(client, MEMBER).status_code == 404, "they no longer see it themselves"
    assert page(client, STAFF, a).status_code == 200


def test_who_sees_and_revokes_the_records(client):
    a = own_token(client, MEMBER)
    page(client, STAFF, a)
    access.create_group("Owners", "", ["view_admin"], ["owner@ptc.com"], "t")
    url = "/api/admin/gxc-links"
    assert client.get(url, headers=easyauth_headers("owner@ptc.com")).status_code == 403
    r = client.get(url, params={"person": STAFF}, headers=easyauth_headers(ADMIN))
    assert r.status_code == 200
    data = r.json()
    assert data["grants"][0]["title"] == "Lamborghini walkthrough"
    assert data["opens"][0]["via"] == MEMBER
    csv = client.get(url + ".csv", headers=easyauth_headers(ADMIN))
    assert csv.status_code == 200 and STAFF in csv.text
    revoke = lambda who: client.post(url + "/revoke", json={"sender": MEMBER},  # noqa: E731
                                     headers=easyauth_headers(who))
    assert revoke("owner@ptc.com").status_code == 403
    assert revoke(ADMIN).status_code == 200
    assert page(client, STAFF).status_code == 404


def test_the_shared_admin_sign_in_never_sees_gxc():
    assert access.Perm.VIEW_GXC.value not in access.ADMIN_SESSION_PERMS


def test_hub_activity_leaves_out_views_through_a_link(client, repo):
    """Liwei, 2026-11-03: written as usual, never shown as Hub activity."""
    page(client, STAFF, own_token(client, MEMBER))
    repo.record_usage_event("view", VIDEO, user=STAFF)
    repo.record_usage_event("view", VIDEO, user=MEMBER)
    assert len([e for e in repo.usage_events() if e.get("asset_id") == VIDEO]) == 2
    kept = gxc_shares.without_link_views(repo.usage_events())
    assert [e["user"] for e in kept if e.get("asset_id") == VIDEO] == [MEMBER]
    seen = client.get("/api/reports/activity", headers=easyauth_headers(ADMIN)).json()
    assert [c["views"] for c in seen["content"] if c["asset_id"] == VIDEO] == [1]


# ───────────────────────────────── GXC group only (Liwei 11/02, Elio 11/04)
def test_gxc_group_only_opens_for_the_group_alone(client):
    a = own_token(client, MEMBER)
    page(client, STAFF, a)                                   # granted before the mark
    put = lambda who, on: client.put(f"/api/admin/gxc-group-only/{VIDEO}",  # noqa: E731
                                     json={"on": on}, headers=easyauth_headers(who))
    assert put(STAFF, True).status_code in (401, 403)
    r = put(ADMIN, True)
    assert r.status_code == 200 and r.json()["grants_ended"] == 1
    assert page(client, STAFF).status_code == 404, "the earlier grant ended"
    assert page(client, OTHER, a).status_code == 404, "a link sent before does nothing"
    body = page(client, MEMBER).json()
    assert body["gxc_group_only"] and body["share_token"] is None, "no link to share"
    card = next(c for c in client.get("/api/assets", headers=easyauth_headers(MEMBER)).json()[
        "items"] if c["id"] == VIDEO)
    assert card["gxc_group_only"] and card["share_token"] is None
    assert gxc_shares.opens()[-1]["who"] == STAFF, "the blocked opens are not recorded"
    listing = client.get("/api/admin/gxc-group-only", headers=easyauth_headers(ADMIN)).json()
    assert [m["asset_id"] for m in listing["marked"]] == [VIDEO]
    assert put(ADMIN, False).status_code == 200
    assert page(client, STAFF).status_code == 404, "unmarking brings no access back"
    assert page(client, MEMBER).json()["share_token"], "links can be shared again"


def test_only_a_gxc_video_can_be_marked(client):
    r = client.put("/api/admin/gxc-group-only/bobcat", json={"on": True},
                   headers=easyauth_headers(ADMIN))
    assert r.status_code == 404
