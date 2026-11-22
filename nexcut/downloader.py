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
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from urllib.parse import parse_qs, urlsplit

from . import cutter

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
ID = re.compile(r"[A-Za-z0-9_-]{11}")
FORMAT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}")
KEY = re.compile(r"[0-9a-f]{32}")
MIME_TYPES = {"mp4": "video/mp4", "webm": "video/webm", "mp3": "audio/mpeg"}
INSPECTION_TTL = 15 * 60
FILE_TTL = 60 * 60
MAX_INSPECTIONS = 48
MAX_JOBS = 8
MAX_ACTIVE = 2
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
        video = [f for f in formats if f.get("ext") == ext and _codec(f, "vcodec")]
        if ext == "mp4":
            # Prefer H.264 for MP4 when offered at the chosen tier.
            video.sort(key=lambda f: not _codec(f, "vcodec").startswith(("avc", "h264")))
        for f in video:
            width, height = f.get("width"), f.get("height")
            if type(width) is not int or type(height) is not int or not 0 < min(width, height) <= 8192:
                continue
            tier = min(width, height)  # same display rule for landscape and Shorts
            key = f"{ext}-{tier}"
            if key in choices:
                continue
            combined = _codec(f, "acodec").startswith(audio_codecs)
            if not combined and (f.get("acodec") != "none" or not companion):
                continue
            selector = f["format_id"] if combined else f"{f['format_id']}+{companion['format_id']}"
            choices[key] = Choice(key, ext, selector, tier, f"{tier}p · {width} × {height}", not combined)
    best_audio = next(iter(audio), None) or next((f for f in formats if _codec(f, "acodec")), None)
    if best_audio:
        choices["mp3-audio"] = Choice("mp3-audio", "mp3", best_audio["format_id"], None, "Best available audio")
    return dict(sorted(choices.items(), key=lambda pair: (pair[1].container, -(pair[1].quality or 0))))


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


def _verify(path: Path, choice: Choice, ffprobe: str) -> None:
    if not path.is_file() or path.stat().st_size <= 0:
        raise DownloadError("The download did not produce a file in the selected format.")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise DownloadError("The result exceeds the 2 GiB download limit.", "Choose a smaller quality.", 413)
    result = _capture([ffprobe, "-v", "error", "-show_entries",
                       "format=format_name:stream=codec_type,codec_name,width,height",
                       "-of", "json", str(path)], 20)
    try:
        if result.returncode:
            raise ValueError("probe failed")
        info = json.loads(result.stdout)
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


def _transfer(args: list[str], on_progress) -> None:
    # stdout and stderr share one pipe, including yt-dlp's progress output.
    with subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                          env=_tool_env(), start_new_session=os.name != "nt",
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0) as process:
        timed_out = threading.Event()

        def expire() -> None:
            timed_out.set()
            _kill(process)

        timer = threading.Timer(DOWNLOAD_TIMEOUT, expire)
        timer.daemon = True
        timer.start()
        errors: deque[str] = deque(maxlen=6)
        try:
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
        finally:
            timer.cancel()
            if process.poll() is None:
                _kill(process)
        if timed_out.is_set():
            raise DownloadError("The download exceeded the time limit.", "Try a smaller quality or a shorter video.", 504)
        if code:
            raise _provider_error("\n".join(errors))


@dataclass
class Inspection:
    url: str
    title: str
    choices: dict[str, Choice]
    expires: float


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

    def payload(self) -> dict:
        return {"job_id": self.id, "status": self.status, "progress": self.progress,
                "speed": self.speed, "eta": self.eta, "detail": self.error, "hint": self.hint,
                "file": {"name": self.name, "size": self.size,
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
        key = secrets.token_hex(16)
        with self._lock:
            self._prune()
            if len(self._inspections) >= MAX_INSPECTIONS:
                self._inspections.pop(next(iter(self._inspections)))
            self._inspections[key] = Inspection(url, title, choices, time.monotonic() + INSPECTION_TTL)
        return {"inspection_id": key, "title": title, "duration": _number(info.get("duration")),
                "channel": _text(info.get("channel") or info.get("uploader"), 140),
                "thumbnail": _thumbnail(info.get("thumbnail")),
                "formats": [choice.payload() for choice in choices.values()]}

    def start(self, key: object, option: object) -> dict:
        if not isinstance(key, str) or not KEY.fullmatch(key) or not isinstance(option, str) or len(option) > 32:
            raise DownloadError("Inspect the link and select one of the available formats.", status=400)
        with self._lock:
            self._prune()
            record = self._inspections.get(key)
            if record is None:
                raise DownloadError("This inspection expired. Inspect the link again.", status=410)
            choice = record.choices.get(option)
            if choice is None:
                raise DownloadError("That format and quality were not offered by this source.", status=400)
            if sum(job.finished is None for job in self._jobs.values()) >= MAX_ACTIVE:
                raise DownloadError("NexCut is already preparing two downloads. Try again when one finishes.", status=429)
            tools = _media_tools()
            if len(self._jobs) >= MAX_JOBS:
                self._discard(next(job.id for job in self._jobs.values() if job.finished is not None))
            title = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", record.title[:100]).strip(" .") or "YouTube video"
            suffix = f"{choice.quality}p" if choice.quality else "audio"
            job = Job(secrets.token_hex(16), secrets.token_hex(16), f"{title} - {suffix}.{choice.container}", choice)
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

    def open_file(self, job_id: str, *, authorised: bool, token: str) -> tuple[BinaryIO, str, str, int]:
        with self._lock:
            self._prune()
            job = self._job(job_id)
            if not authorised and not (KEY.fullmatch(token) and secrets.compare_digest(token, job.token)):
                raise DownloadError("Invite code or a valid file link required.", status=403)
            if job.status != "ready":
                raise DownloadError("The file is not ready.", status=409)
            try:
                stream = (self.root / job.id / f"media.{job.choice.container}").open("rb")
            except OSError as exc:
                raise DownloadError("The prepared file is no longer available.", status=404) from exc
            return stream, job.name, MIME_TYPES[job.choice.container], job.size

    def _job(self, key: str) -> Job:
        job = self._jobs.get(key)
        if job is None:
            raise DownloadError("Unknown or expired download.", status=404)
        return job

    def _run(self, job: Job, url: str, tools: tuple[str, str]) -> None:
        choice = job.choice
        directory = self.root / job.id
        target = directory / f"media.{choice.container}"
        ffmpeg, ffprobe = tools
        size = 0
        error = hint = ""

        def progress(event: dict | None) -> None:
            if event is None:
                with self._lock:
                    job.status = "processing"
                    job.progress = job.speed = job.eta = None
                return
            done = _number(event.get("downloaded_bytes"))
            total = _number(event.get("total_bytes")) or _number(event.get("total_bytes_estimate"))
            if done is not None and done > MAX_FILE_BYTES:
                raise DownloadError("The download exceeds the 2 GiB limit.", "Choose a smaller quality.")
            with self._lock:
                job.status = "downloading"
                job.progress = round(min(100, 100 * done / total), 1) if done is not None and total else None
                job.speed = _number(event.get("speed"))
                job.eta = _number(event.get("eta"))

        try:
            directory.mkdir(parents=True, mode=0o700)
            with tempfile.TemporaryDirectory(prefix="nexcut-dl-") as folder:
                args = [*_command(Path(folder)), "--ffmpeg-location", ffmpeg,
                        "--quiet", "--progress", "--newline", "--progress-delta", "0.5",
                        "--progress-template", "download:" + PROGRESS + "%(progress)j",
                        "--progress-template", "postprocess:" + PROCESSING + "%(progress.status)s",
                        "--max-filesize", str(MAX_FILE_BYTES), "-f", choice.selector,
                        "--paths", f"home:{directory}", "-o", "media.%(ext)s"]
                if choice.container == "mp3":
                    args += ["--extract-audio", "--audio-format", "mp3", "--audio-quality", "0"]
                else:
                    args += ["--merge-output-format", choice.container]
                with self._lock:
                    job.status = "downloading"
                _transfer([*args, "--", url], progress)
            progress(None)
            _verify(target, choice, ffprobe)
            size = target.stat().st_size
        except DownloadError as exc:
            error, hint = str(exc), exc.hint
        except Exception:  # do not leak tool invocations or server paths via job status
            error, hint = "NexCut could not prepare the file.", "Check the server's media tools and available disk space."
        finally:
            if not size:
                shutil.rmtree(directory, ignore_errors=True)
            with self._lock:
                job.size = size
                job.error, job.hint = error, hint
                job.progress = 100 if size else None
                job.speed = job.eta = None
                job.status = "ready" if size else "error"
                job.finished = time.monotonic()
