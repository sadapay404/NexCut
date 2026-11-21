"""`details.md` — the run rendered as a document.

The model returns a structured object; this turns it back into the layout the
master prompt describes, so a ZIP can carry the MP4s plus their packaging notes
without the user copying anything out of a chat.
"""

from __future__ import annotations

from datetime import date


def _tier(clip: dict) -> str:
    scores = clip.get("scores") or {}
    return "BACKUP" if float(scores.get("avg") or 0) < 8.0 and scores.get("avg") else "MAIN"


def _line(label: str, value) -> str:
    text = str(value or "").strip()
    return f"**{label}:** {text}" if text else ""


def _clip_block(clip: dict) -> str:
    scores = clip.get("scores") or {}
    titles = clip.get("titles") or {}
    out: list[str] = []
    avg = scores.get("avg")
    head = f"## Clip {clip.get('n', '?')}"
    if clip.get("hook_summary"):
        head += f" — {clip['hook_summary']}"
    if avg is not None:
        head += f" · avg {avg} · {_tier(clip)}"
    out.append(head)
    out.append("")
    out.append(f"**Start:** {clip.get('start_stamp', '')}   **End:** {clip.get('end_stamp', '')}")
    out.append("")
    duration = clip.get("duration_str") or ""
    extra = clip.get("duration_line") or ""
    out.append(f"**Duration:** {duration}{(' (' + extra + ')') if extra else ''}")
    out.append("")
    out.append(f'**First line:** "{clip.get("start_sentence", "")}"')
    out.append("")
    out.append(f'**Last line:** "{clip.get("end_sentence", "")}"')
    out.append("")
    if clip.get("ending"):
        out.append(f"**Ending type:** {clip['ending']}")
        out.append("")
    if scores:
        pairs = " · ".join(
            f"{k} {scores[k]}" for k in ("curiosity", "stakes", "specificity", "speed") if scores.get(k) is not None
        )
        if avg is not None:
            pairs += f" · average {avg}"
        out.append(f"**Scores:** {pairs}")
        out.append("")
    for label, value in (
        ("Verbal hook", clip.get("verbal_hook")),
        ("Thumbnail text", titles.get("clickbait")),
        ("Search title", titles.get("search")),
        ("Video Title", titles.get("debate")),
        ("Upload caption", clip.get("upload_caption")),
        ("Hashtags", clip.get("hashtags")),
        ("Pinned comment", clip.get("pinned_comment")),
        ("Why it works", clip.get("why_it_works")),
        ("Share trigger", clip.get("share_trigger")),
    ):
        line = _line(label, value)
        if line:
            out.append(line)
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def run_markdown(payload: dict, *, requested: int | None = None, generated: str | None = None) -> str:
    clips = payload.get("clips") or []
    dropped = payload.get("dropped") or []
    title = payload.get("video_title") or "Untitled session"
    video_id = payload.get("video_id") or ""

    out: list[str] = [f"# {title}", ""]
    facts = [
        _line("Channel", payload.get("channel")),
        _line("Video", f"https://youtu.be/{video_id}" if video_id else ""),
        _line("Video ID", video_id),
        _line("Captions", payload.get("transcript_source")),
        _line("Model", payload.get("model_used")),
        _line("Coverage", payload.get("ranges_planned")),
        _line("Generated", generated or date.today().isoformat()),
    ]
    out.extend([f for f in facts if f])
    out.append("")
    count = f"**Clips delivered:** {len(clips)}"
    if requested:
        count += f" of {requested} requested"
    out.append(count)
    sweep = payload.get("sweep") or {}
    if sweep.get("longlist"):
        out.append(f"**Longlist:** {sweep.get('longlist')} candidates")
    out.extend(["", "---", ""])

    for clip in clips:
        out.append(_clip_block(clip))
        out.append("---")
        out.append("")

    if dropped:
        out.extend(["## Rejected candidates", ""])
        for item in dropped:
            out.append(f"- Clip {item.get('clip', '?')} — {item.get('reason', '')}")
        out.append("")

    out.extend([
        "## Files",
        "",
        "Each clip is an MP4 cut from the 1080p source, frame-accurate at both ends.",
        "Upload MAIN clips first.",
        "",
    ])
    return "\n".join(out)
