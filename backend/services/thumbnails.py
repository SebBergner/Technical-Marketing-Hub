"""SharePoint-hosted thumbnails, served by the Hub (2026-10-20).

Demo pages lend their picture to the demos they describe (Lamborghini, Hill
Helicopters, Bobcat ...), and CAD models carry an `Image` column: both are
addresses inside ptccloud.sharepoint.com. Handed to the browser as they are,
they load only while the viewer's browser holds a SharePoint session and
allows it cross-site -- so they came and went (Liwei, 2026-10-20: "Lambo,
Hill" without thumbnails on production), and a partner never saw them.

So the Hub fetches them itself, with the app's own Graph access, and serves
them from /api/assets/{id}/thumbnail:

* the address is resolved through Graph's /shares endpoint, which takes any
  SharePoint URL in the tenant -- Site Assets included, a library /drives
  does not list (measured 2026-10-20);
* Graph's "large" thumbnail (at most 800 px) is fetched, not the original:
  some originals are close to 1 MB;
* the picture is cached under mirror/private/thumbs for a week -- rebuildable
  like the rest of mirror/, and a changed picture shows within days.

Only the asset's own thumbnail address is ever fetched (the route looks it up
by asset id), so this is no general window into SharePoint.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import threading
import time
from urllib.parse import parse_qs, quote, unquote, urlparse

log = logging.getLogger(__name__)

CACHE_DAYS = 7
#: A picture SharePoint does not have (a CAD Image naming a missing file) is
#: not asked for again on every view; nor, for this long, after an outage.
MISS_HOURS = 6
_SUBDIR = ("private", "thumbs")


def is_sharepoint(url: str | None) -> bool:
    host = (urlparse(url or "").netloc or "").lower()
    return host.endswith(".sharepoint.com")


def public_url(asset_id: str, url: str | None) -> str | None:
    """What the browser is given: the Hub's own address for a SharePoint
    picture, anything else (Consensus, Brightcove) as it is."""
    if not url or not is_sharepoint(url):
        return url
    return f"/api/assets/{quote(asset_id, safe='')}/thumbnail"


def direct_url(url: str) -> str:
    """The file's own address: getpreview.ashx?path=/sites/... -> that path."""
    parsed = urlparse(url)
    path = parse_qs(parsed.query).get("path")
    target = path[0] if path and parsed.path.lower().endswith("getpreview.ashx") \
        else unquote(parsed.path)
    return f"{parsed.scheme}://{parsed.netloc}{quote(target)}"


def _share_token(url: str) -> str:
    return "u!" + base64.urlsafe_b64encode(url.encode("utf-8")).decode("ascii").rstrip("=")


def fetch(client, url: str) -> tuple[bytes, str] | None:
    """(bytes, content type) of the picture, or None when SharePoint has none."""
    item = client._request("GET", f"/shares/{_share_token(direct_url(url))}/driveItem",
                           params={"$select": "id,parentReference"})
    if not item:
        return None
    sets = client.thumbnails(item["parentReference"]["driveId"], item["id"])
    large = (sets[0].get("large") or sets[0].get("medium") or {}) if sets else {}
    if not large.get("url"):
        return None
    response = client._client.get(large["url"])   # pre-authorised; no token
    if response.status_code != 200 or not response.content:
        return None
    return response.content, response.headers.get("content-type") or "image/jpeg"


def warm(repo, client=None) -> int:
    """Fetch every SharePoint picture not cached or gone stale, one at a
    time -- after a sync, in the background, so the first viewer of a card
    does not wait on SharePoint. Returns how many were fetched."""
    if client is None:
        from backend.integrations.graph.client import get_graph_client
        client = get_graph_client()
    if client is None or not hasattr(repo, "_load_mirror"):
        return 0
    fetched = 0
    urls = {r.get("thumbnail_url") for r in repo._load_mirror() if is_sharepoint(r.get("thumbnail_url"))}
    for url in sorted(urls):
        if _fresh(repo.mirror_dir, url):
            continue
        if get(repo.mirror_dir, client, url) is not None:
            fetched += 1
    log.info("thumbnails: %d fetched, %d SharePoint pictures in all", fetched, len(urls))
    return fetched


_warming = threading.Lock()


def warm_soon(repo) -> None:
    """One warm-up at a time; a call while one runs is dropped (it covers
    every picture anyway)."""
    def run():
        if not _warming.acquire(blocking=False):
            return
        try:
            warm(repo)
        finally:
            _warming.release()
    threading.Thread(target=run, name="thumbnails", daemon=True).start()


def _paths(mirror_dir: str, url: str) -> tuple[str, str]:
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()
    folder = os.path.join(mirror_dir, *_SUBDIR)
    return os.path.join(folder, key + ".bin"), os.path.join(folder, key + ".json")


def _miss_path(mirror_dir: str, url: str) -> str:
    return _paths(mirror_dir, url)[0][:-4] + ".miss"


def _young(path: str, seconds: float) -> bool:
    return os.path.exists(path) and time.time() - os.path.getmtime(path) < seconds


def _fresh(mirror_dir: str, url: str) -> bool:
    """Cached and fresh, or known missing and not yet worth asking again."""
    return (_young(_paths(mirror_dir, url)[0], CACHE_DAYS * 86400)
            or _young(_miss_path(mirror_dir, url), MISS_HOURS * 3600))


class Busy(Exception):
    """Every fetch slot is taken: the card shows its cover this time."""


#: At most this many fetches from SharePoint at once (2026-10-20): an empty
#: cache and a page of cards once queued dozens of 1-2 s fetches, and the
#: catalogue itself waited ~20 s behind them for a worker thread.
SLOTS = 4
_slots = threading.BoundedSemaphore(SLOTS)


#: Bumped when compact() changes, so pictures cached by an earlier one are
#: made again (2: opaque PNGs become JPEGs too).
COMPACT_VERSION = 2

#: The card shows a picture at most ~400 px wide (twice that on a sharp
#: screen); Graph's "large" is 800 px and 91 KB on average.
COMPACT_PX = 640


def compact(data: bytes, ctype: str) -> tuple[bytes, str]:
    """The picture at most COMPACT_PX on its longer side: a JPEG, or a PNG
    when it has transparency. 91 KB -> 19 KB on average, 8 ms each
    (measured 2026-11-04 on 424 cached pictures): a first Home page loads
    15 of them at once. The original whenever this fails or is no smaller."""
    try:
        import io
        from PIL import Image
        image = Image.open(io.BytesIO(data))
        image.load()
        image.thumbnail((COMPACT_PX, COMPACT_PX))
        out = io.BytesIO()
        # Graph's PNGs carry an alpha channel that is almost always fully
        # opaque (seen on staging 2026-11-04: 100-258 KB PNGs): only a
        # picture with a pixel actually see-through stays a PNG.
        if image.mode == "P" and "transparency" in image.info:
            image = image.convert("RGBA")
        clear = image.mode in ("RGBA", "LA") and image.getchannel("A").getextrema()[0] < 250
        if clear:
            image.save(out, "PNG", optimize=True)
            kind = "image/png"
        else:
            image.convert("RGB").save(out, "JPEG", quality=80, optimize=True,
                                      progressive=True)
            kind = "image/jpeg"
        small = out.getvalue()
    except Exception as exc:                                    # noqa: BLE001
        log.info("thumbnail kept as it is: %s", exc)
        return data, ctype
    return (small, kind) if small and len(small) < len(data) else (data, ctype)


def _compact_cached(data_path: str, meta_path: str, meta: dict,
                    cached: tuple[bytes, str]) -> tuple[bytes, str]:
    """A picture cached before COMPACT_PX, made compact once, keeping its
    age: the week it is fresh for still counts from when it was fetched."""
    small = compact(*cached)
    try:
        from backend.file_safety import replace, replace_with, temp_path
        stamp = os.path.getmtime(data_path)
        tmp = temp_path(data_path)
        with open(tmp, "wb") as fh:
            fh.write(small[0])
        replace(tmp, data_path)
        os.utime(data_path, (stamp, stamp))
        replace_with(meta_path, lambda fh: json.dump(
            {**meta, "content_type": small[1], "compact": COMPACT_VERSION}, fh))
    except OSError as exc:
        log.warning("thumbnail cache not made compact: %s", exc)
    return small


_refreshing: set[str] = set()
_refreshing_lock = threading.Lock()


def _refresh_soon(mirror_dir: str, client, url: str) -> None:
    """Fetch a stale picture again in the background, once at a time."""
    with _refreshing_lock:
        if url in _refreshing:
            return
        _refreshing.add(url)

    def run():
        try:
            get(mirror_dir, client, url, wait=True)
        except Exception as exc:                                # noqa: BLE001
            log.warning("thumbnail %s not refreshed: %s", url[:120], exc)
        finally:
            with _refreshing_lock:
                _refreshing.discard(url)
    threading.Thread(target=run, name="thumbnail-refresh", daemon=True).start()


def get(mirror_dir: str, client, url: str, wait: bool = True) -> tuple[bytes, str] | None:
    """From the cache while it is fresh, else from SharePoint (and cached).
    A stale copy is still served when SharePoint cannot be reached; a picture
    SharePoint does not have is remembered for MISS_HOURS. `wait=False`
    (a viewer's request): raise Busy rather than queue for a fetch slot."""
    data_path, meta_path = _paths(mirror_dir, url)
    cached = None
    if os.path.exists(data_path) and os.path.exists(meta_path):
        try:
            with open(meta_path, encoding="utf-8") as fh:
                meta = json.load(fh)
            ctype = meta.get("content_type") or "image/jpeg"
            with open(data_path, "rb") as fh:
                cached = (fh.read(), ctype)
            if meta.get("compact") != COMPACT_VERSION:
                cached = _compact_cached(data_path, meta_path, meta, cached)
        except (OSError, ValueError):
            cached = None
        if cached and _young(data_path, CACHE_DAYS * 86400):
            return cached
    if client is None or _young(_miss_path(mirror_dir, url), MISS_HOURS * 3600):
        return cached
    if cached is not None and not wait:
        # A viewer never waits on SharePoint for a picture the Hub already
        # has: this one now, a fresh one fetched behind it (2026-11-04).
        _refresh_soon(mirror_dir, client, url)
        return cached
    if not _slots.acquire(blocking=wait):
        # A picture past its week is still the right picture: shown while
        # every slot is busy, not the cover (2026-11-04, before the stress
        # test -- many viewers at once is exactly when the slots are full).
        if cached is not None:
            return cached
        raise Busy()
    try:
        fresh = fetch(client, url)
    except Exception as exc:                                    # noqa: BLE001
        log.warning("thumbnail %s not fetched: %s", url[:120], exc)
        fresh = None
    finally:
        _slots.release()
    try:
        os.makedirs(os.path.dirname(data_path), exist_ok=True)
        if fresh is None:
            open(_miss_path(mirror_dir, url), "w").close()
            return cached
        fresh = compact(*fresh)
        from backend.file_safety import replace, replace_with, temp_path
        tmp = temp_path(data_path)
        with open(tmp, "wb") as fh:
            fh.write(fresh[0])
        replace(tmp, data_path)
        replace_with(meta_path, lambda fh: json.dump(
            {"content_type": fresh[1], "url": url, "compact": COMPACT_VERSION}, fh))
        if os.path.exists(_miss_path(mirror_dir, url)):
            os.remove(_miss_path(mirror_dir, url))
    except OSError as exc:
        log.warning("thumbnail cache not written: %s", exc)
    return fresh
