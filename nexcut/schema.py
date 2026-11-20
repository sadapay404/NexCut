"""Core data contract for a NexCut extraction run.

Every field here was recovered from what the reference client *renders*, not
from its server source. Provenance markers:
  [V] observed directly in the client / API response shape
  [H] inferred constraint (behaviourally motivated, not proven)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# --- duration windows -------------------------------------------------------
# [V] labels straight from GET /api/config. Option E is the default and is
# described as "Oracle Wide Range"; its 5m25s ceiling is the odd one out and
# strongly implies the window is enforced server-side as a hard bound.
WINDOWS: dict[str, tuple[str, int, int]] = {
    "A": ("Option A: 30-60s", 30, 60),
    "B": ("Option B: 60-90s", 60, 90),
    "C": ("Option C: 90-180s", 90, 180),
    "D": ("Option D: 180-300s", 180, 300),
    "E": ("Option E: 45s-5m25s (Oracle Wide Range - default)", 45, 325),
}

SCORE_KEYS = ("curiosity", "stakes", "specificity", "speed")

# [H] The marketing copy and the admin "Wanted/Kept" column both imply one
# average-of-four judgement gate at 8.0. Treated as configurable on purpose.
QUALITY_GATE = 8.0

# [H] "3-Second Deletion Gate": the opening beat must carry the hook on its
# own. Anything that opens with housekeeping is trimmed or rejected.
FILLER_OPENERS = (
    "um", "uh", "so yeah", "anyway", "welcome back", "welcome to",
    "hey guys", "hi guys", "before we start", "let me introduce",
    "in today's video", "in this video", "quick announcement",
)


def hms(seconds: float) -> str:
    """Render seconds as h:mm:ss [V] — the client's secToHms() format."""
    s = max(0, int(round(seconds or 0)))
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


@dataclass
class Overlay:
    """A burned-in text cue at an offset from clip start [V]."""

    offset: str = ""
    text: str = ""


@dataclass
class Scores:
    curiosity: float | None = None
    stakes: float | None = None
    specificity: float | None = None
    speed: float | None = None
    reported_avg: float | None = None

    @property
    def avg(self) -> float | None:
        vals = [v for v in (self.curiosity, self.stakes, self.specificity, self.speed) if v is not None]
        if not vals:
            return None
        return round(sum(vals) / len(vals), 2)


@dataclass
class Clip:
    """One deliverable clip with its full production metadata [V]."""

    n: int
    hook_summary: str = ""
    start_sec: float = 0.0
    end_sec: float = 0.0
    start_stamp: str = ""
    end_stamp: str = ""
    start_sentence: str = ""
    end_sentence: str = ""
    duration_line: str = ""          # the model's own arithmetic, for auditing
    titles: dict[str, str] = field(default_factory=dict)
    scores: Scores = field(default_factory=Scores)
    verbal_hook: str = ""
    ending: str = ""
    why_it_works: str = ""
    share_trigger: str = ""
    safety: str = "none"
    overlays: list[Overlay] = field(default_factory=list)
    sfx: str = ""
    captions: str = ""
    upload_caption: str = ""
    hashtags: str = ""
    pinned_comment: str = ""
    transcript_ts: str = ""          # transcript slice WITH timestamps [V]
    transcript: str = ""             # plain slice [V]

    @property
    def duration_sec(self) -> float:
        return max(0.0, float(self.end_sec) - float(self.start_sec))

    @property
    def duration_str(self) -> str:
        return hms(self.duration_sec)


@dataclass
class Dropped:
    """A candidate rejected by rule check, with a human-readable reason [V]."""

    clip: int
    reason: str


@dataclass
class SweepReport:
    """The server's own coverage summary [V]. `ranges` is the chunk plan."""

    window: str = ""
    ranges: str = ""
    longlist: int = 0
    cleared: int = 0


@dataclass
class OracleResult:
    """The full payload behind GET /api/jobs/{id}/results [V]."""

    sweep: SweepReport = field(default_factory=SweepReport)
    longlist: list[dict[str, str]] = field(default_factory=list)
    clips: list[Clip] = field(default_factory=list)
    dropped: list[Dropped] = field(default_factory=list)
    oracle_report: str = ""
    video_id: str = ""
    video_title: str = ""
    window_label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "sweep": {
                "window": self.sweep.window,
                "ranges": self.sweep.ranges,
                "longlist": self.sweep.longlist,
                "cleared": self.sweep.cleared,
            },
            "longlist": self.longlist,
            "clips": [
                {
                    "n": c.n,
                    "hook_summary": c.hook_summary,
                    "start_sec": c.start_sec,
                    "start_stamp": c.start_stamp,
                    "start_sentence": c.start_sentence,
                    "end_sec": c.end_sec,
                    "end_stamp": c.end_stamp,
                    "end_sentence": c.end_sentence,
                    "duration_str": c.duration_str,
                    "duration_line": c.duration_line,
                    "titles": c.titles,
                    "scores": {
                        **{k: getattr(c.scores, k) for k in SCORE_KEYS},
                        "avg": c.scores.avg,
                    },
                    "verbal_hook": c.verbal_hook,
                    "ending": c.ending,
                    "why_it_works": c.why_it_works,
                    "share_trigger": c.share_trigger,
                    "safety": c.safety,
                    "overlays": [{"offset": o.offset, "text": o.text} for o in c.overlays],
                    "sfx": c.sfx,
                    "captions": c.captions,
                    "upload_caption": c.upload_caption,
                    "hashtags": c.hashtags,
                    "pinned_comment": c.pinned_comment,
                    "transcript_ts": c.transcript_ts,
                    "transcript": c.transcript,
                }
                for c in self.clips
            ],
            "dropped": [{"clip": d.clip, "reason": d.reason} for d in self.dropped],
            "oracle_report": self.oracle_report,
            "video_id": self.video_id,
            "video_title": self.video_title,
            "window_label": self.window_label,
        }
