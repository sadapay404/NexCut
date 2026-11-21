"""Parsing the model's answer into the NexCut schema.

The reference tool classifies failures with plain substring matching on the
error text, which tells us the *server contract* is string-based, not
code-based. We keep the same vocabulary deliberately so behaviour (including
the one-shot timeout auto-retry) matches:

    "Gemini is slow right now"      -> timeout, retryable exactly once
    "NO TIMESTAMPS"                 -> pre-flight transcript rejection
    "not in the clip-report format" -> unparseable answer, not retryable
"""

from __future__ import annotations

import json
import re

from .schema import Clip, OracleResult, Overlay, Scores, SweepReport

TIMEOUT_MSG = "Gemini is slow right now — the request timed out before it answered."
NO_TIMESTAMPS_MSG = (
    "NO TIMESTAMPS in the transcript — this run needs [00:12:30]-style stamps."
)
FORMAT_MSG = "The model answered, but not in the clip-report format we asked for."

# [V] "[00:12:30]" / "00:12:30" / "12:30" at line start.
_TS_LINE = re.compile(r"^\s*\[?(\d{1,2}):(\d{2})(?::(\d{2}))?\]?\s*[-–—:]?\s*", re.M)


class ExtractError(Exception):
    """Base for all pipeline failures surfaced to the UI."""


class TimeoutError_(ExtractError):
    def __init__(self, msg: str = TIMEOUT_MSG) -> None:
        super().__init__(msg)


class NoTimestampsError(ExtractError):
    def __init__(self, msg: str = NO_TIMESTAMPS_MSG) -> None:
        super().__init__(msg)


class FormatError(ExtractError):
    def __init__(self, detail: str = "") -> None:
        super().__init__(FORMAT_MSG + (f" ({detail})" if detail else ""))


def parse_stamp(stamp: str) -> float | None:
    """Turn '00:01:18' or '01:18' into seconds."""
    parts = [p for p in re.split(r"[:.]", (stamp or "").strip()) if p != ""]
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if not nums or len(nums) > 3:
        return None
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    return float(nums[0])


def ensure_timestamps(transcript: str) -> None:
    """Pre-flight gate: never spend tokens on a transcript we cannot cite."""
    if not _TS_LINE.search(transcript or ""):
        raise NoTimestampsError()


def _balance_scan(text: str) -> str | None:
    """Return the first balanced {...} block, ignoring braces inside strings."""
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        start = text.find("{", start + 1)
    return None


def _looks_cut_off(text: str) -> bool:
    """A reply that stops mid-object: more openers than closers.

    Workers AI caps output at 256 tokens unless told otherwise, and a cut-off
    report used to surface as "the answer has no clips key" — true, but useless.
    """
    stripped = text.rstrip()
    if not stripped:
        return False
    if stripped[0] not in "{[":
        return False
    opens = stripped.count("{") + stripped.count("[")
    closes = stripped.count("}") + stripped.count("]")
    return opens > closes


def extract_json(text: str) -> dict:
    """Pull the report object out of a model answer (fenced or bare)."""
    if not text or not text.strip():
        raise FormatError("empty answer")
    candidates: list[str] = []
    for m in re.finditer(r"```(?:json)?\s*(.+?)```", text, re.S):
        candidates.append(m.group(1).strip())
    candidates.append(text.strip())
    balanced = _balance_scan(text)
    if balanced:
        candidates.append(balanced)

    for cand in candidates:
        try:
            data = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and ("clips" in data or "longlist" in data):
            return data
    if _looks_cut_off(text):
        exc = FormatError(
            f"the answer was cut off after {len(text)} characters — the model ran "
            "out of output room before it finished the JSON"
        )
        exc.hint = ("The model's output budget was too small for a full report. "
                    "NexCut now asks for 4096 tokens; if this repeats, raise it: put "
                    "NEXCUT_MAX_TOKENS=6000 in .env and restart the server, or ask "
                    "for fewer clips.")
        raise exc
    raise FormatError("no JSON object with a clips/longlist key")


def _num(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _str(v) -> str:
    return "" if v is None else str(v).strip()


def _as_list(v) -> list:
    """A list, or nothing. Models answer "longlist": 12 or "overlays": 3."""
    if isinstance(v, list):
        return v
    if isinstance(v, tuple):
        return list(v)
    return []


def _preview(v, limit: int = 40) -> str:
    text = v if isinstance(v, str) else repr(v)
    text = " ".join(str(text).split())
    return text[:limit] + ("…" if len(text) > limit else "")


def _as_dict(v) -> dict:
    """A dict, or nothing. Models answer "scores": 9 or "titles": "..."."""
    return v if isinstance(v, dict) else {}


def _clip_from_dict(d: dict, idx: int) -> Clip:
    raw_scores = _as_dict(d.get("scores"))   # tolerates "8/10" and bare numbers
    scores = Scores(
        curiosity=_num(raw_scores.get("curiosity")),
        stakes=_num(raw_scores.get("stakes")),
        specificity=_num(raw_scores.get("specificity")),
        speed=_num(raw_scores.get("speed")),
        reported_avg=_num(raw_scores.get("avg")),
    )
    start = _num(d.get("start_sec"))
    if start is None:
        start = parse_stamp(_str(d.get("start_stamp"))) or 0.0
    end = _num(d.get("end_sec"))
    if end is None:
        end = parse_stamp(_str(d.get("end_stamp"))) or 0.0

    titles = _as_dict(d.get("titles"))

    overlays = [
        Overlay(offset=_str(o.get("offset")), text=_str(o.get("text")))
        for o in _as_list(d.get("overlays"))
        if isinstance(o, dict)
    ]

    return Clip(
        n=int(_num(d.get("n"), idx + 1) or idx + 1),
        hook_summary=_str(d.get("hook_summary")),
        start_sec=start,
        end_sec=end,
        start_stamp=_str(d.get("start_stamp")) or "",
        end_stamp=_str(d.get("end_stamp")) or "",
        start_sentence=_str(d.get("start_sentence")),
        end_sentence=_str(d.get("end_sentence")),
        duration_line=_str(d.get("duration_line")),
        titles={k: _str(v) for k, v in titles.items()},
        scores=scores,
        # [V] safety is suppressed in the UI when it is literally "none".
        safety=_str(d.get("safety")) or "none",
        overlays=overlays,
        sfx=_str(d.get("sfx")),
        captions=_str(d.get("captions")),
        upload_caption=_str(d.get("upload_caption")),
        hashtags=_str(d.get("hashtags")),
        pinned_comment=_str(d.get("pinned_comment")),
        transcript_ts=_str(d.get("transcript_ts")),
        transcript=_str(d.get("transcript")),
    )


def build_result(
    answer: str,
    *,
    video_id: str = "",
    video_title: str = "",
    window_label: str = "",
) -> OracleResult:
    """Parse a raw model answer into an OracleResult (no rule checks here)."""
    data = extract_json(answer)

    sweep_raw = data.get("sweep") or {}
    if not isinstance(sweep_raw, dict):
        sweep_raw = {}
    sweep = SweepReport(
        window=_str(sweep_raw.get("window")) or window_label,
        ranges=_str(sweep_raw.get("ranges")),
        longlist=int(_num(sweep_raw.get("longlist"), 0) or 0),
        cleared=int(_num(sweep_raw.get("cleared"), 0) or 0),
    )

    longlist = [
        {"start": _str(x.get("start")), "gist": _str(x.get("gist"))}
        for x in _as_list(data.get("longlist"))
        if isinstance(x, dict)
    ]

    if "clips" not in data:
        raise FormatError("the answer has no clips key")
    raw_clips = data.get("clips")
    if isinstance(raw_clips, dict):          # a single clip object, not a list
        raw_clips = [raw_clips]
    clips = [
        _clip_from_dict(c, i)
        for i, c in enumerate(_as_list(raw_clips))
        if isinstance(c, dict)
    ]
    if not clips and raw_clips not in (None, [], {}):
        kind = type(raw_clips).__name__
        raise FormatError(
            f"clips came back as {kind} ({_preview(raw_clips)}), not a list of clip objects"
        )

    return OracleResult(
        sweep=sweep,
        longlist=longlist,
        clips=clips,
        oracle_report=answer,
        video_id=video_id,
        video_title=video_title,
        window_label=window_label,
    )
