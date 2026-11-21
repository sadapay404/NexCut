"""Prompt loading and templating.

Your master prompt lives in a text file, not in code:

    prompts/master.md      <- YOUR prompt. Edit it any time; no restart needed.
    prompts/system.md      <- optional system instruction
    prompts/contract.md    <- optional machine contract appended for parsing

Placeholders are `{{name}}` and are filled from the run's settings:

    {{transcript}}      the timestamped transcript (the big one)
    {{niche}}           "True Crime — Scandal" if a sub-category is chosen
    {{niche_base}}      "True Crime"
    {{subniche}}        "Scandal" (empty if none)
    {{audience}}        "U.S. English"
    {{language}}        "Urdu-English mix"
    {{window}}          human label, e.g. "Option E: 45s-5m25s"
    {{window_min}} / {{window_max}}   seconds, e.g. 45 / 325
    {{num_clips}}       integer
    {{channel}} {{title}} {{host_guest}} {{video_url}} {{video_id}}
    {{already_extracted}}  anything the user says is already published
    {{gate}}            quality gate, e.g. 8.0
    {{date}}            today's date

If `master.md` is missing, a built-in prompt is used so the app always runs.
`contract.md` is appended automatically unless the master already mentions JSON.
"""

from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path

from .schema import QUALITY_GATE, WINDOWS

ROOT = Path(__file__).resolve().parent.parent
PROMPT_DIR = Path(os.environ.get("NEXCUT_PROMPT_DIR", ROOT / "prompts"))

DEFAULT_SYSTEM = (
    "You are a senior short-form video editor working for Sheikh Arsalan Automation. "
    "You work only from the transcript you are given. You never invent dialogue, "
    "timestamps or events. If the transcript does not support a clip, you return "
    "fewer clips rather than guessing."
)

CONTRACT = """## MACHINE CONTRACT — the app parses your answer, so this part is fixed
Return ONE JSON object and nothing else. No prose before or after, no markdown fence.

{
  "sweep":    {"window": str, "ranges": str, "longlist": int, "cleared": int},
  "longlist": [{"start": "HH:MM:SS", "gist": str}],
  "clips": [{
    "n": int,
    "hook_summary": str,
    "start_sec": int, "start_stamp": "HH:MM:SS", "start_sentence": "copied verbatim",
    "end_sec": int,   "end_stamp": "HH:MM:SS",   "end_sentence": "copied verbatim",
    "duration_line": str,
    "titles": {"clickbait": str, "search": str, "debate": str},
    "scores": {"curiosity": float, "stakes": float, "specificity": float, "speed": float, "avg": float},
    "verbal_hook": str, "ending": str, "why_it_works": str, "share_trigger": str,
    "safety": "none" or str,
    "sfx": str, "captions": str, "upload_caption": str, "hashtags": str, "pinned_comment": str,
    "transcript_ts": "verbatim slice with timestamps",
    "transcript": "same slice without timestamps"
  }],
  "dropped": [{"clip": int, "reason": str}]
}

Rules the app enforces after you answer: `start_sentence` and `end_sentence` must
exist character-for-character in the transcript; the stamps must match those exact
lines; `end_sec - start_sec` must equal `duration_line` and sit inside the window;
`avg` is the mean of the four scores. A clip that fails is dropped and shown to
the user as a rejection, not delivered.
"""

_TOKEN = re.compile(r"\{\{(\w+)\}\}")


def _read(name: str) -> str:
    path = PROMPT_DIR / name
    if path.is_file():
        return path.read_text(encoding="utf-8", errors="replace")
    return ""


def master_exists() -> bool:
    return (PROMPT_DIR / "master.md").is_file()


def render(template: str, ctx: dict) -> tuple[str, list[str]]:
    """Substitute {{tokens}}. Returns (rendered, unknown_tokens)."""
    unknown: list[str] = []

    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key in ctx:
            return str(ctx[key])
        unknown.append(key)
        return m.group(0)

    return _TOKEN.sub(sub, template), sorted(set(unknown))


def context(
    *,
    transcript: str,
    niche: str = "True Crime",
    audience: str = "U.S. English",
    language: str = "U.S. English",
    window: str = "E",
    num_clips: int = 5,
    channel: str = "",
    title: str = "",
    host_guest: str = "",
    video_url: str = "",
    video_id: str = "",
    already_extracted: str = "",
    custom_min: int | None = None,
    custom_max: int | None = None,
    ranges: str = "",
) -> dict:
    if niche.strip().lower() in ("", "auto", "auto-detect", "auto detect", "detect"):
        niche = "AUTO — detect it from the transcript, then state `niche > sub-niche` at the top"
    count = int(num_clips or 0)
    if count <= 0:
        num_clips = "AUTO — decide with Step 0 and print the AUTO line first"

    base, _, sub = niche.partition(" — ")
    if custom_min and custom_max:
        lo, hi, label = int(custom_min), int(custom_max), f"custom {custom_min}-{custom_max}s"
    else:
        label, lo, hi = WINDOWS.get(window, WINDOWS["E"])
    return {
        "transcript": transcript,
        "niche": niche,
        "niche_base": base.strip(),
        "subniche": sub.strip(),
        "audience": audience,
        "language": language,
        "window": label,
        "window_min": lo,
        "window_max": hi,
        "num_clips": num_clips,
        "channel": channel,
        "title": title,
        "host_guest": host_guest,
        "video_url": video_url,
        "video_id": video_id,
        "already_extracted": already_extracted or "(none)",
        "gate": QUALITY_GATE,
        "ranges": ranges,
        "date": date.today().isoformat(),
    }


def compose(
    *,
    transcript: str,
    niche: str = "True Crime",
    audience: str = "U.S. English",
    language: str = "U.S. English",
    window: str = "E",
    num_clips: int = 5,
    channel_show: str = "",
    episode_title: str = "",
    host_guest: str = "",
    already_extracted: str = "",
    custom_min: int | None = None,
    custom_max: int | None = None,
    video_id: str = "",
    ranges_text: str = "",
) -> tuple[str, str, list[str]]:
    """Return (system, user, warnings). Uses YOUR prompt when present."""
    ctx = context(
        transcript=transcript, niche=niche, audience=audience, language=language,
        window=window, num_clips=num_clips, channel=channel_show, title=episode_title,
        host_guest=host_guest, video_url=f"https://youtu.be/{video_id}" if video_id else "",
        video_id=video_id, already_extracted=already_extracted,
        custom_min=custom_min, custom_max=custom_max, ranges=ranges_text,
    )

    master = _read("master.md")
    system_file = _read("system.md")
    system = system_file.strip() or DEFAULT_SYSTEM

    if not master.strip():
        from .prompt import build_prompt  # built-in fallback

        sys_default, user = build_prompt(
            transcript=transcript, niche=niche, audience=audience, language=language,
            window=window, num_clips=num_clips, channel_show=channel_show,
            host_guest=host_guest, episode_title=episode_title,
            already_extracted=already_extracted, custom_min=custom_min,
            custom_max=custom_max, ranges_text=ranges_text,
        )
        return sys_default, user, ["prompts/master.md not found — using the built-in prompt"]

    user, unknown = render(master, ctx)
    warnings = [f"unknown placeholder(s) in master.md: {', '.join(unknown)}"] if unknown else []

    contract = _read("contract.md").strip() or CONTRACT
    append = os.environ.get("NEXCUT_APPEND_CONTRACT", "auto")
    wants = append == "1" or (append == "auto" and "json" not in master.lower())
    if wants:
        user = f"{user.rstrip()}\n\n{contract}"

    return system, user, warnings
