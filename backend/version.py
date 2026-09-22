"""The version string shown in the sidebar, and where each part comes from.

`vYEAR.X.Y`, following the scheme Seb already uses on AMP:

* **YEAR.X** live in the `VERSION` file at the repository root. `X` is bumped
  by hand, once, each time staging is swapped into production — it answers
  "which release of the Hub am I looking at".
* **Y** is the GitHub Actions run number, written into `BUILD_NUMBER` by the
  deploy workflow. It moves on every deploy, so two people on the same
  release can still say which build they are on.

Why `Y` is not also manual: the whole point of putting a version on screen is
that a tester reporting "the filter is broken" can say which code they were
running. A number somebody has to remember to increment is a number that is
sometimes wrong, and a version that is sometimes wrong is worse than none —
it sends you looking at the wrong commit with confidence.

Outside a deploy there is no run number, so `Y` is absent and the string ends
at the release: a local checkout reads `v2026.1-dev`, which cannot be
mistaken for something that was ever deployed.
"""
from __future__ import annotations

import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(name: str) -> str:
    """A missing or unreadable file is not worth failing a request over: the
    version is a label, and a page that would not load because it could not
    find one would be a self-inflicted outage."""
    try:
        with open(os.path.join(BASE_DIR, name), encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def app_version() -> str:
    release = _read("VERSION") or "0.0"
    build = _read("BUILD_NUMBER") or os.getenv("BUILD_NUMBER", "")
    return f"v{release}.{build}" if build else f"v{release}-dev"
