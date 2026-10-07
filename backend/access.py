"""Users, groups and permissions -- who may do what in the Hub (2026-10-06).

Agreed with Liwei on 2026-10-05 and built in that order: a fixed catalogue of
permissions in code, groups created on the Admin page, membership kept by hand
there (not Entra groups), and a person's permissions the union of their
groups'. Every endpoint checks a permission on the server; the pages only hide
what a person could not use anyway.

The groups
----------
Three are built in and cannot be deleted:

* **Administrators** -- every permission, always. Members are listed on the
  Admin page, plus anyone named in the HUB_ADMIN_EMAILS app setting: the
  bootstrap, so a fresh deployment (or a mistake on the page) can never leave
  the Hub with nobody able to manage it.
* **PTC employees** -- automatic: everyone who signs in with a member account.
* **Partners** -- automatic: everyone who signs in with a guest account
  (`CurrentUser.is_partner`). By default they may not see Internal content.

The two automatic groups have no member list; their permissions can be changed.
Any other group is created on the page, with its members typed as an email or
picked from the people who have signed in (`owned/users.json`).

Where it lives
--------------
`owned/access.json` (groups) and `owned/access_audit.jsonl` (every change, by
whom). Portal-authored like the rest of `owned/`, so no sync touches it, and
nothing here is ever written to SharePoint.

Who else gets in
----------------
* The local development principal (AUTH_MODE=disabled) has every permission
  except the Admin page's own two, so the Admin page still needs a real
  sign-in locally -- as it did before groups existed.
* The shared Admin sign-in (backend/admin_auth.py) has everything but
  editing metadata, which writes SharePoint columns and so must be traceable
  to a person. It stays as a way in until ADMIN_PASSWORD is removed from the
  app settings (Liwei, 2026-10-06: kept for the transition).
* The curator settings (AUTH_CURATOR_GROUPS / _EMAILS / _OIDS) still grant
  editing metadata, so nothing that worked before stops working.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from backend.config import settings

log = logging.getLogger(__name__)

STATE_FILE = "access.json"
AUDIT_FILE = "access_audit.jsonl"
USERS_FILE = "users.json"


class Perm(str, Enum):
    VIEW_HUB = "view_hub"
    PREVIEW = "preview"
    DOWNLOAD = "download"
    INTERNAL = "access_internal"
    CREATE_DEMO = "create_demo"
    EDIT_METADATA = "edit_metadata"
    MANAGE_HOME = "manage_home"
    RUN_SYNC = "run_sync"
    RUN_MIGRATION = "run_migration"
    VIEW_ADMIN = "view_admin"
    MANAGE_USERS = "manage_users"


#: In the order the Admin page lists them, with the words it shows.
CATALOGUE: list[tuple[Perm, str, str]] = [
    (Perm.VIEW_HUB, "View the Hub", "Sign in and browse, search and open demos."),
    (Perm.PREVIEW, "Preview files", "Open a demo's files in the preview."),
    (Perm.DOWNLOAD, "Download files", "Download a demo's files."),
    (Perm.INTERNAL, "Access internal content",
     "Preview and download demos marked Internal."),
    (Perm.CREATE_DEMO, "Create new demo", "Submit a new demo request."),
    (Perm.EDIT_METADATA, "Edit metadata",
     "Review metadata proposals and write them back to SharePoint."),
    (Perm.MANAGE_HOME, "Manage the Home page",
     "Choose Featured demos, hide demos and switch the Hub's display options."),
    (Perm.RUN_SYNC, "Run sync", "Sync SharePoint and Consensus, and set the daily sync."),
    (Perm.RUN_MIGRATION, "Run Brightcove migration",
     "Use the migration page, which uploads videos to SharePoint."),
    (Perm.VIEW_ADMIN, "View Admin", "Open the Admin page: usage, content and sync status."),
    (Perm.MANAGE_USERS, "Manage users & groups", "Create groups, add members, set permissions."),
]
ALL = frozenset(p.value for p in Perm)

ADMINS, EMPLOYEES, PARTNERS = "administrators", "ptc-employees", "partners"

#: The Admin page's own permissions, which a local run does not get for free.
_ADMIN_ONLY = frozenset({Perm.VIEW_ADMIN.value, Perm.MANAGE_USERS.value})

_EMPLOYEE_DEFAULT = [Perm.VIEW_HUB, Perm.PREVIEW, Perm.DOWNLOAD, Perm.INTERNAL,
                     Perm.CREATE_DEMO]
_PARTNER_DEFAULT = [Perm.VIEW_HUB, Perm.PREVIEW, Perm.DOWNLOAD]

BUILTIN = {
    ADMINS: {"name": "Administrators", "auto": None,
             "description": "Every permission. Also everyone in HUB_ADMIN_EMAILS.",
             "permissions": sorted(ALL)},
    EMPLOYEES: {"name": "PTC employees", "auto": "members",
                "description": "Everyone who signs in with a PTC account.",
                "permissions": [p.value for p in _EMPLOYEE_DEFAULT]},
    PARTNERS: {"name": "Partners", "auto": "guests",
               "description": "Everyone who signs in with a guest account.",
               "permissions": [p.value for p in _PARTNER_DEFAULT]},
}

_lock = threading.RLock()
#: (path, mtime) -> state; checked on every request, so read once per change.
_cache: dict = {}


class AccessError(ValueError):
    """A change the rules do not allow; the message is for the Admin page."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _owned(name: str) -> str:
    return os.path.join(settings.data_dir, "owned", name)


def _norm_email(value: str | None) -> str:
    return (value or "").strip().lower()


_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _clean_perms(values) -> list[str]:
    return sorted({str(v) for v in values or []} & ALL)


# ───────────────────────────────────────────────────────────────── the store
def _defaults() -> dict:
    return {"groups": [dict(id=gid, builtin=True, members=[], **spec)
                       for gid, spec in BUILTIN.items()]}


def _normalise(state: dict) -> dict:
    """Built-ins always present and in front, Administrators always complete."""
    groups = [g for g in state.get("groups") or [] if isinstance(g, dict) and g.get("id")]
    by_id = {g["id"]: g for g in groups}
    out = []
    for gid, spec in BUILTIN.items():
        g = by_id.pop(gid, None) or dict(id=gid, members=[], permissions=spec["permissions"])
        g.update(builtin=True, auto=spec["auto"], name=spec["name"],
                 description=spec["description"])
        if gid == ADMINS:
            g["permissions"] = sorted(ALL)
        if spec["auto"]:
            g["members"] = []
        out.append(g)
    for g in groups:
        if g["id"] in by_id:
            g.update(builtin=False, auto=None)
            out.append(g)
    for g in out:
        g["permissions"] = _clean_perms(g.get("permissions"))
        g["members"] = sorted({_norm_email(m) for m in g.get("members") or [] if _norm_email(m)})
        g.setdefault("description", "")
    return {**state, "groups": out}


def load_state() -> dict:
    path = _owned(STATE_FILE)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return _normalise(_defaults())
    cached = _cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        with open(path, encoding="utf-8") as fh:
            state = _normalise(json.load(fh) or {})
    except (OSError, ValueError):
        log.exception("could not read %s; using the built-in groups", path)
        return _normalise(_defaults())
    _cache[path] = (mtime, state)
    return state


def _save(state: dict, actor: str) -> dict:
    from backend.repositories.json_repo import _atomic_write   # the one safe writer
    state = _normalise({**state, "changed_by": actor, "changed_at": _now()})
    _atomic_write(_owned(STATE_FILE), state)
    _cache.pop(_owned(STATE_FILE), None)
    return state


def _audit(actor: str, action: str, group: dict, **detail) -> None:
    path = _owned(AUDIT_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    entry = {"at": _now(), "actor": actor, "action": action,
             "group": group.get("id"), "group_name": group.get("name"), **detail}
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    log.info("access: %s %s %s by %s", action, group.get("id"), detail, actor)


def audit_log(limit: int = 200) -> list[dict]:
    """Newest first."""
    try:
        with open(_owned(AUDIT_FILE), encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return []
    out = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
        if len(out) >= limit:
            break
    return out


def _group(state: dict, group_id: str) -> dict:
    for g in state["groups"]:
        if g["id"] == group_id:
            return g
    raise KeyError(group_id)


def _slug(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "group"
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    return slug


def _check_members(members) -> list[str]:
    cleaned = sorted({_norm_email(m) for m in members or [] if _norm_email(m)})
    bad = [m for m in cleaned if not _EMAIL.match(m)]
    if bad:
        raise AccessError(f"Not an email address: {', '.join(bad)}")
    return cleaned


def create_group(name: str, description: str, permissions, members, actor: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise AccessError("A group needs a name.")
    with _lock:
        state = load_state()
        if any(g["name"].lower() == name.lower() for g in state["groups"]):
            raise AccessError(f"There is already a group called {name!r}.")
        group = {"id": _slug(name, {g["id"] for g in state["groups"]}), "name": name,
                 "description": (description or "").strip(),
                 "permissions": _clean_perms(permissions),
                 "members": _check_members(members)}
        state = _save({**state, "groups": state["groups"] + [group]}, actor)
        _audit(actor, "create", group, permissions=group["permissions"],
               members=group["members"])
        return _group(state, group["id"])


def update_group(group_id: str, actor: str, *, name: str | None = None,
                 description: str | None = None, permissions=None, members=None) -> dict:
    with _lock:
        state = load_state()
        group = dict(_group(state, group_id))
        changes: dict = {}
        if name is not None and not group["builtin"]:
            name = name.strip()
            if not name:
                raise AccessError("A group needs a name.")
            if any(g["name"].lower() == name.lower() and g["id"] != group_id
                   for g in state["groups"]):
                raise AccessError(f"There is already a group called {name!r}.")
            if name != group["name"]:
                changes["name"] = {"from": group["name"], "to": name}
                group["name"] = name
        if description is not None and not group["builtin"]:
            group["description"] = description.strip()
        if permissions is not None:
            if group_id == ADMINS:
                raise AccessError("Administrators always have every permission.")
            new = _clean_perms(permissions)
            added, removed = sorted(set(new) - set(group["permissions"])), \
                sorted(set(group["permissions"]) - set(new))
            if added or removed:
                changes["permissions"] = {"added": added, "removed": removed}
            group["permissions"] = new
        if members is not None:
            if group["auto"]:
                raise AccessError(f"{group['name']} is filled automatically at sign-in.")
            new = _check_members(members)
            added, removed = sorted(set(new) - set(group["members"])), \
                sorted(set(group["members"]) - set(new))
            if group_id == ADMINS and not new and not _bootstrap_admins():
                raise AccessError("Administrators cannot be left empty while "
                                  "HUB_ADMIN_EMAILS names nobody.")
            if added or removed:
                changes["members"] = {"added": added, "removed": removed}
            group["members"] = new
        if not changes:
            return _group(state, group_id)
        groups = [group if g["id"] == group_id else g for g in state["groups"]]
        state = _save({**state, "groups": groups}, actor)
        _audit(actor, "update", group, **changes)
        return _group(state, group_id)


def delete_group(group_id: str, actor: str) -> None:
    with _lock:
        state = load_state()
        group = _group(state, group_id)
        if group["builtin"]:
            raise AccessError(f"{group['name']} is built in and cannot be deleted.")
        _save({**state, "groups": [g for g in state["groups"] if g["id"] != group_id]}, actor)
        _audit(actor, "delete", group, permissions=group["permissions"],
               members=group["members"])


# ─────────────────────────────────────────────────────────── who is in what
def _bootstrap_admins() -> set[str]:
    return {_norm_email(e) for e in (settings.hub_admin_emails or "").split(",")
            if _norm_email(e)}


def _identities(user) -> set[str]:
    return {_norm_email(v) for v in (user.email, getattr(user, "username", None))
            if _norm_email(v)}


def groups_of(user, state: dict | None = None) -> list[dict]:
    """The groups a signed-in person belongs to. Nobody, for anyone else."""
    if not user.is_authenticated:
        return []
    state = state or load_state()
    me = _identities(user)
    out = []
    for g in state["groups"]:
        if g["auto"] == "members":
            hit = not user.is_partner
        elif g["auto"] == "guests":
            hit = user.is_partner
        else:
            hit = bool(me & set(g["members"]))
            if g["id"] == ADMINS:
                hit = hit or bool(me & _bootstrap_admins())
        if hit:
            out.append(g)
    return out


def permissions_of(user) -> frozenset[str]:
    if user.is_dev_principal:
        return ALL - _ADMIN_ONLY
    perms: set[str] = set()
    for g in groups_of(user):
        perms.update(g["permissions"])
    if user.can_curate:
        # AUTH_CURATOR_* -- the way in before groups existed.
        perms.add(Perm.EDIT_METADATA.value)
    return frozenset(perms)


#: The shared Admin sign-in: everything but writing SharePoint columns.
ADMIN_SESSION_PERMS = ALL - {Perm.EDIT_METADATA.value}


# ─────────────────────────────────────────────────────────── who signed in
def record_sign_in(*, oid: str, email: str | None, username: str | None,
                   name: str | None, external: bool) -> None:
    """Remember who has signed in, so the Admin page can offer them as members.

    Best effort: a failure here must never stop a sign-in."""
    try:
        from backend.repositories.json_repo import _atomic_write
        with _lock:
            users = known_users()
            by_oid = {u.get("oid"): u for u in users}
            entry = by_oid.get(oid) or {"oid": oid, "first_seen": _now()}
            entry.update(email=_norm_email(email) or None,
                         username=_norm_email(username) or None,
                         name=name, external=bool(external), last_seen=_now())
            by_oid[oid] = entry
            _atomic_write(_owned(USERS_FILE),
                          sorted(by_oid.values(), key=lambda u: u.get("last_seen") or "",
                                 reverse=True))
    except Exception:                                      # noqa: BLE001
        log.exception("could not record the sign-in of %s", oid)


def known_users() -> list[dict]:
    try:
        with open(_owned(USERS_FILE), encoding="utf-8") as fh:
            users = json.load(fh)
        return users if isinstance(users, list) else []
    except (OSError, ValueError):
        return []


@dataclass
class _Known:
    """A known user, shaped enough like CurrentUser for groups_of()."""
    email: str | None
    username: str | None
    external: bool
    is_authenticated: bool = True
    is_dev_principal: bool = False

    @property
    def is_partner(self) -> bool:
        from backend.auth import CurrentUser
        return CurrentUser(email=self.email or self.username,
                           external=self.external).is_partner


def users_view() -> list[dict]:
    """Everyone who has signed in, with the groups they fall into today."""
    state = load_state()
    out = []
    for u in known_users():
        groups = groups_of(_Known(u.get("email"), u.get("username"),
                                  bool(u.get("external"))), state)
        out.append({**u, "groups": [g["id"] for g in groups]})
    return out


def catalogue() -> list[dict]:
    return [{"id": p.value, "label": label, "description": text}
            for p, label, text in CATALOGUE]
