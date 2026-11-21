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
CONSENT_COOKIE = (
    "CONSENT=YES+cb.20210328-17-p0.en+FX+410; "
    "SOCS=CAISNQgDEitib3FfaWRlbnRpdHlmcm9udGVuZHVpc2VydmVyXzIwMjMwODI5LjA3X3AxGgJlbiACGgYIgLC_pwY"
)
CONSENT = {"Cookie": CONSENT_COOKIE}

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
VR_UA = ("com.google.android.apps.youtube.vr.oculus/1.60.19 "
         "(Linux; U; Android 12; GB) gzip")
TV_UA = ("Mozilla/5.0 (PlayStation; PlayStation 4/12.00) AppleWebKit/605.1.15 "
         "(KHTML, like Gecko) Version/16.0 Safari/605.1.15")
INNERTUBE_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"

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
# track selection (shared by every strategy)
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


# Only the sign-in wall counts. "This video is unavailable" means the video, not
# the network, so it must not trigger the IP-block verdict.
BOT_WALL_MARKERS = ("sign in to confirm", "not a bot", "login_required")


def looks_like_ip_block(errors: list[str]) -> bool:
    """True when several independent methods were walled the same way."""
    if not errors:
        return False
    walled = sum(1 for e in errors
                 if any(marker in e.lower() for marker in BOT_WALL_MARKERS))
    return walled >= 2


def inspect_innertube(vid: str, language: str = "en") -> list[dict]:
    """What each client identity actually answered — for diagnostics, not for runs."""
    report: list[dict] = []
    for client in INNERTUBE_CLIENTS:
        entry = {"client": client["id"], "status": "", "reason": "", "tracks": 0,
                 "lines": 0, "format": "", "error": ""}
        try:
            url, headers = player_request(client)
            player = _post_json(url, {"context": client["context"], "videoId": vid,
                                      "contentCheckOk": True, "racyCheckOk": True},
                                headers=headers)
            info = read_player_response(player)
            entry["status"] = info["status"]
            entry["reason"] = info["reason"]
            entry["tracks"] = len(info["tracks"])
            track = _pick_track(info["tracks"], language)
            if track:
                lines, fmt = fetch_track_lines(client, track["baseUrl"])
                entry["lines"], entry["format"] = len(lines), fmt
        except IngestError as exc:
            entry["error"] = str(exc)
            entry["reason"] = entry["reason"] or (exc.hint or "")[:160]
        except Exception as exc:  # noqa: BLE001 - diagnostics never raise
            entry["error"] = f"{type(exc).__name__}: {exc}"
        report.append(entry)
    return report


def cookie_path() -> str:
    """Same rule as the cutter: NEXCUT_COOKIES, else ./cookies.txt if it exists."""
    raw = os.environ.get("NEXCUT_COOKIES", "").strip()
    path = Path(raw) if raw else (ROOT / "cookies.txt")
    return str(path) if path.is_file() and path.stat().st_size > 0 else ""


def cookies_arg() -> list[str]:
    found = cookie_path()
    return ["--cookies", found] if found else []


# --------------------------------------------------------------------------
# strategy 1: Innertube as several client identities
# --------------------------------------------------------------------------
# Why several: YouTube decides *per client* whether to expose caption tracks, and
# from a datacenter IP (Cloud Shell, VPS, CI) the WEB client often hides them or
# answers with a sign-in wall while another identity returns them. Each entry must
# look exactly like the real client — URL key, body context and, crucially, the
# x-youtube-client-name / -version headers. A mismatch is answered with 400 or an
# empty body, which reads exactly like "no captions" unless you check.
INNERTUBE_CLIENTS: tuple[dict, ...] = (
    {
        "id": "android-vr", "label": "ANDROID_VR", "client_name_id": 28,
        "headers": {"content-type": "application/json", "user-agent": VR_UA,
                    "accept-language": "en-US,en;q=0.9"},
        "context": {"client": {
            "clientName": "ANDROID_VR", "clientVersion": "1.60.19",
            "androidSdkVersion": 32, "deviceMake": "Oculus", "deviceModel": "Quest 3",
            "osName": "Android", "osVersion": "12", "hl": "en", "gl": "US",
            "userAgent": VR_UA}},
        "consent": False,
    },
    {
        "id": "web", "label": "WEB", "client_name_id": 1,
        "headers": {"content-type": "application/json", "user-agent": CHROME_UA,
                    "accept-language": "en-US,en;q=0.9",
                    "origin": "https://www.youtube.com", "referer": "https://www.youtube.com/",
                    "cookie": CONSENT_COOKIE},
        "context": {"client": {"clientName": "WEB", "clientVersion": "2.20250201.00.00",
                               "hl": "en", "gl": "US"},
                    "user": {"lockedSafetyMode": False}},
        "consent": True,
    },
    {
        "id": "web-embedded", "label": "WEB_EMBEDDED_PLAYER", "client_name_id": 56,
        "headers": {"content-type": "application/json", "user-agent": CHROME_UA,
                    "accept-language": "en-US,en;q=0.9",
                    "origin": "https://www.youtube.com", "referer": "https://www.youtube.com/",
                    "cookie": CONSENT_COOKIE},
        "context": {"client": {"clientName": "WEB_EMBEDDED_PLAYER",
                               "clientVersion": "1.20250201.00.00", "hl": "en", "gl": "US"},
                    "thirdParty": {"embedUrl": "https://www.youtube.com/"}},
        "consent": True,
    },
    {
        "id": "tv-embedded", "label": "TVHTML5_SIMPLY_EMBEDDED_PLAYER", "client_name_id": 85,
        "headers": {"content-type": "application/json", "user-agent": TV_UA,
                    "accept-language": "en-US,en;q=0.9",
                    "origin": "https://www.youtube.com", "referer": "https://www.youtube.com/tv",
                    "cookie": CONSENT_COOKIE},
        "context": {"client": {"clientName": "TVHTML5_SIMPLY_EMBEDDED_PLAYER",
                               "clientVersion": "2.0", "clientScreen": "EMBED",
                               "hl": "en", "gl": "US"},
                    "thirdParty": {"embedUrl": "https://www.youtube.com/tv"}},
        "consent": True,
    },
)


def player_request(client: dict) -> tuple[str, dict]:
    """(url, headers) for the player call — identity headers must match the body."""
    version = (client["context"]["client"] or {}).get("clientVersion", "")
    headers = {
        **client["headers"],
        "x-youtube-client-name": str(client["client_name_id"]),
        "x-youtube-client-version": str(version),
    }
    url = f"https://www.youtube.com/youtubei/v1/player?key={INNERTUBE_KEY}&prettyPrint=false"
    return url, headers


def with_caption_format(base_url: str, fmt: str) -> str:
    """Swap only `fmt` on a signed caption URL — the rest of the signature is opaque."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parts = urlsplit(base_url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "fmt"]
    query.append(("fmt", fmt))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def read_player_response(payload: dict) -> dict:
    status = (payload.get("playabilityStatus") or {})
    details = payload.get("videoDetails") or {}
    tracks = (((payload.get("captions") or {})
               .get("playerCaptionsTracklistRenderer") or {})
              .get("captionTracks") or [])
    keep = [t for t in tracks if t.get("baseUrl") and t.get("languageCode")]
    return {"status": status.get("status") or "?", "reason": status.get("reason") or "",
            "tracks": keep, "title": details.get("title") or "",
            "channel": details.get("author") or ""}


def parse_srv3(xml: str) -> list[tuple[float, str]]:
    """`<p t="12340" d="2000"><s>Hello</s><s> world</s></p>` — t is milliseconds."""
    out: list[tuple[float, str]] = []
    for attrs, inner in re.findall(r"<p\s([^>]*)>([\s\S]*?)</p>", xml):
        found = re.search(r'\bt="(\d+)"', attrs)
        if not found:
            continue
        words = re.findall(r"<s[^>]*>([\s\S]*?)</s>", inner)
        body = _clean("".join(words) if words else inner)
        if body:
            out.append((int(found.group(1)) / 1000.0, body))
    return out


def caption_lines(raw: bytes, fmt: str) -> list[tuple[float, str]]:
    text = raw.decode("utf-8", "replace")
    if fmt == "json3":
        return parse_json3(raw)
    if fmt == "srv3":
        return parse_srv3(text)
    if fmt == "vtt":
        return parse_vtt(text)
    return parse_timedtext_xml(raw) or parse_srv3(text) or parse_vtt(text)


def fetch_track_lines(client: dict, base_url: str) -> tuple[list[tuple[float, str]], str]:
    """Try the signed URL in the three shapes YouTube serves it in."""
    failures: list[str] = []
    for fmt in ("json3", "srv3", "vtt"):
        try:
            raw = _get(with_caption_format(base_url, fmt), timeout=25,
                       headers={"User-Agent": client["headers"]["user-agent"],
                                "Accept-Language": "en-US,en;q=0.9",
                                **({"Cookie": CONSENT_COOKIE} if client.get("consent") else {})})
        except IngestError as exc:
            failures.append(f"{fmt}: {exc}")
            continue
        lines = caption_lines(raw, fmt)
        if lines:
            return lines, fmt
        failures.append(f"{fmt}: empty")
    raise IngestError("The caption track returned nothing.", "; ".join(failures)[:240])


def _via_innertube(vid: str, language: str) -> Transcript:
    reasons: list[str] = []
    for client in INNERTUBE_CLIENTS:
        name = f"innertube:{client['id']}"
        url, headers = player_request(client)
        try:
            player = _post_json(url, {"context": client["context"], "videoId": vid,
                                      "contentCheckOk": True, "racyCheckOk": True},
                                headers=headers)
        except IngestError as exc:
            reasons.append(f"{name}: {exc}")
            continue

        info = read_player_response(player)
        if info["status"] not in ("OK", "LIVE_STREAM_OFFLINE"):
            reasons.append(f"{name}: {info['status']}"
                           f"{' — ' + info['reason'] if info['reason'] else ''}")
            continue
        track = _pick_track(info["tracks"], language)
        if not track:
            reasons.append(f"{name}: OK but 0 caption tracks")
            continue
        try:
            lines, fmt = fetch_track_lines(client, track["baseUrl"])
        except IngestError as exc:
            reasons.append(f"{name}: {exc}")
            continue
        merged = consolidate(lines)
        return Transcript(
            text=to_text(merged), lines=merged,
            source=f"innertube:{client['id']}",
            language=track.get("languageCode") or "",
            is_auto=track.get("kind") == "asr", video_id=vid,
            title=info["title"], channel=info["channel"],
        )
    raise IngestError("No client identity returned captions for this video.",
                      "; ".join(reasons)[:400])


# --------------------------------------------------------------------------
# strategy 2: watch page (player response embedded in the HTML)
# --------------------------------------------------------------------------
def _via_watch_page(vid: str, language: str) -> Transcript:
    html = _get(
        f"https://www.youtube.com/watch?v={vid}&bpctr=9999999999&has_verified=1&hl=en",
        timeout=25, headers={"User-Agent": CHROME_UA,
                             "Accept-Language": "en-US,en;q=0.9",
                             "Cookie": CONSENT_COOKIE},
    ).decode("utf-8", "replace")

    m = re.search(r"ytInitialPlayerResponse\s*=\s*(\{.+?\})\s*;", html, flags=re.S)
    if not m:
        m = re.search(r'"captionTracks":(\[.*?\])', html)
        if not m:
            raise IngestError(
                "The watch page served no player response.",
                "YouTube showed a consent or bot page instead. Export cookies.txt from "
                "a browser and put it in the repo root, or paste the transcript.",
            )
        tracks = json.loads(m.group(1))
        title = channel = ""
    else:
        try:
            info = read_player_response(json.loads(m.group(1)))
        except ValueError as exc:
            raise IngestError("Could not read the page's player data.", str(exc)) from exc
        tracks, title, channel = info["tracks"], info["title"], info["channel"]

    track = _pick_track(tracks, language)
    if not track:
        raise IngestError("No usable caption track on this video.",
                          "Paste the transcript manually.")
    lines, _fmt = fetch_track_lines(INNERTUBE_CLIENTS[1], track["baseUrl"])
    merged = consolidate(lines)
    return Transcript(text=to_text(merged), lines=merged, source="watch-page",
                      language=track.get("languageCode") or "",
                      is_auto=track.get("kind") == "asr", video_id=vid,
                      title=title, channel=channel)


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
# strategy 3: unsigned timedtext (no player round-trip at all)
# --------------------------------------------------------------------------
def _via_timedtext(vid: str, language: str) -> Transcript:
    """Manual tracks are often served unsigned; it costs one request to find out."""
    candidates: list[str] = []
    for lang in (language, (language or "").split("-")[0], "en"):
        if lang and lang not in candidates:
            candidates.append(lang)
    failures: list[str] = []
    for lang in candidates:
        for asr in (False, True):
            url = (f"https://www.youtube.com/api/timedtext?v={vid}&lang={lang}"
                   f"&fmt=json3" + ("&kind=asr" if asr else ""))
            try:
                raw = _get(url, timeout=20,
                           headers={"User-Agent": CHROME_UA,
                                    "Accept-Language": "en-US,en;q=0.9",
                                    "Cookie": CONSENT_COOKIE})
            except IngestError as exc:
                failures.append(f"{lang}{'(asr)' if asr else ''}: {exc}")
                continue
            lines = parse_json3(raw) or parse_timedtext_xml(raw)
            if not lines:
                failures.append(f"{lang}{'(asr)' if asr else ''}: empty")
                continue
            merged = consolidate(lines)
            return Transcript(text=to_text(merged), lines=merged,
                              source="timedtext-unsigned", language=lang,
                              is_auto=asr, video_id=vid)
    raise IngestError("The unsigned timedtext endpoint served nothing.",
                      "; ".join(failures)[:240])


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


# (label, function) — the labels appear in error messages, so they are fixed here
# rather than derived from function names.
STRATEGIES: tuple[tuple[str, str], ...] = (
    ("innertube", "_via_innertube"),
    ("timedtext", "_via_timedtext"),
    ("watch-page", "_via_watch_page"),
    ("yt-dlp", "_via_ytdlp"),
    ("transcript-api", "_via_transcript_api"),
)


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
    for name, attribute in STRATEGIES:
        strategy = globals()[attribute]     # resolved per call, so it stays swappable
        try:
            tr = strategy(vid, language)
        except IngestError as exc:
            # keep the strategy's own diagnostics: that is where the reason lives
            detail = str(exc) + (f" — {exc.hint}" if exc.hint else "")
            errors.append(f"{name}: {detail}")
            continue
        except Exception as exc:  # noqa: BLE001 - one broken strategy must not stop the run
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
            continue
        try:
            meta = fetch_metadata(vid)
            tr.title = tr.title or meta["title"]
            tr.channel = tr.channel or meta["channel"]
        except (IngestError, KeyError, TypeError):
            pass
        if tr.lines:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({
                "text": tr.text, "lines": tr.lines, "source": tr.source,
                "language": tr.language, "is_auto": tr.is_auto,
                "video_id": tr.video_id, "title": tr.title, "channel": tr.channel,
            }))
        return tr

    if looks_like_ip_block(errors):
        raise IngestError(
            "YouTube is blocking this machine's IP address.",
            "Every method hit 'Sign in to confirm you're not a bot', including on "
            "videos that certainly have captions — that is YouTube refusing this "
            "network, not a problem with the video. Fix any of: run Sheikh Arsalan Automation on your "
            "own computer instead of a cloud shell, put a cookies.txt (exported from a "
            "browser) in the repo root and restart, or paste the transcript manually.",
        )

    hint = "Tried: " + " | ".join(errors)
    if len(hint) > 900:
        hint = hint[:900] + " …"
    raise IngestError(
        "Could not get captions for this video by any method.",
        hint + " — paste the transcript, or add cookies.txt and retry.",
    )
