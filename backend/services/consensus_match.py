"""Matching Portal assets to Consensus demos, and reporting the gaps.

This is the "metadata donor" and "reconciliation report" from the architecture
doc. It is deliberately pure — no HTTP, no database — so it can be tested
exhaustively without either.

Matching is by title, because that is the only field both systems reliably
share. Titles drift, so exact equality is far too brittle: the same asset can
be "Windchill AI – Parts Rationalization LDK" on one side and "Windchill AI
Parts Rationalization LDK" on the other. Normalising then scoring similarity
handles that, while still refusing to guess when two candidates are close.

Every match carries a confidence and is treated as a *proposal*, never as
truth. A human confirms it before anything is written back.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from backend.integrations.consensus import ConsensusDemo
from backend.models import AssetSummary

#: Below this, not a candidate at all.
MATCH_THRESHOLD = 0.72
#: Above this, confident enough to propose without flagging as ambiguous.
STRONG_MATCH = 0.88
#: If the runner-up is this close to the winner, refuse to choose.
AMBIGUITY_MARGIN = 0.05

#: Dropped before comparison — they carry no distinguishing signal and their
#: presence varies between the two systems.
#:
#: Note what is deliberately NOT here: "part", "v1", "v2" and anything numeric.
#: Those look like filler but are exactly what separates "Part 1" from "Part 3".
_NOISE = {
    "the", "a", "an", "and", "or", "of", "for", "with", "to", "in", "on",
    "demo", "video", "replay",
}

#: Words that invert meaning. "No Audio" and "Audio" describe opposite assets,
#: and an attract loop with no narration cannot be shared the way a narrated
#: walkthrough can — so this distinction is not cosmetic.
_NEGATIONS = {"no", "not", "without", "silent", "mute", "muted"}

#: Multipliers applied when a discriminating signal disagrees.
_NUMBER_MISMATCH_PENALTY = 0.55
_NEGATION_MISMATCH_PENALTY = 0.45
#: Sequence similarity is a weak signal here — two titles sharing a long prefix
#: score high even when the distinguishing tail is completely different — so it
#: is discounted and can only win where token overlap is already respectable.
_SEQUENCE_WEIGHT = 0.80


def normalise(title: str) -> str:
    """Lowercase, strip punctuation and noise words, collapse whitespace.

    'Windchill AI – Parts Rationalization LDK' -> 'windchill ai parts rationalization ldk'
    """
    text = (title or "").lower()
    text = re.sub(r"[‐-―]", "-", text)          # unify dash variants
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(t for t in text.split() if t and t not in _NOISE)


def _numeric_tokens(tokens: set[str]) -> set[str]:
    return {t for t in tokens if any(ch.isdigit() for ch in t)}


def similarity(a: str, b: str) -> float:
    """0.0–1.0 confidence that two titles name the same asset.

    Token-set overlap is the primary signal. An earlier version also treated
    "short title fully contained in a longer one" as strong evidence, which
    scored 'Tech Walkthrough **No Audio** — Engineering Part 1' against
    'Tech Walkthrough **Audio** — Engineering' at 0.95 — a confident match
    between two assets that are opposites. Containment ignores precisely the
    words that carry the distinction, so it is gone.

    Two hard disqualifiers remain, because they encode real domain meaning:
    disagreeing numbers (Part 1 vs Part 3, Creo 11 vs Creo 13) and mismatched
    negation (Audio vs No Audio).
    """
    na, nb = normalise(a), normalise(b)
    if not na or not nb:
        return 0.0

    ta, tb = set(na.split()), set(nb.split())
    if ta == tb:
        return 1.0

    jaccard = len(ta & tb) / len(ta | tb)
    sequence = SequenceMatcher(None, na, nb).ratio() * _SEQUENCE_WEIGHT
    score = max(jaccard, sequence)

    num_a, num_b = _numeric_tokens(ta), _numeric_tokens(tb)
    if (num_a or num_b) and num_a != num_b:
        score *= _NUMBER_MISMATCH_PENALTY

    if (ta & _NEGATIONS) != (tb & _NEGATIONS):
        score *= _NEGATION_MISMATCH_PENALTY

    return score


@dataclass
class Candidate:
    demo: ConsensusDemo
    confidence: float


@dataclass
class AssetMatch:
    asset_id: str
    asset_title: str
    demo: ConsensusDemo
    confidence: float
    ambiguous: bool = False
    runner_up: ConsensusDemo | None = None

    @property
    def strong(self) -> bool:
        return self.confidence >= STRONG_MATCH and not self.ambiguous


@dataclass
class ReconciliationReport:
    """Gaps in both directions, plus what we would propose."""
    matched: list[AssetMatch] = field(default_factory=list)
    #: Confident, and the asset does not already carry a UUID — safe to propose.
    proposals: list[AssetMatch] = field(default_factory=list)
    #: A UUID is already recorded, and it disagrees with the match. Needs a human.
    conflicts: list[AssetMatch] = field(default_factory=list)
    #: Two or more plausible demos — refuse to choose.
    ambiguous: list[AssetMatch] = field(default_factory=list)
    #: Portal assets with no Consensus counterpart — cannot be shared externally.
    portal_only: list[AssetSummary] = field(default_factory=list)
    #: Consensus demos with no Portal asset — orphaned externally.
    consensus_only: list[ConsensusDemo] = field(default_factory=list)

    def summary(self) -> dict[str, int]:
        return {
            "matched": len(self.matched),
            "proposals": len(self.proposals),
            "conflicts": len(self.conflicts),
            "ambiguous": len(self.ambiguous),
            "portal_only": len(self.portal_only),
            "consensus_only": len(self.consensus_only),
        }


def best_candidates(title: str, demos: list[ConsensusDemo],
                    threshold: float = MATCH_THRESHOLD) -> list[Candidate]:
    scored = [Candidate(demo=d, confidence=similarity(title, d.title)) for d in demos]
    scored = [c for c in scored if c.confidence >= threshold]
    scored.sort(key=lambda c: c.confidence, reverse=True)
    return scored


def reconcile(assets: list[AssetSummary], demos: list[ConsensusDemo],
              threshold: float = MATCH_THRESHOLD) -> ReconciliationReport:
    """Compare both catalogues and classify every asset and demo.

    Exact UUID matches are honoured first and never second-guessed by title
    similarity — a recorded UUID is a human decision and outranks a heuristic.
    """
    report = ReconciliationReport()
    by_uuid = {d.uuid: d for d in demos if d.uuid}
    claimed: set[str] = set()

    for asset in assets:
        # 1. An existing, valid UUID settles it.
        if asset.consensus_uuid and asset.consensus_uuid in by_uuid:
            demo = by_uuid[asset.consensus_uuid]
            match = AssetMatch(asset.id, asset.title, demo, confidence=1.0)
            report.matched.append(match)
            claimed.add(demo.uuid)
            continue

        candidates = best_candidates(asset.title, demos, threshold)
        if not candidates:
            report.portal_only.append(asset)
            continue

        top = candidates[0]
        runner_up = candidates[1] if len(candidates) > 1 else None
        ambiguous = bool(runner_up and (top.confidence - runner_up.confidence) < AMBIGUITY_MARGIN)

        match = AssetMatch(
            asset_id=asset.id, asset_title=asset.title, demo=top.demo,
            confidence=round(top.confidence, 3), ambiguous=ambiguous,
            runner_up=runner_up.demo if runner_up else None,
        )
        report.matched.append(match)
        claimed.add(top.demo.uuid)

        if ambiguous:
            report.ambiguous.append(match)
        elif asset.consensus_uuid and asset.consensus_uuid != top.demo.uuid:
            # A UUID is recorded but points somewhere else. Never overwrite silently.
            report.conflicts.append(match)
        elif not asset.consensus_uuid:
            report.proposals.append(match)

    report.consensus_only = [d for d in demos if d.uuid not in claimed]
    return report
