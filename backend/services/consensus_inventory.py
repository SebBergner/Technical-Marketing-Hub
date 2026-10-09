"""Which Consensus videos are already in SharePoint, and which need migrating.

Meeting 2026-10-07 (Elio, Seb, Liwei): before anything is migrated, a
reviewed inventory of Consensus videos against SharePoint, because names
differ between the two. Pure -- no HTTP -- so it can be tested; the script
`scripts/consensus_inventory.py` fetches and writes the spreadsheet.

The unit is a Consensus **video**, not a demo. Measured 2026-10-09 on the
reports endpoint (`/api/reports/v1.0/demosDetails`, published demos only):

* a `single` demo has one `mainVideo` {videoUuid, duration};
* a playlist (`standard`, `advanced`, `flow`) lists its chapters under
  `features`, each pointing at a video by uuid -- the same uuid a single
  demo carries when that video is also published on its own;
* `advanced` demos nest whole demos under `subDemos`.

So one video can be a demo of its own and a chapter of several playlists,
and a chapter can be a video with no demo of its own. Keying on the video
uuid gives each video one row, with every demo and playlist that uses it.

Matching against SharePoint uses what both sides have:

* **duration** -- exact on Consensus (to 1/100 s), whole seconds in
  SharePoint's file metadata. On its own it is NOT evidence: with ~1,400
  SharePoint videos a Consensus video typically has ~7 within two seconds
  by coincidence (measured 2026-10-09). It confirms a name; it never makes
  one.
* **name** -- the demo title and the topic parts of its internal title,
  against the SharePoint file name and its demo's title, scored by the same
  `consensus_match.similarity` the rest of the Hub uses (it already guards
  against language, number and "No Audio" mismatches), after removing event
  and kit boilerplate ("PTC NEXT - Spring 2026", "Demonstration Spotlight",
  "_Technical Walkthrough", "v.1").
* **language** -- a different language is a different video.

File size is not available from Consensus at all, so it cannot be compared;
it is shown for SharePoint so a reviewer can tell copies apart.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.services.consensus_match import normalise, similarity

# ─────────────────────────────────────────────────────────────── statuses
IN_SP = "In SharePoint"
LIKELY = "Probably in SharePoint - check"
OTHER_CUT = "Similar title, different length - check"
#: Same name and length as a SharePoint video, but a Consensus video of its
#: own in another language -- measured 2026-10-09: five localized playlists
#: (ja, it, de, fr, zh) whose 21 chapters each have English names and the
#: exact length of the English SharePoint video. Subtitled or dubbed: the
#: reviewers decide whether that is a file to migrate.
OTHER_LANGUAGE = "Other-language version of a SharePoint video - check"
MIGRATE = "Not in SharePoint - migrate"
NO_DURATION = "No duration in Consensus - check by name"
STATUS_ORDER = [IN_SP, LIKELY, OTHER_LANGUAGE, OTHER_CUT, NO_DURATION, MIGRATE]

#: Duration agreement. Strong: the same file, give or take rounding and a
#: re-encode. Near: the same video with a trimmed intro or end card.
STRONG_SECONDS, STRONG_SHARE = 2.0, 0.005
NEAR_SECONDS, NEAR_SHARE = 10.0, 0.03

#: Name agreement on the 0-1 similarity scale.
NAME_SAME = 0.5          # with a strong duration: the same video
NAME_LIKELY = 0.4        # with a strong duration: worth a look (0.3-0.4 measured
                         # 2026-10-09 to be coincidences of length)
NAME_NEAR = 0.6          # with a near duration: worth a look
NAME_OTHER_CUT = 0.7     # alone, with the duration off: a different edit
NAME_ONLY = 0.8          # alone, when Consensus has no duration

#: Boilerplate that says where or how a video was shown, not what it is.
_BOILERPLATE = [
    r"ptc\s*next\s*[-–]?\s*(?:(?:spring|summer|fall|autumn|winter)\s*)?\d{4}",
    r"\bdemonstration spotlight\b", r"\btechnical walkthrough\b",
    r"\btechnical overview\b", r"\bproduct overview\b", r"\bsynopsis\b",
    r"\bsingle\b", r"\bplaylist\b", r"\btraining\b", r"\bdemo picks\b",
    r"\b(?:vdk|ldk|bdk)\b", r"\bv\.?\s?\d+(?:\.\d+)?\b",
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{4}\b",
    r"\bqks\b", r"\bdemo video\b", r"\bvoice[\s_-]*over\b",
]
_EXT = re.compile(r"\.(?:mp4|mov|m4v|wmv|avi|mkv|webm)$", re.I)
_DURATION_PART = re.compile(r"^\s*\d{1,3}:\d{2}(?::\d{2})?\s*$")
#: Segment labels at the front of the internal-title convention
#: ("CAD | Creo | Topic | Kind | 11:00").
_SEGMENTS = {"cad", "plm", "slm", "alm", "iot", "ar", "saas", "corp", "corporate"}


#: Product names. Two names that each name a product, but no product in
#: common, are two different videos however alike the rest reads ("Mathcad
#: Prime - Symbolics" is not "AutoCAD WGM Overview").
PRODUCTS = {"creo", "windchill", "codebeamer", "servicemax", "mathcad", "arbortext",
            "onshape", "thingworx", "vuforia", "servigistics", "kepware", "autocad",
            "solidworks", "jetstream", "orbit", "ignition", "illustrate", "modeler",
            "flexplm", "integrity", "navigate"}
#: Language tags in internal titles and file names ("... MBD KO", "(ZH-CN)").
_LOCALE_TAGS = {"ko", "kr", "zh", "cn", "ja", "jp", "de", "fr", "it", "es", "pt", "ru",
                "chs", "cht", "kor", "jpn", "chn"}


def _non_latin(text: str | None) -> bool:
    return any(c.isalpha() and not c.isascii() for c in text or "")


def _localized(texts) -> bool:
    """Written in another script, or tagged with another language."""
    for t in texts:
        if _non_latin(t):
            return True
        tokens = set(re.split(r"[^a-z]+", (t or "").lower()))
        if tokens & _LOCALE_TAGS:
            return True
    return False


def _products(text: str) -> set[str]:
    return set(normalise(text).split()) & PRODUCTS


def _without_products(text: str) -> str:
    return " ".join(t for t in normalise(text).split() if t not in PRODUCTS)


def name_score(a: str, b: str) -> float:
    """`similarity`, plus credit when one name is wholly inside the other
    ("Working with Geometry and Visualization" inside "Creo Illustrate -
    Working with Geometry and Visualization"). Only for names of three or
    more words, where containment says something."""
    # Products are compared on their own (see `match`), so the name is scored
    # on what is left: two Codebeamer videos of the same length must not pass
    # on "codebeamer" alone (measured 2026-10-09: "Codebeamer AI Requirement
    # Assistant" against "Codebeamer Test Basics").
    a_topic, b_topic = _without_products(a), _without_products(b)
    if a_topic and b_topic:
        a, b = a_topic, b_topic
    score = similarity(a, b)
    ta, tb = set(normalise(a).split()), set(normalise(b).split())
    small, large = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if len(small) >= 3 and small <= large:
        score = max(score, 0.6)
    return score


def clean(name: str | None) -> str:
    """A title or file name without extension, separators and boilerplate."""
    text = _EXT.sub("", name or "")
    text = re.sub(r"^\s*\d+(?:\.\d+)*\s*[.)_-]\s*", "", text)   # "2.Working with ..."
    text = re.sub(r"[_|]+", " ", text)
    for pattern in _BOILERPLATE:
        text = re.sub(pattern, " ", text, flags=re.I)
    return " ".join(text.split()).strip(" -–.,:")


def internal_topic(internal_title: str | None) -> str | None:
    """The informative parts of "CAD | Creo | Topic | Kind | 11:00"."""
    if not internal_title or "|" not in internal_title:
        return None
    parts = [p.strip() for p in internal_title.split("|")]
    keep = [p for p in parts if p and not _DURATION_PART.match(p)
            and p.lower() not in _SEGMENTS]
    return " ".join(keep) or None


def _duration(value) -> float | None:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


def _lang(value) -> str | None:
    if isinstance(value, dict):
        value = value.get("code")
    return (value or "").split("-")[0].lower() or None


# ─────────────────────────────────────────────────────── the Consensus side
@dataclass
class ConsensusVideo:
    video_uuid: str
    duration: float | None = None
    language: str | None = None
    #: Demos whose own video this is: {uuid, title, internal_title, public, created_at}.
    demos: list[dict] = field(default_factory=list)
    #: Playlists that use it as a chapter: {uuid, title, chapter, public}.
    playlists: list[dict] = field(default_factory=list)

    @property
    def title(self) -> str:
        if self.demos:
            return self.demos[0]["title"]
        return self.playlists[0]["chapter"] if self.playlists else self.video_uuid

    def names(self) -> list[str]:
        out = []
        for d in self.demos:
            out += [d.get("title"), internal_topic(d.get("internal_title"))]
        out += [p.get("chapter") for p in self.playlists]
        seen, names = set(), []
        for n in out:
            c = clean(n)
            if c and c.lower() not in seen:
                seen.add(c.lower())
                names.append(c)
        return names

    @property
    def public(self) -> bool:
        return any(d.get("public") for d in self.demos) or any(
            p.get("public") for p in self.playlists)


def _demo_ref(d: dict) -> dict:
    return {"uuid": d.get("uuid"), "title": d.get("title"),
            "internal_title": d.get("internalTitle"), "public": bool(d.get("isPublic")),
            "created_at": d.get("createdAt"), "type": d.get("type")}


def consensus_videos(details: list[dict], languages: dict[str, str] | None = None
                     ) -> tuple[list[ConsensusVideo], list[dict], list[dict]]:
    """(videos, playlists, demos without a video) from demosDetails items.

    The reports endpoint carries no language; `languages` ({demo uuid: code},
    from demo/search) fills it in."""
    languages = languages or {}
    videos: dict[str, ConsensusVideo] = {}
    no_video: list[dict] = []

    def video(uuid: str, duration, language) -> ConsensusVideo:
        v = videos.get(uuid)
        if v is None:
            v = videos[uuid] = ConsensusVideo(uuid)
        v.duration = v.duration or _duration(duration)
        v.language = v.language or _lang(language)
        return v

    def own(demo: dict, language) -> None:
        main = demo.get("mainVideo") or {}
        uuid = main.get("videoUuid")
        if not uuid:
            if demo.get("type") == "single":
                no_video.append(_demo_ref(demo))
            return
        ref = _demo_ref(demo)
        v = video(uuid, main.get("duration"), language)
        if ref["uuid"] not in {d["uuid"] for d in v.demos} and demo.get("type") == "single":
            v.demos.append(ref)

    playlists: list[dict] = []

    def chapters(playlist: dict, demo: dict, language) -> None:
        for f in demo.get("features") or []:
            for kind in ("long", "short"):
                uuid = f.get(f"{kind}VideoUuid")
                if not uuid:
                    continue
                v = video(uuid, f.get(f"{kind}VideoDuration"), language)
                chapter = f.get("name") + (" (short)" if kind == "short" else "")
                v.playlists.append({"uuid": playlist["uuid"], "title": playlist["title"],
                                    "chapter": chapter, "public": playlist["public"]})
                playlist["chapters"].append({"chapter": chapter, "video_uuid": uuid})

    for d in details:
        language = d.get("language") or languages.get(d.get("uuid"))
        if d.get("type") == "single":
            own(d, language)
            continue
        playlist = {**_demo_ref(d), "chapters": []}
        playlists.append(playlist)
        chapters(playlist, d, language)
        for sub in d.get("subDemos") or []:
            if sub.get("uuid") == d.get("uuid"):
                continue
            if sub.get("type") == "single":
                own(sub, languages.get(sub.get("uuid")) or language)
                main = (sub.get("mainVideo") or {}).get("videoUuid")
                if main:
                    v = videos[main]
                    v.playlists.append({"uuid": playlist["uuid"], "title": playlist["title"],
                                        "chapter": sub.get("title"), "public": playlist["public"]})
                    playlist["chapters"].append({"chapter": sub.get("title"),
                                                 "video_uuid": main})
            else:
                chapters(playlist, sub, language)
    return list(videos.values()), playlists, no_video


# ─────────────────────────────────────────────────────── the SharePoint side
def sharepoint_videos(libraries: dict[str, list[dict]]) -> list[dict]:
    """Every video file in the mirrors, one dict each. `libraries` maps a
    library name to its mirror rows ("Demo Video": [...], "Demo Catalog": [...])."""
    out = []
    for library, rows in libraries.items():
        for r in rows:
            for res in r.get("resources") or []:
                if res.get("kind") != "video":
                    continue
                out.append({
                    "library": library, "asset_id": r.get("id"), "asset_title": r.get("title"),
                    "file": res.get("name"), "item_id": res.get("item_id"),
                    "size_bytes": res.get("size_bytes"),
                    "duration": _duration(res.get("duration_seconds")),
                    "width": res.get("width"), "height": res.get("height"),
                    "created_at": res.get("created_at"), "language": _lang(r.get("language")),
                    "web_url": r.get("web_url"), "consensus_uuid": r.get("consensus_uuid"),
                })
    return out


# ─────────────────────────────────────────────────────────────── matching
def _agreement(a: float | None, b: float | None) -> str | None:
    """"strong", "near", "off", or None when either side has no duration."""
    if a is None or b is None:
        return None
    diff = abs(a - b)
    if diff <= max(STRONG_SECONDS, a * STRONG_SHARE):
        return "strong"
    if diff <= max(NEAR_SECONDS, a * NEAR_SHARE):
        return "near"
    return "off"


def _classify(name: float, duration: str | None) -> str | None:
    if duration == "strong" and name >= NAME_SAME:
        return IN_SP
    if (duration == "strong" and name >= NAME_LIKELY) or (
            duration == "near" and name >= NAME_NEAR):
        return LIKELY
    if duration is None and name >= NAME_ONLY:
        return NO_DURATION
    if duration in ("off", "near") and name >= NAME_OTHER_CUT:
        return OTHER_CUT
    return None


@dataclass
class Match:
    status: str
    best: dict | None = None
    name_score: float = 0.0
    duration_diff: float | None = None
    #: Other SharePoint files that are the same file as `best` (same length
    #: and size): copies in another folder or library.
    copies: list[dict] = field(default_factory=list)
    #: The next-best candidate of a different file, for the reviewer.
    runner_up: dict | None = None
    runner_up_score: float = 0.0


def _rank(status: str | None) -> int:
    return len(STATUS_ORDER) - STATUS_ORDER.index(status) if status in STATUS_ORDER else 0


def match(video: ConsensusVideo, sp: list[dict]) -> Match:
    names = video.names()
    raw = [d.get("title") for d in video.demos] + [d.get("internal_title") for d in video.demos]         + [p.get("chapter") for p in video.playlists]
    localized = _localized(raw)
    products = set().union(*(_products(n) for n in names)) if names else set()
    scored = []
    for s in sp:
        other_language = bool(video.language and s.get("language")
                              and s["language"] != video.language)
        if localized != _localized([s.get("file"), s.get("asset_title")]):
            continue
        targets = [clean(s.get("file")), clean(s.get("asset_title"))]
        theirs = set().union(*(_products(t) for t in targets if t))
        if products and theirs and not products & theirs:
            continue                       # different products: different videos
        name = max((name_score(n, t) for n in names for t in targets if n and t), default=0.0)
        if name < NAME_LIKELY:
            continue
        agree = _agreement(video.duration, s.get("duration"))
        status = _classify(name, agree)
        if status is None:
            continue
        if other_language:
            # Another language is another file. Only worth showing when it
            # would otherwise have counted as the same video.
            if status not in (IN_SP, LIKELY):
                continue
            status = OTHER_LANGUAGE
        diff = (abs(video.duration - s["duration"])
                if video.duration is not None and s.get("duration") is not None else None)
        scored.append((_rank(status), name, -(diff if diff is not None else 9e9), status, diff, s))
    if not scored:
        return Match(MIGRATE)
    scored.sort(key=lambda t: t[:3], reverse=True)
    _, name, _, status, diff, best = scored[0]
    same_file = lambda s: (s is not best and s.get("duration") == best.get("duration")  # noqa: E731
                           and s.get("size_bytes") and s.get("size_bytes") == best.get("size_bytes"))
    copies = [s for *_, s in scored[1:] if same_file(s)]
    others = [t for t in scored[1:] if not same_file(t[-1])]
    runner = others[0] if others else None
    return Match(status, best, round(name, 2), None if diff is None else round(diff, 1),
                 copies, runner[-1] if runner else None, round(runner[1], 2) if runner else 0.0)


def build(details: list[dict], libraries: dict[str, list[dict]],
          languages: dict[str, str] | None = None) -> dict:
    """Everything the spreadsheet shows."""
    videos, playlists, no_video = consensus_videos(details, languages)
    sp = sharepoint_videos(libraries)
    rows = [(v, match(v, sp)) for v in videos]
    rows.sort(key=lambda r: (STATUS_ORDER.index(r[1].status), r[0].title.lower()))
    by_uuid = {v.video_uuid: m for v, m in rows}
    for p in playlists:
        for c in p["chapters"]:
            c["status"] = by_uuid[c["video_uuid"]].status if c["video_uuid"] in by_uuid else None
    # SharePoint files more than one Consensus video was matched to.
    claimed: dict[str, list[str]] = {}
    for v, m in rows:
        if m.best and m.status in (IN_SP, LIKELY):
            claimed.setdefault(m.best["item_id"] or m.best["file"], []).append(v.title)
    return {"videos": rows, "playlists": playlists, "no_video": no_video,
            "sharepoint": sp, "shared_files": {k: t for k, t in claimed.items() if len(t) > 1}}
