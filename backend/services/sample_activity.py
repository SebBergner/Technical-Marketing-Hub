"""Sample activity for demonstrating Hub activity (Liwei, 2026-10-14).

The Hub activity page is a team showcase, but per-person usage has only been
recorded since 2026-10-09, so on a fresh deployment it is nearly empty. This
writes a believable sample -- and keeps it impossible to mistake for, or
mix up with, real data:

* every event carries `"synthetic": true`; the Admin usage page and the Hub
  activity page show a banner whenever a period contains one;
* it goes to its own file, `owned/usage_events.demo.jsonl` (the file
  scripts/seed_usage_events.py introduced), never the real log; the
  repository merges the two on read, and removing the sample is deleting
  that one file;
* the people are made up and say so -- "Sample User 01" at the reserved
  `.invalid` domain -- so no real colleague is credited with activity they
  never had. The demos are real, so "most used content" and "whose demos
  were used most" have something to show; the banner says the numbers are
  not.
"""
from __future__ import annotations

import json
import os
import random
from datetime import datetime, timedelta, timezone

from backend.repositories.base import AssetQuery

DEMO_FILE = "usage_events.demo.jsonl"
SAMPLE_DOMAIN = "sample.invalid"
QUERIES = ["windchill", "creo parametric", "codebeamer requirements", "servicemax",
           "digital thread", "mathcad", "creo illustrate", "jetstream", "orbit",
           "model based definition", "bobcat", "ai assistant", "onshape", "kepware opc"]


def sample_people(n: int = 24) -> list[str]:
    return [f"sample.user.{i:02d}@{SAMPLE_DOMAIN}" for i in range(1, n + 1)]


def _path(repo) -> str:
    return os.path.join(repo.owned_dir, DEMO_FILE)


def creators_available(repo) -> int:
    """How many listed demos have a known creator."""
    return sum(1 for a in repo.list(AssetQuery(limit=10 ** 6)).items if a.creator)


def loaded(repo) -> bool:
    return os.path.exists(_path(repo))


def remove(repo) -> bool:
    try:
        os.remove(_path(repo))
        return True
    except FileNotFoundError:
        return False


def generate(repo, *, days: int = 90, events: int = 2600, seed: int | None = None,
             now: datetime | None = None) -> int:
    """Write the sample (replacing an earlier one); returns how many events.

    The demos it uses are picked from those with a known creator, so "whose
    demos were used most" has something to rank. Creators are written by a
    full sync; with none yet, any demo is used, and the sample is worth
    loading again after that sync (see creators_available())."""
    rng = random.Random(seed)
    now = now or datetime.now(timezone.utc)
    assets = repo.list(AssetQuery(limit=10 ** 6)).items
    if not assets:
        return 0
    # A handful of demos carry most of the traffic, as in real catalogues;
    # kits with a known creator first, so the creator ranking has content.
    rng.shuffle(assets)
    with_creator = [a for a in assets if a.creator] or assets
    popular = with_creator[:14]
    middling = with_creator[14:80] or with_creator
    people = sample_people()
    # Some people use the Hub every day, most now and then.
    weights = [max(1.0, 30 / (i + 1) ** 0.9) for i in range(len(people))]

    def pick_asset():
        roll = rng.random()
        if roll < 0.5:
            return rng.choice(popular)
        if roll < 0.88:
            return rng.choice(middling)
        return rng.choice(assets)

    lines = []
    for _ in range(events):
        day = int(abs(rng.gauss(0, days / 2.4))) % days
        when = now - timedelta(days=day, hours=rng.randint(0, 9), minutes=rng.randint(0, 59))
        if when.weekday() >= 5 and rng.random() < 0.7:
            when -= timedelta(days=2)              # quieter weekends
        who = ({"external": True} if rng.random() < 0.06
               else {"user": rng.choices(people, weights)[0]})
        roll = rng.random()
        if roll < 0.14:
            entry = {"event": "search", "q": rng.choice(QUERIES), "results": rng.randint(0, 40)}
        else:
            asset = pick_asset()
            kind = "view" if roll < 0.7 else "preview" if roll < 0.86 else "download"
            entry = {"event": kind, "asset_id": asset.id}
        entry.update(at=when.isoformat(timespec="seconds"), synthetic=True, **who)
        lines.append(entry)
    lines.sort(key=lambda e: e["at"])
    os.makedirs(repo.owned_dir, exist_ok=True)
    with open(_path(repo), "w", encoding="utf-8", newline="\n") as fh:
        fh.writelines(json.dumps(e, ensure_ascii=False) + "\n" for e in lines)
    return len(lines)
