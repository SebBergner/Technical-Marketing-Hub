"""What /health checks (2026-11-26): that the data the Hub runs on is there.

It used to answer "ok" whatever state the app was in. Now it checks the two
things that matter and cost nothing to look at:

* DATA_DIR exists -- on Azure the Azure Files mount at /mnt/data;
* `owned/` inside it can be read. That folder is the Hub's own,
  irreplaceable data.

Where the storage is durable (outside the code folder, i.e. a mount), both
must be there: a mount that failed often leaves an empty directory at the
mount point, so a missing `owned/` fails as surely as an unreadable one.
Inside the code folder -- a local checkout -- neither exists before the
first write, and that is fine; an `owned/` that exists but cannot be read
still fails.

`storage_durable` is reported the way /api/debug/backend works it out,
for the platform's eyes; it does not fail the check. The answer names no
path and holds no data: /health is open to everyone.
"""
from __future__ import annotations

import os

from backend.config import BASE_DIR, settings


def storage_durable(data_dir: str) -> bool:
    """Outside the code folder: App Service's own disk under the code does
    not survive a redeploy (same rule as /api/debug/backend)."""
    return not os.path.abspath(data_dir).startswith(os.path.abspath(BASE_DIR))


def _readable(folder: str) -> bool:
    """Listing the first entry reads the directory itself, on the share,
    which os.access does not reliably do over SMB."""
    try:
        with os.scandir(folder) as entries:
            next(entries, None)
        return True
    except OSError:
        return False


def check() -> tuple[bool, dict]:
    """(healthy, body). `owned_readable` is None where there is no owned/."""
    data_dir = settings.data_dir
    durable = storage_durable(data_dir)
    exists = os.path.isdir(data_dir)
    owned = os.path.join(data_dir, "owned")
    owned_readable = _readable(owned) if exists and os.path.isdir(owned) else None
    if durable:
        # A mount: both must be there, or the mount is not.
        ok = exists and owned_readable is True
    else:
        # The code folder: a checkout before its first write has neither.
        ok = owned_readable is not False
    return ok, {"status": "ok" if ok else "fail", "storage_durable": durable,
                "checks": {"data_dir": exists, "owned_readable": owned_readable}}
