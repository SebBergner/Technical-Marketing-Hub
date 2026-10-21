"""API tokens: how a program uses the Hub's API (Liwei, 2026-10-15).

Seb's ask: create demos through the API. A program cannot do the Microsoft
sign-in a person does, so an administrator issues it a token on the Admin
page (Users & groups -> API tokens):

* named for what uses it, with a responsible person ("AMP pipeline", Seb);
* carrying only the permissions it needs, from TOKEN_PERMISSIONS -- never
  an administrative one;
* expiring (90 days unless chosen otherwise), revocable at any time;
* optionally publishing what it creates without review (`skip_review`),
  for a pipeline that is trusted as much as a reviewer;
* shown once, when created; only its SHA-256 is kept.

A request presents it as `Authorization: Bearer tmh_<id>_<secret>`. It acts
as `token:<name>` everywhere -- the Admin log included -- reaches /api/
paths only, and is never a partner. Kept in owned/api_tokens.json.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
from datetime import datetime, timedelta, timezone

FILE = "api_tokens.json"
PREFIX = "tmh_"
#: What a token may carry. Reading the catalogue and creating demos; not
#: reviewing, managing or administering anything.
TOKEN_PERMISSIONS = ("view_hub", "preview", "download", "access_internal", "upload_content")
DEFAULT_DAYS = 90
MAX_DAYS = 365
#: last_used is written at most this often per token, not on every call.
TOUCH_SECONDS = 300
_lock = threading.Lock()


class TokenError(ValueError):
    """A token the rules refuse; the message is for the Admin page."""


def _path() -> str:
    from backend import access
    return access._owned(FILE)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load() -> list[dict]:
    try:
        with open(_path(), encoding="utf-8") as fh:
            items = json.load(fh)
        return items if isinstance(items, list) else []
    except (FileNotFoundError, ValueError):
        return []


def _save(items: list[dict]) -> None:
    from backend.repositories.json_repo import _atomic_write
    _atomic_write(_path(), items)


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _public(t: dict) -> dict:
    out = {k: v for k, v in t.items() if k != "hash"}
    now = _now().isoformat()
    out["status"] = ("revoked" if t.get("revoked_at")
                     else "expired" if t["expires_at"] <= now else "active")
    return out


def listing() -> list[dict]:
    return [_public(t) for t in sorted(_load(), key=lambda t: t["created_at"], reverse=True)]


def create(*, name: str, owner: str, permissions: list[str], days: int | None,
           skip_review: bool, actor: str) -> tuple[dict, str]:
    """(the token's record, the secret to show once)."""
    name = (name or "").strip()
    owner = (owner or "").strip().lower()
    perms = sorted(set(permissions or []))
    if not name:
        raise TokenError("Name the token after what will use it.")
    if "@" not in owner:
        raise TokenError("Name the person responsible for it (an email address).")
    bad = [p for p in perms if p not in TOKEN_PERMISSIONS]
    if bad or not perms:
        raise TokenError("A token may carry only: " + ", ".join(TOKEN_PERMISSIONS) + ".")
    if skip_review and "upload_content" not in perms:
        raise TokenError("Publishing without review only applies to Create new demo.")
    days = days or DEFAULT_DAYS
    if not 1 <= days <= MAX_DAYS:
        raise TokenError(f"A token lasts between 1 and {MAX_DAYS} days.")
    with _lock:
        items = _load()
        if any(t["name"].lower() == name.lower() and not t.get("revoked_at") for t in items):
            raise TokenError(f'A token named "{name}" already exists; revoke it first.')
        token_id = secrets.token_hex(4)
        secret = f"{PREFIX}{token_id}_{secrets.token_urlsafe(32)}"
        record = {"id": token_id, "name": name, "owner": owner, "permissions": perms,
                  "skip_review": bool(skip_review), "created_by": actor,
                  "created_at": _now().isoformat(timespec="seconds"),
                  "expires_at": (_now() + timedelta(days=days)).isoformat(timespec="seconds"),
                  "last_used_at": None, "revoked_at": None, "revoked_by": None,
                  "hint": secret[:len(PREFIX) + 8 + 5] + "…", "hash": _digest(secret)}
        items.append(record)
        _save(items)
    return _public(record), secret


def revoke(token_id: str, actor: str) -> dict:
    with _lock:
        items = _load()
        record = next((t for t in items if t["id"] == token_id), None)
        if record is None:
            raise LookupError(token_id)
        if not record.get("revoked_at"):
            record.update(revoked_at=_now().isoformat(timespec="seconds"), revoked_by=actor)
            _save(items)
    return _public(record)


def resolve(presented: str | None) -> dict | None:
    """The live token a request presents, or None (unknown, revoked, expired)."""
    if not presented or not presented.startswith(PREFIX):
        return None
    token_id = presented[len(PREFIX):].split("_", 1)[0]
    record = next((t for t in _load() if t["id"] == token_id), None)
    if record is None or not hmac.compare_digest(record["hash"], _digest(presented)):
        return None
    now = _now()
    if record.get("revoked_at") or record["expires_at"] <= now.isoformat():
        return None
    last = record.get("last_used_at")
    if not last or (now - datetime.fromisoformat(last)).total_seconds() > TOUCH_SECONDS:
        try:
            with _lock:
                items = _load()
                for t in items:
                    if t["id"] == token_id:
                        t["last_used_at"] = now.isoformat(timespec="seconds")
                _save(items)
        except OSError:
            pass                 # never what refuses a request
    return record


def bearer(request) -> str | None:
    header = request.headers.get("authorization") or ""
    scheme, _, value = header.partition(" ")
    return value.strip() if scheme.lower() == "bearer" and value.strip() else None
