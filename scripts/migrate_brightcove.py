#!/usr/bin/env python
"""Move Brightcove Gallery videos into SharePoint (docs/brightcove-migration-plan.md).

Runs from a workstation, never from App Service: a batch takes hours, and
this machine measured 4.4-5.5 MB/s to SharePoint (2026-09-28).

Usage, from the repo root:

    python scripts/migrate_brightcove.py check   --library Gallery_Brightcove_Test
    python scripts/migrate_brightcove.py dry-run --library Gallery_Brightcove_Test --manifest m.csv
    python scripts/migrate_brightcove.py run     --library Gallery_Brightcove_Test --manifest m.csv --limit 5
    python scripts/migrate_brightcove.py resume  <batch id>

`check` and `dry-run` write nothing to SharePoint. `run` and `resume` write,
and only after the library passes every check:

  * the Demo Catalog is refused outright;
  * the production library (MIGRATION_BRIGHTCOVE_LIBRARY) is refused unless
    --allow-production is given -- for the reviewed pilot and batches only;
  * `run` asks you to type the library's name before the first write.

Every run leaves a batch log under DATA_DIR/owned/migration/brightcove/batches/,
which the /migration page lists and which is the record needed to undo a run.
The tool never deletes anything.
"""
from __future__ import annotations

import argparse
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from backend.config import settings                                    # noqa: E402
from backend.integrations.brightcove import get_brightcove_client     # noqa: E402
from backend.integrations.graph import migration_writer as w           # noqa: E402
from backend.integrations.graph.client import GraphError, get_graph_client  # noqa: E402
from backend.services import brightcove_runner as run                  # noqa: E402

RULE = "─" * 76


def head(text: str) -> None:
    print(f"\n{RULE}\n{text}\n{RULE}")


def connect(args):
    client = get_graph_client()
    if client is None:
        sys.exit("Graph is not configured (GRAPH_TENANT_ID / CLIENT_ID / CLIENT_SECRET).")
    try:
        target = w.LibraryTarget.resolve(client, args.library,
                                         # check and dry-run only read, so the
                                         # production guard -- which exists to
                                         # stop writes -- does not apply to them
                                         allow_production=(args.allow_production
                                                           or args.cmd in ("check", "dry-run")))
    except GraphError as exc:
        sys.exit(f"REFUSED: {exc}")
    terms = w.TermIndex.load(client, target.site_id, settings.migration_product_term_set)
    return client, target, terms


#: End-to-end rate from this workstation, Brightcove -> SharePoint streamed:
#: 212.9 MB in 97 s, measured 2026-09-29 (one video). Upload alone ran at
#: 4.4 MB/s (2026-09-28), so the Brightcove download through Zscaler halves
#: it. Used only to label an estimate.
MEASURED_MB_PER_S = 2.2


def brightcove_for(records):
    """A read-only Brightcove client when any record is fetched from it."""
    if not any(r.from_brightcove for r in records):
        return None
    bc = get_brightcove_client()
    if bc is None:
        sys.exit("These videos come from Brightcove, but BRIGHTCOVE_ACCOUNT_ID / "
                 "CLIENT_ID / CLIENT_SECRET are not all set.")
    return bc


def loaded(path, target, terms):
    records = run.load_manifest(path)
    bc = brightcove_for(records)
    if bc is not None:
        print(f"  reading {sum(r.from_brightcove for r in records)} video(s) from Brightcove...")
        run.enrich(records, bc)
    run.validate(records, target.choices, terms)
    return records, bc


def prepared(args, client, target, terms):
    records, bc = loaded(args.manifest, target, terms)
    existing = w.existing_by_brightcove_id(client, target)
    names = w.folder_names(client, target)
    return records, run.plan(records, existing, names), bc


def report(records, status) -> None:
    head("PLAN")
    for r in records:
        key = r.brightcove_id or f"row {r.row}"
        size = f"{r.size_bytes / 1e6:8.1f} MB" if r.size_bytes else " " * 11
        print(f"  row {r.row:<4} {status[key]:<9} {r.brightcove_id or '—':<16} {size}  {r.title[:44]}")
        for p in r.problems:
            print(f"             ! {p}")
    totals: dict[str, int] = {}
    for s in status.values():
        totals[s] = totals.get(s, 0) + 1
    print("\n  " + " · ".join(f"{k} {v}" for k, v in sorted(totals.items())))
    new = [r for r in records if status.get(r.brightcove_id) == "new"]
    volume = sum(r.size_bytes or 0 for r in new)
    if volume:
        unknown = sum(1 for r in new if not r.size_bytes)
        hours = volume / (MEASURED_MB_PER_S * 1e6) / 3600
        print(f"  to upload: {volume / 1e9:.2f} GB over {len(new)} video(s)"
              + (f" ({unknown} of unknown size)" if unknown else "")
              + f" -- about {hours:.1f} h at the {MEASURED_MB_PER_S} MB/s measured end to end 2026-09-29")


def cmd_check(args) -> int:
    client, target, terms = connect(args)
    head(f"LIBRARY {target.name}")
    print("  ready: Demo document set, Video choice, every column the migration writes")
    print(f"  Segment choices: {', '.join(target.segment_choices)}")
    print(f"  Product terms loaded: {len(terms)}")
    print(f"  demos already migrated: {len(w.existing_by_brightcove_id(client, target))}")
    return 0


def cmd_dry_run(args) -> int:
    client, target, terms = connect(args)
    records, status, _ = prepared(args, client, target, terms)
    report(records, status)
    log = run.BatchLog.new("dry-run", target.name, args.manifest, planned=len(records))
    for r in records:
        log.data["items"].append({"brightcove_id": r.brightcove_id or f"row {r.row}",
                                  "row": r.row, "title": r.title,
                                  "status": status[r.brightcove_id or f"row {r.row}"],
                                  "size_bytes": r.size_bytes, "problems": r.problems})
    log.finish()
    print(f"\n  nothing was written to SharePoint. Log: {log.path}")
    return 0


def _migrate(client, target, terms, records, log, todo, bc=None) -> int:
    failed = 0
    for n, r in enumerate(todo, start=1):
        head(f"{n}/{len(todo)}  {r.title}  ({r.brightcove_id})")
        try:
            run.migrate_one(client, target, terms, r, log, bc=bc)
        except (GraphError, OSError) as exc:
            failed += 1
            log.set_item(r.brightcove_id, status="failed", error=str(exc)[:500])
            print(f"  FAILED: {exc}")
    log.finish()
    print(f"\n  {log.data['counts']}   Log: {log.path}")
    return 1 if failed else 0


def cmd_run(args) -> int:
    client, target, terms = connect(args)
    records, status, bc = prepared(args, client, target, terms)
    report(records, status)
    todo = [r for r in records if status.get(r.brightcove_id) == "new"][: args.limit or None]
    if not todo:
        print("\n  nothing new to migrate.")
        return 0
    if not args.yes:
        typed = input(f"\n  About to write {len(todo)} video(s) into {target.name!r}. "
                      f"Type the library name to continue: ")
        if typed.strip() != target.name:
            print("  not confirmed; nothing written.")
            return 1
    log = run.BatchLog.new("upload", target.name, args.manifest, planned=len(records))
    for r in records:                       # the plan, recorded before any write
        key = r.brightcove_id or f"row {r.row}"
        if status[key] != "new" or r in todo:
            log.data["items"].append({"brightcove_id": key, "row": r.row, "title": r.title,
                                      "status": "pending" if r in todo else status[key],
                                      "problems": r.problems})
    log.save()
    return _migrate(client, target, terms, records, log, todo, bc)


def cmd_resume(args) -> int:
    try:
        log = run.BatchLog.load(args.batch_id)
    except OSError:
        sys.exit(f"no batch log {args.batch_id!r} in {run.batches_dir()}")
    args.library, args.manifest = log.data["library"], log.data["manifest"]
    client, target, terms = connect(args)
    records, bc = loaded(args.manifest, target, terms)
    unfinished = {i["brightcove_id"] for i in log.data["items"]
                  if i.get("status") in ("pending", "folder_created", "uploading", "uploaded", "failed")}
    todo = [r for r in records if r.brightcove_id in unfinished and not r.problems]
    print(f"  resuming {len(todo)} unfinished video(s) of batch {args.batch_id}")
    log.data["finished_at"] = None
    return _migrate(client, target, terms, records, log, todo, bc)


def cmd_from_sheet(args) -> int:
    """Seb's workbook -> a manifest CSV. Reads the workbook only."""
    from backend.services import gallery_sheet
    rows, rep = gallery_sheet.read(args.sheet)
    gallery_sheet.write_manifest(rows, args.out)
    head("FROM SHEET")
    kept = sum(s["kept"] for s in rep["sheets"].values())
    dropped = sum(s["deleted"] for s in rep["sheets"].values())
    print(f"  {kept} videos to migrate, {dropped} left out (ticked Delete?/Archive?), "
          f"from {len(rep['sheets'])} sheets")
    print(f"  Segment column in the sheet: {'yes' if rep['has_segment_column'] else 'NO'}   "
          f"Customer Facing column: {'yes' if rep['has_customer_facing_column'] else 'NO'}")
    if rep["skipped_sheets"]:
        print(f"  sheets skipped (not part of this migration): {rep['skipped_sheets']}")
    if rep["no_gallery"]:
        print(f"  sheets not named '(PTC Gallery)' / '(GXC Gallery)', so Gallery is left blank: "
              f"{rep['no_gallery']}")
    if rep["customers"]:
        print("  Proposed Tags read as CUSTOMERS (check none is a product): "
              + ", ".join(f"{k} x{v}" for k, v in rep["customers"].most_common()))
    print(f"\n  manifest written: {args.out}\n  next: dry-run --manifest {args.out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    fs = sub.add_parser("from-sheet", help="convert Seb's workbook into a manifest (no writes)")
    fs.add_argument("--sheet", required=True)
    fs.add_argument("--out", required=True)
    for name in ("check", "dry-run", "run", "resume"):
        p = sub.add_parser(name)
        if name == "resume":
            p.add_argument("batch_id")
        else:
            p.add_argument("--library", required=True)
        if name in ("dry-run", "run"):
            p.add_argument("--manifest", required=True)
        if name == "run":
            p.add_argument("--limit", type=int, help="migrate at most N new videos")
            p.add_argument("--yes", action="store_true", help="skip the typed confirmation")
        p.add_argument("--allow-production", action="store_true",
                       help="permit writing to the production Brightcove library")
    args = parser.parse_args()
    return {"check": cmd_check, "dry-run": cmd_dry_run, "run": cmd_run, "resume": cmd_resume,
            "from-sheet": cmd_from_sheet}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
