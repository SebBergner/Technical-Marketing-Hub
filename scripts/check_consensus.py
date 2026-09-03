#!/usr/bin/env python
"""Verify the connection to a live Consensus tenant.

READ-ONLY. This script never creates, sends or modifies anything. It calls:

    POST /api/integr/v1.0/info/userInfo     — confirms credentials
    POST /api/integr/v1.0/demo/search       — one page, to inspect the real shape

Nothing else. No DemoBoards are created and no emails go anywhere.

Usage, from the repo root:

    python scripts/check_consensus.py              # probe + field mapping
    python scripts/check_consensus.py --demos 20   # also list demos
    python scripts/check_consensus.py --reconcile  # compare against the catalogue
    python scripts/check_consensus.py --raw        # dump one full raw record
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys

# Run directly (`python scripts/check_consensus.py`), so the repo root is not
# on sys.path yet.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from backend.config import settings                                    # noqa: E402
from backend.integrations.consensus import (                           # noqa: E402
    ConsensusError, HttpConsensusClient, get_consensus_client,
)

RULE = "─" * 74


def head(text: str) -> None:
    print(f"\n{RULE}\n{text}\n{RULE}")


def show_config() -> bool:
    head("CONFIGURATION")
    rows = [
        ("CONSENSUS_BASE_URL", settings.consensus_base_url, True),
        ("CONSENSUS_API_KEY", settings.consensus_api_key, False),
        ("CONSENSUS_API_SECRET", settings.consensus_api_secret, False),
        ("CONSENSUS_USER_EMAIL", settings.consensus_user_email, True),
        ("CONSENSUS_SOURCE_NAME", settings.consensus_source_name, True),
        ("CONSENSUS_VIEWER_URL_TEMPLATE", settings.consensus_viewer_url_template, True),
    ]
    for name, value, showable in rows:
        if not value:
            print(f"  {name:<32} (not set)")
        elif showable:
            print(f"  {name:<32} {value}")
        else:
            print(f"  {name:<32} set, {len(value)} chars ending …{value[-4:]}")

    if not settings.consensus_configured:
        print("\n  Not configured — base_url, api_key, api_secret and user_email are all")
        print("  required. Create a .env in the repo root (see .env.example).")
        print("  Without them the app runs on the offline stub.")
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demos", type=int, metavar="N", help="list the first N demos")
    parser.add_argument("--reconcile", action="store_true",
                        help="compare Consensus against the local catalogue")
    parser.add_argument("--raw", action="store_true", help="dump one full raw demo record")
    parser.add_argument("--limit", type=int, default=2000, metavar="N",
                        help="max demos to pull for --reconcile (default 2000)")
    parser.add_argument("--include-unpublished", action="store_true",
                        help="include unpublished demos (default: published only)")
    args = parser.parse_args()

    if not show_config():
        return 1

    client = get_consensus_client()
    if not isinstance(client, HttpConsensusClient):
        print("\n  Still resolved to the stub — check the .env location.")
        return 1

    # ---------------------------------------------------------------- probe
    head("PROBE  (userInfo, then one demo/search)")
    try:
        result = client.probe()
    except ConsensusError as exc:
        print(f"  FAILED: {exc}")
        return 1

    auth = result.get("auth", {})
    if not auth.get("ok"):
        print(f"  AUTH FAILED: {auth.get('error')}")
        print("\n  Check api_key / api_secret / user_email. Note that user_email must be")
        print("  a real user in the tenant, not just any address.")
        return 1

    print(f"  auth ok        {auth.get('user_email')}  "
          f"({auth.get('display_name')}, group: {auth.get('group')})")

    search = result.get("demo_search", {})
    if not search.get("ok"):
        print(f"  demo/search FAILED: {search.get('error')}")
        return 1

    paging = search.get("paging") or {}
    print(f"  demo/search ok total demos visible: {paging.get('countItems', '?')}")

    # ------------------------------------------------- mapping verification
    head("FIELD MAPPING  (live response -> our model)")
    mapped, keys = search.get("mapped"), search.get("record_keys")
    if not mapped:
        print("  No demos returned, so the mapping could not be checked.")
    else:
        for field in ("uuid", "title", "description", "preview_link", "demo_type",
                      "created_at", "is_published", "owner_email", "folder", "language"):
            value = mapped.get(field)
            marker = " " if value not in (None, "", (), []) else "!"
            print(f" {marker} {field:<16} {str(value)[:52]}")
        print(f"\n  fields Consensus actually returned:\n    {', '.join(keys or [])}")
        missing = [f for f in ("uuid", "title") if not mapped.get(f)]
        if missing:
            print(f"\n  WARNING: {missing} did not map. Correct _to_demo() in "
                  f"backend/integrations/consensus.py against the raw record below.")

    if args.raw and search.get("sample"):
        head("RAW RECORD")
        print(json.dumps(search["sample"], indent=2, ensure_ascii=False)[:4000])

    # ---------------------------------------------------------------- demos
    if args.demos:
        head(f"DEMOS  (first {args.demos})")
        try:
            demos = client.list_demos(limit=args.demos)
        except ConsensusError as exc:
            print(f"  FAILED: {exc}")
            return 1
        print(f"  retrieved {len(demos)}\n")
        for demo in demos:
            created = demo.created_at.date() if demo.created_at else "—"
            print(f"  {demo.uuid}  {created}  {demo.title[:46]}")

    # ------------------------------------------------------------ reconcile
    if args.reconcile:
        head("RECONCILIATION  (Consensus vs the local catalogue)")
        from backend.db import SessionLocal
        from backend.repositories.base import AssetQuery
        from backend.repositories.sql_repo import SqlAssetRepository
        from backend.services.consensus_match import reconcile

        try:
            demos = client.list_demos(limit=args.limit,
                                      published_only=not args.include_unpublished)
        except ConsensusError as exc:
            print(f"  FAILED: {exc}")
            return 1

        with SessionLocal() as session:
            assets = SqlAssetRepository(session).list(AssetQuery(limit=1000)).items

        scope = "all" if args.include_unpublished else "published only"
        print(f"  local assets    {len(assets)}")
        print(f"  consensus demos {len(demos)}  ({scope}, limit {args.limit})")
        if len(demos) >= args.limit:
            print(f"  NOTE: hit the limit — there may be more. Re-run with a higher --limit.")
        print()

        report = reconcile(assets, demos)
        for key, count in report.summary().items():
            print(f"    {key:<16} {count}")

        if report.proposals:
            print("\n  PROPOSED matches (no UUID recorded yet) — review before accepting:")
            for m in report.proposals[:15]:
                print(f"    {m.confidence:.2f}  {m.asset_title[:44]}")
                print(f"          -> {m.demo.title[:44]}  ({m.demo.uuid})")
        if report.conflicts:
            print("\n  CONFLICTS — a recorded UUID disagrees with the best match:")
            for m in report.conflicts[:15]:
                print(f"    {m.asset_title[:42]}  ->  {m.demo.title[:42]}")
        if report.portal_only:
            print(f"\n  PORTAL ONLY ({len(report.portal_only)}) — cannot be shared externally:")
            for a in report.portal_only[:10]:
                print(f"    [{a.type.value:>5}] {a.title[:52]}")
        if report.consensus_only:
            print(f"\n  CONSENSUS ONLY ({len(report.consensus_only)}) — no Portal asset:")
            for d in report.consensus_only[:10]:
                print(f"    {d.uuid}  {d.title[:48]}")

    head("DONE — no data was created or modified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
