"""Cross-site request forgery: writes only from the Hub's own pages (2026-11-26).

Until now the only defence was the session cookie's SameSite=lax. Lax stops a
cookie riding along on a POST from another *site*, but staging and production
are one site -- dev-tmh.ptcxc.com and tmh.ptcxc.com share ptcxc.com -- so a
page on one slot could write to the other with the visitor's session. Every
other host under ptcxc.com is in the same position.

So every write (POST, PUT, PATCH, DELETE) that does not carry an API token is
checked against the headers the browser itself sets, and which a page cannot
forge:

1. `Sec-Fetch-Site` when present: `same-origin` (the Hub's own page) or
   `none` (typed in, a bookmark) pass; `same-site` and `cross-site` do not.
   `same-site` is precisely the staging-versus-production case.
2. Otherwise `Origin`, which must be this request's own origin.
3. A request with **neither** header passes. Every browser in use sends
   `Origin` on a cross-origin POST, and every current one sends
   `Sec-Fetch-Site` as well; a request with neither did not come from a
   browser page, so it carries no visitor's cookie to abuse -- it is curl,
   a script, or the test client. Refusing it would protect nobody and break
   those.

Requests with an API token (Authorization: Bearer) are left to the token: a
page on another site cannot attach that header without a CORS preflight the
Hub never answers. The two sign-in callbacks are GETs today and are named
here so that a later switch to a form-post return from the identity
provider -- which arrives cross-site by design and is protected by its state
check -- does not quietly break sign-in.
"""
from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: Returns from another site's sign-in, which cannot come from our origin.
EXEMPT_PATHS = frozenset({"/auth/callback", "/api/consensus/oauth/callback"})

_ALLOWED_FETCH_SITES = frozenset({"same-origin", "none"})


def _own_origins(request: Request) -> set[str]:
    """This request's origin, as the browser would write it.

    Behind App Service the app sees http while the browser used https, so
    the forwarded scheme counts too. The host is the one the browser asked
    for, and canonical_host has already sent *.azurewebsites.net elsewhere.
    """
    host = (request.headers.get("host") or "").strip().lower()
    schemes = {request.url.scheme}
    forwarded = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
    if forwarded:
        schemes.add(forwarded.lower())
    return {f"{scheme}://{host}" for scheme in schemes if host}


def refusal(request: Request) -> str | None:
    """Why this request is refused, or None when it may proceed."""
    if request.method not in UNSAFE_METHODS or request.url.path in EXEMPT_PATHS:
        return None
    from backend import api_tokens
    if api_tokens.bearer(request):
        return None
    site = (request.headers.get("sec-fetch-site") or "").strip().lower()
    if site:
        return None if site in _ALLOWED_FETCH_SITES else f"Sec-Fetch-Site {site}"
    origin = (request.headers.get("origin") or "").strip().lower().rstrip("/")
    if not origin:
        return None                       # not a browser page; see the module docstring
    return None if origin in _own_origins(request) else f"Origin {origin}"


async def check_origin(request: Request, call_next):
    reason = refusal(request)
    if reason:
        log.warning("CSRF: refused %s %s (%s)", request.method, request.url.path, reason)
        return JSONResponse(
            {"detail": "This change did not come from a Hub page, so it was refused. "
                       "Reload the page and try again."},
            status_code=403)
    return await call_next(request)
