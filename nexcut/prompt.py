"""Clean-room prompt construction.

The reference tool's prompt is server-side and was never observable. What *is*
observable is the shape of what comes back (`oracle_report`, the clip field
set) and the rules it enforces afterwards. This module therefore specifies the
same *contract* in original wording: strict JSON, verbatim citation, explicit
arithmetic, an explicit quality gate.

Design choices worth defending:
  * Long videos are swept in overlapping chunks, because the reference result
    carries `sweep.ranges` and a `longlist` separate from `cleared`/delivered.
  * The model must copy sentences, never paraphrase: that is what makes the
    rule gate in validate.py able to verify anything at all.
  * Scores are demanded per-axis, not as one number, so the gate can be
    audited and so weak axes can be retried individually later.
"""

from __future__ import annotations

import json
import re

from .parse import parse_stamp
from .schema import QUALITY_GATE, SCORE_KEYS, WINDOWS, hms

_TS_LINE = re.compile(r"^\s*\[?(\d{1,2}):(\d{2})(?::(\d{2}))?\]?\s*[-–—:]?\s*(.*)$")

OUTPUT_SCHEMA = {
    "sweep": {"window": "str", "ranges": "str", "longlist": "int", "cleared": "int"},
    "longlist": [{"start": "HH:MM:SS", "gist": "one line, no spoiler"}],
    "clips": [
        {
            "n": "int",
            "hook_summary": "str",
            "start_sec": "int", "start_stamp": "HH:MM:SS", "start_sentence": "verbatim",
            "end_sec": "int", "end_stamp": "HH:MM:SS", "end_sentence": "verbatim",
            "duration_line": "str",
            "titles": {"clickbait": "str", "search": "str", "debate": "str"},
            "scores": {k: "float 1-10" for k in (*SCORE_KEYS, "avg")},
            "verbal_hook": "str", "ending": "str",
            "why_it_works": "str", "share_trigger": "str",
            "safety": "str|none",
            "overlays": [{"offset": "mm:ss", "text": "str"}],
            "sfx": "str", "captions": "str", "upload_caption": "str",
            "hashtags": "str", "pinned_comment": "str",
            "transcript_ts": "verbatim slice with stamps",
            "transcript": "same slice without stamps",
        }
    ],
}


def split_transcript(transcript: str) -> list[tuple[float, str]]:
    """[(seconds, line text)] from a timestamped transcript."""
    out: list[tuple[float, str]] = []
    for line in (transcript or "").splitlines():
        m = _TS_LINE.match(line)
        if not m:
            continue
        sec = parse_stamp(":".join(p for p in m.groups()[:3] if p))
        if sec is None:
            continue
        out.append((sec, m.group(4).strip()))
    return out


def plan_sweep(
    transcript: str, chunk_sec: int = 600, overlap_sec: int = 30
) -> list[tuple[int, int]]:
    """Overlapping coverage windows over the whole recording.

    This is our reading of `sweep.ranges`: a coverage report, so a long video is
    walked in chunks rather than truncated at a token limit.
    """
    lines = split_transcript(transcript)
    if not lines:
        return []
    total = int(lines[-1][0]) or 1
    if total <= chunk_sec:
        return [(0, total)]
    step = max(1, chunk_sec - overlap_sec)
    ranges: list[tuple[int, int]] = []
    start = 0
    while start < total:
        end = min(start + chunk_sec, total)
        ranges.append((start, end))
        if end >= total:
            break
        start += step
    return ranges


def format_ranges(ranges: list[tuple[int, int]]) -> str:
    return " | ".join(f"{hms(a)}-{hms(b)}" for a, b in ranges)


def slice_transcript(transcript: str, start: int, end: int) -> str:
    """Verbatim transcript lines whose stamp falls inside [start, end]."""
    keep = []
    for line in (transcript or "").splitlines():
        m = _TS_LINE.match(line)
        if not m:
            continue
        sec = parse_stamp(":".join(p for p in m.groups()[:3] if p))
        if sec is not None and start <= sec <= end:
            keep.append(line)
    return "\n".join(keep)


SYSTEM = """You are a short-form video editor for TikTok, Reels and Shorts.
You work only from the transcript you are given. You never invent dialogue,
timestamps or events. If the transcript does not support a clip, you return
fewer clips rather than guessing."""


def build_prompt(
    *,
    transcript: str,
    niche: str,
    audience: str,
    language: str,
    window: str = "E",
    num_clips: int = 5,
    channel_show: str = "",
    host_guest: str = "",
    episode_title: str = "",
    already_extracted: str = "",
    custom_min: int | None = None,
    custom_max: int | None = None,
    chunk: tuple[int, int] | None = None,
    ranges_text: str = "",
) -> tuple[str, str]:
    """Return (system, user) for one extraction or one sweep chunk."""
    if custom_min and custom_max:
        lo, hi = int(custom_min), int(custom_max)
        window_label = f"custom {lo}-{hi}s"
    else:
        label, lo, hi = WINDOWS.get(window, WINDOWS["E"])
        window_label = f"{label} -> {lo}-{hi}s"

    body = transcript if chunk is None else slice_transcript(transcript, *chunk)

    context = {
        "niche": niche,
        "audience": audience,
        "language": language,
        "duration_window": window_label,
        "clips_requested": num_clips,
        "channel_or_show": channel_show or "(not given)",
        "host_or_guest": host_guest or "(not given)",
        "episode_title": episode_title or "(not given)",
        "already_used": already_extracted or "(none)",
        "coverage": format_ranges([chunk]) if chunk else (ranges_text or "whole recording"),
    }

    user = f"""## JOB
Find the {num_clips} strongest standalone moments in this transcript and write
them up as vertical-video clips for a {audience} audience, delivered in
{language}.

## CONTEXT
{json.dumps(context, indent=2, ensure_ascii=False)}

## RULES — every one is checked after you answer
1. COPY, DO NOT PARAPHRASE. `start_sentence` and `end_sentence` must be copied
   character-for-character from the transcript lines you chose, including
   their wording. `start_stamp` and `end_stamp` must be the stamps printed on
   those exact lines. A checker compares your strings to the transcript; a
   paraphrase is rejected.
2. DURATION. `end_sec - start_sec` must land inside the duration window above,
   and `duration_line` must state the same number you computed. Do not round
   your way outside the window.
3. THREE-SECOND GATE. The first three seconds carry the whole clip. The opening
   sentence must land the hook with zero setup — no greetings, no housekeeping,
   no "before we start", no channel business. If the real hook starts later,
   move `start_sentence` forward to it.
4. STRANGER TEST. Someone scrolling with no context must understand the stakes
   inside the first line. No "as I said earlier", no unresolved pronouns.
5. ONE IDEA & FUN FACTOR. One moment, one turn, one payoff. Never merge two
   separate stories to reach the duration window. Pick moments with genuine
   energy — surprise, humor, absurdity, conflict, or a sharp reveal — not
   flat explanations.
6. STRONG ENDING. End on a punchline, a twist, a visual/verbal mic-drop, or a
   sharp open loop — never trail off on filler or "so yeah".
7. LENGTH HONESTY. If the transcript cannot fill the window without padding,
   return fewer clips. Fewer good clips beats a padded one.
8. NO DUPLICATES. Clips must not overlap in time, and must not reuse anything
   listed under `already_used`.
9. SAFETY. No accusations against named private individuals, no addresses, no
   phone numbers, no medical or legal advice. If a clip needs a caution, say so
   in `safety`; otherwise write "none".

## SCORING
Score each clip 1-10 on: curiosity (does it open a loop), stakes (does it
matter), specificity (concrete detail, not generalities), speed (does it move).
`avg` is the mean of the four, to one decimal. Anything below {QUALITY_GATE}
will be dropped, so do not pad the list with weak candidates.

## TITLES
- clickbait: 6-10 words, curiosity only, no false claim.
- search: what a viewer would actually type into search, 3-7 words.
- debate: a question the comments will fight over.

## OUTPUT
Return ONE JSON object and nothing else. No prose, no markdown fence.
Shape (keys exactly as named):
{json.dumps(OUTPUT_SCHEMA, indent=2)}

`transcript_ts` is a verbatim slice of the transcript between your two stamps.
`transcript` is that same slice with the stamps stripped. `overlays` are at most
three burn-in cues with `offset` as mm:ss from clip start.

## TRANSCRIPT — {context["coverage"]}
{body}
"""
    return SYSTEM, user
