"""A shared username/password for the Admin page, until Entra SSO exists.

Why this exists, and what it deliberately is not
------------------------------------------------
Measured against the deployed app on 2026-09-21: `AUTH_MODE=easyauth` and
`enforcing=true`, so an anonymous caller is ANONYMOUS, `require_authenticated`
401s, and `require_curator` refuses everyone — including the people who are
supposed to curate, because `AUTH_CURATOR_GROUPS` is empty. The door is not
open; it is locked with no key cut. This module cuts a temporary key.

It is a bridge, not an answer, and the difference is attribution. One
credential shared by everyone means no action can be traced to a person, so
what it may unlock is bounded by what is safe to do anonymously:

    allowed   reading diagnostics already exposed by /api/debug/backend
    allowed   refreshing the mirror (a sync reads from SharePoint/Consensus
              and writes our own rebuildable cache; WouldShrinkMirror and
              WouldDowngrade already guard it, and it touches no upstream)
    refused   anything that writes back to SharePoint — approving a metadata
              proposal above all. That edits somebody else's system, and
              §8.5/§8.4 of the handover exist precisely because an
              unattributable write there is the failure mode to avoid.

Since 2026-10-06 the Hub has users, groups and permissions (backend/access.py)
and this sign-in is one more way to hold them: every permission except Edit
metadata, which writes SharePoint columns. `require_perm` below is the single
gate both go through. It stays, for the transition, until ADMIN_PASSWORD is
removed from the app settings (Liwei, 2026-10-06); with it blank this module
grants nothing.

Mechanics
---------
A signed cookie, not HTTP Basic: Basic re-sends the password on every request
and cannot be logged out of without closing the browser. The cookie carries
an expiry and an HMAC over it, keyed by the password itself — so changing the
password invalidates every outstanding session for free, and there is no
second secret to manage or forget to set.

The password sits in an App Setting in the clear. That is a real weakness and
an accepted one for a temporary shared credential: hashing it at rest would
protect against someone who can already read the app's configuration, which
is the same someone who can read every other secret there. Both halves blank
means no admin exists at all — `admin_configured` is checked before the
comparison, never after.

Delete the shared half of this module once ADMIN_PASSWORD is gone everywhere.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time

from fastapi import Depends, HTTPException, Request, Response

from backend.config import settings

log = logging.getLogger(__name__)

COOKIE_NAME = "tdd_admin"

#: Eight hours: long enough for a working day, short enough that a session
#: left open on a shared machine does not outlive the week.
SESSION_SECONDS = 8 * 60 * 60


def _signing_key() -> bytes:
    """Derived from the password, so a password change revokes every session.

    Salted with a constant so the key is not the password itself in any form
    that could be compared against a leaked cookie.
    """
    return hashlib.sha256(
        b"tdd-admin-session:" + settings.admin_password.encode("utf-8")).digest()


def _sign(payload: bytes) -> str:
    return base64.urlsafe_b64encode(
        hmac.new(_signing_key(), payload, hashlib.sha256).digest()).decode().rstrip("=")


def _is_local(request: Request) -> bool:
    """Only a loopback host counts as local. Anything else — including any
    deployment — is treated as remote and gets the Secure flag."""
    return (request.url.hostname or "") in ("localhost", "127.0.0.1", "::1")


def issue_session(request: Request, response: Response) -> None:
    """Set the cookie. Called only after the password has been verified.

    `secure` is conditional, and this is the one place it is allowed to be:
    a Secure cookie is never stored over plain http, so setting it
    unconditionally would make the page impossible to sign into on
    http://localhost — the developer would see a successful login followed
    by an immediate "not signed in". Every non-loopback host still gets it.
    """
    payload = json.dumps({"exp": int(time.time()) + SESSION_SECONDS}).encode()
    encoded = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    response.set_cookie(
        COOKIE_NAME, f"{encoded}.{_sign(payload)}",
        max_age=SESSION_SECONDS,
        httponly=True,                   # an XSS cannot read it out
        samesite="lax",                  # not sent on cross-site POSTs
        secure=not _is_local(request),   # HTTPS everywhere that is not loopback
        path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def verify_password(username: str, password: str) -> bool:
    """Constant-time on both halves, and False whenever no admin is configured."""
    if not settings.admin_configured:
        return False
    ok_user = hmac.compare_digest(username or "", settings.admin_username)
    ok_pass = hmac.compare_digest(password or "", settings.admin_password)
    return ok_user and ok_pass          # no short-circuit: both always compared


def has_admin_session(request: Request) -> bool:
    raw = request.cookies.get(COOKIE_NAME)
    if not raw or not settings.admin_configured:
        return False
    encoded, _, signature = raw.partition(".")
    if not signature:
        return False
    try:
        payload = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    except (ValueError, TypeError):
        return False
    if not hmac.compare_digest(signature, _sign(payload)):
        return False
    try:
        return int(json.loads(payload).get("exp", 0)) > time.time()
    except (ValueError, TypeError, AttributeError):
        return False


def require_perm(perm):
    """Gate one endpoint on one permission (backend/access.py). Returns who is
    acting, for the log line and the "changed by" fields:

    * ``user:<email>`` -- a signed-in person whose groups give the permission;
    * ``admin-session`` -- the shared Admin sign-in, which has every
      permission but Edit metadata (see access.ADMIN_SESSION_PERMS);
    * ``dev:<email>`` -- the local development principal.

    401 for nobody, 403 for somebody who lacks it: the second can be helped by
    an administrator, the first needs to sign in.
    """
    from backend.access import ADMIN_SESSION_PERMS
    from backend.auth import principal_from_request   # local: avoids a cycle

    value = getattr(perm, "value", perm)

    async def dependency(request: Request) -> str:
        user = principal_from_request(request)
        session = value in ADMIN_SESSION_PERMS and has_admin_session(request)
        if user.is_authenticated and user.can(value):
            return f"user:{user.email}"
        if session:
            return "admin-session"
        if user.is_dev_principal and user.can(value):
            return f"dev:{user.email}"
        if user.is_authenticated:
            raise HTTPException(
                status_code=403,
                detail="Your account does not have permission for this. Ask a Hub "
                       "administrator to add you to a group that has it.")
        raise HTTPException(status_code=401, detail="Sign-in required.")

    dependency.__name__ = f"require_{value}"
    return dependency
