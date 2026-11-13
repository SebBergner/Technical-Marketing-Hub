"""Search terms that mean the same: abbreviations and their spelled-out forms
(Liwei, 2026-11-13; Hub Tasks #15, #17, #29).

"MBSE" and "Model-Based Systems Engineering" found different demos, and so
did "IPL" and "Intelligent Product Lifecycle", "EHT" and "E&HT": a demo says
one or the other. Here each group is a set of terms that mean the same; a
search that names one of them also looks for the others, so either way finds
the same demos (relevance.score takes the best of them).

The groups are kept in owned/search_terms.json and edited on Admin -> Search
terms. Until the first edit the Hub uses DEFAULTS, the first version: the
abbreviations the catalogue spells out itself ("Connected Work Cell (CWC)",
counted 2026-11-13 over the 1,715 records), and those the feedback named.
The first edit writes them all to the file, so later ones change the file.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from functools import lru_cache

from backend.config import settings

FILE = "search_terms.json"
MAX_GROUPS = 500
MAX_TERMS = 10
MAX_LEN = 80
MAX_NOTE = 200
#: A query naming several groups' terms is tried in at most this many ways.
MAX_VARIANTS = 8
#: How often a worker looks at the file again (each worker keeps its own copy).
RECHECK_SECONDS = 5

#: The first version. [terms, note].
DEFAULTS: list[tuple[list[str], str]] = [
    # Named in feedback (Hub Tasks #15, #29).
    (["MBSE", "Model-Based Systems Engineering"], "Hub Tasks #29"),
    (["IPL", "Intelligent Product Lifecycle"], "Hub Tasks #29; 25 demos spell it out"),
    (["EHT", "E&HT", "Electronics & High Tech"], "Hub Tasks #29: both spellings are used"),
    (["PLE", "Product Line Engineering"], "Hub Tasks #15"),
    # Spelled out in the catalogue's own titles and descriptions.
    (["CWC", "Connected Work Cell"], "Catalogue"),
    (["DPM", "Digital Performance Management"], "Catalogue"),
    (["CSL", "Creo Simulation Live"], "Catalogue"),
    (["MDO", "Mechanism Dynamics Option"], "Catalogue"),
    (["BMX", "Behavioral Modeling"], "Catalogue"),
    (["AMX", "Advanced Assembly Extension"], "Catalogue"),
    (["RTPPM", "Real-Time Production Performance Monitoring"], "Catalogue"),
    (["ACD", "Arbortext Content Delivery"], "Catalogue"),
    (["CEM", "Customer Experience Management"], "Catalogue"),
    (["SPC", "Statistical Process Control"], "Catalogue"),
    (["TLA", "Time Loss Analytics"], "Catalogue"),
    (["SDV", "Software-Defined Vehicle"], "Catalogue"),
    (["MBD", "Model-Based Definition"], "Catalogue"),
    (["SCPA", "SCP Accelerator"], "Catalogue"),
    (["AR", "Augmented Reality"], "Catalogue"),
    # Common words in the catalogue, written both ways.
    (["BOM", "Bill of Materials"], "Catalogue: 74 demos say BOM, 9 the words"),
    (["PLM", "Product Lifecycle Management"], "Catalogue"),
    (["ALM", "Application Lifecycle Management"], "Catalogue"),
    (["SLM", "Service Lifecycle Management"], "Segment name"),
    (["GD&T", "Geometric Dimensioning and Tolerancing"], "Catalogue"),
    (["CFD", "Computational Fluid Dynamics"], "Catalogue"),
    (["FMEA", "Failure Mode and Effects Analysis"], "Catalogue"),
    (["CAPA", "Corrective and Preventive Action"], "Catalogue"),
    (["IoT", "Internet of Things"], "Catalogue: 16 demos say IoT"),
    (["AI", "Artificial Intelligence"], "Catalogue: 54 demos say AI"),
    (["SysML", "Systems Modeling Language"], "Catalogue"),
    (["VDK", "Video Demo Kit", "Virtual Demo Kit"], "Asset type"),
    (["LDK", "Live Demo Kit"], "Asset type"),
    (["VM", "Virtual Machine"], "Asset type"),
]

_lock = threading.Lock()
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


class TermsError(ValueError):
    """What the person editing is told."""


def _path(data_dir: str | None = None) -> str:
    return os.path.join(data_dir or settings.data_dir, "owned", FILE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _default_groups() -> list[dict]:
    return [{"id": f"d{i + 1}", "terms": list(t), "note": n}
            for i, (t, n) in enumerate(DEFAULTS)]


def load(data_dir: str | None = None) -> dict:
    """{"groups": [...], "saved": bool}: the file's, or DEFAULTS until the first edit."""
    try:
        with open(_path(data_dir), encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get("groups"), list):
            return {"groups": data["groups"], "saved": True,
                    "changed_at": data.get("changed_at"), "changed_by": data.get("changed_by")}
    except (FileNotFoundError, ValueError):
        pass
    return {"groups": _default_groups(), "saved": False}


def words(term: str) -> tuple[str, ...]:
    """A term as search words, the way relevance.terms splits a query
    ("&" and "and" are no words: "E&HT" is ("e", "ht"))."""
    from backend.services.relevance import terms
    return tuple(terms(term))


def _clean(terms_in, note, groups, own_id=None) -> tuple[list[str], str]:
    out, seen = [], set()
    for t in terms_in or []:
        t = " ".join(str(t or "").split())
        if not t:
            continue
        if len(t) > MAX_LEN:
            raise TermsError(f"“{t[:30]}…” is longer than {MAX_LEN} characters.")
        w = words(t)
        if not w:
            raise TermsError(f"“{t}” has no letters or digits to search for.")
        if w in seen:
            raise TermsError(f"“{t}” is the same search as another term in this group.")
        seen.add(w)
        out.append(t)
    if len(out) < 2:
        raise TermsError("A group needs at least two terms that mean the same.")
    if len(out) > MAX_TERMS:
        raise TermsError(f"At most {MAX_TERMS} terms in a group.")
    for g in groups:
        if g.get("id") == own_id:
            continue
        for t in g.get("terms") or []:
            if words(t) in seen:
                raise TermsError(f"“{t}” is already in the group “{' = '.join(g['terms'])}”. "
                                 "Add the new terms to that group instead.")
    return out, " ".join(str(note or "").split())[:MAX_NOTE]


def _save(data_dir, groups, actor) -> dict:
    from backend.file_safety import replace_with
    path = _path(data_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {"groups": groups, "changed_at": _now(), "changed_by": actor}
    replace_with(path, lambda fh: json.dump(data, fh, ensure_ascii=False, indent=1))
    return data


def add(terms_in, note, actor, data_dir: str | None = None) -> dict:
    from backend.file_safety import locked
    with _lock, locked(_path(data_dir)):
        groups = load(data_dir)["groups"]
        if len(groups) >= MAX_GROUPS:
            raise TermsError(f"At most {MAX_GROUPS} groups.")
        terms_out, note_out = _clean(terms_in, note, groups)
        group = {"id": secrets.token_hex(4), "terms": terms_out, "note": note_out,
                 "changed_at": _now(), "changed_by": actor}
        _save(data_dir, groups + [group], actor)
    return group


def update(group_id, terms_in, note, actor, data_dir: str | None = None) -> dict:
    from backend.file_safety import locked
    with _lock, locked(_path(data_dir)):
        groups = load(data_dir)["groups"]
        found = next((g for g in groups if g.get("id") == group_id), None)
        if found is None:
            raise KeyError(group_id)
        terms_out, note_out = _clean(terms_in, note, groups, own_id=group_id)
        found.update({"terms": terms_out, "note": note_out,
                      "changed_at": _now(), "changed_by": actor})
        _save(data_dir, groups, actor)
    return found


def remove(group_id, actor, data_dir: str | None = None) -> None:
    from backend.file_safety import locked
    with _lock, locked(_path(data_dir)):
        groups = load(data_dir)["groups"]
        kept = [g for g in groups if g.get("id") != group_id]
        if len(kept) == len(groups):
            raise KeyError(group_id)
        _save(data_dir, kept, actor)


# ─────────────────────────────────────────────────────────── for the search
_seen: dict = {"path": None, "at": 0.0, "stamp": None, "table": ()}


def _table() -> tuple:
    """((words, ...), ...) per group, for this worker; the file is looked at
    again at most every RECHECK_SECONDS, so another worker's edit shows soon."""
    path = _path()
    now = time.monotonic()
    if _seen["path"] == path and now - _seen["at"] < RECHECK_SECONDS:
        return _seen["table"]
    try:
        stamp = os.stat(path).st_mtime_ns
    except OSError:
        stamp = None
    if _seen["path"] != path or stamp != _seen["stamp"]:
        table = tuple(tuple(dict.fromkeys(w for w in (words(t) for t in g.get("terms") or []) if w))
                      for g in load()["groups"])
        _seen.update(table=tuple(g for g in table if len(g) > 1), stamp=stamp)
    _seen.update(path=path, at=now)
    return _seen["table"]


def variants(text: str | None) -> tuple[str, ...]:
    """The query, and the query with each group's term swapped for the
    group's others: "mbse demo" -> ("mbse demo", "model based systems
    engineering demo"). The query itself always comes first."""
    if not text:
        return (text,) if text is not None else ()
    return _variants(text, _table())


def _same(q: str, t: str) -> bool:
    # A plural in the query still names the term: "software defined vehicles".
    return q == t or q == t + "s" or q == t + "es"


def _find(tokens: tuple, member: tuple) -> int:
    n = len(member)
    for i in range(len(tokens) - n + 1):
        if all(_same(tokens[i + k], member[k]) for k in range(n)):
            return i
    return -1


@lru_cache(maxsize=4096)
def _variants(text: str, table: tuple) -> tuple[str, ...]:
    from backend.services.relevance import terms
    start = tuple(terms(text))
    found = [start]
    for group in table:
        for tokens in list(found):
            for member in group:
                i = _find(tokens, member)
                if i < 0:
                    continue
                for other in group:
                    if other == member:
                        continue
                    swapped = tokens[:i] + other + tokens[i + len(member):]
                    if swapped not in found:
                        found.append(swapped)
                    if len(found) >= MAX_VARIANTS:
                        break
                break
            if len(found) >= MAX_VARIANTS:
                break
    return (text,) + tuple(" ".join(t) for t in found[1:])
