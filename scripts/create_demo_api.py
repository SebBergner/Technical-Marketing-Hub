"""Create a demo in the Technical Marketing Hub through its API.

The whole flow in one command, for a program or a person with an API token
(Admin -> Users & groups -> API tokens; it needs "Create new demo"):

    python scripts/create_demo_api.py \\
        --hub https://tmh.ptcxc.com --token "$TMH_TOKEN" \\
        --target demo_catalog --kind ldk --metadata kit.json \\
        --preview "Videos/Overview_CF.mp4" "C:/Demos/Creo Sheetmetal Kit"

    python scripts/create_demo_api.py --hub ... --token ... \\
        --target demo_video --kind video --metadata video.json "Creo Teaser.mp4"

`--metadata` is a JSON object with the target's fields -- see
`--show-form`, which prints them, required ones marked, with the allowed
options. A folder is uploaded with its sub-folders; `--preview` names the
video to play first when there are several. Files go straight to the
destination in 10 MiB chunks; the Hub never holds them.

What happens after: the demo waits for review, unless the token publishes
without review. Exit code 0 on success; the upload's id is printed either
way, so a failed run can be looked at in the Hub ("My demos" for people,
the Admin log for tokens).

Needs only httpx (pip install httpx).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import httpx

CHUNK = 32 * 320 * 1024          # 10 MiB, a multiple of 320 KiB as SharePoint requires


def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def check(r: httpx.Response) -> dict:
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail")
        except ValueError:
            detail = r.text[:300]
        die(f"{r.request.method} {r.request.url.path}: HTTP {r.status_code}: {detail}")
    return r.json() if r.content else {}


def collect(paths: list[str]) -> list[tuple[str, str]]:
    """(path inside the demo, local file) for every file named or under a folder."""
    out = []
    for p in paths:
        if os.path.isdir(p):
            for root, _, names in os.walk(p):
                for n in sorted(names):
                    local = os.path.join(root, n)
                    out.append((os.path.relpath(local, p).replace(os.sep, "/"), local))
        elif os.path.isfile(p):
            out.append((os.path.basename(p), p))
        else:
            die(f"no such file or folder: {p}")
    return out


def send_file(local: str, size: int, upload_url: str) -> str:
    """PUT the file to its upload URL in chunks; returns the created item's id."""
    with open(local, "rb") as fh, httpx.Client(timeout=httpx.Timeout(300.0, connect=30.0)) as up:
        offset = 0
        while True:
            data = fh.read(CHUNK)
            end = offset + len(data) - 1
            for attempt in range(6):
                try:
                    r = up.put(upload_url, content=data, headers={
                        "Content-Length": str(len(data)),
                        "Content-Range": f"bytes {offset}-{end}/{size}"})
                except httpx.HTTPError:
                    time.sleep(2 ** attempt)
                    continue
                if r.status_code == 429 or r.status_code >= 500:
                    time.sleep(float(r.headers.get("Retry-After", 2 ** attempt)))
                    continue
                break
            else:
                die(f"{local}: the chunk at byte {offset} kept failing")
            if r.status_code == 202:
                offset = end + 1
                print(f"    {offset / size:6.1%}", end="\r", flush=True)
                continue
            if r.status_code in (200, 201):
                print("    100.0%")
                return r.json()["id"]
            die(f"{local}: the destination answered HTTP {r.status_code}: {r.text[:200]}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hub", required=True, help="e.g. https://tmh.ptcxc.com")
    ap.add_argument("--token", default=os.environ.get("TMH_TOKEN"),
                    help="API token (or set TMH_TOKEN)")
    ap.add_argument("--target", help="demo_catalog or demo_video (see --show-form)")
    ap.add_argument("--kind", help="ldk, vdk or video")
    ap.add_argument("--metadata", help="JSON file with the fields")
    ap.add_argument("--preview", help="with several videos: the one to play first")
    ap.add_argument("--internal", action="store_true", help="files only for internal access")
    ap.add_argument("--submitted-by", help="the PTC email address of the person this upload "
                    "is for (recommended; without it the token's owner is credited)")
    ap.add_argument("--show-form", action="store_true", help="print the targets and their fields")
    ap.add_argument("files", nargs="*", help="files and/or one folder")
    a = ap.parse_args()
    if not a.token:
        die("an API token is needed: --token or TMH_TOKEN")

    api = httpx.Client(base_url=a.hub.rstrip("/"), timeout=120.0,
                       headers={"Authorization": f"Bearer {a.token}"})
    form = check(api.get("/api/uploads/targets"))
    if a.show_form:
        for t in form["targets"]:
            print(f"{t['key']}  ({t['label']})  kinds: {', '.join(k['key'] for k in t['kinds'])}"
                  + (f"  UNAVAILABLE: {t['unavailable']}" if t.get("unavailable") else ""))
            for f in t["fields"]:
                choices = f" one or more of: {f['choices']}" if f["kind"] == "multi" else \
                          f" one of: {f['choices']}" if f.get("choices") else ""
                print(f"   {'*' if f['required'] else ' '} {f['key']:24} {f['kind']:8}{choices}")
        return

    if not (a.target and a.kind and a.metadata and a.files):
        die("--target, --kind, --metadata and at least one file or folder are needed")
    values = json.load(open(a.metadata, encoding="utf-8"))
    files = collect(a.files)
    listed = [{"path": path, "size": os.path.getsize(local)} for path, local in files]
    print(f"Creating '{values.get('title')}' with {len(listed)} file(s)…")
    record = check(api.post("/api/uploads", json={
        "target": a.target, "kind": a.kind, "values": values, "files": listed,
        "internal": a.internal, "preview": a.preview, "submitted_by": a.submitted_by}))
    print(f"  upload {record['id']}: folder '{record['folder_name']}' created")

    local_of = dict(files)
    for i, f in enumerate(record["files"]):
        print(f"  {f['path']} ({f['size'] / 1e6:.1f} MB)")
        session = check(api.post(f"/api/uploads/{record['id']}/files/{i}/session"))
        item_id = send_file(local_of[f["path"]], f["size"], session["upload_url"])
        check(api.post(f"/api/uploads/{record['id']}/files/{i}/done", json={"item_id": item_id}))

    done = check(api.post(f"/api/uploads/{record['id']}/finish"))
    for warning in done.get("warnings") or []:
        print(f"  warning: {warning}")
    print(f"Done: '{done['title']}' is {done['status'].replace('_', ' ')} "
          f"(upload {done['id']}).")
    print(f"  SharePoint: {done['sharepoint_url']}")
    # Permanent: opens the demo's page once the Hub has read the new folder
    # (a sync starts by itself), My demos until then.
    print(f"  Hub:        {done['hub_url']}")


if __name__ == "__main__":
    main()
