"""Brightcove Video Cloud, READ-ONLY, for the Gallery migration.

Measured 2026-09-29 (docs/brightcove-migration-plan.md §12): the credential in
.env carries WRITE permissions on the account (videos, playlists, players).
This client therefore has no way to send anything but GET: there is no
generic request method, only the reads the migration needs. A write to
Brightcove would change what customers and partners see in the Galleries.

Signed rendition URLs work like credentials for as long as they live, so
they are never logged, and they are fetched fresh each time a download
starts or resumes, because they expire.
"""
from __future__ import annotations

import logging
import time

import httpx

from backend.config import settings
from backend.integrations.tls import system_trust

log = logging.getLogger(__name__)

TOKEN_URL = "https://oauth.brightcove.com/v4/access_token"
CMS_ROOT = "https://cms.api.brightcove.com/v1/accounts"


class BrightcoveError(RuntimeError):
    pass


class BrightcoveClient:
    def __init__(self, account_id: str, client_id: str, client_secret: str, *,
                 transport: httpx.BaseTransport | None = None, verify=None):
        self.account_id = account_id
        self._auth = (client_id, client_secret)
        self._verify = system_trust() if verify is None else verify
        self._http = httpx.Client(timeout=30, verify=self._verify, transport=transport)
        self._token: str | None = None
        self._token_until = 0.0

    # ─────────────────────────────────────────────────────────── plumbing
    def _bearer(self) -> str:
        """Tokens live 300 s; renew a minute early rather than mid-request."""
        if self._token and time.time() < self._token_until:
            return self._token
        r = self._http.post(TOKEN_URL, data={"grant_type": "client_credentials"}, auth=self._auth)
        if r.status_code != 200:
            raise BrightcoveError(f"Brightcove token refused: HTTP {r.status_code}")
        body = r.json()
        self._token = body["access_token"]
        self._token_until = time.time() + int(body.get("expires_in", 300)) - 60
        return self._token

    def _get(self, path: str, **params):
        """The only call this client makes to the CMS API, and it is a GET."""
        url = f"{CMS_ROOT}/{self.account_id}{path}"
        for attempt in range(4):
            r = self._http.get(url, params=params or None,
                               headers={"Authorization": f"Bearer {self._bearer()}"})
            if r.status_code == 401 and attempt == 0:
                self._token = None                 # expired early; renew once
                continue
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(min(2 ** attempt, 10))
                continue
            if r.status_code == 404:
                return None
            if r.status_code >= 400:
                raise BrightcoveError(f"Brightcove GET {path}: HTTP {r.status_code}")
            return r.json()
        raise BrightcoveError(f"Brightcove GET {path} kept failing")

    # ─────────────────────────────────────────────────────────── reads
    def video(self, video_id: str) -> dict | None:
        return self._get(f"/videos/{video_id}")

    #: The CMS API takes up to 10 comma-separated ids in one GET /videos/.
    BATCH = 10

    def cover_images(self, video_ids: list[str]) -> dict[str, str]:
        """Each video's poster image, by id. (Not named "posters": the suite
        refuses any public name here that reads like a write, "post" included.)
        Brightcove's 1280x720 still on
        its public image CDN (cf-images...boltdns.net), which a browser loads
        with no sign-in (checked 2026-10-01). The 160x90 "thumbnail" is the
        fallback only -- too small for a card.

        Ten ids per request. A batch that answers 404 (an id that no longer
        exists can do that) is retried one id at a time, so one deleted video
        does not cost its nine neighbours their posters.
        """
        out: dict[str, str] = {}
        ids = [str(i) for i in dict.fromkeys(video_ids) if i]
        for start in range(0, len(ids), self.BATCH):
            chunk = ids[start:start + self.BATCH]
            videos = self._get("/videos/" + ",".join(chunk))
            if videos is None and len(chunk) > 1:
                videos = [v for v in (self._get(f"/videos/{i}") for i in chunk) if v]
            if isinstance(videos, dict):
                videos = [videos]
            for v in videos or []:
                images = v.get("images") or {}
                src = ((images.get("poster") or {}).get("src")
                       or (images.get("thumbnail") or {}).get("src") or "")
                if src.startswith("https://"):
                    out[str(v.get("id"))] = src
        return out

    def playlist_video_ids(self, playlist_id: str) -> list[str]:
        playlist = self._get(f"/playlists/{playlist_id}") or {}
        return [str(v) for v in playlist.get("video_ids") or []]

    #: Liwei, 2026-09-29: at most 1080p; where there is no 1080p, the highest
    #: there is. A 4K rendition would multiply the upload for no use in a
    #: demo catalogue.
    MAX_HEIGHT = 1080

    def best_mp4(self, video_id: str) -> dict | None:
        """The H.264 MP4 rendition to migrate, over https: url, size, width, height.

        The tallest at or below MAX_HEIGHT; if every rendition is taller, the
        smallest of those. These are Brightcove's transcodes, not the
        uploaded master; masters need a permission this credential does not
        have (§12). Audio-only MP4s have no height and are never chosen.
        """
        sources = self._get(f"/videos/{video_id}/sources") or []
        mp4 = [s for s in sources
               if (s.get("container") or "").upper() == "MP4" and s.get("height")
               and (s.get("src") or "").startswith("https://")]
        if not mp4:
            return None
        within = [s for s in mp4 if s["height"] <= self.MAX_HEIGHT]
        if within:
            best = max(within, key=lambda s: (s["height"], s.get("size") or 0))
        else:
            best = min(mp4, key=lambda s: (s["height"], s.get("size") or 0))
        return {"url": best["src"], "size": best.get("size"),
                "width": best.get("width"), "height": best.get("height")}


def get_brightcove_client() -> BrightcoveClient | None:
    """None when any of the three settings is missing."""
    if not (settings.brightcove_account_id and settings.brightcove_client_id
            and settings.brightcove_client_secret):
        return None
    return BrightcoveClient(settings.brightcove_account_id, settings.brightcove_client_id,
                            settings.brightcove_client_secret)
