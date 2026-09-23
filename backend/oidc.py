"""The app's own sign-in: OpenID Connect against Entra ID, through msal.

Active only when `AUTH_MODE=oidc`. Three routes and two middlewares:

    /login           start: remember where the person was going, send them
                     to Microsoft with state, nonce and PKCE
    /auth/callback   finish: check the answer, write the session, send them on
    /logout          clear our session (not their Microsoft one)

    require_sign_in  every other route needs a session -- default deny
    canonical_host   *.azurewebsites.net is redirected to CUSTOM_DOMAIN

Why hand-rolled rather than App Service Easy Auth
-------------------------------------------------
Both work, and `easyauth` mode is still in backend/auth.py, tested. This one
was chosen on 2026-09-23 because the callback addresses Seb had already given
IT (`https://tmh.ptcxc.com/auth/callback`, `https://dev-tmh.ptcxc.com/...`)
belong to it, and because AMP is planned the same way -- two apps, one
pattern. It also means local development runs the real sign-in rather than a
stand-in, since this is ordinary app code and behaves the same everywhere.

The cost is that the security-critical parts are ours, so they are kept
narrow and each one is tested on its own:

* **msal does the protocol.** Authorization code flow with PKCE, the nonce,
  and the ID token's issuer and audience. The ID token's signature is not
  checked, and does not need to be: it arrives directly from the token
  endpoint over TLS, which OpenID Connect Core 3.1.3.7 allows in place of a
  signature check.
* **state is checked again here**, before msal sees the response, and so is
  the tenant. Both are also covered by msal or by the tenant-specific
  authority; checking them here is cheap, and it makes each property one that
  a test can break on its own.
* **the gate is default deny.** OPEN_PATHS is the whole list of what works
  without a session. A route added later is closed until someone decides
  otherwise, which is the right way round for "only our team has access".
* **the session has a hard ceiling** (SESSION_ABSOLUTE_HOURS) on top of the
  sliding idle timeout. Entra cannot reach into our cookie, so without it a
  person disabled in the directory would keep access for as long as they kept
  using the page.

Session shape
-------------
`request.session["user"]`, the same key AMP's password login writes, so the
two apps can share helpers later. What goes in it is deliberately small --
the whole thing lives in a cookie with a 4 KB limit, and a user in 200 groups
would otherwise blow through it. Only the groups that could grant the curator
role are kept.
"""
from __future__ import annotations

import html
import logging
import re
import secrets
import time
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from backend.auth import AuthMode, session_user
from backend.config import settings

log = logging.getLogger(__name__)

router = APIRouter(tags=["sign-in"], include_in_schema=False)

#: Not Starlette's default "session": the admin bridge already sets its own
#: cookie, and a name that says whose it is makes a browser's cookie list
#: readable when something needs debugging.
SESSION_COOKIE = "hub_session"

#: Added to the three msal always requests itself -- openid, profile and
#: offline_access, which it refuses to be handed explicitly. `email` because
#: for members of our own tenant the email claim is only sent when asked for.
#: `profile` is what brings `oid`, `name` and `preferred_username`.
SCOPES = ["email"]

#: Everything reachable without a session. Short on purpose.
OPEN_PATHS = frozenset({
    "/login", "/auth/callback", "/logout",
    # Platform probes, and the version a tester quotes when reporting a
    # problem -- neither says anything about the catalogue.
    "/health", "/api/version",
})

#: Sent with the 401 the gate returns to API calls. The front end redirects to
#: sign-in only when it sees this, because the Admin page's own 401 ("the
#: admin password was not entered") must keep meaning what it means.
SIGN_IN_HEADER = "X-Sign-In"

_GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


# ─────────────────────────────────────────────────────────────── plumbing
_ephemeral_key: str | None = None


def session_secret() -> str:
    """SECRET_KEY, or a random key for this process.

    Random rather than a fixed fallback string: AMP's is a literal default,
    and a literal default is a key anyone who has read the source can sign
    cookies with. A random one forges nothing; the cost is that a restart
    signs everyone out, which security_warnings() reports on Azure.
    """
    global _ephemeral_key
    if settings.secret_key:
        return settings.secret_key
    if _ephemeral_key is None:
        _ephemeral_key = secrets.token_urlsafe(48)
    return _ephemeral_key


#: msal's cache for Microsoft's own metadata documents (openid-configuration
#: and friends), shared across sign-ins so each one does not refetch them.
_HTTP_CACHE: dict = {}


def _msal_app():
    """A fresh client per call, sharing only the metadata cache.

    Fresh because a long-lived ConfidentialClientApplication keeps every
    token it has ever acquired in memory -- including refresh tokens for
    everyone who has signed in. We use the ID token once and never call an
    API with the rest, so there is no reason to hold them. Sign-ins are rare
    (one per person per day at most), and the metadata cache makes a new
    client cheap.
    """
    import msal
    return msal.ConfidentialClientApplication(
        settings.oidc_client_id,
        authority=f"https://login.microsoftonline.com/{settings.oidc_tenant_id}",
        client_credential=settings.oidc_client_secret,
        http_cache=_HTTP_CACHE,
    )


def _redirect_uri(request: Request) -> str:
    """OIDC_REDIRECT_URI when set, which it must be on Azure; otherwise the
    address of this server's own callback, which is right for localhost."""
    return settings.oidc_redirect_uri or str(request.url_for("auth_callback"))


def _safe_next(value: object) -> str:
    """Only paths on this site, so the sign-in cannot be used to bounce
    someone to an address of an attacker's choosing.

    Rejects anything that is not a plain absolute path -- including `//host`
    and `/\\host`, which browsers read as another site -- and anything
    pointing back into the sign-in routes, which would loop.
    """
    if not isinstance(value, str) or not value.startswith("/"):
        return "/"
    if value[1:2] in ("/", "\\") or any(c in value for c in "\r\n\t\x00"):
        return "/"
    if value.startswith(("/login", "/logout", "/auth/")):
        return "/"
    return value


def _expected_tenant() -> str | None:
    """The tenant id to compare the `tid` claim against, when there is one.

    IT may hand over a domain ("ptc.com") rather than the GUID. The authority
    then still pins sign-in to that tenant -- msal checks the issuer against
    it -- but there is no GUID to compare `tid` to, so the extra check is
    skipped rather than failing every sign-in.
    """
    value = (settings.oidc_tenant_id or "").strip().lower()
    return value if _GUID.match(value) else None


def _curator_groups(claims: dict) -> list[str]:
    """Only the groups that could make this person a curator. The rest would
    fill the cookie and could never change what they are allowed to do."""
    wanted = {g.strip().lower() for g in (settings.auth_curator_groups or "").split(",")
              if g.strip()}
    return [str(g) for g in claims.get("groups") or [] if str(g).lower() in wanted]


def _page(title: str, message: str, status: int,
          action: tuple[str, str] | None = ("/login", "Sign in again")) -> HTMLResponse:
    """A minimal page for the moments between sign-in and the app.

    Plain on purpose: it has to render when nothing else can be trusted,
    including the stylesheet, which sits behind the gate like everything else.
    """
    link = ""
    if action:
        link = (f'<p><a href="{html.escape(action[0])}">'
                f"{html.escape(action[1])}</a></p>")
    body = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} · Technical Marketing Hub</title>
<style>
  body{{font:15px/1.5 -apple-system,"Segoe UI",Roboto,sans-serif;margin:0;
    background:#f6f7f5;color:#1f2a1c}}
  main{{max-width:30rem;margin:18vh auto 0;padding:0 1.25rem}}
  h1{{font-size:1.3rem;margin:0 0 .5rem}}
  p{{margin:.4rem 0;color:#4b5a44}}
  a{{color:#00890B;font-weight:600}}
</style></head>
<body><main><h1>{html.escape(title)}</h1><p>{html.escape(message)}</p>{link}</main></body></html>"""
    return HTMLResponse(body, status_code=status)


def _require_oidc_mode() -> None:
    """The routes exist in every mode but mean something only in this one.
    Elsewhere they are not there, rather than half-working."""
    if settings.auth_mode != AuthMode.OIDC.value:
        raise HTTPException(status_code=404)


# ───────────────────────────────────────────────────────────────── routes
@router.get("/login")
def login(request: Request, next: str | None = None):
    _require_oidc_mode()
    if session_user(request) is not None:
        # Already signed in: go on. Starting a fresh flow here would replace
        # one that may still be in progress in this browser.
        return RedirectResponse(_safe_next(next), status_code=302)
    if not settings.oidc_configured:
        return _page("Sign-in isn't set up yet",
                     "This deployment has no identity provider configured, so "
                     "nobody can sign in. That is a setting, not something you "
                     "did.", 503, action=None)
    try:
        flow = _msal_app().initiate_auth_code_flow(
            SCOPES, redirect_uri=_redirect_uri(request))
    except Exception:                                      # noqa: BLE001
        log.exception("could not start sign-in")
        return _page("Microsoft sign-in is unreachable",
                     "We couldn't contact Microsoft to start signing you in. "
                     "Try again in a moment.", 502, action=("/login", "Try again"))

    # The authorize URL goes to the browser, not into the cookie: it is
    # the longest part of the flow and msal does not need it back.
    auth_uri = flow.pop("auth_uri")
    request.session["auth_flow"] = flow
    request.session["auth_next"] = _safe_next(next)
    return RedirectResponse(auth_uri, status_code=302)


@router.get("/auth/callback", name="auth_callback")
def auth_callback(request: Request):
    _require_oidc_mode()
    params = dict(request.query_params)
    # Popped before anything is checked: a flow is good for one answer, so a
    # replayed or failed callback cannot be retried against it.
    flow = request.session.pop("auth_flow", None)
    next_url = _safe_next(request.session.pop("auth_next", None))

    if params.get("error"):
        log.warning("sign-in refused by Entra: %s %s", params.get("error"),
                    params.get("error_description"))
        return _page("Sign-in didn't complete",
                     "Microsoft reported: " + (params.get("error_description")
                                               or params["error"]), 400)
    if not isinstance(flow, dict) or not flow.get("state"):
        # Usually a sign-in started in another tab, a callback bookmarked, or
        # cookies blocked for this site.
        return _page("That sign-in has expired",
                     "The sign-in you're returning from wasn't started in this "
                     "browser session. Start again and it will go through.", 400)
    if not secrets.compare_digest(str(params.get("state", "")), str(flow["state"])):
        log.warning("sign-in callback with a state that does not match its flow")
        return _page("That sign-in couldn't be verified",
                     "The response didn't match the sign-in this browser "
                     "started, so it was not accepted.", 400)

    try:
        result = _msal_app().acquire_token_by_auth_code_flow(flow, params)
    except (ValueError, RuntimeError) as exc:
        # msal's own checks -- state, nonce, issuer, audience -- raise these.
        log.warning("sign-in callback rejected: %s", exc)
        return _page("That sign-in couldn't be verified",
                     "The response from Microsoft failed a security check and "
                     "was not accepted.", 400)
    except Exception:                                      # noqa: BLE001
        log.exception("sign-in callback failed")
        return _page("Microsoft sign-in is unreachable",
                     "We couldn't complete signing you in. Try again in a moment.",
                     502, action=("/login", "Try again"))

    if "error" in result:
        log.warning("token exchange refused: %s %s", result.get("error"),
                    result.get("error_description"))
        return _page("Sign-in didn't complete",
                     "Microsoft declined to complete the sign-in.", 400)

    claims = result.get("id_token_claims") or {}
    expected = _expected_tenant()
    if expected and str(claims.get("tid", "")).lower() != expected:
        log.warning("sign-in from another tenant refused: %s", claims.get("tid"))
        return _page("This account can't sign in here",
                     "Only accounts from PTC's own directory can use the Hub.", 403,
                     action=("/logout", "Sign out"))
    if not claims.get("oid"):
        # `profile` should always bring it; without it there is nothing
        # stable to recognise this person by.
        log.warning("sign-in without an oid claim refused")
        return _page("Sign-in didn't complete",
                     "Microsoft didn't send the account identifier the Hub needs.",
                     400)

    # Cleared rather than updated, so nothing from before sign-in survives
    # into the signed-in session.
    request.session.clear()
    request.session["user"] = {
        "oid": str(claims["oid"]),
        "tid": claims.get("tid"),
        "email": claims.get("email"),
        "username": claims.get("preferred_username"),
        "name": claims.get("name"),
        "roles": [str(r) for r in claims.get("roles") or []][:20],
        "groups": _curator_groups(claims),
        "signed_in_at": int(time.time()),
    }
    log.info("signed in: %s", claims.get("preferred_username") or claims["oid"])
    return RedirectResponse(next_url, status_code=302)


@router.get("/logout")
def logout(request: Request):
    """Ends our session only. The person stays signed in to Microsoft, which
    is what every other PTC tool expects -- a full single sign-out would
    sign them out of Outlook and Teams as well, for the sake of one tab."""
    _require_oidc_mode()
    request.session.clear()
    return _page("You're signed out",
                 "Your Technical Marketing Hub session has ended. You're still "
                 "signed in to Microsoft, so signing in again is one click.", 200)


# ───────────────────────────────────────────────────────────── middleware
async def require_sign_in(request: Request, call_next):
    """Default deny: every route needs a session, except OPEN_PATHS.

    Must run inside SessionMiddleware (added after it in app.py), since it
    reads the session that middleware decodes. A page gets a redirect to
    sign-in that brings the person back where they were; an API call gets a
    401 with SIGN_IN_HEADER, because a redirect to a login page is not
    something a fetch() can act on.
    """
    if settings.auth_mode != AuthMode.OIDC.value or request.url.path in OPEN_PATHS:
        return await call_next(request)
    if session_user(request) is not None:
        return await call_next(request)
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Sign-in required.", "login": "/login"},
                            status_code=401, headers={SIGN_IN_HEADER: "/login"})
    if not _is_navigation(request):
        # A favicon, an image, a script: the browser fetches these on its own,
        # and sending one to /login would start a second sign-in that replaces
        # the flow the person is actually in the middle of -- their return
        # from Microsoft then fails the state check. Seen 2026-09-23 with the
        # favicon, in the first end-to-end run.
        return JSONResponse({"detail": "Sign-in required."}, status_code=401)
    target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    return RedirectResponse("/login?next=" + quote(target, safe=""), status_code=302)


#: Fetched by the browser without anyone navigating. Used only for clients
#: that do not send Sec-Fetch-Mode.
_BACKGROUND_PREFIXES = ("/static/", "/favicon")


def _is_navigation(request: Request) -> bool:
    """Is a person opening this page, rather than the browser fetching part
    of one? Browsers say so in Sec-Fetch-Mode; anything that does not send
    it (curl, very old browsers) is treated as a navigation unless it is
    plainly a resource."""
    mode = request.headers.get("sec-fetch-mode")
    if mode:
        return mode == "navigate"
    return not request.url.path.startswith(_BACKGROUND_PREFIXES)


async def canonical_host(request: Request, call_next):
    """Send *.azurewebsites.net to CUSTOM_DOMAIN, keeping path and query.

    AMP does the same (its CUSTOM_DOMAIN middleware), and it matters more here
    than it looks: the invitation email links to the azurewebsites.net
    address, the session cookie belongs to whichever host set it, and the
    sign-in only returns to the custom domain. Without the redirect, someone
    using that link would sign in, land on the custom domain, and have no
    session on the host they came from.

    Two deliberate differences from AMP's version. The query string is kept
    -- AMP drops it, which turns /login?next=/x into /login and loses where
    the person was going. And it is a 302, not a 301: browsers cache a 301
    indefinitely, so a mistyped CUSTOM_DOMAIN would keep sending people to
    the wrong place after it was fixed. /health is left alone so platform
    probes see the app itself, not a redirect.
    """
    domain = (settings.custom_domain or "").strip().lower()
    if domain and request.url.path != "/health":
        host = (request.headers.get("host") or "").split(":")[0].lower()
        if host.endswith(".azurewebsites.net"):
            target = f"https://{domain}{request.url.path}"
            if request.url.query:
                target += f"?{request.url.query}"
            return RedirectResponse(target, status_code=302)
    return await call_next(request)
