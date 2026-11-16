"""View the Hub as a group (A9; Liwei 2026-10-21, planned 2026-11-16).

One person with one account cannot see what a partner, a PTC employee or the
team sees. An administrator starts a preview from Admin -> Users & groups; the
Hub then answers exactly as it would for a member of that group -- who sees
what, which buttons exist, whether Admin opens -- until they exit.

How it works, in four rules (docs/A9-view-as-plan.md):

* The preview is one key in the signed session cookie, so the browser cannot
  forge it, a sign-out ends it, and it survives page loads.
* `auth.principal_from_request` -- the one function every identity check goes
  through -- returns an *effective user* while a preview is on: no email, name
  or object id (so no personal favourites, playlists, GXC link grants or
  disclaimer are found or written), the group's permissions cut to the real
  person's own (a preview lowers, never raises), and an explicit partner flag.
* The whole preview is read-only: every write is refused with one message, and
  the Hub's own telemetry (searches, views, feature use) is dropped quietly, so
  a preview never counts as anyone's use.
* Starting and stopping are in the Admin log, by the real person.

A preview cannot show GXC personal links (a grant is written when a person
first opens one), SharePoint's own permissions or a real partner's sign-in.
"""
from __future__ import annotations

import re

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

SESSION_KEY = "view_as"

#: Paths a preview answers 204 to without running them: the page reports
#: these by itself, and a refusal would only add errors to its console.
TELEMETRY = re.compile(
    r"^/api/assets/(search-event|feature-event)$"
    r"|^/api/assets/[^/]+/(view|consensus-preview)$"
    r"|^/api/welcome/(seen|shown)$")

#: GETs that write something (Consensus tokens) and so are refused too.
WRITING_GETS = ("/api/consensus/oauth/start", "/api/consensus/oauth/callback")

EXIT_PATH = "/api/admin/view-as/exit"


def _session(scope) -> dict | None:
    session = scope.get("session")
    return session if isinstance(session, dict) else None


def identity_key(real) -> str | None:
    """Who started a preview: the object id, else the address."""
    return (getattr(real, "object_id", None) or getattr(real, "email", None) or "").strip().lower() or None


def _end(request: Request, real, data: dict, why: str) -> None:
    session = _session(request.scope)
    if session is not None:
        session.pop(SESSION_KEY, None)
    try:
        from backend import admin_log
        admin_log.record(f"user:{real.email}" if real.email else "dev", why,
                         method="", path="", status=200,
                         target=data.get("label") or data.get("group_id"))
    except Exception:                                    # the log must never break a request
        import logging
        logging.getLogger(__name__).exception("could not log the end of a preview")


def may_start(real) -> bool:
    """Manage users & groups, as for every group change. The local development
    principal (never on a deployed slot) may too, so a preview can be tried
    locally."""
    from backend.access import Perm
    if real.token_name:
        return False
    return real.can(Perm.MANAGE_USERS) or real.is_dev_principal


def effective(request: Request, real):
    """The user this request acts as: the real person, or the preview's
    effective user. A preview that no longer holds (the group is gone, the
    person lost the right, the session is another person's) is dropped."""
    from backend.auth import CurrentUser
    if real.token_name or not (real.is_authenticated or real.is_dev_principal):
        return real
    session = _session(request.scope)
    data = session.get(SESSION_KEY) if session else None
    if not isinstance(data, dict):
        return real
    if data.get("by") != identity_key(real) or not may_start(real):
        _end(request, real, data, "Preview ended: not the person who started it")
        return real
    from backend import access
    profile = access.preview_profile(str(data.get("group_id") or ""), real.permissions)
    if profile is None:
        _end(request, real, data, "Preview ended: the group was deleted")
        return real
    return CurrentUser(
        provider="view-as", is_authenticated=True,
        partner_as=profile["partner"], preview_permissions=profile["permissions"],
        view_as={"group_id": profile["group_id"], "label": profile["label"],
                 "by": real.name or real.email})


def start(request: Request, real, group_id: str) -> dict | None:
    """Begin previewing; None when the group does not exist."""
    from backend import access
    profile = access.preview_profile(group_id, real.permissions)
    session = _session(request.scope)
    if profile is None or session is None:
        return None
    session[SESSION_KEY] = {"group_id": profile["group_id"], "label": profile["label"],
                            "by": identity_key(real)}
    return profile


def stop(request: Request) -> None:
    session = _session(request.scope)
    if session is not None:
        session.pop(SESSION_KEY, None)


def active(request: Request) -> bool:
    """Is a preview on for this request (validated, as `effective` does)."""
    from backend.auth import principal_from_request
    return principal_from_request(request).view_as is not None


class ReadOnly:
    """ASGI middleware: while a preview is on, nothing is written.

    Sits inside the session and outside the Admin log, so a refused attempt
    is neither run nor logged (only starting and stopping are)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        session = _session(scope) if scope["type"] == "http" else None
        if not session or SESSION_KEY not in session:
            return await self.app(scope, receive, send)
        request = Request(scope)
        if not active(request):
            return await self.app(scope, receive, send)
        path, method = scope.get("path", ""), scope.get("method", "GET")
        label = request.scope["state"]["hub_principal"].view_as["label"]
        if method in ("GET", "HEAD", "OPTIONS") and not path.startswith(WRITING_GETS):
            return await self.app(scope, receive, send)
        if method == "POST" and path == EXIT_PATH:
            return await self.app(scope, receive, send)
        if method == "POST" and TELEMETRY.search(path):
            return await Response(status_code=204)(scope, receive, send)
        return await JSONResponse(
            {"detail": f"Read-only: you are viewing the Hub as {label}. "
                       "Exit the preview to make changes.", "view_as": True},
            status_code=403, headers={"X-Hub-View-As": "read-only"})(scope, receive, send)
