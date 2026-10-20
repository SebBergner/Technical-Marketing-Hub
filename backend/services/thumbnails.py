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
import time
from urllib.parse import parse_qs, quote, unquote, urlparse

log = logging.getLogger(__name__)

CACHE_DAYS = 7
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
        data_path, _ = _paths(repo.mirror_dir, url)
        if os.path.exists(data_path) and time.time() - os.path.getmtime(data_path) < CACHE_DAYS * 86400:
            continue
        if get(repo.mirror_dir, client, url) is not None:
            fetched += 1
    log.info("thumbnails: %d fetched, %d SharePoint pictures in all", fetched, len(urls))
    return fetched


def warm_soon(repo) -> None:
    import threading
    threading.Thread(target=warm, args=(repo,), name="thumbnails", daemon=True).start()


def _paths(mirror_dir: str, url: str) -> tuple[str, str]:
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()
    folder = os.path.join(mirror_dir, *_SUBDIR)
    return os.path.join(folder, key + ".bin"), os.path.join(folder, key + ".json")


def get(mirror_dir: str, client, url: str) -> tuple[bytes, str] | None:
    """From the cache while it is fresh, else from SharePoint (and cached).
    A stale copy is still served when SharePoint cannot be reached."""
    data_path, meta_path = _paths(mirror_dir, url)
    cached = None
    if os.path.exists(data_path) and os.path.exists(meta_path):
        try:
            with open(meta_path, encoding="utf-8") as fh:
                ctype = json.load(fh).get("content_type") or "image/jpeg"
            with open(data_path, "rb") as fh:
                cached = (fh.read(), ctype)
        except (OSError, ValueError):
            cached = None
        if cached and time.time() - os.path.getmtime(data_path) < CACHE_DAYS * 86400:
            return cached
    if client is None:
        return cached
    try:
        fresh = fetch(client, url)
    except Exception as exc:                                    # noqa: BLE001
        log.warning("thumbnail %s not fetched: %s", url[:120], exc)
        return cached
    if fresh is None:
        return cached
    try:
        os.makedirs(os.path.dirname(data_path), exist_ok=True)
        with open(data_path + ".tmp", "wb") as fh:
            fh.write(fresh[0])
        os.replace(data_path + ".tmp", data_path)
        with open(meta_path, "w", encoding="utf-8") as fh:
            json.dump({"content_type": fresh[1], "url": url}, fh)
    except OSError as exc:
        log.warning("thumbnail cache not written: %s", exc)
    return fresh
