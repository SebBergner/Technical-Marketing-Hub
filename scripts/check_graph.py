#!/usr/bin/env python
"""Verify Microsoft Graph access to the SharePoint site.

READ-ONLY by default. Nothing is created, modified or deleted.

RUN THIS FIRST when IT delivers the app registration. `Sites.Selected` is a
two-step grant and step 2 is easy to miss; when it is missed you get a perfectly
valid token followed by 403 on every call, which looks exactly like a bug in our
code. This script tells the two apart in one go.

Usage, from the repo root:
    python scripts/check_graph.py                # verify access
    python scripts/check_graph.py --drives       # also list document libraries
    python scripts/check_graph.py --sample 10    # also inspect top-level folders
    python scripts/check_graph.py --columns      # dump the real column names
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from backend.config import settings                                    # noqa: E402
from backend.integrations.graph.client import GraphError, get_graph_client   # noqa: E402

RULE = "─" * 76


def head(text: str) -> None:
    print(f"\n{RULE}\n{text}\n{RULE}")


def show_config() -> bool:
    head("CONFIGURATION")
    rows = [
        ("GRAPH_TENANT_ID", settings.graph_tenant_id, False),
        ("GRAPH_CLIENT_ID", settings.graph_client_id, False),
        ("GRAPH_CLIENT_SECRET", settings.graph_client_secret, False),
        ("GRAPH_SITE_URL", settings.graph_site_url, True),
        ("GRAPH_LIST_NAME", settings.graph_list_name, True),
    ]
    for name, value, showable in rows:
        if not value:
            print(f"  {name:<24} (not set)")
        elif showable:
            print(f"  {name:<24} {value}")
        else:
            print(f"  {name:<24} set, {len(value)} chars ending …{value[-4:]}")

    if not settings.graph_configured:
        print("\n  Not configured — tenant id, client id and secret are all required.")
        print("  Pending the Entra ID app registration request to IT.")
        print("  See: C:\\Work\\TDD Hub\\IT_Request_Graph_App_Registration.md")
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drives", action="store_true", help="list document libraries")
    parser.add_argument("--sample", type=int, metavar="N",
                        help="inspect the first N top-level folders")
    parser.add_argument("--columns", action="store_true",
                        help="dump the real column internal names (fixes the mapping)")
    args = parser.parse_args()

    if not show_config():
        return 1

    client = get_graph_client()

    # ------------------------------------------------------------- verify
    head("ACCESS  (token, then site, then the per-site grant)")
    try:
        result = client.verify_access()
    except GraphError as exc:
        print(f"  FAILED: {exc}")
        return 1

    token = result.get("token", {})
    print(f"  token        {'ok' if token.get('ok') else 'FAILED — ' + str(token.get('error'))}")
    if not token.get("ok"):
        print(f"\n  {result.get('diagnosis')}")
        return 1

    site = result.get("site", {})
    if not site.get("ok"):
        print(f"  site         FAILED — {site.get('error')}")
        print(f"\n  >>> {result.get('diagnosis')}")
        print("\n  Ask IT to run, for this app:")
        print("      POST https://graph.microsoft.com/v1.0/sites/{siteId}/permissions")
        print('      { "roles": ["write"], "grantedToIdentities": [ ... ] }')
        return 1

    print(f"  site         ok  {site.get('name')}  ({site.get('web_url')})")
    print(f"  site_id      {site.get('site_id')}")
    perms = result.get("permissions", {})
    if perms.get("ok"):
        print(f"  permissions  roles={perms.get('roles')}  ({perms.get('count')} grant(s))")
    else:
        print(f"  permissions  could not list — {perms.get('note', '')}")
    print(f"\n  >>> {result.get('diagnosis')}")

    site_id = site["site_id"]

    # ------------------------------------------------------------- drives
    if args.drives or args.sample or args.columns:
        head("DOCUMENT LIBRARIES")
        try:
            drives = client.list_drives(site_id)
        except GraphError as exc:
            print(f"  FAILED: {exc}")
            return 1
        for drive in drives:
            marker = " <- target" if (drive.name or "") == settings.graph_list_name else ""
            print(f"  {drive.name}{marker}")

        target = client.find_drive(site_id, settings.graph_list_name)
        if target is None:
            print(f"\n  '{settings.graph_list_name}' not found. "
                  f"Set GRAPH_LIST_NAME to one of the names above.")
            return 1

        # ---------------------------------------------------------- sample
        if args.sample or args.columns:
            head(f"TOP-LEVEL FOLDERS  (an asset is one of these with a Demo Type)")
            try:
                children = client.list_children(target.drive_id, "root")
            except GraphError as exc:
                print(f"  FAILED: {exc}")
                return 1

            folders = [c for c in children if "folder" in c]
            with_fields = [c for c in folders
                           if (c.get("listItem") or {}).get("fields")]
            print(f"  {len(children)} children, {len(folders)} folders, "
                  f"{len(with_fields)} with columns expanded")

            if args.columns and with_fields:
                head("REAL COLUMN INTERNAL NAMES  (correct sync.py COLUMNS with these)")
                fields = (with_fields[0].get("listItem") or {}).get("fields", {})
                for key in sorted(fields):
                    value = str(fields[key])[:56]
                    print(f"  {key:<34} {value}")
                print("\n  Graph returns INTERNAL names, not display names. If Demo Type "
                      "\n  appears as something other than what backend/integrations/graph/"
                      "\n  sync.py COLUMNS expects, add it there.")

            if args.sample:
                for child in folders[:args.sample]:
                    fields = (child.get("listItem") or {}).get("fields", {})
                    demo_type = next((fields[k] for k in
                                      ("DemoType", "Demo_x0020_Type", "Demo Type")
                                      if k in fields), None)
                    flag = "asset" if demo_type else "  -  "
                    print(f"  [{flag}] {str(child.get('name'))[:58]}")

    head("DONE — no data was created or modified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
