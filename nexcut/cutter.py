"""Video download and clip cutting.

Mechanism, plainly:

  1. `yt-dlp` asks YouTube for the available formats, then downloads one
     video-only stream plus one audio stream and merges them to MP4.
  2. `ffmpeg` seeks to each clip's start, re-encodes the span to H.264/AAC,
     and writes a standalone MP4 with fast-start enabled.

`-c copy` would be faster but lands on keyframes, so a "00:00:08 → 00:01:03"
clip would really start at 7.4 s or 8.6 s. The whole product claims exact
timestamps, so every clip is re-encoded for frame accuracy instead.

Nothing here is assumed present: availability is probed and reported, and a
missing binary produces an install instruction rather than a stack trace.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

MIN_HEIGHT = 1080
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = DATA / "source"
CUTS = DATA / "cuts"


class CutterError(Exception):
    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


# --------------------------------------------------------------------------
# tool discovery
# --------------------------------------------------------------------------
def _ytdlp_invocation() -> list[str] | None:
    exe = shutil.which("yt-dlp")
    if exe:
        return [exe]
    try:
        import yt_dlp  # noqa: F401,PLC0415

        return ["python3", "-m", "yt_dlp"]
    except ImportError:
        return None


def tool_status() -> dict:
    ytdlp = _ytdlp_invocation()
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    return {
        "ffmpeg": bool(ffmpeg),
        "ffprobe": bool(ffprobe),
        "yt_dlp": bool(ytdlp),
        "can_cut": bool(ytdlp and ffmpeg and ffprobe),
        "hints": {
            "ffmpeg": "" if ffmpeg else "Install ffmpeg and put it on PATH (Windows: winget install Gyan.FFmpeg).",
            "yt_dlp": "" if ytdlp else "pip install yt-dlp, or download the yt-dlp binary.",
        },
    }


def _run(cmd: list[str], *, timeout: int = 3600) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise CutterError(
            f"Required program not found: {cmd[0]}",
            "Install it and make sure it is on PATH, then restart the studio.",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise CutterError(
            f"{Path(cmd[0]).name} timed out after {timeout}s.",
            "The connection may be slow — try a shorter video or a smaller height.",
        ) from exc


def _require_cut_tools() -> list[str]:
    status = tool_status()
    if not status["yt_dlp"]:
        raise CutterError("yt-dlp is not installed, so nothing can be downloaded.",
                          status["hints"]["yt_dlp"])
    if not status["ffmpeg"]:
        raise CutterError("ffmpeg is not installed, so clips cannot be cut.",
                          status["hints"]["ffmpeg"])
    if not status["ffprobe"]:
        raise CutterError("ffprobe is missing (it ships with ffmpeg).",
                          status["hints"]["ffmpeg"])
    return _ytdlp_invocation() or []


# --------------------------------------------------------------------------
# cookies (Cloud Shell, VPS and any datacenter IP get bot-checked by YouTube)
# --------------------------------------------------------------------------
COOKIES_ENV = "NEXCUT_COOKIES"


def cookies_arg() -> list[str]:
    """`--cookies <file>` when one is configured or a cookies.txt sits in the repo."""
    raw = os.environ.get(COOKIES_ENV, "").strip()
    path = Path(raw) if raw else (ROOT / "cookies.txt")
    if path.is_file() and path.stat().st_size > 0:
        return ["--cookies", str(path)]
    return []


# --------------------------------------------------------------------------
# qualities
# --------------------------------------------------------------------------
_H = re.compile(r"(\d{3,4})")


def probe_heights(video_id: str) -> list[int]:
    """Descending list of heights >= 1080 actually available for this video."""
    ytdlp = _require_cut_tools()
    proc = _run([*ytdlp, "-J", "--no-warnings", "--no-playlist", *cookies_arg(),
                 f"https://www.youtube.com/watch?v={video_id}"], timeout=120)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or ["unknown error"]
        raise CutterError("Could not read this video's formats.", tail[0][:200])
    try:
        info = json.loads(proc.stdout)
    except ValueError as exc:
        raise CutterError("yt-dlp returned unreadable metadata.") from exc

    heights: set[int] = set()
    for fmt in info.get("formats") or []:
        h = fmt.get("height")
        if isinstance(h, int) and h >= MIN_HEIGHT:
            heights.add(h)
    heights.add(MIN_HEIGHT)
    return sorted(heights, reverse=True)


# --------------------------------------------------------------------------
# download
# --------------------------------------------------------------------------
def source_path(video_id: str, height: int) -> Path:
    return CACHE / f"{video_id}_{height}.mp4"


def download(video_id: str, height: int) -> Path:
    """Download (or reuse) the source video at `height`. Returns the file path."""
    ytdlp = _require_cut_tools()
    CACHE.mkdir(parents=True, exist_ok=True)
    target = source_path(video_id, height)
    if target.is_file() and target.stat().st_size > 0:
        return target

    fmt = f"bv*[height<={height}]+ba/b[height<={height}]/b"
    proc = _run([
        *ytdlp, "--no-playlist", "--no-warnings", "--no-progress", *cookies_arg(),
        "-f", fmt, "--merge-output-format", "mp4",
        "-o", str(target), f"https://www.youtube.com/watch?v={video_id}",
    ])
    if proc.returncode != 0 or not target.is_file():
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or ["unknown error"]
        raise CutterError(
            "The source video could not be downloaded.",
            f"{tail[0][:200]} — if YouTube asks for a sign-in, export cookies.txt from a browser "
            "and drop it in the repo root (or set NEXCUT_COOKIES).",
        )
    return target


# --------------------------------------------------------------------------
# cutting
# --------------------------------------------------------------------------
def safe_name(n: int, start: float, end: float) -> str:
    def stamp(sec: float) -> str:
        s = max(0, int(sec))
        return f"{s // 3600:02d}-{(s % 3600) // 60:02d}-{s % 60:02d}"
    return f"clip-{n:02d}_{stamp(start)}_{stamp(end)}.mp4"


def cut(source: Path, start: float, end: float, out: Path, *, height: int) -> Path:
    if end <= start:
        raise CutterError(f"Invalid span {start}->{end}.")
    out.parent.mkdir(parents=True, exist_ok=True)
    duration = max(0.5, float(end) - float(start))
    proc = _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-ss", f"{float(start):.3f}",
        "-i", str(source),
        "-t", f"{duration:.3f}",
        "-vf", f"scale=-2:{min(height, 2160)}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(out),
    ])
    if proc.returncode != 0 or not out.is_file():
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or ["unknown error"]
        raise CutterError("ffmpeg could not cut this clip.", tail[0][:200])
    return out


@dataclass
class CutJob:
    id: str
    status: str = "pending"      # pending | running | done | error
    progress: int = 0
    stage: str = "Queued"
    error: str | None = None
    error_hint: str = ""
    quality: str = ""
    files: list[dict] = field(default_factory=list)
    created: float = 0.0

    def payload(self) -> dict:
        return {
            "cut_id": self.id,
            "status": self.status,
            "progress": self.progress,
            "stage": self.stage,
            "error": self.error,
            "error_hint": self.error_hint,
            "quality": self.quality,
            "files": self.files,
        }


def files_for(cut_id: str, directory: Path) -> list[dict]:
    out = []
    for path in sorted(directory.glob("*.mp4")):
        stat = path.stat()
        out.append({
            "name": path.name,
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            "url": f"/api/cuts/{cut_id}/file/{path.name}",
        })
    return out


def as_dict(job: CutJob) -> dict:
    return asdict(job)
