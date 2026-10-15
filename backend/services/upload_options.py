"""Which options Create New Demo offers, in what order, with what default
(Admin -> Metadata options; Liwei, 2026-10-15).

The options themselves are SharePoint's: a choice column's choices, or for
the Demo Catalog's products the terms its demos carry (upload_writer). An
option is added in SharePoint; here it is offered or not, ordered, and made
the default. The Hub's own rules come first and cannot be undone here: a
product PTC no longer sells, and the retired segments, are never offered.

Kept in owned/upload_options.json, applied every time the form or a new
demo's metadata is read -- so a change is live at once, whatever the
libraries' cache holds.
"""
from __future__ import annotations

import json
import os
import threading

FILE = "upload_options.json"
_lock = threading.Lock()

#: What can be managed: key -> (label, choices_from, targets it applies to,
#: single choice?). Products differ per library, so one entry each.
MANAGED = {
    "products@demo_catalog": ("Products — Demo Catalog", "products", ("demo_catalog",), False),
    "products@demo_video": ("Products — Demo Video", "products", ("demo_video",), False),
    "Segment": ("Segment", "Segment", ("demo_catalog", "demo_video"), False),
    "Language": ("Language", "Language", ("demo_catalog",), True),
    "Owned_x0020_By": ("Owned by", "Owned_x0020_By", ("demo_catalog",), True),
}


class OptionsError(ValueError):
    """A setting the rules refuse; the message is for the Admin page."""


def _path(repo) -> str:
    return os.path.join(repo.owned_dir, FILE)


def load(repo) -> dict:
    try:
        with open(_path(repo), encoding="utf-8") as fh:
            value = json.load(fh)
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}


def key_for(target: str, choices_from: str) -> str | None:
    """The MANAGED key a target's field is governed by, if any."""
    for key, (_, source, targets, _) in MANAGED.items():
        if source == choices_from and target in targets:
            return key
    return None


def apply(repo, target: str, choices: dict) -> tuple[dict, dict]:
    """(choices as offered, defaults) for one target: hidden ones out, the
    chosen order first then SharePoint's, the chosen default."""
    settings_ = load(repo)
    out, defaults = dict(choices), {}
    for source, options in choices.items():
        key = key_for(target, source)
        rule = settings_.get(key) if key else None
        if not rule:
            continue
        hidden = set(rule.get("hidden") or [])
        order = [o for o in rule.get("order") or [] if o in options and o not in hidden]
        out[source] = order + [o for o in options if o not in hidden and o not in order]
        if rule.get("default") in out[source]:
            defaults[source] = rule["default"]
    return out, defaults


def save(repo, key: str, *, hidden: list[str], order: list[str], default: str | None,
         offered_now: list[str], actor: str) -> dict:
    """offered_now: the options SharePoint has today (after the Hub's own
    rules), so a setting can only name real ones."""
    if key not in MANAGED:
        raise OptionsError("No such field.")
    label, _, _, single = MANAGED[key]
    real = set(offered_now)
    hidden = sorted({h for h in hidden or [] if h in real})
    order = [o for o in dict.fromkeys(order or []) if o in real]
    if len(real - set(hidden)) == 0:
        raise OptionsError(f"{label}: keep at least one option offered.")
    if default and (not single or default not in real or default in hidden):
        raise OptionsError(f"{label}: the default must be an offered option of a single-choice field.")
    from datetime import datetime, timezone
    with _lock:
        state = load(repo)
        state[key] = {"hidden": hidden, "order": order, "default": default or None,
                      "by": actor, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        from backend.repositories.json_repo import _atomic_write
        _atomic_write(_path(repo), state)
    return state[key]
