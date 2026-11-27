"""The API reference (/docs, /redoc, /openapi.json), for administrators only.

FastAPI serves these to anyone who reaches the app. Behind the sign-in that
still meant everyone with View the Hub, partners included, and the schema
lists every route the Hub has -- admin, migration and write-back among them
(audit, 2026-11-26). So FastAPI's own routes are switched off in app.py and
these take their place, gated on View Admin, which partners never hold
(backend/access.py).

The two HTML pages load their scripts from FastAPI's CDN and Swagger's page
starts itself with one inline script, neither of which the Hub's own
Content-Security-Policy (`script-src 'self'`) allows. Each page therefore
sends its own policy, naming the CDN and the exact hash of its inline
script, rather than loosening the policy for every page.
"""
from __future__ import annotations

import base64
import hashlib
import re

from fastapi import APIRouter, Depends, Request
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse

from backend.access import Perm
from backend.admin_auth import require_perm

#: Where FastAPI's pages load Swagger UI and ReDoc from.
CDN = "https://cdn.jsdelivr.net"

router = APIRouter(include_in_schema=False,
                   dependencies=[Depends(require_perm(Perm.VIEW_ADMIN))])

_INLINE_SCRIPT = re.compile(r"<script>(.*?)</script>", re.S | re.I)


def _with_policy(page: HTMLResponse) -> HTMLResponse:
    """The page's own CSP: the CDN, plus each inline script by its hash."""
    body = page.body.decode("utf-8")
    hashes = " ".join(
        "'sha256-" + base64.b64encode(hashlib.sha256(s.encode("utf-8")).digest()).decode() + "'"
        for s in _INLINE_SCRIPT.findall(body))
    page.headers["Content-Security-Policy"] = (
        f"frame-ancestors 'self'; script-src 'self' {CDN} {hashes}".rstrip()
        + "; object-src 'none'; base-uri 'self'")
    return page


@router.get("/openapi.json")
def openapi(request: Request):
    return JSONResponse(request.app.openapi())


@router.get("/docs")
def swagger(request: Request):
    return _with_policy(get_swagger_ui_html(openapi_url="/openapi.json",
                                            title=f"{request.app.title} - API"))


@router.get("/redoc")
def redoc(request: Request):
    return _with_policy(get_redoc_html(openapi_url="/openapi.json",
                                       title=f"{request.app.title} - API"))
