"""Read-only smoke test of a Hub slot, run after a swap (Liwei, 2026-11-11).

    python scripts/smoke_test.py                       # production
    python scripts/smoke_test.py --base https://dev-tmh.ptcxc.com
    python scripts/smoke_test.py --expect-version v2026.3.195

It only reads: no sync, no saving, no plays or downloads (a play would add a
usage record). It needs an API token with View the Hub, from Admin -> Users &
groups -> API tokens, in the environment variable TMH_SMOKE_TOKENS -- never
on the command line, where it would land in the shell history.

Each slot keeps its own data, tokens included, and a swap takes a slot's
data with it. So create one token on each slot and put both in the variable,
separated by a comma; the script uses whichever the slot knows.

Counts are compared with the last run against the same host (kept in
~/.tmh-smoke/), so a slot that lost half its catalogue shows up even though
nobody wrote the number down.

Exit code 0 when nothing failed (warnings allowed), 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_BASE = "https://tmh.ptcxc.com"
TOKEN_ENV = "TMH_SMOKE_TOKENS"
#: Hub settings as they are meant to be (Liwei, 2026-11-08).
EXPECTED_SETTINGS = {"show_page_only_demos": False, "show_demo_page_links": False,
                     "gxc_downloads": True}
#: Searches that must always find something.
SEARCHES = ("creo", "windchill", "codebeamer")
#: Product families that were cleaned out of the catalogue (2026-11-10).
RETIRED_FAMILIES = ("proengineer", "pro/engineer", "division")
#: SharePoint syncs at least twice a day; older than this is a failure.
SYNC_MAX_AGE_HOURS = 26
#: A drop larger than this against the last run is a warning.
DROP_WARN = 0.05
BASELINE_DIR = Path.home() / ".tmh-smoke"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


class Hub:
    def __init__(self, base: str, token: str | None):
        self.base = base.rstrip("/")
        self.token = token

    def get(self, path: str, params: dict | None = None) -> tuple[int, object, float]:
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        started = time.monotonic()
        try:
            with OPENER.open(req, timeout=60) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as err:
            status, raw = err.code, err.read()
        elapsed = time.monotonic() - started
        try:
            body = json.loads(raw) if raw else None
        except ValueError:
            body = None
        return status, body, elapsed


class Report:
    def __init__(self):
        self.rows: list[tuple[str, str, str]] = []

    def add(self, level: str, name: str, detail: str = "") -> None:
        self.rows.append((level, name, detail))
        print(f"  {level:<4}  {name:<34} {detail}", flush=True)

    def ok(self, name, detail=""):
        self.add("PASS", name, detail)

    def warn(self, name, detail=""):
        self.add("WARN", name, detail)

    def fail(self, name, detail=""):
        self.add("FAIL", name, detail)

    def check(self, cond: bool, name: str, detail: str = "") -> bool:
        (self.ok if cond else self.fail)(name, detail)
        return cond

    @property
    def failed(self) -> int:
        return sum(1 for r in self.rows if r[0] == "FAIL")

    @property
    def warned(self) -> int:
        return sum(1 for r in self.rows if r[0] == "WARN")


def pick_token(base: str) -> str | None:
    """The first token in TMH_SMOKE_TOKENS this slot accepts."""
    tokens = [t.strip() for t in os.environ.get(TOKEN_ENV, "").split(",") if t.strip()]
    for token in tokens:
        status, _, _ = Hub(base, token).get("/api/status")
        if status == 200:
            return token
    return None


def hours_since(stamp: str | None) -> float | None:
    if not stamp:
        return None
    try:
        then = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).total_seconds() / 3600


def baseline_path(base: str) -> Path:
    host = urllib.parse.urlparse(base).netloc.replace(":", "_")
    return BASELINE_DIR / f"{host}.json"


def run(base: str, expect_version: str | None) -> Report:
    rep = Report()
    print(f"Smoke test of {base}  ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n")

    # 1. Version: public, no token needed.
    status, body, secs = Hub(base, None).get("/api/version")
    version = (body or {}).get("version") if isinstance(body, dict) else None
    if rep.check(status == 200 and bool(version), "Version", f"{version} ({secs:.1f}s)"):
        if expect_version and version != expect_version:
            rep.fail("Expected version", f"wanted {expect_version}, got {version}")

    token = pick_token(base)
    if not token:
        rep.fail("API token", f"none of the tokens in {TOKEN_ENV} works on this slot")
        return rep
    hub = Hub(base, token)

    # 2. Release status: sync, schedule, settings.
    status, st, _ = hub.get("/api/status")
    if not rep.check(status == 200 and isinstance(st, dict), "Status API", f"HTTP {status}"):
        return rep
    sp = st["sync"].get("sharepoint") or {}
    age = hours_since(sp.get("last_success_at"))
    rep.check(age is not None and age <= SYNC_MAX_AGE_HOURS, "SharePoint sync",
              f"last success {sp.get('last_success_at')}"
              + (f" ({age:.0f}h ago)" if age is not None else ""))
    for name, row in st["sync"].items():
        if row.get("last_attempt_ok") is False:
            rep.warn(f"Last {name} sync failed", f"at {row.get('last_attempt_at')}")
    auto = st.get("auto_sync") or {}
    rep.check(bool(auto.get("enabled")), "Daily sync on",
              f"hours UTC {auto.get('hours_utc')}, next {auto.get('next_run_at')}")
    last = auto.get("last_run") or {}
    if last and last.get("ok") is False:
        bad = [k for k, v in (last.get("sources") or {}).items() if v is False]
        rep.warn("Last daily sync", f"{last.get('started_at')}: failed {', '.join(bad)}")
    settings = st.get("hub_settings") or {}
    wrong = {k: settings.get(k) for k, v in EXPECTED_SETTINGS.items() if settings.get(k) != v}
    rep.check(not wrong, "Hub settings",
              "as expected" if not wrong else f"differ: {wrong}")

    # 3. Catalogue size per type, against the last run on this host.
    status, facets, secs = hub.get("/api/taxonomy")
    if not rep.check(status == 200 and isinstance(facets, dict), "Facets",
                     f"HTTP {status} ({secs:.1f}s)"):
        return rep
    types = {f["value"]: f["count"] for f in facets.get("types", [])}
    status, page, secs = hub.get("/api/assets", {"limit": 1})
    total = (page or {}).get("total", 0) if isinstance(page, dict) else 0
    rep.check(status == 200 and total > 0, "Assets listed",
              f"{total} ({', '.join(f'{k} {v}' for k, v in sorted(types.items()))}; {secs:.1f}s)")
    counts = {"total": total, **types}
    path = baseline_path(base)
    try:
        before = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        before = None
    if before:
        drops = [f"{k} {before['counts'][k]}->{counts.get(k, 0)}"
                 for k in before["counts"]
                 if before["counts"][k] and
                 (before["counts"][k] - counts.get(k, 0)) / before["counts"][k] > DROP_WARN]
        if drops:
            rep.warn("Counts vs last run", f"dropped since {before['at']}: {'; '.join(drops)}")
        else:
            rep.ok("Counts vs last run", f"no drop since {before['at']}")
    else:
        rep.ok("Counts vs last run", "first run on this host")

    # 4. Product families: none of the retired names.
    families = [f["value"] for f in facets.get("product_families", [])]
    retired = [f for f in families if any(r in f.lower() for r in RETIRED_FAMILIES)]
    rep.check(not retired, "Product dropdown",
              f"{len(families)} families" + (f"; retired names back: {retired}" if retired else ""))

    # 5. Searches.
    for q in SEARCHES:
        status, page, secs = hub.get("/api/assets", {"q": q, "limit": 1})
        n = (page or {}).get("total", 0) if isinstance(page, dict) else 0
        rep.check(status == 200 and n > 0, f"Search \"{q}\"", f"{n} results ({secs:.1f}s)")

    # 6. One demo: details, related, thumbnail.
    status, page, _ = hub.get("/api/assets", {"limit": 1, "type": "video"})
    items = (page or {}).get("items") or [] if isinstance(page, dict) else []
    if rep.check(bool(items), "A demo to open", items[0]["title"] if items else "none"):
        aid = items[0]["id"]
        status, _, secs = hub.get(f"/api/assets/{aid}")
        rep.check(status == 200, "Demo details", f"HTTP {status} ({secs:.1f}s)")
        status, _, secs = hub.get(f"/api/assets/{aid}/related")
        rep.check(status == 200, "Related demos", f"HTTP {status} ({secs:.1f}s)")
        status, _, secs = hub.get(f"/api/assets/{aid}/thumbnail")
        # Some demos have no picture yet (D20): a warning, not a failure.
        (rep.ok if status in (200, 302, 307) else rep.warn)(
            "Thumbnail", f"HTTP {status} ({secs:.1f}s)")

    # 7. User guide video: its length and cover (not the video itself).
    status, info, secs = hub.get("/api/welcome/video/info")
    dur = (info or {}).get("duration_seconds") if isinstance(info, dict) else None
    rep.check(status == 200 and bool(dur), "Guide video",
              f"{dur // 60}:{dur % 60:02d} ({secs:.1f}s)" if dur else f"HTTP {status}")
    status, _, secs = hub.get("/api/welcome/video/poster")
    rep.check(status in (200, 302, 307), "Guide video cover", f"HTTP {status} ({secs:.1f}s)")

    if rep.failed == 0:
        BASELINE_DIR.mkdir(exist_ok=True)
        path.write_text(json.dumps({"at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                    "version": version, "counts": counts}, indent=2),
                        encoding="utf-8")
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", default=DEFAULT_BASE, help=f"default {DEFAULT_BASE}")
    ap.add_argument("--expect-version", help="fail unless the slot runs this build")
    args = ap.parse_args()
    rep = run(args.base, args.expect_version)
    print(f"\n{len(rep.rows)} checks: {rep.failed} failed, {rep.warned} warnings")
    return 1 if rep.failed else 0


if __name__ == "__main__":
    sys.exit(main())
