"""Brightcove as the migration's source, against a mocked Brightcove.

The credential can WRITE the Brightcove account (measured 2026-09-29), so the
first thing pinned is that the client only ever GETs from the CMS API. Then:
the rendition choice, filling a manifest's blanks without overriding the
sheet, and a fresh signed URL on every (re)start of a download.
"""
from __future__ import annotations

import httpx
import pytest

from backend.integrations.brightcove import BrightcoveClient
from backend.integrations.graph import migration_writer as w
from backend.services import brightcove_runner as run

VIDEO = {"id": "6300000000001", "name": "Windchill: Change Management Overview",
         "description": "How change flows.", "long_description": "Longer.",
         "published_at": "2019-05-14T10:00:00.000Z", "created_at": "2019-05-01T00:00:00.000Z",
         "state": "ACTIVE", "original_filename": "WC_Change_Mgmt_v3.mov"}
SOURCES = [
    {"container": "M2TS", "type": "application/x-mpegURL", "src": "https://hls/master.m3u8"},
    {"container": "MP4", "codec": "H264", "height": 1080, "width": 1920, "size": 50_000,
     "src": "http://cdn/1080.mp4"},                                   # http: never chosen
    {"container": "MP4", "codec": "H264", "height": 1080, "width": 1920, "size": 50_000,
     "src": "https://cdn/1080.mp4?sig=1"},
    {"container": "MP4", "codec": "H264", "height": 720, "width": 1280, "size": 30_000,
     "src": "https://cdn/720.mp4?sig=1"},
    {"container": "MP4", "codec": "mp4a", "size": 2_000, "src": "https://cdn/audio.mp4"},
]


class FakeBrightcove:
    def __init__(self, videos=None, sources=None):
        self.videos = {VIDEO["id"]: VIDEO} if videos is None else videos
        self.sources = SOURCES if sources is None else sources
        self.cms_methods: list[str] = []
        self.source_calls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth.brightcove.com":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 300})
        self.cms_methods.append(request.method)
        path = request.url.path
        if path.endswith("/sources"):
            self.source_calls += 1
            vid = path.split("/")[-2]
            return httpx.Response(200, json=self.sources) if vid in self.videos else httpx.Response(404)
        vid = path.rsplit("/", 1)[-1]
        if vid in self.videos:
            return httpx.Response(200, json=self.videos[vid])
        return httpx.Response(404)

    def client(self) -> BrightcoveClient:
        return BrightcoveClient("2088006836001", "id", "secret",
                                transport=httpx.MockTransport(self.handler), verify=True)


# ─────────────────────────────────────────────────────────── the client
def test_the_client_only_ever_gets_from_the_cms():
    fake = FakeBrightcove()
    bc = fake.client()
    bc.video(VIDEO["id"]); bc.best_mp4(VIDEO["id"]); bc.video("missing")
    assert set(fake.cms_methods) == {"GET"}
    public = [n for n in dir(bc) if not n.startswith("_")]
    assert not [n for n in public if any(w_ in n.lower() for w_ in
                                         ("post", "put", "patch", "delete", "update", "create"))]


def test_the_best_rendition_is_the_largest_https_mp4_never_audio_only():
    best = FakeBrightcove().client().best_mp4(VIDEO["id"])
    assert best == {"url": "https://cdn/1080.mp4?sig=1", "size": 50_000,
                    "width": 1920, "height": 1080}


def test_the_rendition_is_capped_at_1080p():
    """Liwei, 2026-09-29: at most 1080p, else the highest there is."""
    uhd = {"container": "MP4", "height": 2160, "width": 3840, "size": 900_000,
           "src": "https://cdn/2160.mp4?sig=1"}
    assert FakeBrightcove(sources=SOURCES + [uhd]).client().best_mp4(VIDEO["id"])["height"] == 1080
    only_720 = [s for s in SOURCES if s.get("height") != 1080]
    assert FakeBrightcove(sources=only_720).client().best_mp4(VIDEO["id"])["height"] == 720
    assert FakeBrightcove(sources=[uhd]).client().best_mp4(VIDEO["id"])["height"] == 2160


def test_a_missing_video_is_none_not_an_error():
    assert FakeBrightcove().client().video("nope") is None


# ─────────────────────────────────────────────────────────── enrich
def manifest(tmp_path, rows):
    header = "brightcove_id,title,description,segments,products,customer_facing,source,filename"
    p = tmp_path / "m.csv"
    p.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return str(p)


def test_blanks_are_filled_from_brightcove_and_the_sheet_wins(tmp_path):
    records = run.load_manifest(manifest(tmp_path, [
        f"{VIDEO['id']},,,PLM,,no,,",                              # everything from Brightcove
        f"{VIDEO['id'][:-1]}2,My Own Title,Own text,PLM,,yes,,",   # not in Brightcove
    ]))
    fake = FakeBrightcove(videos={VIDEO["id"]: VIDEO,
                                  VIDEO["id"][:-1] + "2": {**VIDEO, "name": "BC name"}})
    run.enrich(records, fake.client())
    a, b = records
    assert a.title == "Windchill: Change Management Overview"
    assert a.folder_name == "Windchill - Change Management Overview"
    assert a.description == "How change flows."
    assert str(a.original_publish_date) == "2019-05-14"          # published_at, not created_at
    run.validate(records, ["PLM"], w.TermIndex({}))
    # Named after the demo, not Brightcove's upload name (no Video Type here).
    assert a.filename == "Windchill - Change Management Overview.mp4"
    assert a.size_bytes == 50_000
    assert (b.title, b.description) == ("My Own Title", "Own text")


def test_the_file_is_named_demo_underscore_video_type(tmp_path):
    """Liwei, 2026-09-29: "Creo 10 Top Enhancements_Technical Overview"."""
    p = tmp_path / "m.csv"
    p.write_text("brightcove_id,title,customer_facing,video_type,filename\n"
                 f"{VIDEO['id']},Creo 10 Top Enhancements,yes,Technical Overview,\n"
                 f"{VIDEO['id'][:-1]}2,Kept As Given,yes,Technical Overview,own-name.mp4\n",
                 encoding="utf-8")
    records = run.load_manifest(str(p))
    run.validate(records, ["PLM"], w.TermIndex({}))
    assert records[0].filename == "Creo 10 Top Enhancements_Technical Overview.mp4"
    assert records[1].filename == "own-name.mp4"


def test_videos_brightcove_cannot_supply_are_reported(tmp_path):
    records = run.load_manifest(manifest(tmp_path, [
        "6399999999999,,,PLM,,no,,",
        f"{VIDEO['id']},,,PLM,,no,,"]))
    fake = FakeBrightcove(videos={VIDEO["id"]: {**VIDEO, "state": "INACTIVE"}},
                          sources=[s for s in SOURCES if s["container"] != "MP4"])
    run.enrich(records, fake.client())
    run.validate(records, ["PLM"], w.TermIndex({}))
    assert "not found in Brightcove" in records[0].problems
    assert any("INACTIVE" in p for p in records[1].problems)
    assert any("no downloadable MP4" in p for p in records[1].problems)


def test_a_local_source_does_not_touch_brightcove(tmp_path):
    records = run.load_manifest(manifest(tmp_path, [f"{VIDEO['id']},T,,PLM,,no,C:/x/clip.mp4,"]))
    assert not records[0].from_brightcove
    run.enrich(records, None)                  # would fail if it tried to call Brightcove
    assert records[0].filename == "clip.mp4"


# ─────────────────────────────────────────────────────────── the download
def test_every_open_asks_for_a_fresh_signed_url_and_resumes_by_range():
    fake = FakeBrightcove()
    bc = fake.client()
    seen = []

    def cdn(request):
        seen.append((str(request.url), request.headers.get("range")))
        body = b"x" * 50_000
        if request.headers.get("range"):
            start = int(request.headers["range"].split("=")[1].rstrip("-"))
            return httpx.Response(206, content=body[start:])
        return httpx.Response(200, content=body)

    src = w.BrightcoveSource(bc, VIDEO["id"], http=httpx.Client(transport=httpx.MockTransport(cdn)))
    assert src.size() == 50_000
    first = sum(len(c) for c in src.open(0))
    rest = sum(len(c) for c in src.open(20_000))
    assert (first, rest) == (50_000, 30_000)
    assert fake.source_calls == 3, "size + two opens: a fresh URL each time"
    assert seen[1][1] == "bytes=20000-"
