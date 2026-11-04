"""Personal links to GXC videos (B10 step 2, Liwei 2026-11-02/03).

A GXC video is for the GXC group. Anyone else at PTC opens one only through a
link somebody gave them, and every such link is personal: it carries its
sender's token (`#/asset/gxc-...?s=<token>`), so the Hub knows who passed it
on. The first time B opens A's link, B is *granted* that video (B may see it,
via A); B's own page then shows B's own token, and B may pass it on in turn.
Partners never: a token does nothing for them.

Decisions this carries (Liwei, 2026-11-03, "都按建议"):

* A token is the same for the same person and video, and is never stored:
  `<code><mac>`, where `code` is the sender's random six-character code
  (owned/gxc_share_people.json -- no name, no address in the link) and
  `mac` an HMAC of (code, video, generation) under a key derived from
  GXC_ID_KEY. A changed character fails the HMAC; another slot's key makes
  other tokens.
* No expiry. An administrator revokes everything a person sent (their code
  is replaced) or what they sent for one video (its generation goes up).
  Revoking cascades: every grant made through the revoked links, and so
  every link those people sent on for that video, stops working.
* Someone leaving the GXC group keeps their links working; only revoking
  stops them.
* A grant stands without a token: B opening the video again later, from
  history, is still B.
* Every open through somebody else's token is recorded, the GXC group's too,
  so the whole chain can be read (owned/gxc_opens.jsonl). Kept like the
  usage history: no expiry.

**GXC group only** (Liwei 2026-11-02; Elio 2026-11-04 agreed the scope:
the three Lamborghini videos in GXC Video, nothing outside it): a GXC video
so marked on Admin opens for the GXC group alone. No personal link, no
Share Internally; a link sent before does nothing, and marking it ends the
grants already made (recorded as a revocation). owned/gxc_group_only.json.

The grant is enforced where GXC already is: `deps.get_repo` hands the
repository the videos granted to the caller, and json_repo keeps them out
of every list -- page, files, thumbnail and downloads open; nothing lists.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading

from backend.config import settings
from backend.tables import utcnow

log = logging.getLogger(__name__)

PEOPLE_FILE = "gxc_share_people.json"
STATE_FILE = "gxc_share_state.json"
GRANTS_FILE = "gxc_grants.json"
OPENS_FILE = "gxc_opens.jsonl"
GROUP_ONLY_FILE = "gxc_group_only.json"

CODE_LENGTH = 6
MAC_LENGTH = 16
TOKEN_LENGTH = CODE_LENGTH + MAC_LENGTH
_ALPHABET = frozenset("abcdefghijklmnopqrstuvwxyz234567")

_lock = threading.RLock()


def _owned(name: str) -> str:
    return os.path.join(settings.data_dir, "owned", name)


def _read(name: str, default):
    from backend.repositories.json_repo import _read as read
    return read(_owned(name), default)


def _write(name: str, payload) -> None:
    from backend.repositories.json_repo import _atomic_write   # the one safe writer
    _atomic_write(_owned(name), payload)


def _norm(email: str | None) -> str:
    return (email or "").strip().lower()


def _now() -> str:
    return utcnow().isoformat(timespec="seconds")


def may_be_granted(user) -> bool:
    """A PTC person signed in as themselves: not a partner, not a program
    with an API token, not the shared Admin sign-in (which has no user)."""
    return bool(user.is_authenticated and not user.is_partner
                and not user.token_name and _norm(user.email))


def may_share(user) -> bool:
    """Who gets a token of their own: whoever may be granted, and the local
    development principal."""
    return may_be_granted(user) or bool(user.is_dev_principal and _norm(user.email))


# ─────────────────────────────────────────────────────────────── tokens
def _mac_key() -> bytes:
    from backend.integrations.graph.video_sync import gxc_key
    return hmac.new(gxc_key(), b"tmh-gxc-share-links-v1", hashlib.sha256).digest()


def _mac(code: str, asset_id: str, generation: int) -> str:
    digest = hmac.new(_mac_key(), f"{code}|{asset_id}|{generation}".encode(),
                      hashlib.sha256).digest()
    return base64.b32encode(digest).decode().lower()[:MAC_LENGTH]


def _new_code(taken) -> str:
    while True:
        code = "".join(secrets.choice(sorted(_ALPHABET)) for _ in range(CODE_LENGTH))
        if code not in taken:
            return code


def _people() -> dict:
    data = _read(PEOPLE_FILE, {}) or {}
    data.setdefault("codes", {})        # code -> email
    data.setdefault("by_email", {})     # email -> code
    return data


def _generation(state: dict, code: str, asset_id: str) -> int:
    return int(((state.get("generations") or {}).get(code) or {}).get(asset_id, 0))


def token_for(email: str, asset_id: str) -> str:
    """This person's token for this video: the same every time, until revoked."""
    email = _norm(email)
    with _lock:
        people = _people()
        code = people["by_email"].get(email)
        if not code:
            code = _new_code(people["codes"])
            people["codes"][code] = email
            people["by_email"][email] = code
            _write(PEOPLE_FILE, people)
    state = _read(STATE_FILE, {}) or {}
    return code + _mac(code, asset_id, _generation(state, code, asset_id))


def sender_of(token: str | None, asset_id: str) -> str | None:
    """Whose link this is, if it is a working link to this video: the
    HMAC holds, it has not been revoked, and its sender's own grant (for
    someone outside the GXC group) still stands."""
    token = (token or "").strip().lower()
    if len(token) != TOKEN_LENGTH or not set(token) <= _ALPHABET:
        return None
    if is_group_only(asset_id):
        return None
    code, mac = token[:CODE_LENGTH], token[CODE_LENGTH:]
    email = _people()["codes"].get(code)
    if not email:
        return None
    state = _read(STATE_FILE, {}) or {}
    if not hmac.compare_digest(mac, _mac(code, asset_id, _generation(state, code, asset_id))):
        return None
    grant = (_grants().get(email) or {}).get(asset_id)
    if grant and grant.get("revoked_at"):
        return None
    return email


# ─────────────────────────────────────────────────────── GXC group only
def group_only() -> dict[str, dict]:
    """{GXC video id: {by, at}}: for the GXC group alone, links or not."""
    return _read(GROUP_ONLY_FILE, {}) or {}


def is_group_only(asset_id: str) -> bool:
    return asset_id in group_only()


def set_group_only(asset_id: str, on: bool, actor: str) -> dict:
    """Mark or unmark a GXC video. Marking ends every grant made for it,
    so unmarking later opens nothing by itself."""
    now = _now()
    ended = 0
    with _lock:
        marked = group_only()
        if on:
            marked.setdefault(asset_id, {"by": actor, "at": now})
            grants = _grants()
            for mine in grants.values():
                g = mine.get(asset_id)
                if g and not g.get("revoked_at"):
                    g["revoked_at"], g["revoked_by"] = now, actor
                    ended += 1
            if ended:
                _write(GRANTS_FILE, grants)
                state = _read(STATE_FILE, {}) or {}
                state.setdefault("revocations", []).append(
                    {"at": now, "by": actor, "sender": None, "asset_id": asset_id,
                     "grants_revoked": ended, "why": "GXC group only"})
                _write(STATE_FILE, state)
        else:
            marked.pop(asset_id, None)
        _write(GROUP_ONLY_FILE, marked)
    log.info("gxc group only %s: %s by %s (%d grant(s) ended)",
             "on" if on else "off", asset_id, actor, ended)
    return {"asset_id": asset_id, "group_only": on, "grants_ended": ended}


# ─────────────────────────────────────────────────────────────── grants
def _grants() -> dict:
    return _read(GRANTS_FILE, {}) or {}


def granted_ids(email: str | None) -> frozenset[str]:
    """The GXC videos this person may open without being in the GXC group
    -- none that is GXC group only."""
    mine = _grants().get(_norm(email)) or {}
    closed = group_only()
    return frozenset(a for a, g in mine.items()
                     if not g.get("revoked_at") and a not in closed)


def grant(email: str, asset_id: str, via: str) -> bool:
    """B may see this video, via A's link. False when B already may."""
    email, via = _norm(email), _norm(via)
    with _lock:
        grants = _grants()
        mine = grants.setdefault(email, {})
        current = mine.get(asset_id)
        if current and not current.get("revoked_at"):
            return False
        mine[asset_id] = {"via": via, "at": _now(), "revoked_at": None}
        _write(GRANTS_FILE, grants)
        return True


def without_link_views(events: list[dict]) -> list[dict]:
    """Usage events less those of people outside the GXC group on the GXC
    videos a link granted them (B10, 2026-11-03): Hub activity does not show
    them, to anyone. They are still written; this file is where who opened
    what through whose link is read."""
    pairs = {(who, aid) for who, mine in _grants().items() for aid in mine}
    if not pairs:
        return events
    return [e for e in events
            if not ((e.get("asset_id") or "").startswith("gxc-")
                    and (_norm(e.get("user")), e["asset_id"]) in pairs)]


def record_open(asset_id: str, who: str, via: str, granted: bool) -> None:
    """Somebody opened a GXC video through somebody else's link."""
    entry = {"at": _now(), "asset_id": asset_id, "who": _norm(who), "via": _norm(via),
             "granted": granted}
    path = _owned(OPENS_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with _lock, open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def opens() -> list[dict]:
    path = _owned(OPENS_FILE)
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue          # a torn final line loses one entry, not the log
    return rows


# ─────────────────────────────────────────────────────────────── revoking
def revoke(sender: str, asset_id: str | None, actor: str) -> dict:
    """Stop the links `sender` sent -- for one video, or all of them -- and
    everything that came through them. Returns what was revoked."""
    sender = _norm(sender)
    now = _now()
    with _lock:
        people, state, grants = _people(), _read(STATE_FILE, {}) or {}, _grants()
        code = people["by_email"].get(sender)
        if code:
            if asset_id is None:
                # A new code: every token of the old one stops at once.
                del people["codes"][code]
                fresh = _new_code(people["codes"])
                people["codes"][fresh] = sender
                people["by_email"][sender] = fresh
            else:
                gens = state.setdefault("generations", {}).setdefault(code, {})
                gens[asset_id] = int(gens.get(asset_id, 0)) + 1
        # The cascade: grants through a revoked link, then through theirs.
        queue, seen, revoked = [(sender, asset_id)], set(), []
        while queue:
            via, only = queue.pop()
            if (via, only) in seen:
                continue
            seen.add((via, only))
            for who, mine in grants.items():
                for aid, g in mine.items():
                    if g.get("via") == via and not g.get("revoked_at") \
                            and (only is None or aid == only):
                        g["revoked_at"], g["revoked_by"] = now, actor
                        revoked.append({"who": who, "asset_id": aid, "via": via})
                        queue.append((who, aid))
        state.setdefault("revocations", []).append(
            {"at": now, "by": actor, "sender": sender, "asset_id": asset_id,
             "grants_revoked": len(revoked)})
        _write(PEOPLE_FILE, people)
        _write(STATE_FILE, state)
        _write(GRANTS_FILE, grants)
    log.info("gxc links revoked: %s%s by %s, %d grant(s)", sender,
             f" ({asset_id})" if asset_id else "", actor, len(revoked))
    return {"sender": sender, "asset_id": asset_id, "grants_revoked": revoked}


# ─────────────────────────────────────────────────────────────── Admin
def report(asset_id: str | None = None, person: str | None = None) -> dict:
    """Who opened whose link, and who holds a grant -- by video or by person
    (sender or receiver), newest first."""
    person = _norm(person)

    def keep(row: dict, *people: str) -> bool:
        return ((not asset_id or row.get("asset_id") == asset_id)
                and (not person or person in people))

    grant_rows = [{"who": who, "asset_id": aid, **g}
                  for who, mine in _grants().items() for aid, g in mine.items()]
    grant_rows = [g for g in grant_rows if keep(g, g["who"], g.get("via"))]
    open_rows = [o for o in opens() if keep(o, o.get("who"), o.get("via"))]
    state = _read(STATE_FILE, {}) or {}
    revocations = [r for r in state.get("revocations") or []
                   if (not asset_id or r.get("asset_id") in (None, asset_id))
                   and (not person or r.get("sender") == person)]
    by_time = lambda r: r.get("at") or ""                       # noqa: E731
    return {"grants": sorted(grant_rows, key=by_time, reverse=True),
            "opens": sorted(open_rows, key=by_time, reverse=True),
            "revocations": sorted(revocations, key=by_time, reverse=True)}
