"""One report shape for every source.

Each sync grew its own vocabulary, and the two were impossible to compare:

    sharepoint   assets 455 · skipped_no_demo_type 295 · orphan_files 2745
    consensus    demos_seen 637 · indexed 491 · skipped_private 146

Worse, neither said whether a number was "how many changed" or "how many there
are". `indexed 491` after a Consensus sync is unreadable — 491 updated, or 491
in total and nothing happened?

So every sync answers the same four questions, in the same words:

    unchanged   did this run do anything at all?
    indexed     how many are in the index NOW  (a total, never a delta)
    examined    how many upstream things were considered
    skipped     what did not make it, and why

Source-specific numbers go under `details`, where they cannot be mistaken for
the headline.
"""
from __future__ import annotations

from typing import Any


def report(source: str, *, unchanged: bool, indexed: int, examined: int,
           skipped: dict[str, int], details: dict[str, Any]) -> dict:
    return {
        "source": source,
        "unchanged": unchanged,
        # Deliberately a total. "How many are there now" is the question a
        # person actually has after a sync, and a delta cannot answer it.
        "indexed": indexed,
        "examined": examined,
        "skipped": skipped,
        "skipped_total": sum(skipped.values()),
        "details": details,
    }


#: The keys every source must produce. A test asserts both syncs emit exactly
#: these, so the two reports cannot drift apart again.
KEYS = frozenset({"source", "unchanged", "indexed", "examined",
                  "skipped", "skipped_total", "details"})
