"""Writing the Hub's own files safely when several workers share them.

App Service runs several gunicorn workers on one Azure Files share
(DATA_DIR). A threading lock only covers its own process, so before
2026-11-04 two workers could:

* write the same `<file>.tmp` at once, leaving a mix of both that a reader
  then took for an empty file (`json_repo._read` returns its default on a
  parse error), so the next write kept a single entry; and
* each read a file, change it, and write it back, so one change was lost.

The stress test of 2026-11-06 (20 people at once, signing in together) made
both likely for the files written while people browse: who has signed in,
who is active, and the GXC personal-link codes (a lost code breaks every
link that person already sent).

`temp_path` gives every write its own temporary file, and `locked` is a
lock across processes for a read-modify-write: a lock file created with
O_EXCL next to the file, as `auto_sync` and `migration_jobs` already do on
the same share. A lock older than STALE_SECONDS was left by a worker that
died mid-write and is taken over -- what it guards takes milliseconds.
"""
from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from contextlib import contextmanager
from typing import Iterator

log = logging.getLogger(__name__)

STALE_SECONDS = 10.0
WAIT_SECONDS = 15.0

_registry_lock = threading.Lock()
#: lock-file path -> (this process's lock for it, per-thread depth)
_held: dict[str, tuple[threading.RLock, threading.local]] = {}


def temp_path(path: str) -> str:
    """A temporary file beside `path` that no other writer will pick:
    os.replace from it is atomic, and two writers never share it."""
    return f"{path}.{os.getpid()}.{secrets.token_hex(4)}.tmp"


def replace_with(path: str, write) -> None:
    """Write `path` through its own temporary file: `write(fh)` fills it,
    then it replaces `path` in one step. The temporary file is removed if
    writing fails."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = temp_path(path)
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            write(fh)
        replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def replace(tmp: str, path: str) -> None:
    """os.replace, tried again for up to a second while another process has
    `path` open: Windows refuses then, and so can an SMB share like Azure
    Files (measured locally 2026-11-04 with six processes). A reader holds
    it for milliseconds."""
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.05)


def _entry(lock_path: str) -> tuple[threading.RLock, threading.local]:
    with _registry_lock:
        entry = _held.get(lock_path)
        if entry is None:
            entry = _held[lock_path] = (threading.RLock(), threading.local())
        return entry


def _take(lock_path: str, wait: float) -> None:
    deadline = time.monotonic() + wait
    pause = 0.005
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                age = time.time() - os.path.getmtime(lock_path)
            except OSError:
                continue                    # released between the two calls
            if age > STALE_SECONDS:
                log.warning("taking over %s, left %.0f s ago", lock_path, age)
                try:
                    os.remove(lock_path)
                except OSError:
                    pass
                continue
            if time.monotonic() > deadline:
                raise TimeoutError(f"{lock_path} is held by another worker")
            time.sleep(pause)
            pause = min(pause * 2, 0.1)
            continue
        with os.fdopen(fd, "w") as fh:
            fh.write(f"{os.getpid()}")
        return


@contextmanager
def locked(path: str, wait: float = WAIT_SECONDS) -> Iterator[None]:
    """Hold `path`'s lock across every worker for a read-modify-write.

    Re-entrant within a thread, so a function holding it may call another
    that takes it too."""
    lock_path = path + ".lock"
    rlock, local = _entry(lock_path)
    with rlock:
        depth = getattr(local, "depth", 0)
        if depth == 0:
            os.makedirs(os.path.dirname(lock_path) or ".", exist_ok=True)
            _take(lock_path, wait)
        local.depth = depth + 1
        try:
            yield
        finally:
            local.depth -= 1
            if local.depth == 0:
                try:
                    os.remove(lock_path)
                except OSError:
                    pass
