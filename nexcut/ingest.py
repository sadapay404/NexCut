"""YouTube transcript + metadata ingestion.

The reference tool needs a residential proxy and uploaded cookies because it
downloads video from a server IP. We only need *captions*, which is a far
lighter ask — so this module tries three independent strategies in order and
falls back to a paste box instead of failing:

  1. watch-page caption tracks  (no dependencies, no key)
  2. yt-dlp                     (if installed)
  3. youtube-transcript-api     (if installed)

Every failure raises IngestError with a message a beginner can act on, because
"403" is not an instruction.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)
YT_ID = re.compile(r"(?:v=|youtu\.be/|shorts/|live/|embed/)([\w-]{11})")
CONSENT = {"Cookie": "CONSENT=YES+cb; SOCS=CAI"}

# Caption line as we hand it to the model: "HH:MM:SS - sentence"
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


class IngestError(Exception):
    """Failure with a human-actionable message."""

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


@dataclass
class Transcript:
    text: str
    lines: list[tuple[float, str]]
    source: str
    language: str = ""
    is_auto: bool = False
    video_id: str = ""
    title: str = ""
    channel: str = ""

    @property
    def seconds(self) -> float:
        return self.lines[-1][0] if self.lines else 0.0


def video_id(url_or_id: str) -> str:
    s = (url_or_id or "").strip()
    if re.fullmatch(r"[\w-]{11}", s):
        return s
    m = YT_ID.search(s)
    return m.group(1) if m else ""


def hms(sec: float) -> str:
    s = max(0, int(sec))
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


# --------------------------------------------------------------------------
# http
# --------------------------------------------------------------------------
def _get(url: str, *, timeout: int = 20, headers: dict | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or CONSENT)})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            raise IngestError(
                "YouTube refused the request for this video.",
                "Usually a bot-check on this network. Try again, or paste the transcript manually.",
            ) from exc
        raise IngestError(f"YouTube returned HTTP {exc.code} for this video.") from exc
    except urllib.error.URLError as exc:
        raise IngestError(
            "Could not reach YouTube from this machine.",
            f"Network/proxy problem: {exc.reason}",
        ) from exc
    except TimeoutError as exc:
        raise IngestError("YouTube took too long to answer.", "Try again in a minute.") from exc


# --------------------------------------------------------------------------
# metadata (oEmbed — no key, no quota)
# --------------------------------------------------------------------------
def fetch_metadata(vid: str) -> dict:
    if not vid:
        return {"title": "", "channel": ""}
    url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json"
    try:
        data = json.loads(_get(url, timeout=12, headers={}).decode() or "{}")
        return {"title": data.get("title", ""), "channel": data.get("author_name", "")}
    except (IngestError, ValueError, KeyError):
        return {"title": "", "channel": ""}


# --------------------------------------------------------------------------
# cue parsing
# --------------------------------------------------------------------------
def _post_json(url: str, payload: dict, *, timeout: int = 20,
               headers: dict | None = None) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"User-Agent": UA, "Content-Type": "application/json",
                 **CONSENT, **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as exc:
        raise IngestError(
            f"YouTube refused the player request (HTTP {exc.code}).",
            "Try again in a minute; if it persists, export cookies.txt from a browser "
            "and put it in the repo root.",
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise IngestError("Could not reach YouTube.", str(exc)[:200]) from exc


def parse_timedtext_xml(raw: bytes) -> list[tuple[float, str]]:
    """Classic timedtext XML -> [(seconds, text)]."""
    text = raw.decode("utf-8", "replace")
    out: list[tuple[float, str]] = []
    for start, body in re.findall(
            r'<text[^>]*\bstart="([0-9.]+)"[^>]*>(.*?)</text>', text, flags=re.S):
        clean = _clean(body)
        if clean:
            out.append((float(start), clean))
    return out


def _clean(text: str) -> str:
    text = _TAG.sub("", text)
    text = (
        text.replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')
        .replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " ")
    )
    return _WS.sub(" ", text).strip()


def _stamp_to_sec(stamp: str) -> float | None:
    parts = stamp.strip().replace(",", ".").split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    if len(nums) == 1:
        return nums[0]
    return None


def parse_vtt(text: str) -> list[tuple[float, str]]:
    """VTT/SRT -> [(seconds, text)] with duplicate rolling captions collapsed."""
    out: list[tuple[float, str]] = []
    block: list[str] = []

    def flush() -> None:
        if not block:
            return
        start = None
        payload: list[str] = []
        for line in block:
            if start is None and "-->" in line:
                start = _stamp_to_sec(line.split("-->")[0])
            elif start is not None:
                payload.append(line)
        body = _clean(" ".join(payload))
        if start is not None and body:
            if not out or out[-1][1] != body:      # collapse rolling duplicates
                out.append((start, body))
        block.clear()

    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw.strip() == "":
            flush()
        elif raw.strip().upper().startswith(("WEBVTT", "NOTE", "STYLE", "REGION", "KIND:", "LANGUAGE:")):
            continue
        else:
            block.append(raw)
    flush()
    return out


def parse_json3(raw: bytes) -> list[tuple[float, str]]:
    """YouTube timedtext json3 -> [(seconds, text)]."""
    try:
        data = json.loads(raw.decode() or "{}")
    except ValueError:
        return []
    out: list[tuple[float, str]] = []
    for ev in data.get("events") or []:
        if "segs" not in ev:
            continue
        body = _clean("".join(s.get("utf8", "") for s in ev["segs"]))
        if not body:
            continue
        sec = (ev.get("tStartMs") or 0) / 1000.0
        if out and out[-1][1] == body:
            continue
        out.append((sec, body))
    return out


def consolidate(lines: list[tuple[float, str]], *, target_words: int = 22) -> list[tuple[float, str]]:
    """Merge short ASR cues into sentence-sized units, keeping the first stamp.

    Auto captions arrive as 2-4 word fragments; the model is instructed to copy
    whole sentences verbatim, so it needs units that read as sentences.
    """
    out: list[tuple[float, str]] = []
    buf: list[str] = []
    start: float | None = None
    for sec, text in lines:
        if start is None:
            start = sec
            buf = []
        buf.append(text)
        joined = " ".join(buf)
        if len(joined.split()) >= target_words or re.search(r"[.!?][\"')\]]?$", joined):
            out.append((start, joined.strip()))
            start = None
    if start is not None and buf:
        out.append((start, " ".join(buf).strip()))
    return out


def to_text(lines: list[tuple[float, str]]) -> str:
    return "\n".join(f"{hms(sec)} - {body}" for sec, body in lines)


# --------------------------------------------------------------------------
# strategy 1: watch page caption tracks (no deps)
# --------------------------------------------------------------------------
def _pick_track(tracks: list[dict], preferred: str = "en") -> dict | None:
    def score(t: dict) -> tuple:
        lang = (t.get("languageCode") or "").lower()
        return (
            0 if lang.startswith(preferred) and t.get("kind") != "asr" else
            1 if lang.startswith(preferred) else
            2 if t.get("kind") != "asr" else 3
        )
    return sorted(tracks, key=score)[0] if tracks else None


def _via_watch_page(vid: str, language: str) -> Transcript:
    html = _get(f"https://www.youtube.com/watch?v={vid}&hl=en", timeout=25).decode("utf-8", "replace")
    m = re.search(r'"captionTracks":(\[.*?\])', html)
    if not m:
        raise IngestError(
            "This video has no captions available.",
            "No subtitles were published and none could be auto-generated — paste a transcript instead.",
        )
    tracks = json.loads(m.group(1))
    track = _pick_track(tracks, language)
    if not track:
        raise IngestError("No usable caption track on this video.", "Paste the transcript manually.")
    base = track.get("baseUrl") or ""
    if not base:
        raise IngestError("Caption track had no URL.", "Paste the transcript manually.")
    body = _get(base + "&fmt=json3", timeout=25)
    lines = parse_json3(body)
    if not lines:
        body = _get(base, timeout=25)
        lines = parse_vtt(body.decode("utf-8", "replace"))
    if not lines:
        raise IngestError("Captions came back empty.", "Paste the transcript manually.")
    return Transcript(
        text=to_text(consolidate(lines)),
        lines=consolidate(lines),
        source="youtube-captions",
        language=track.get("languageCode") or "",
        is_auto=track.get("kind") == "asr",
        video_id=vid,
    )


def cookie_path() -> str:
    """Same rule as the cutter: NEXCUT_COOKIES, else ./cookies.txt if it exists."""
    raw = os.environ.get("NEXCUT_COOKIES", "").strip()
    path = Path(raw) if raw else (ROOT / "cookies.txt")
    return str(path) if path.is_file() and path.stat().st_size > 0 else ""


def cookies_arg() -> list[str]:
    found = cookie_path()
    return ["--cookies", found] if found else []


# --------------------------------------------------------------------------
# strategy 1b: innertube player API — the same call the apps make, so it answers
# without a browser session even when the watch page is a consent/bot wall
# --------------------------------------------------------------------------
INNERTUBE_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
INNERTUBE_CLIENTS = (
    {"clientName": "ANDROID", "clientVersion": "20.10.38",
     "androidSdkVersion": 30, "hl": "en", "gl": "US"},
    {"clientName": "IOS", "clientVersion": "20.10.4", "deviceModel": "iPhone15,3",
     "hl": "en", "gl": "US"},
    {"clientName": "TVHTML5_SIMPLY_EMBEDDED_PLAYER", "clientVersion": "2.0",
     "hl": "en", "gl": "US"},
    {"clientName": "WEB", "clientVersion": "2.20241010.00.00", "hl": "en", "gl": "US"},
)


def _captions_from_player(player: dict) -> list[dict]:
    tracks = (((player.get("captions") or {})
               .get("playerCaptionsTracklistRenderer") or {})
              .get("captionTracks") or [])
    return tracks


def _fetch_track(track: dict) -> list[tuple[float, str]]:
    base = track.get("baseUrl") or ""
    if not base:
        return []
    for suffix in ("&fmt=json3", ""):
        try:
            raw = _get(base + suffix, timeout=25)
        except IngestError:
            continue
        lines = parse_json3(raw) if "json3" in suffix else []
        if not lines:
            lines = parse_timedtext_xml(raw) or parse_vtt(raw.decode("utf-8", "replace"))
        if lines:
            return lines
    return []


def _via_innertube(vid: str, language: str) -> Transcript:
    reasons: list[str] = []
    for client in INNERTUBE_CLIENTS:
        try:
            player = _post_json(
                f"https://www.youtube.com/youtubei/v1/player?key={INNERTUBE_KEY}"
                "&prettyPrint=false",
                {"context": {"client": client}, "videoId": vid,
                 "contentCheckOk": True, "racyCheckOk": True},
            )
        except IngestError as exc:
            reasons.append(f"{client['clientName']}: {exc}")
            continue
        status = player.get("playabilityStatus") or {}
        tracks = _captions_from_player(player)
        if not tracks:
            reasons.append(
                f"{client['clientName']}: no tracks ({status.get('status', '?')}"
                f"{', ' + status['reason'] if status.get('reason') else ''})")
            continue
        track = _pick_track(tracks, language)
        if not track:
            reasons.append(f"{client['clientName']}: no {language} track")
            continue
        lines = _fetch_track(track)
        if not lines:
            reasons.append(f"{client['clientName']}: track returned nothing")
            continue
        merged = consolidate(lines)
        meta = player.get("videoDetails") or {}
        return Transcript(
            text=to_text(merged), lines=merged, source="innertube",
            language=track.get("languageCode") or "", is_auto=track.get("kind") == "asr",
            video_id=vid, title=meta.get("title") or "", channel=meta.get("author") or "",
        )
    raise IngestError("No caption track through YouTube's player API.",
                      "; ".join(reasons)[:300])


# --------------------------------------------------------------------------
# strategy 2: yt-dlp
# --------------------------------------------------------------------------
def _via_ytdlp(vid: str, language: str) -> Transcript:
    exe = shutil.which("yt-dlp")
    with tempfile.TemporaryDirectory() as tmp:
        if exe:
            cmd = [
                exe, "--skip-download", "--write-auto-subs", "--write-subs",
                *cookies_arg(),
                "--sub-langs", f"{language}.*,{language}", "--sub-format", "vtt",
                "-o", str(Path(tmp) / "%(id)s.%(ext)s"),
                f"https://www.youtube.com/watch?v={vid}",
            ]
            try:
                done = subprocess.run(cmd, capture_output=True, timeout=120, check=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise IngestError("yt-dlp failed to run.", str(exc)) from exc
        else:
            try:
                import yt_dlp  # noqa: PLC0415
            except ImportError as exc:
                raise IngestError("yt-dlp is not installed.", "pip install yt-dlp") from exc
            cookie_file = cookie_path()
            opts = {"skip_download": True, "writesubtitles": True,
                    "writeautomaticsub": True, "subtitleslangs": [f"{language}.*", language],
                    "subtitlesformat": "vtt", "outtmpl": str(Path(tmp) / "%(id)s.%(ext)s"),
                    "quiet": True, "noprogress": True}
            if cookie_file:
                opts["cookiefile"] = cookie_file
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([f"https://www.youtube.com/watch?v={vid}"])
            except Exception as exc:  # noqa: BLE001 - yt-dlp raises its own types
                raise IngestError("yt-dlp could not download captions.", str(exc)[:200]) from exc

        files = sorted(Path(tmp).glob("*.vtt"))
        if not files and done.returncode != 0:
            detail = (done.stderr or done.stdout or b"").decode("utf-8", "replace")
            detail = " ".join(detail.strip().splitlines()[-2:])[:220] or "no output"
            raise IngestError("yt-dlp could not fetch captions.", detail)
        if not files:
            raise IngestError("yt-dlp found no caption file for this video.", "Paste the transcript manually.")
        lines = parse_vtt(files[0].read_text(encoding="utf-8", errors="replace"))
        if not lines:
            raise IngestError("The caption file was empty.", "Paste the transcript manually.")
        merged = consolidate(lines)
        return Transcript(text=to_text(merged), lines=merged, source="yt-dlp", video_id=vid,
                          is_auto="auto" in files[0].name or True)


# --------------------------------------------------------------------------
# strategy 2c: the old timedtext endpoint (no signing, sometimes still open)
# --------------------------------------------------------------------------
def _via_timedtext(vid: str, language: str) -> Transcript:
    for host in ("https://www.youtube.com/api/timedtext",
                 "https://video.google.com/timedtext"):
        for lang in (language, "en"):
            try:
                raw = _get(f"{host}?lang={lang}&v={vid}", timeout=20)
            except IngestError:
                continue
            lines = parse_timedtext_xml(raw)
            if lines:
                merged = consolidate(lines)
                return Transcript(text=to_text(merged), lines=merged,
                                  source="timedtext", language=lang,
                                  is_auto=True, video_id=vid)
    raise IngestError("The timedtext endpoint returned no cues.",
                      "Paste the transcript manually.")


# --------------------------------------------------------------------------
# strategy 3: youtube-transcript-api
# --------------------------------------------------------------------------
def _via_transcript_api(vid: str, language: str) -> Transcript:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # noqa: PLC0415
    except ImportError as exc:
        raise IngestError("youtube-transcript-api is not installed.", "pip install youtube-transcript-api") from exc
    try:
        api = YouTubeTranscriptApi()
        fetched = api.fetch(vid, languages=[language, "en"])
        rows = list(fetched)
    except Exception as exc:  # noqa: BLE001
        raise IngestError("youtube-transcript-api could not fetch captions.", str(exc)[:200]) from exc
    raw = [(float(getattr(r, "start", 0) or 0), str(getattr(r, "text", ""))) for r in rows]
    lines = consolidate([(s, _clean(t)) for s, t in raw if t])
    if not lines:
        raise IngestError("No caption lines returned.", "Paste the transcript manually.")
    return Transcript(text=to_text(lines), lines=lines, source="youtube-transcript-api",
                      video_id=vid, is_auto=True, language=language)


# --------------------------------------------------------------------------
# public entry
# --------------------------------------------------------------------------
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"


def fetch_transcript(url_or_id: str, *, language: str = "en", use_cache: bool = True) -> Transcript:
    if os.environ.get("NEXCUT_OFFLINE") == "1":
        raise IngestError(
            "Offline mode is on, so captions were not fetched.",
            "Unset NEXCUT_OFFLINE, or paste the transcript manually.",
        )

    vid = video_id(url_or_id)
    if not vid:
        raise IngestError(
            "That does not look like a YouTube link.",
            "Paste a link like https://www.youtube.com/watch?v=XXXXXXXXXXX or a video id.",
        )

    cache = CACHE_DIR / f"{vid}.json"
    if use_cache and cache.is_file():
        try:
            blob = json.loads(cache.read_text())
            return Transcript(**blob)
        except (ValueError, TypeError):
            pass

    errors: list[str] = []
    for strategy in (_via_innertube, _via_watch_page, _via_ytdlp,
                     _via_timedtext, _via_transcript_api):
        try:
            tr = strategy(vid, language)
        except IngestError as exc:
            errors.append(f"{strategy.__name__.replace('_via_', '')}: {exc}")
            continue
        meta = fetch_metadata(vid)
        tr.title = meta["title"]
        tr.channel = meta["channel"]
        if tr.lines:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({
                "text": tr.text, "lines": tr.lines, "source": tr.source,
                "language": tr.language, "is_auto": tr.is_auto,
                "video_id": tr.video_id, "title": tr.title, "channel": tr.channel,
            }))
        return tr

    raise IngestError(
        "Could not get captions for this video by any method.",
        "Tried: " + " | ".join(errors[:3]) + " — paste the transcript manually if this keeps happening.",
    )
