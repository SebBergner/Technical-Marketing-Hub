"""Authentication and authorisation.

Identity comes from **Azure App Service Easy Auth**: the platform performs the
Entra ID sign-in and injects the result as request headers before our code runs.

    X-MS-CLIENT-PRINCIPAL-NAME   the user's UPN / email
    X-MS-CLIENT-PRINCIPAL-ID     their object id
    X-MS-CLIENT-PRINCIPAL-IDP    the provider ("aad")
    X-MS-CLIENT-PRINCIPAL        base64 JSON with the full claim set

The thing to be careful about
-----------------------------
Those are just headers. Anything that can reach the app *without* passing
through the auth gate can set them itself and become anybody. That is not
hypothetical — it happens when Easy Auth is left on "allow unauthenticated
requests", when a container port is exposed directly, or when someone puts a
proxy in front and forgets to strip inbound `X-MS-*`.

So the headers are trusted **only** when `AUTH_MODE=easyauth` is set
explicitly. The default is `disabled`, and in that mode the headers are ignored
entirely rather than believed — a forged header on a machine where auth was
never configured must not grant anything.

The remaining hazard is the opposite mistake: deploying to App Service and
forgetting to set `AUTH_MODE`. `security_warnings()` detects exactly that (App
Service always sets `WEBSITE_SITE_NAME`) and it is surfaced by
`/api/auth/me`, `/api/debug/backend` and a startup log line, because a silent
"everyone is a curator" is the worst possible failure here.
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
import os
from dataclasses import dataclass, field
from enum import Enum

from fastapi import Depends, HTTPException, Request

from backend.config import settings

log = logging.getLogger(__name__)

#: Set by Azure App Service on every instance. Its presence means we are
#: running in the platform that provides Easy Auth.
APP_SERVICE_MARKER = "WEBSITE_SITE_NAME"

PRINCIPAL_NAME_HEADER = "x-ms-client-principal-name"
PRINCIPAL_ID_HEADER = "x-ms-client-principal-id"
PRINCIPAL_IDP_HEADER = "x-ms-client-principal-idp"
PRINCIPAL_HEADER = "x-ms-client-principal"

#: Claim types that carry group membership or app roles, depending on how the
#: app registration is configured. Both are checked.
ROLE_CLAIMS = {
    "roles",
    "groups",
    "http://schemas.microsoft.com/ws/2008/06/identity/claims/role",
}


class Role(str, Enum):
    #: May read the catalogue and share externally.
    VIEWER = "viewer"
    #: May additionally decide metadata proposals and trigger a sync — i.e.
    #: anything that will eventually write to SharePoint.
    CURATOR = "curator"


class AuthMode(str, Enum):
    #: Local development. Platform headers are IGNORED, not trusted.
    DISABLED = "disabled"
    #: Running behind App Service Easy Auth; headers are authoritative.
    EASYAUTH = "easyauth"


@dataclass
class CurrentUser:
    email: str | None = None
    name: str | None = None
    object_id: str | None = None
    provider: str | None = None
    roles: set[str] = field(default_factory=set)
    is_authenticated: bool = False
    #: True when running with auth disabled, so callers and diagnostics can
    #: tell "a real curator" from "nobody, and nothing is enforced".
    is_dev_principal: bool = False

    @property
    def can_curate(self) -> bool:
        return Role.CURATOR.value in self.roles

    def as_dict(self) -> dict:
        return {
            "email": self.email, "name": self.name, "object_id": self.object_id,
            "provider": self.provider, "roles": sorted(self.roles),
            "is_authenticated": self.is_authenticated,
            "is_dev_principal": self.is_dev_principal,
            "can_curate": self.can_curate,
        }


ANONYMOUS = CurrentUser()

#: In `disabled` mode there is nobody to authorise, and refusing every write
#: would make the app untestable locally. So local runs get a clearly-labelled
#: principal with full rights — safe precisely because `security_warnings()`
#: makes it impossible for that mode to go unnoticed in production.
DEV_PRINCIPAL = CurrentUser(
    email="dev@localhost", name="Local development",
    roles={Role.VIEWER.value, Role.CURATOR.value},
    is_authenticated=False, is_dev_principal=True,
)


def _decode_principal(encoded: str) -> dict:
    """Decode the base64 JSON claim blob Easy Auth sends."""
    padding = "=" * (-len(encoded) % 4)
    try:
        return json.loads(base64.b64decode(encoded + padding))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        log.warning("could not decode X-MS-CLIENT-PRINCIPAL: %s", exc)
        return {}


def _roles_from_claims(payload: dict) -> set[str]:
    """Pull group ids and app roles out of the claim set.

    Easy Auth serialises claims as a list of {typ, val}, and which claim type
    carries the roles depends on how the app registration was set up — app
    roles land in `roles`, security groups in `groups`.
    """
    found: set[str] = set()
    for claim in payload.get("claims") or []:
        if not isinstance(claim, dict):
            continue
        if claim.get("typ") in ROLE_CLAIMS and claim.get("val"):
            found.add(str(claim["val"]))
    for key in ("roles", "groups"):
        value = payload.get(key)
        if isinstance(value, list):
            found.update(str(v) for v in value if v)
    return found


def _map_roles(claim_values: set[str]) -> set[str]:
    """Map Entra ID group ids / app role names onto our two roles.

    Configured rather than hardcoded, because the group ids do not exist yet —
    they come from whoever sets up the app registration. Until
    `AUTH_CURATOR_GROUPS` is set, every authenticated user is a viewer only,
    which fails closed: read and share work, curation does not.
    """
    configured = {g.strip() for g in (settings.auth_curator_groups or "").split(",")
                  if g.strip()}
    roles = {Role.VIEWER.value}
    if configured and (claim_values & configured):
        roles.add(Role.CURATOR.value)
    # An explicit app role named "curator" also counts, so app roles work
    # without needing group object ids.
    if Role.CURATOR.value in {v.lower() for v in claim_values}:
        roles.add(Role.CURATOR.value)
    return roles


def principal_from_request(request: Request) -> CurrentUser:
    """Build the current user. Headers are honoured only in easyauth mode."""
    if settings.auth_mode != AuthMode.EASYAUTH.value:
        # Deliberately ignore any X-MS-* header here. Believing them with auth
        # switched off would mean a forged header grants access.
        return DEV_PRINCIPAL

    headers = request.headers
    name = headers.get(PRINCIPAL_NAME_HEADER)
    encoded = headers.get(PRINCIPAL_HEADER)
    if not name and not encoded:
        return ANONYMOUS

    payload = _decode_principal(encoded) if encoded else {}
    claim_values = _roles_from_claims(payload)

    email = name or payload.get("userPrincipalName") or payload.get("name")
    return CurrentUser(
        email=email,
        name=payload.get("name") or email,
        object_id=headers.get(PRINCIPAL_ID_HEADER),
        provider=headers.get(PRINCIPAL_IDP_HEADER) or payload.get("auth_typ"),
        roles=_map_roles(claim_values),
        is_authenticated=True,
    )


# ------------------------------------------------------------- dependencies
async def get_current_user(request: Request) -> CurrentUser:
    return principal_from_request(request)


async def require_authenticated(
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    if not (user.is_authenticated or user.is_dev_principal):
        raise HTTPException(
            status_code=401,
            detail="Sign-in required. This app expects Azure App Service Easy Auth "
                   "(Entra ID) in front of it.",
        )
    return user


async def require_curator(
    user: CurrentUser = Depends(require_authenticated),
) -> CurrentUser:
    """For anything that will eventually write to SharePoint."""
    if not user.can_curate:
        raise HTTPException(
            status_code=403,
            detail="This action needs the curator role. Ask an administrator to add "
                   "you to a group listed in AUTH_CURATOR_GROUPS.",
        )
    return user


# ---------------------------------------------------------------- diagnostics
def security_warnings() -> list[str]:
    """Misconfigurations that would silently weaken access control.

    Surfaced by /api/auth/me, /api/debug/backend and a startup log line. The
    failure being guarded against is a deploy where AUTH_MODE was simply never
    set, which would make every caller a curator without anything looking wrong.
    """
    warnings: list[str] = []
    on_app_service = bool(os.environ.get(APP_SERVICE_MARKER))
    disabled = settings.auth_mode != AuthMode.EASYAUTH.value

    if on_app_service and disabled:
        warnings.append(
            "AUTH IS DISABLED ON APP SERVICE. Every caller is treated as a curator. "
            "Set AUTH_MODE=easyauth and enable App Service Authentication (Entra ID) "
            "with 'Require authentication'.")
    if settings.auth_mode == AuthMode.EASYAUTH.value and not settings.auth_curator_groups:
        warnings.append(
            "AUTH_CURATOR_GROUPS is empty, so nobody has the curator role and "
            "curation endpoints will refuse everyone. Set it to the Entra ID group "
            "object id(s), or assign an app role named 'curator'.")
    if on_app_service and settings.graph_configured and disabled:
        warnings.append(
            "Graph write access is configured while auth is disabled — an "
            "unauthenticated caller could reach SharePoint write paths.")
    return warnings


def log_security_warnings() -> None:
    for warning in security_warnings():
        log.warning("SECURITY: %s", warning)
