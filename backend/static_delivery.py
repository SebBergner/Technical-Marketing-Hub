"""How the pages and their static files reach the browser (WS-C, 2026-11-26).

Measured locally on 2026-11-26, before this module: the Hub page pulled 32
static files (814 KB) uncompressed, each marked `no-cache`, so every visit
sent 32 conditional requests, and the ES modules were discovered four levels
deep, one level per round trip.

Three things change that, and nothing else does:

* **A versioned URL.** On a deployed build (one with a `BUILD_NUMBER`, see
  backend/version.py) the pages name their files under
  `/static/v<build>/...`, served with a one-year `immutable` lifetime. A new
  deploy is a new build number, so a new URL, so nobody can be left on a stale
  script -- the reason RevalidatingStatic existed. Relative module imports
  (`./util.js`) resolve against the importing module's URL, so the whole
  graph inherits the prefix without the JavaScript knowing about it.
* **No build number, no versioning.** A local checkout (`uvicorn --reload`)
  has none, so its pages keep naming `/static/...` and every file stays
  `no-cache`: an edit shows on the next reload, as it always has.
* **modulepreload.** Each page lists the module graph below its entry script,
  read from the `import ... from` lines at serve time, so the browser asks for
  all of it at once instead of discovering it a level at a time. Generated,
  not a hand-kept list, because a hand-kept list goes stale the first time
  somebody adds a module and nobody would notice.

The plain `/static/...` path keeps working (old links, a page loaded before a
deploy), revalidated as before. A request for another build's prefix is
served the current file, revalidated, never `immutable`: the content may not
be what that build had.

The pages themselves stay `no-cache`, with an ETag so an unchanged page is a
304 rather than 80 KB again.
"""
from __future__ import annotations

import hashlib
import os
import re
from typing import Iterable

from starlette.requests import Request
from starlette.responses import HTMLResponse, Response
from starlette.staticfiles import StaticFiles

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "static")

IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"

#: What GZip leaves alone: Starlette's own list (already compressed media,
#: video, audio, event streams; it also never touches a 206) plus binary
#: downloads that gain nothing and would only cost CPU.
GZIP_EXCLUDE = (
    "application/gzip", "application/x-gzip", "application/zip",
    "application/octet-stream", "application/pdf",
    "audio/*", "video/*",
    "font/woff", "font/woff2",
    "image/avif", "image/gif", "image/jpeg", "image/png", "image/webp",
    "text/event-stream",
)

# `v` then a digit: a real folder such as static/videos/ is never mistaken
# for a version prefix.
_VERSION_PREFIX = re.compile(r"^v(\d[0-9A-Za-z.\-]*)[\\/](.+)$", re.S)


def asset_token() -> str:
    """The build number, or "" outside a deploy. Read like version.py reads
    it (the file the workflow writes, then the environment), and reduced to
    characters that are safe in a URL path."""
    build = ""
    try:
        with open(os.path.join(BASE_DIR, "BUILD_NUMBER"), encoding="utf-8") as fh:
            build = fh.read().strip()
    except OSError:
        pass
    build = build or os.getenv("BUILD_NUMBER", "")
    return re.sub(r"[^0-9A-Za-z.\-]", "", build)


_token_cache: list[str] = []


def current_token() -> str:
    """asset_token(), read once per process: a deploy is a restart."""
    if not _token_cache:
        _token_cache.append(asset_token())
    return _token_cache[0]


def static_prefix(token: str | None = None) -> str:
    token = current_token() if token is None else token
    return f"/static/v{token}/" if token else "/static/"


class VersionedStatic(StaticFiles):
    """static/, under both `/static/<path>` and `/static/v<build>/<path>`."""

    async def get_response(self, path: str, scope) -> Response:
        requested = None
        m = _VERSION_PREFIX.match(path)
        if m and not os.path.isdir(os.path.join(self.directory or STATIC_DIR, path.split(os.sep)[0])):
            requested, path = m.group(1), m.group(2)
        response = await super().get_response(path, scope)
        token = current_token()
        if token and requested == token and response.status_code in (200, 304):
            response.headers["Cache-Control"] = IMMUTABLE
        else:
            response.headers["Cache-Control"] = REVALIDATE
        return response


# ------------------------------------------------------------------ pages

_IMPORT_FROM = re.compile(r"""(?m)^[ \t]*(?:import|export)\b[^;'"]*?\bfrom\s*['"]([^'"]+)['"]""")
_IMPORT_BARE = re.compile(r"""(?m)^[ \t]*import\s*['"]([^'"]+)['"]""")
_MODULE_SCRIPT = re.compile(r"""<script\b[^>]*\btype=["']module["'][^>]*\bsrc=["']/static/([^"']+)["']""")
_ASSET_TAG = re.compile(r"""(<(?:script|link)\b[^>]*?\s(?:src|href)=["'])/static/""")
_STYLESHEET = re.compile(r"""<link\b[^>]*\brel=["']stylesheet["'][^>]*>""")


def module_graph(entry: str, static_dir: str = STATIC_DIR) -> list[str]:
    """Every module reachable from `entry` (a path under static/, with "/"),
    entry first, then in the order they were found. Only relative imports
    are followed; anything else is not ours to preload."""
    seen: list[str] = []
    stack = [entry]
    while stack:
        rel = stack.pop(0)
        if rel in seen:
            continue
        full = os.path.join(static_dir, *rel.split("/"))
        try:
            with open(full, encoding="utf-8") as fh:
                source = fh.read()
        except OSError:
            continue                       # a broken import is the browser's to report
        seen.append(rel)
        base = rel.rsplit("/", 1)[0] if "/" in rel else ""
        for spec in _IMPORT_FROM.findall(source) + _IMPORT_BARE.findall(source):
            if not spec.startswith(("./", "../")):
                continue
            joined = os.path.normpath(os.path.join(base, spec)).replace(os.sep, "/")
            if not joined.startswith(".."):
                stack.append(joined)
    return seen


def _preload_links(entries: Iterable[str], prefix: str) -> str:
    modules: list[str] = []
    for entry in entries:
        for rel in module_graph(entry):
            if rel not in modules:
                modules.append(rel)
    return "".join(f'<link rel="modulepreload" href="{prefix}{rel}">\n' for rel in modules)


def render_page(path: str, token: str | None = None) -> str:
    """The page at `path`, with its asset URLs under the build's prefix and
    a modulepreload line for each module its entry script pulls in."""
    token = current_token() if token is None else token
    prefix = static_prefix(token)
    with open(path, encoding="utf-8") as fh:
        html = fh.read()
    entries = _MODULE_SCRIPT.findall(html)
    if token:
        html = _ASSET_TAG.sub(lambda m: m.group(1) + prefix, html)
    links = _preload_links(entries, prefix) if entries else ""
    if links:
        # Before </head> where there is one; index.html has none, so right
        # after its stylesheet, which is near the top.
        if "</head>" in html:
            html = html.replace("</head>", links + "</head>", 1)
        elif (sheet := _STYLESHEET.search(html)):
            html = html[:sheet.end()] + "\n" + links.rstrip("\n") + html[sheet.end():]
        else:
            html = links + html
    return html


_page_cache: dict[tuple[str, str, float], tuple[str, str]] = {}


def page_response(request: Request, path: str) -> Response:
    """A page, never cached without asking (`no-cache`), but answered with a
    304 when the browser already has this exact version. Rendered once per
    build in a deploy; on every request locally, so edits show at once."""
    token = current_token()
    body = etag = None
    if token:
        key = (path, token, os.path.getmtime(path))
        if key in _page_cache:
            body, etag = _page_cache[key]
    if body is None:
        body = render_page(path, token)
        etag = '"' + hashlib.sha1(body.encode("utf-8")).hexdigest()[:20] + '"'
        if token:
            _page_cache[(path, token, os.path.getmtime(path))] = (body, etag)
    headers = {"Cache-Control": REVALIDATE, "ETag": etag}
    inm = request.headers.get("if-none-match", "")
    if etag in (t.strip() for t in inm.split(",")):
        return Response(status_code=304, headers=headers)
    return HTMLResponse(body, headers=headers)
