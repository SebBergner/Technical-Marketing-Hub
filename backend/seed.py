"""Load the seed catalogue into whichever repository is configured.

Writes the two groups through different paths, because they are different kinds
of data:

  * mirror -> repo.replace_source_rows()  — the sanctioned mirror writer
  * owned  -> the repository's owned-data setters

When Graph sync arrives it will call exactly the same `replace_source_rows` and
will not touch owned data at all. Seeding is a rehearsal of the real sync path,
not a special case.
"""
from __future__ import annotations

import json
import os

from backend.config import settings
from backend.models import Asset
from backend.repositories.base import AssetRepository

SEED_SOURCE = "seed"


def load_seed(repo: AssetRepository, path: str | None = None) -> dict[str, int]:
    path = path or settings.seed_path
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"seed file not found: {path}\nRun: python scripts/extract_seed.py"
        )

    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)

    assets = [Asset.model_validate(record) for record in raw]

    # ---- mirror ----------------------------------------------------------
    written = repo.replace_source_rows(assets, source_system=SEED_SOURCE)

    # ---- Portal-owned ----------------------------------------------------
    curation = roadmaps = stats = 0
    for record, asset in zip(raw, assets):
        rails = record.get("rails") or []
        pick = bool(record.get("is_editor_pick"))
        if rails or pick:
            repo.set_curation(asset.id, rails=rails, is_editor_pick=pick)
            curation += 1

        counters = asset.stats
        if any((counters.views, counters.downloads, counters.launches, counters.shares)):
            repo.set_stats(asset.id, counters.model_dump())
            stats += 1

        if vr := record.get("value_roadmap"):
            repo.set_roadmap(asset.id, vr)
            roadmaps += 1

    return {"assets": written, "curation": curation, "stats": stats, "roadmaps": roadmaps}
