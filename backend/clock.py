"""The Hub's one clock.

Naive UTC everywhere: stored timestamps are written without an offset, and
mixing aware and naive values is a classic source of silent comparison bugs.
Lived in `tables.py` with the SQLAlchemy models until those were removed
(2026-11-28, optimisation plan WS-F).
"""
from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Now, as naive UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
