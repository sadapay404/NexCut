"""NexusDownloader for NexCut's UI D. No web framework or browser runtime.

The inspection owns the format selectors; clients can only choose an offered
MP4, WebM or MP3 option. Downloads use their own working directories, never the
Cutter's source cache. Set NEXCUT_PROXY and NEXCUT_COOKIES in the server's .env
if needed, and use NEXCUT_INVITE_CODES on a trusted network when sharing access.
"""

from __future__ import annotations

import json
import math
import os
import re
import secrets
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO
from urllib.parse import parse_qs, urlsplit
from zipfile import ZipFile

from . import cutter

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
ID = re.compile(r"[A-Za-z0-9_-]{11}")
FORMAT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}")
KEY = re.compile(r"[0-9a-f]{32}")
MIME_TYPES = {"mp4": "video/mp4", "webm": "video/webm", "mp3": "audio/mpeg", "zip": "application/zip"}
INSPECTION_TTL = 15 * 60
FILE_TTL = 60 * 60
MAX_INSPECTIONS = 48
MAX_JOBS = 8
MAX_ACTIVE = 2
MAX_RANGES = 10
MAX_FILE_BYTES = 2 * 1024**3
PROBE_TIMEOUT = 75
DOWNLOAD_TIMEOUT = 45 * 60
PROGRESS = "NEXCUT_PROGRESS:"
PROCESSING = "NEXCUT_PROCESSING:"
TOOL_HINT = 'Update yt-dlp (pip install -U "yt-dlp[default]") and ensure its YouTube JavaScript runtime is installed.'


class DownloadError(Exception):
    def __init__(self, message: str, hint: str = "", status: int = 422) -> None:
        super().__init__(message)
        self.hint = hint
        self.status = status


class _Cancelled(Exception):
    pass


def youtube_url(raw: object) -> str:
    """Canonicalize one YouTube video before starting an extractor on the server."""
    if isinstance(raw, str):
        value = raw.strip()
        if 0 < len(value) <= 2048 and not any(c.isspace() or c == "\\" or ord(c) < 32 for c in value):
            try:
                url = urlsplit(value)
                if url.scheme in {"http", "https"} and url.netloc.lower() == url.hostname:
                    ids = []
                    if url.hostname == "youtu.be":
                        ids = re.findall(r"^/([A-Za-z0-9_-]{11})/?$", url.path)
                    elif url.hostname in YOUTUBE_HOSTS:
                        if url.path == "/watch":
                            ids = parse_qs(url.query, keep_blank_values=True).get("v", [])
                        else:
                            ids = re.findall(r"^/(?:shorts|live|embed)/([A-Za-z0-9_-]{11})/?$", url.path)
                    if len(ids) == 1 and ID.fullmatch(ids[0]):
                        return f"https://www.youtube.com/watch?v={ids[0]}"
            except ValueError:
                pass
    raise DownloadError("Enter a single YouTube video or Shorts link.", status=400)


def _number(value: object) -> float | None:
    if type(value) in (int, float) and 0 <= value <= 1e16 and math.isfinite(value):
        return float(value)
    return None


def _codec(fmt: dict, key: str) -> str:
    codec = fmt.get(key)
    return codec.lower() if isinstance(codec, str) and codec.lower() not in {"none", "unknown"} else ""


def _text(value: object, limit: int) -> str:
    return " ".join(value.split())[:limit].encode("utf-8", "replace").decode() if isinstance(value, str) else ""


def _thumbnail(value: object) -> str:
    if isinstance(value, str) and len(value) <= 2048 and not re.search(r"[\s\\]", value):
        try:
            url = urlsplit(value)
            if url.scheme == "https" and url.netloc.lower() in {"i.ytimg.com", "img.youtube.com"}:
                return value
        except ValueError:
            pass
    return ""


@dataclass(frozen=True)
class Choice:
    id: str
    container: str
    selector: str
    quality: int | None
    label: str
    separate_tracks: bool = False
    # If set, download in this container and convert the audio to AAC locally.
    source_container: str | None = None

    def payload(self) -> dict:
        return {"id": self.id, "format": self.container, "quality": self.quality,
                "label": self.label, "separate_tracks": self.separate_tracks}


def _choices(info: dict) -> dict[str, Choice]:
    """Use real format IDs and compatible audio; never use a lower-tier fallback."""
    formats = info.get("formats") or []
    if not isinstance(formats, list):
        return {}
    # yt-dlp sorts formats worst to best. Retain its order within each quality.
    formats = [f for f in reversed(formats) if isinstance(f, dict) and not f.get("has_drm")
               and isinstance(f.get("format_id"), str) and FORMAT_ID.fullmatch(f["format_id"])]
    audio = [f for f in formats if _codec(f, "acodec") and f.get("vcodec") == "none"]
    choices: dict[str, Choice] = {}
    for ext, audio_codecs in (("mp4", ("mp4a", "aac")), ("webm", ("opus", "vorbis"))):
        companion = next((f for f in audio if f.get("ext") in ({"m4a", "mp4", "aac"} if ext == "mp4" else {"webm"})
                          and _codec(f, "acodec").startswith(audio_codecs)), None)
        video = [f for f in formats if _codec(f, "vcodec") and (
            f.get("ext") == ext or (ext == "mp4" and f.get("ext") == "webm"
                                    and _codec(f, "vcodec").startswith(("vp9", "vp09", "av1", "av01")))
        )]
        if ext == "mp4":
            # Prefer H.264, then native MP4. YouTube sometimes offers 2K/4K
            # only as WebM VP9; it can be muxed into MP4 without scaling.
            video.sort(key=lambda f: (not _codec(f, "vcodec").startswith(("avc", "h264")),
                                      f.get("ext") != ext))
        for f in video:
            width, height = f.get("width"), f.get("height")
            if type(width) is not int or type(height) is not int or not 0 < min(width, height) <= 8192:
                continue
            tier = min(width, height)  # same display rule for landscape and Shorts
            key = f"{ext}-{tier}"
            if key in choices:
                continue
            selector = f["format_id"]
            source_container = None
            separate = f.get("acodec") == "none"
            if separate:
                track = companion or (audio[0] if ext == "mp4" and audio else None)
                if not track:
                    continue
                selector += f"+{track['format_id']}"
                if not companion:
                    source_container = "mkv"
            elif f.get("ext") != ext or not _codec(f, "acodec").startswith(audio_codecs):
                if ext != "mp4" or not _codec(f, "acodec"):
                    continue
                source_container = f["ext"]
            choices[key] = Choice(key, ext, selector, tier, f"{tier}p · {width} × {height}",
                                  separate, source_container)
    for tier in (2160, 1440, 1080, 720, 480):
        key = f"mp4-{tier}"
        if key not in choices:
            choices[key] = Choice(key, "mp4", f"bv*[height<={tier}]+ba/b[height<={tier}]/b", tier, f"{tier}p · MP4", True)
    best_audio = next(iter(audio), None) or next((f for f in formats if _codec(f, "acodec")), None)
    if best_audio:
        choices["mp3-audio"] = Choice("mp3-audio", "mp3", best_audio["format_id"], None, "Best available audio")
    return dict(sorted(choices.items(), key=lambda pair: (pair[1].container, -(pair[1].quality or 0))))


def _trim_ranges(raw: object, duration: float | None) -> tuple[tuple[float, float], ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or len(raw) > MAX_RANGES:
        raise DownloadError(f"Supply up to {MAX_RANGES} clip ranges.", status=400)
    if raw and duration is None:
        raise DownloadError("The video duration is unavailable. Inspect again or leave the range blank.", status=400)
    ranges = []
    for i, item in enumerate(raw, start=1):
        start = _number(item.get("start")) if isinstance(item, dict) else None
        end = _number(item.get("end")) if isinstance(item, dict) else None
        if start is None or end is None or start >= end:
            raise DownloadError(f"Clip {i}: Start must be nonnegative and before End.", status=400)
        if duration is not None and end > duration:
            raise DownloadError(f"Clip {i}: End cannot exceed the video duration.", status=400)
        ranges.append((start, end))
    return tuple(ranges)


def _provider_error(output: str, *, probing: bool = False) -> DownloadError:
    # Tool diagnostics can include proxy credentials, local paths and signed URLs.
    # Classify them without forwarding any raw output to the HTTP client or log.
    text = output.lower()
    if any(mark in text for mark in ("sign in", "not a bot", "login required", "confirm your age")):
        return DownloadError("YouTube requires verification for this video or connection.",
                             "Use an authorized source. If appropriate, configure a Netscape cookie file via NEXCUT_COOKIES on the server.")
    if "requested format is not available" in text or "no video formats found" in text:
        return DownloadError("YouTube did not return the requested formats.", "Inspect the link again. " + TOOL_HINT)
    if any(mark in text for mark in ("private video", "video unavailable", "not available in your country")):
        return DownloadError("YouTube reports this video is unavailable to the server.")
    if any(mark in text for mark in ("proxy", "timed out", "connection", "network", "http error")):
        return DownloadError("The server could not fetch media from YouTube.",
                             "Check the server connection and NEXCUT_PROXY, then retry.", 502)
    return DownloadError("Could not inspect this video." if probing else "yt-dlp could not finish this download.", TOOL_HINT)


def _command(private: Path) -> list[str]:
    invocation = cutter._ytdlp_invocation()
    if not invocation:
        raise DownloadError("yt-dlp is not installed on the NexCut server.", TOOL_HINT, 503)
    args = [*invocation, "--ignore-config", "--no-plugin-dirs", "--use-extractors", "youtube",
            "--no-playlist", "--no-continue", "--no-warnings", "--color", "never",
            "--concurrent-fragments", "8", "--buffer-size", "16K",
            "--socket-timeout", "20", "--retries", "2", "--fragment-retries", "2",
            "--extractor-args", "youtube:player_client=android,web"]
    proxy = os.environ.get("NEXCUT_PROXY", "").strip()
    if proxy:
        args.extend(("--proxy", proxy))
    try:
        cookies = cutter.cookies_arg()
        if cookies:
            # yt-dlp writes back to its cookie jar. Each operation gets its own copy.
            with Path(cookies[1]).open("rb") as source:
                payload = source.read(8 * 1024**2 + 1)
            if len(payload) > 8 * 1024**2:
                raise OSError("cookie jar too large")
            copy = private / "cookies.txt"
            copy.write_bytes(payload)
            args.extend(("--cookies", str(copy)))
        elif os.environ.get("NEXCUT_COOKIES", "").strip():
            raise OSError("configured jar is missing or empty")
    except OSError as exc:
        raise DownloadError("NexCut could not read its cookie file.",
                            "Check that NEXCUT_COOKIES points to a readable Netscape cookies.txt file.", 503) from exc
    return args


def _tool_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("NEXCUT_")}
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return env


def _capture(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=_tool_env(), timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise DownloadError("Checking the media took too long.", "Try a shorter video or check the connection.", 504) from exc
    except OSError as exc:
        raise DownloadError("A media tool could not start.", "Check yt-dlp, FFmpeg and ffprobe on the server PATH.", 503) from exc


def _probe(url: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="nexcut-dl-") as folder:
        result = _capture([*_command(Path(folder)), "--skip-download", "--dump-single-json", "--", url], PROBE_TIMEOUT)
    if result.returncode:
        raise _provider_error(result.stderr, probing=True)
    try:
        info = json.loads(result.stdout)
        if not isinstance(info, dict) or info.get("_type") in {"playlist", "multi_video"}:
            raise ValueError("not a single video")
    except ValueError as exc:
        raise DownloadError("yt-dlp did not return usable video metadata.", TOOL_HINT) from exc
    if info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming", "post_live"}:
        raise DownloadError("Wait until the live stream is available as a replay.")
    return info


def _media_tools() -> tuple[str, str]:
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not (ffmpeg and ffprobe):
        raise DownloadError("FFmpeg and ffprobe are required to prepare the file.",
                            "Install FFmpeg and put both tools on the server PATH.", 503)
    return ffmpeg, ffprobe


def _verify(path: Path, choice: Choice, ffprobe: str, stop: threading.Event, deadline: float) -> None:
    if not path.is_file() or path.stat().st_size <= 0:
        raise DownloadError("The download did not produce a file in the selected format.")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise DownloadError("The result exceeds the 2 GiB download limit.", "Choose a smaller quality.", 413)
    args = [ffprobe, "-v", "error", "-show_entries", "format=format_name:stream=codec_type,codec_name,width,height",
            "-of", "json", str(path)]
    with _child(args, stop, min(deadline, time.monotonic() + 20)) as process:
        output, _ = process.communicate()
        code = process.returncode
    try:
        if code:
            raise ValueError("probe failed")
        info = json.loads(output)
        containers = info["format"]["format_name"].split(",")
        audio = [s for s in info["streams"] if s.get("codec_type") == "audio"]
        video = [s for s in info["streams"] if s.get("codec_type") == "video"]
        if choice.container not in containers or not audio:
            raise ValueError("wrong container or no audio")
        if choice.container == "mp3":
            if video or audio[0].get("codec_name") != "mp3":
                raise ValueError("not an audio-only MP3")
        elif not any(min(s.get("width", 0), s.get("height", 0)) == choice.quality for s in video):
            raise ValueError("wrong video quality")
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise DownloadError("The result does not match the selected format and quality.",
                            "Inspect the source again and try another available format.") from exc


def _kill(process: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            if process.poll() is None:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False)
                if process.poll() is None:
                    process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except (OSError, subprocess.TimeoutExpired):
        if process.poll() is None:
            process.kill()


def _check_running(stop: threading.Event, deadline: float) -> None:
    if stop.is_set():
        raise _Cancelled
    if time.monotonic() >= deadline:
        raise DownloadError("The download exceeded the time limit.", "Try a smaller quality or a shorter video.", 504)


@contextmanager
def _child(args: list[str], stop: threading.Event, deadline: float):
    """A cancellable process group, including yt-dlp's FFmpeg children."""
    _check_running(stop, deadline)
    with subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                          env=_tool_env(), start_new_session=os.name != "nt",
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0) as process:
        done = threading.Event()

        def watch() -> None:
            while not done.wait(0.1):
                if stop.is_set() or time.monotonic() >= deadline:
                    _kill(process)
                    return

        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        try:
            yield process
        finally:
            done.set()
            watcher.join()
            if process.poll() is None:
                _kill(process)
        _check_running(stop, deadline)


def _transfer(args: list[str], on_progress, stop: threading.Event, deadline: float) -> None:
    errors: deque[str] = deque(maxlen=6)
    with _child(args, stop, deadline) as process:
        for line in process.stdout:
            if line.startswith(PROGRESS):
                try:
                    event = json.loads(line[len(PROGRESS):])
                except ValueError:
                    continue
                if isinstance(event, dict):
                    on_progress(event)
            elif line.startswith(PROCESSING):
                on_progress(None)
            elif line.startswith("ERROR:"):
                errors.append(line[:1000])
        code = process.wait()
    if code:
        raise _provider_error("\n".join(errors))


def _make_output(ffmpeg: str, source: Path, target: Path, ext: str, span: tuple[float, float] | None,
                 stop: threading.Event, deadline: float, progress) -> None:
    args = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
    length = 0.0
    if span is not None:
        start, end = span
        length = end - start
        args += ["-ss", f"{start:.6f}"]
    args += ["-i", str(source)]
    if span is not None:
        args += ["-t", f"{length:.6f}"]
    if ext == "mp3":
        args += ["-map", "0:a:0", "-c:a", "libmp3lame", "-q:a", "0"]
    else:
        args += ["-map", "0:v:0", "-map", "0:a:0"]
        if ext == "mp4":
            # Re-encode trims for non-keyframe boundaries, but don't re-encode
            # the full video just to convert its audio track to AAC.
            args += (["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-threads", "4"]
                     if span is not None else ["-c:v", "copy"])
            args += ["-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart"]
        else:
            args += ["-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "6", "-threads", "4",
                     "-b:v", "0", "-crf", "30", "-c:a", "libopus"]
    args += ["-progress", "pipe:1", "-nostats", str(target)]
    with _child(args, stop, deadline) as process:
        for line in process.stdout:
            if length > 0 and line.startswith("out_time_us="):
                try:
                    fraction = int(line.split("=", 1)[1]) / (length * 1_000_000)
                except ValueError:  # FFmpeg emits N/A before the first packet.
                    continue
                progress(min(1.0, max(0.0, fraction)))
        code = process.wait()
    if code:
        raise DownloadError("FFmpeg could not trim the video." if span else "FFmpeg could not prepare the MP4.",
                            "Check FFmpeg and try another range or quality.")


def _bundle(target: Path, clips: list[Path], stop: threading.Event, deadline: float) -> None:
    with ZipFile(target, "w") as bundle:
        for clip in clips:
            with clip.open("rb") as source, bundle.open(clip.name, "w", force_zip64=True) as out:
                for chunk in iter(lambda: source.read(128 * 1024), b""):
                    _check_running(stop, deadline)
                    out.write(chunk)


@dataclass
class Inspection:
    url: str
    title: str
    choices: dict[str, Choice]
    expires: float
    duration: float | None = None


@dataclass
class Job:
    id: str
    token: str
    name: str
    choice: Choice
    status: str = "queued"
    progress: float | None = None
    speed: float | None = None
    eta: float | None = None
    error: str = ""
    hint: str = ""
    size: int = 0
    finished: float | None = None
    ranges: tuple[tuple[float, float], ...] = ()
    stop: threading.Event = field(default_factory=threading.Event)

    @property
    def extension(self) -> str:
        return "zip" if len(self.ranges) > 1 else self.choice.container

    def payload(self) -> dict:
        return {"job_id": self.id, "status": self.status, "progress": self.progress,
                "speed": self.speed, "eta": self.eta, "detail": self.error, "hint": self.hint,
                "file": {"name": self.name, "size": self.size, "format": self.extension,
                         "url": f"/api/dl/file/{self.id}?token={self.token}"} if self.status == "ready" else None}


class DownloadManager:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or cutter.DATA / "downloads").resolve()
        self._lock = threading.Lock()
        self._probes = threading.BoundedSemaphore(2)
        self._inspections: dict[str, Inspection] = {}
        self._jobs: dict[str, Job] = {}
        # Age out orphaned downloads after a restart, without touching other app data.
        if self.root.is_dir():
            for item in self.root.iterdir():
                try:
                    if (KEY.fullmatch(item.name) and not item.is_symlink() and item.is_dir()
                            and time.time() - item.stat().st_mtime > FILE_TTL):
                        shutil.rmtree(item, ignore_errors=True)
                except OSError:
                    continue

    def _prune(self) -> None:
        now = time.monotonic()
        for key, record in list(self._inspections.items()):
            if record.expires <= now:
                self._inspections.pop(key)
        for key, job in list(self._jobs.items()):
            if job.finished is not None and now - job.finished > FILE_TTL:
                self._discard(key)

    def _discard(self, key: str) -> None:
        self._jobs.pop(key)
        shutil.rmtree(self.root / key, ignore_errors=True)

    def inspect(self, raw_url: object) -> dict:
        url = youtube_url(raw_url)
        if not self._probes.acquire(blocking=False):
            raise DownloadError("Other links are being inspected. Try again in a moment.", status=429)
        try:
            info = _probe(url)
        finally:
            self._probes.release()
        choices = _choices(info)
        if not choices:
            raise DownloadError("YouTube returned no compatible MP4, WebM or audio formats.", TOOL_HINT)
        title = _text(info.get("title"), 250) or "YouTube video"
        duration = _number(info.get("duration"))
        key = secrets.token_hex(16)
        with self._lock:
            self._prune()
            if len(self._inspections) >= MAX_INSPECTIONS:
                self._inspections.pop(next(iter(self._inspections)))
            self._inspections[key] = Inspection(url, title, choices, time.monotonic() + INSPECTION_TTL, duration)
        return {"inspection_id": key, "title": title, "duration": duration,
                "channel": _text(info.get("channel") or info.get("uploader"), 140),
                "thumbnail": _thumbnail(info.get("thumbnail")),
                "formats": [choice.payload() for choice in choices.values()]}

    def start(self, key: object, option: object, ranges: object = None) -> dict:
        if not isinstance(key, str) or not KEY.fullmatch(key) or not isinstance(option, str) or len(option) > 32:
            raise DownloadError("Inspect the link and select one of the available formats.", status=400)
        with self._lock:
            self._prune()
            record = self._inspections.get(key)
            if record is None:
                raise DownloadError("This inspection expired. Inspect the link again.", status=410)
            # Accept a human-readable MP4 alias only when that exact tier exists.
            match = re.fullmatch(r"(480|720|1080|1440|2160)p", option)
            choice = record.choices.get(f"mp4-{match[1]}" if match else option)
            if choice is None:
                raise DownloadError("That format and quality were not offered by this source.", status=400)
            spans = _trim_ranges(ranges, record.duration)
            if sum(job.finished is None for job in self._jobs.values()) >= MAX_ACTIVE:
                raise DownloadError("NexCut is already preparing two downloads. Try again when one finishes.", status=429)
            tools = _media_tools()
            if len(self._jobs) >= MAX_JOBS:
                self._discard(next(job.id for job in self._jobs.values() if job.finished is not None))
            title = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", record.title[:100]).strip(" .") or "YouTube video"
            suffix = f"{choice.quality}p" if choice.quality else "audio"
            label = " - clips" if len(spans) > 1 else " - clip" if spans else ""
            ext = "zip" if len(spans) > 1 else choice.container
            job = Job(secrets.token_hex(16), secrets.token_hex(16), f"{title} - {suffix}{label}.{ext}",
                      choice, ranges=spans)
            self._jobs[job.id] = job
            try:
                threading.Thread(target=self._run, args=(job, record.url, tools), daemon=True).start()
            except RuntimeError as exc:
                self._jobs.pop(job.id)
                raise DownloadError("NexCut could not start a download worker. Try again.", status=503) from exc
            return job.payload()

    def status(self, job_id: str) -> dict:
        with self._lock:
            self._prune()
            return self._job(job_id).payload()

    def cancel(self, job_id: str) -> dict:
        with self._lock:
            self._prune()
            job = self._job(job_id)
            if job.finished is None:
                job.stop.set()
                job.status = "cancelling"
                job.progress = job.speed = job.eta = None
            return job.payload()

    def open_file(self, job_id: str, *, authorised: bool, token: str) -> tuple[BinaryIO, str, str, int]:
        with self._lock:
            self._prune()
            job = self._job(job_id)
            if not authorised and not (KEY.fullmatch(token) and secrets.compare_digest(token, job.token)):
                raise DownloadError("Invite code or a valid file link required.", status=403)
            if job.status != "ready":
                raise DownloadError("The file is not ready.", status=409)
            try:
                stream = (self.root / job.id / f"media.{job.extension}").open("rb")
            except OSError as exc:
                raise DownloadError("The prepared file is no longer available.", status=404) from exc
            return stream, job.name, MIME_TYPES[job.extension], job.size

    def _job(self, key: str) -> Job:
        job = self._jobs.get(key)
        if job is None:
            raise DownloadError("Unknown or expired download.", status=404)
        return job

    def _run(self, job: Job, url: str, tools: tuple[str, str]) -> None:
        choice = job.choice
        directory = self.root / job.id
        incoming = directory / "source"
        source_ext = choice.source_container or choice.container
        source = incoming / f"source.{source_ext}"
        target = directory / f"media.{job.extension}"
        ffmpeg, ffprobe = tools
        deadline = time.monotonic() + DOWNLOAD_TIMEOUT
        error = hint = ""

        def update(status: str, pct: float | None = None, speed: float | None = None,
                   eta: float | None = None) -> None:
            with self._lock:
                _check_running(job.stop, deadline)
                job.status, job.progress, job.speed, job.eta = status, pct, speed, eta

        def progress(event: dict | None) -> None:
            if event is None:
                update("processing")
                return
            done = _number(event.get("downloaded_bytes"))
            total = _number(event.get("total_bytes")) or _number(event.get("total_bytes_estimate"))
            if done is not None and done > MAX_FILE_BYTES:
                raise DownloadError("The download exceeds the 2 GiB limit.", "Choose a smaller quality.")
            pct = round(min(100, 100 * done / total), 1) if done is not None and total else None
            update("downloading", pct, _number(event.get("speed")), _number(event.get("eta")))

        try:
            _check_running(job.stop, deadline)
            directory.mkdir(parents=True, mode=0o700)
            incoming.mkdir()
            with tempfile.TemporaryDirectory(prefix="nexcut-dl-") as folder:
                args = [*_command(Path(folder)), "--ffmpeg-location", ffmpeg,
                        "--quiet", "--progress", "--newline", "--progress-delta", "0.5",
                        "--progress-template", "download:" + PROGRESS + "%(progress)j",
                        "--progress-template", "postprocess:" + PROCESSING + "%(progress.status)s",
                        "--max-filesize", str(MAX_FILE_BYTES), "-f", choice.selector,
                        "--paths", f"home:{incoming}", "-o", "source.%(ext)s"]
                if choice.container == "mp3":
                    args += ["--extract-audio", "--audio-format", "mp3", "--audio-quality", "0"]
                else:
                    args += ["--merge-output-format", source_ext]
                update("downloading")
                _transfer([*args, "--", url], progress, job.stop, deadline)
            update("processing")
            if not source.is_file():
                raise DownloadError("The download did not produce a file in the selected format.")
            if source.stat().st_size > MAX_FILE_BYTES:
                raise DownloadError("The source exceeds the 2 GiB limit.", "Choose a smaller quality.", 413)

            if job.ranges:
                clips = []
                total = 0
                count = len(job.ranges)
                for i, span in enumerate(job.ranges):
                    def trim_progress(fraction: float, index: int = i) -> None:
                        update("trimming", round(100 * (index + fraction) / count, 1))

                    trim_progress(0)
                    clip = target if count == 1 else incoming / f"Clip {i + 1:02d}.{choice.container}"
                    _make_output(ffmpeg, source, clip, choice.container, span, job.stop, deadline, trim_progress)
                    _verify(clip, choice, ffprobe, job.stop, deadline)
                    total += clip.stat().st_size
                    if total > MAX_FILE_BYTES:
                        raise DownloadError("The clips exceed the 2 GiB limit.", "Use fewer or shorter ranges.", 413)
                    clips.append(clip)
                if count > 1:
                    update("processing")
                    _bundle(target, clips, job.stop, deadline)
            else:
                if choice.source_container:
                    _make_output(ffmpeg, source, target, choice.container, None, job.stop, deadline, None)
                else:
                    source.replace(target)
                _verify(target, choice, ffprobe, job.stop, deadline)
            shutil.rmtree(incoming)
            size = target.stat().st_size
            if size > MAX_FILE_BYTES:
                raise DownloadError("The result exceeds the 2 GiB limit.", "Choose a smaller quality or fewer clips.", 413)
            with self._lock:
                _check_running(job.stop, deadline)
                job.status, job.progress, job.size = "ready", 100, size
                job.finished = time.monotonic()
            return
        except _Cancelled:
            pass
        except DownloadError as exc:
            error, hint = str(exc), exc.hint
        except Exception:  # do not leak tool invocations or server paths via job status
            error, hint = "NexCut could not prepare the file.", "Check the server's media tools and available disk space."
        shutil.rmtree(directory, ignore_errors=True)
        with self._lock:
            job.progress = job.speed = job.eta = None
            if job.stop.is_set():
                job.status = "cancelled"
            else:
                job.status = "error"
                job.error, job.hint = error, hint
            job.finished = time.monotonic()
