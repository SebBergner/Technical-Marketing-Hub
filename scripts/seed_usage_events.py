"""Write a synthetic usage log, so the Admin page can be judged with the
shapes it will really have to draw.

WHY THIS IS SAFE TO RUN, AND HOW TO BE SURE IT STAYS SAFE
---------------------------------------------------------
Every event it writes carries `"synthetic": true`. The Admin page checks for
that flag and shows a red banner over any window containing one, so a made-up
figure can never be read as a measurement — which is the rule this project
runs on (`docs/HANDOVER-DEVELOPMENT.md` §1.2, and the reason "measure, don't
guess" is written down at all).

Two further guards:

* it writes under `data/runtime/owned/`, which is gitignored, so a synthetic
  log cannot reach the repository by accident;
* to remove it, keep the real events and drop the rest:

      grep -v '"synthetic": true' usage_events.jsonl > clean.jsonl

  Do that before uploading `owned/` to any Azure Files share. Nothing in the
  app deletes these for you.

Usage:  python scripts/seed_usage_events.py [--days 120] [--events 4000]
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import settings                                  # noqa: E402

#: Searches a technical demo team plausibly runs. The zero-result ones are
#: real gaps in the current catalogue, so the page's "we have nothing for
#: this" list shows something recognisable rather than noise.
QUERIES_WITH_HITS = [
    "windchill", "creo parametric", "codebeamer requirements", "servicemax",
    "plm overview", "digital thread", "mathcad", "creo illustrate",
    "jetstream", "orbit", "teaser", "walkthrough",
]
QUERIES_WITHOUT_HITS = [
    "onshape", "arena plm", "kepware opc", "vuforia expert capture",
    "sustainability reporting", "windchill 14", "arbortext editor training",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument("--events", type=int, default=4000)
    parser.add_argument("--seed", type=int, default=20260921)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    mirror_dir = os.path.join(settings.data_dir, "mirror")
    owned_dir = os.path.join(settings.data_dir, "owned")

    assets: list[dict] = []
    for name in ("sharepoint.json", "consensus.json"):
        path = os.path.join(mirror_dir, name)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                assets.extend(json.load(fh))
    if not assets:
        print("no mirror data to base a synthetic log on — sync first")
        return 1

    # The mirror is not the catalogue. Divested products and retired items are
    # filtered out on every read the app makes (json_repo._load_mirror), so
    # seeding straight from the files invents traffic for 139 assets that no
    # page can show — which surfaced as a phantom "(no longer in the
    # catalogue)" row holding 16% of all views. Ask the repository what it
    # actually serves.
    from backend.deps import get_repo                              # noqa: E402
    from backend.repositories.base import AssetQuery               # noqa: E402
    live = {a.id for a in get_repo().list(AssetQuery(limit=10 ** 6)).items}
    dropped = len(assets)
    assets = [a for a in assets if a.get("id") in live]
    dropped -= len(assets)
    if dropped:
        print(f"skipped {dropped} mirror rows the catalogue does not serve")
    if not assets:
        print("no live assets to base a synthetic log on")
        return 1

    # A realistic catalogue is not browsed evenly: a handful of demos carry
    # most of the traffic. Without that skew every chart is a flat line and
    # the page looks like it works when it has not been tested on anything.
    rng.shuffle(assets)
    popular = assets[:12]
    middling = assets[12:90]

    def pick_asset() -> dict:
        roll = rng.random()
        if roll < 0.55:
            return rng.choice(popular)
        if roll < 0.9 and middling:
            return rng.choice(middling)
        return rng.choice(assets)

    now = datetime.now()
    lines: list[str] = []
    for _ in range(args.events):
        # Weighted towards recent days, so "this week" is never empty while
        # "this year" still has depth behind it.
        day_offset = int(abs(rng.gauss(0, args.days / 2.2))) % args.days
        when = now - timedelta(days=day_offset,
                               hours=rng.randint(0, 23),
                               minutes=rng.randint(0, 59))
        # Working hours, roughly: a flat 24-hour spread would be the giveaway
        # that nobody looked at this data before drawing it.
        if when.hour < 7 and rng.random() < 0.8:
            when += timedelta(hours=rng.randint(7, 11))

        roll = rng.random()
        if roll < 0.12:
            hit = rng.random() > 0.25
            query = rng.choice(QUERIES_WITH_HITS if hit else QUERIES_WITHOUT_HITS)
            event = {"event": "search", "q": query,
                     "results": rng.randint(1, 60) if hit else 0}
        else:
            asset = pick_asset()
            resources = [r for r in (asset.get("resources") or []) if r.get("item_id")]
            # The funnel that makes the page worth having: everyone who
            # downloads opened the page first, most people who open it do not
            # download, and previews sit in between.
            if roll < 0.72 or not resources:
                event = {"event": "view", "asset_id": asset["id"]}
            else:
                resource = rng.choice(resources)
                event = {
                    "event": "download" if roll > 0.88 else "preview",
                    "asset_id": asset["id"],
                    "item_id": resource["item_id"],
                    "file": resource.get("name"),
                    "kind": resource.get("kind"),
                }
        event["at"] = when.isoformat(timespec="seconds")
        event["synthetic"] = True
        lines.append(json.dumps(event, ensure_ascii=False))

    lines.sort(key=lambda line: json.loads(line)["at"])
    os.makedirs(owned_dir, exist_ok=True)
    path = os.path.join(owned_dir, "usage_events.jsonl")
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")

    print(f"appended {len(lines)} synthetic events to {path}")
    print("every one is tagged \"synthetic\": true — the Admin page will say so.")
    print("remove with:  grep -v '\"synthetic\": true' usage_events.jsonl > clean.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
