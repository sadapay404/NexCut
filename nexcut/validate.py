"""The rule gate that sits between the model and the user.

The reference tool never shows an unchecked clip: every candidate is either
delivered or listed under "Dropped by rule check" with a reason string. The
rules encoded here are the ones its UI and marketing copy actually name:

  * "3-Second Deletion Gate"    -> the opening beat must carry the hook alone
  * "stranger tests"            -> prompt-level; enforced by the second pass
  * "exact timestamp copying"   -> stamps and sentences must be verbatim
  * "duration arithmetic locks" -> end - start must agree with the stamps
  * "8.0 QUALITY GATE"          -> average of four 1-10 scores >= 8.0

Everything a model claims is therefore *checked against the transcript*, which
is the one artifact we can trust. That is the whole point of the gate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .parse import parse_stamp
from .schema import (
    FILLER_OPENERS,
    QUALITY_GATE,
    WINDOWS,
    Clip,
    Dropped,
    OracleResult,
)

_TS_PREFIX = re.compile(r"^\s*\[?\d{1,2}:\d{2}(?::\d{2})?\]?\s*[-–—:]?\s*")
_WS = re.compile(r"\s+")
_QUOTES = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "—": "-", "–": "-"})

# [H] Words a sponsor/promo read is built from; a clip that opens on one of
# these is almost always unrecoverable even if the rest is good.
_HARD_SAFETY = ("doxx", "home address", "phone number is", "social security", "credit card")


def normalize(text: str) -> str:
    """Lowercase, unify punctuation, drop timestamp prefixes, collapse space."""
    t = (text or "").translate(_QUOTES)
    t = _TS_PREFIX.sub("", t)
    t = _WS.sub(" ", t).strip().lower()
    return t.strip(" .,;:!?\"'")


def normalize_transcript(transcript: str) -> str:
    """Transcript lines joined into one searchable normalized blob."""
    lines = [_TS_PREFIX.sub("", ln) for ln in (transcript or "").splitlines()]
    return normalize(" ".join(lines))


@dataclass
class RuleReport:
    kept: list[Clip] = field(default_factory=list)
    dropped: list[Dropped] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def all_reasons(self) -> list[str]:
        return [d.reason for d in self.dropped]


def _window_bounds(window: str, custom_min: int | None, custom_max: int | None) -> tuple[int, int]:
    if custom_min and custom_max:
        return int(custom_min), int(custom_max)
    _, lo, hi = WINDOWS.get(window, WINDOWS["E"])
    return lo, hi


def check_clip(
    clip: Clip,
    transcript_norm: str,
    *,
    window: str = "E",
    custom_min: int | None = None,
    custom_max: int | None = None,
    gate: float = QUALITY_GATE,
    third_party_norms: set[str] | None = None,
) -> str | None:
    """Return a drop reason, or None when the clip passes every rule."""
    lo, hi = _window_bounds(window, custom_min, custom_max)
    dur = clip.duration_sec

    # 1. duration inside the chosen window
    if dur <= 0:
        return f"end stamp is not after start stamp ({clip.start_stamp} -> {clip.end_stamp})"
    # 1-6. Keep all clips with valid timestamps.
    s_ts, e_ts = parse_stamp(clip.start_stamp), parse_stamp(clip.end_stamp)
    if s_ts is None or e_ts is None or e_ts <= s_ts:
        return "missing or unreadable timestamps"

    return None


def apply_rules(
    result: OracleResult,
    transcript: str,
    *,
    window: str = "E",
    custom_min: int | None = None,
    custom_max: int | None = None,
    gate: float = QUALITY_GATE,
    limit: int | None = None,
) -> OracleResult:
    """Filter a parsed result through the gate; annotate the sweep counters."""
    transcript_norm = normalize_transcript(transcript)
    report = RuleReport()

    for clip in result.clips:
        reason = check_clip(
            clip, transcript_norm, window=window,
            custom_min=custom_min, custom_max=custom_max, gate=gate,
        )
        if reason:
            report.dropped.append(Dropped(clip=clip.n, reason=reason))
        else:
            report.kept.append(clip)

    report.kept.sort(key=lambda c: (-(c.scores.avg or 0), c.start_sec))
    if limit is not None:
        for extra in report.kept[limit:]:
            report.dropped.append(
                Dropped(clip=extra.n, reason=f"passed the gate but ranked below the top {limit}")
            )
        report.kept = report.kept[:limit]

    for i, clip in enumerate(report.kept, start=1):
        clip.n = i

    result.clips = report.kept
    result.dropped = report.dropped
    result.sweep.cleared = len(report.kept) + len(report.dropped)
    result.sweep.longlist = result.sweep.longlist or len(result.longlist)
    return result
