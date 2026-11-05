"""Several workers on one share (2026-11-04, before the stress test).

App Service runs several gunicorn workers over the same DATA_DIR. These
tests start real processes, so a lock that only covers its own process
would fail them.
"""
from __future__ import annotations

import io
import json
import multiprocessing as mp
import os
import time

import pytest

from backend import file_safety
from backend.config import settings
from backend.repositories.json_repo import JsonAssetRepository, _atomic_write
from backend.repositories.base import AssetQuery

WORKERS = 6
EACH = 15


def _add_entries(path: str, worker: int, count: int) -> None:
    for i in range(count):
        with file_safety.locked(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
            except FileNotFoundError:
                data = {}
            data[f"{worker}-{i}"] = i
            _atomic_write(path, data)


def _write_codes(data_dir: str, emails: list[str]) -> None:
    settings.data_dir = data_dir
    from backend import gxc_shares
    for email in emails:
        gxc_shares.token_for(email, "gxc-x")


def _run(target, args_list):
    ctx = mp.get_context("spawn")
    procs = [ctx.Process(target=target, args=args) for args in args_list]
    for p in procs:
        p.start()
    for p in procs:
        p.join(120)
        assert p.exitcode == 0
    return procs


def test_no_update_is_lost_across_processes(tmp_path):
    path = str(tmp_path / "owned" / "shared.json")
    _run(_add_entries, [(path, w, EACH) for w in range(WORKERS)])
    with open(path, encoding="utf-8") as fh:
        assert len(json.load(fh)) == WORKERS * EACH
    assert not [n for n in os.listdir(tmp_path / "owned") if n.endswith((".tmp", ".lock"))]


def test_every_person_keeps_their_gxc_code(tmp_path):
    """The case that mattered: GXC people opening their first video at the
    same moment, in different workers. A lost code breaks every link that
    person already sent."""
    emails = [[f"p{w}-{i}@ptc.com" for i in range(5)] for w in range(WORKERS)]
    _run(_write_codes, [(str(tmp_path), e) for e in emails])
    with open(tmp_path / "owned" / "gxc_share_people.json", encoding="utf-8") as fh:
        people = json.load(fh)
    assert len(people["by_email"]) == WORKERS * 5
    assert len(set(people["by_email"].values())) == WORKERS * 5


def test_a_stale_lock_is_taken_over(tmp_path):
    path = str(tmp_path / "f.json")
    with open(path + ".lock", "w") as fh:
        fh.write("dead")
    old = time.time() - file_safety.STALE_SECONDS - 5
    os.utime(path + ".lock", (old, old))
    with file_safety.locked(path, wait=1):
        pass
    assert not os.path.exists(path + ".lock")


def test_a_held_lock_makes_others_wait_then_gives_up(tmp_path):
    path = str(tmp_path / "f.json")
    with open(path + ".lock", "w") as fh:
        fh.write("alive")
    with pytest.raises(TimeoutError):
        with file_safety.locked(path, wait=0.2):
            pass


def test_the_lock_is_reentrant(tmp_path):
    path = str(tmp_path / "f.json")
    with file_safety.locked(path):
        with file_safety.locked(path):
            pass
        assert os.path.exists(path + ".lock")
    assert not os.path.exists(path + ".lock")


def test_an_unreadable_codes_file_is_never_taken_for_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    from backend import gxc_shares
    gxc_shares.token_for("a@ptc.com", "gxc-x")
    people = tmp_path / "owned" / "gxc_share_people.json"
    people.write_text('{"codes": {', encoding="utf-8")
    with pytest.raises(ValueError):
        gxc_shares.token_for("b@ptc.com", "gxc-x")
    assert people.read_text(encoding="utf-8") == '{"codes": {', "left as it was"


# ───────────────────────────────────────────── the catalogue, shared per worker
@pytest.fixture
def catalogue(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    (tmp_path / "mirror").mkdir()
    rows = [{"id": "kit-a", "type": "vdk", "title": "A", "products": ["Creo"]},
            {"id": "gxc-b", "type": "video", "title": "B", "products": ["Creo"]}]
    (tmp_path / "mirror" / "sharepoint.json").write_text(json.dumps(rows[:1]), encoding="utf-8")
    (tmp_path / "mirror" / "gxc_video.json").write_text(json.dumps(rows[1:]), encoding="utf-8")
    return tmp_path


def _ids(data_dir, **kw):
    return {a.id for a in JsonAssetRepository(str(data_dir), **kw)
            .list(AssetQuery(limit=50)).items}


def test_the_catalogue_is_built_once_for_many_requests(catalogue, monkeypatch):
    built = []
    real = JsonAssetRepository._build_mirror
    monkeypatch.setattr(JsonAssetRepository, "_build_mirror",
                        lambda self: built.append(1) or real(self))
    for _ in range(5):
        assert _ids(catalogue) == {"kit-a", "gxc-b"}
        assert _ids(catalogue, gxc=False) == {"kit-a"}
    assert len(built) == 1


def test_a_change_by_another_worker_shows(catalogue):
    """Written without this process knowing (no _atomic_write here): the
    file's time and size are what notice it."""
    assert _ids(catalogue) == {"kit-a", "gxc-b"}
    path = catalogue / "mirror" / "sharepoint.json"
    path.write_text(json.dumps([{"id": "kit-c", "type": "vdk", "title": "Ccc",
                                 "products": ["Creo"]}]), encoding="utf-8")
    assert _ids(catalogue) == {"kit-c", "gxc-b"}
    (catalogue / "owned").mkdir(exist_ok=True)
    (catalogue / "owned" / "hidden.json").write_text(json.dumps({"kit-c": {}}),
                                                     encoding="utf-8")
    assert _ids(catalogue) == {"gxc-b"}


def test_gxc_stays_out_for_people_without_it(catalogue):
    assert _ids(catalogue, gxc=False) == {"kit-a"}
    repo = JsonAssetRepository(str(catalogue), gxc=False, gxc_granted=frozenset({"gxc-b"}))
    assert repo.get("gxc-b") is not None, "a granted one opens"
    assert _ids(catalogue, gxc=False, gxc_granted=frozenset({"gxc-b"})) == {"kit-a"}, \
        "and is listed nowhere"


def test_a_caller_sorting_its_rows_leaves_the_cache_alone(catalogue):
    rows = JsonAssetRepository(str(catalogue))._load_mirror()
    before = [r["id"] for r in rows]
    rows.reverse()
    rows.clear()
    assert [r["id"] for r in JsonAssetRepository(str(catalogue))._load_mirror()] == before


# ───────────────────────────────────────────────────────────── thumbnails
def _picture(size=(800, 800), mode="RGB", alpha=128):
    """A photo-like picture: noise, which a PNG cannot squeeze."""
    from PIL import Image
    image = Image.merge("RGB", [Image.effect_noise(size, 60 + 10 * i) for i in range(3)])
    if mode == "RGBA":
        image = image.convert("RGBA")
        image.putalpha(Image.new("L", size, alpha))
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def test_pictures_are_made_small():
    from PIL import Image
    from backend.services import thumbnails
    data = _picture()
    small, kind = thumbnails.compact(data, "image/png")
    assert kind == "image/jpeg" and len(small) < len(data)
    assert max(Image.open(io.BytesIO(small)).size) == thumbnails.COMPACT_PX
    clear, kind = thumbnails.compact(_picture(mode="RGBA"), "image/png")
    assert kind == "image/png", "transparency kept"
    opaque, kind = thumbnails.compact(_picture(mode="RGBA", alpha=255), "image/png")
    assert kind == "image/jpeg", "an alpha channel nobody can see through is dropped"
    assert thumbnails.compact(b"not a picture", "image/jpeg") == (b"not a picture", "image/jpeg")


def test_a_picture_cached_before_is_made_small_keeping_its_age(tmp_path):
    from backend.services import thumbnails
    url = "https://ptccloud.sharepoint.com/sites/x/a.png"
    data_path, meta_path = thumbnails._paths(str(tmp_path), url)
    os.makedirs(os.path.dirname(data_path))
    big = _picture()
    with open(data_path, "wb") as fh:
        fh.write(big)
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump({"content_type": "image/png", "url": url}, fh)
    fetched = time.time() - 3 * 86400
    os.utime(data_path, (fetched, fetched))
    got, kind = thumbnails.get(str(tmp_path), None, url)
    assert kind == "image/jpeg" and len(got) < len(big)
    assert abs(os.path.getmtime(data_path) - fetched) < 2
    with open(meta_path, encoding="utf-8") as fh:
        assert json.load(fh)["compact"] == thumbnails.COMPACT_VERSION


def test_a_stale_picture_is_shown_at_once_and_fetched_again_behind_it(tmp_path, monkeypatch):
    from backend.services import thumbnails
    url = "https://ptccloud.sharepoint.com/sites/x/b.png"
    data_path, meta_path = thumbnails._paths(str(tmp_path), url)
    os.makedirs(os.path.dirname(data_path))
    with open(data_path, "wb") as fh:
        fh.write(b"old")
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump({"content_type": "image/jpeg", "url": url,
                   "compact": thumbnails.COMPACT_VERSION}, fh)
    old = time.time() - (thumbnails.CACHE_DAYS + 1) * 86400
    os.utime(data_path, (old, old))
    asked = []
    monkeypatch.setattr(thumbnails, "_refresh_soon", lambda d, c, u: asked.append(u))
    monkeypatch.setattr(thumbnails, "fetch", lambda c, u: pytest.fail("the viewer waited"))
    assert thumbnails.get(str(tmp_path), object(), url, wait=False) == (b"old", "image/jpeg")
    assert asked == [url]
