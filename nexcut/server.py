"""HTTP layer — stdlib only, so `python3 -m nexcut.server` just works.

Route shapes deliberately mirror the contract we recovered in Phase 1 (same
paths, same field names), because that is the part worth being compatible with.
The implementation behind them is ours.

Env:
  NEXCUT_INVITE_CODES   comma list; when set, /api/extract requires X-Invite-Code
  NEXCUT_PROVIDER       "stub" (default) or "gemini"
  NEXCUT_BACKUP_KEY     backup Gemini key used when a member key is exhausted
  NEXCUT_MODEL_MAP      JSON alias -> real model id
  NEXCUT_PORT           default 8137
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__
from .cutter import CutterError, MIN_HEIGHT, probe_heights, tool_status
from .cuts import CutManager
from .ingest import IngestError, fetch_transcript, video_id as parse_video_id
from .jobs import JobManager
from .providers import make_provider, model_catalog, provider_kind
from .prompts import master_exists

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
MAX_BODY = 8 * 1024 * 1024

NICHES = [
    {"id": "True Crime", "icon": "🩸"},
    {"id": "Reddit Stories", "icon": "📜"},
    {"id": "Sports", "icon": "🏀"},
    {"id": "Religious", "icon": "🕌"},
    {"id": "Relationship & Pop Culture", "icon": "💖"},
    {"id": "Motivations", "icon": "💪"},
    {"id": "Finance", "icon": "💰"},
    {"id": "Others", "icon": "➕"},
]
SUBNICHES = {
    "True Crime": ["Scandal", "Sex Crime", "Prison Life", "Cult", "Serial Killer",
                   "Drug Crime", "Courtroom", "Con Artist"],
    "Reddit Stories": ["AITA", "WIBTA", "Family Drama", "Relationship Drama",
                       "Workplace", "Revenge"],
    "Sports": ["NFL", "NBA", "MLB", "Soccer", "Combat Sports-MMA", "Rugby"],
    "Religious": ["Sermon Teaching", "Testimony", "Apologetics & Debate",
                  "Marriage-Family", "Prophecy"],
    "Relationship & Pop Culture": ["Dating Advice", "Red Flags", "Hollywood",
                                   "Scandal", "Marriage-Divorce"],
    "Motivations": ["Success Stories", "Mindset", "Discipline", "Life Lessons"],
    "Finance": ["Crypto", "Stocks", "Business", "Money Tips"],
    "Others": [],
}
WINDOW_OPTIONS = [
    {"id": "A", "label": "Option A: 30–60s"},
    {"id": "B", "label": "Option B: 60–90s"},
    {"id": "C", "label": "Option C: 90–180s"},
    {"id": "D", "label": "Option D: 180–300s"},
    {"id": "E", "label": "Option E: 45s–5m25s (wide range — default)"},
]
AUDIENCES = ["U.S. English", "Pakistani English", "UK English"]
LANGUAGES = ["U.S. English", "Urdu-English mix", "Pure Urdu", "Pure English"]

_YT_ID = re.compile(r"(?:v=|youtu\.be/|shorts/|live/|embed/)([\w-]{11})")


def youtube_id(url: str) -> str:
    m = _YT_ID.search(url or "")
    return m.group(1) if m else ""


def config_payload() -> dict:
    models = model_catalog()
    return {
        "version": f"v{__version__}",
        "models": models,
        "default_model": models[0]["id"],
        "windows": WINDOW_OPTIONS,
        "default_window": "E",
        "niches": NICHES,
        "subniches": SUBNICHES,
        "audiences": AUDIENCES,
        "languages": LANGUAGES,
        "provider": provider_kind(),
        "requires_invite": bool(_invite_codes()),
        "brand": {
            "name": "Sheikh Arsalan Automation",
            "tagline": "Long recordings in. Broadcast-ready clips out.",
        },
        "prompt": {
            "master_loaded": master_exists(),
            "location": "prompts/master.md",
        },
        "tools": tool_status(),
        "min_height": MIN_HEIGHT,
    }


def _invite_codes() -> set[str]:
    raw = os.environ.get("NEXCUT_INVITE_CODES", "")
    return {c.strip().upper() for c in raw.split(",") if c.strip()}


def _provider_factory(api_key: str):
    return make_provider(api_key)


MANAGER = JobManager(_provider_factory)
CUT_MANAGER = CutManager()


class Handler(BaseHTTPRequestHandler):
    server_version = "NexCut"
    protocol_version = "HTTP/1.1"

    # -- helpers -----------------------------------------------------------
    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store" if ctype.startswith("application/json") else "no-cache")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _error(self, status: int, detail: str) -> None:
        self._json(status, {"detail": detail})

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValueError("Request body too large")
        return self.rfile.read(length) if length else b""

    def _json_body(self) -> dict:
        raw = self._body()
        try:
            data = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            raise ValueError("Body must be JSON")
        if not isinstance(data, dict):
            raise ValueError("Body must be a JSON object")
        return data

    def _authorised(self) -> bool:
        codes = _invite_codes()
        if not codes:
            return True
        q = parse_qs(urlparse(self.path).query)
        supplied = (self.headers.get("X-Invite-Code") or (q.get("code") or [""])[0]).strip().upper()
        return supplied in codes

    def log_message(self, fmt: str, *args) -> None:  # quieter, single line
        print(f"[nexcut] {self.address_string()} {fmt % args}")

    # -- routing -----------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/api/config":
                return self._json(200, config_payload())
            if path == "/api/tools":
                return self._json(200, tool_status())
            m = re.fullmatch(r"/api/video-quality/([\w-]{11})", path)
            if m:
                if not self._authorised():
                    return self._error(403, "Invite code required")
                try:
                    heights = probe_heights(m.group(1))
                except CutterError as exc:
                    return self._json(422, {"detail": str(exc),
                                            "hint": getattr(exc, "hint", "")})
                return self._json(200, {"qualities": heights})
            m = re.fullmatch(r"/api/cuts/([A-Za-z0-9_-]+)", path)
            if m:
                cut_job = CUT_MANAGER.get(m.group(1))
                return self._json(200, cut_job.payload()) if cut_job else self._error(404, "Unknown cut job")
            m = re.fullmatch(r"/api/cuts/([A-Za-z0-9_-]+)/file/([^/]+)", path)
            if m:
                if not self._authorised():
                    return self._error(403, "Invite code required")
                return self._cut_file(m.group(1), m.group(2))
            if path == "/api/health":
                return self._json(200, {"ok": True, "version": __version__})
            m = re.fullmatch(r"/api/jobs/([A-Za-z0-9_-]+)", path)
            if m:
                job = MANAGER.get(m.group(1))
                return self._json(200, job.status_payload()) if job else self._error(404, "Unknown job")
            m = re.fullmatch(r"/api/jobs/([A-Za-z0-9_-]+)/results", path)
            if m:
                if not self._authorised():
                    return self._error(403, "Invite code required")
                job = MANAGER.get(m.group(1))
                if not job:
                    return self._error(404, "Unknown job")
                if job.status == "error":
                    return self._json(200, {"error": job.error, "oracle_report": "", "dropped": []})
                if not job.result:
                    return self._error(409, "Job is not finished yet")
                return self._json(200, job.result)
            m = re.fullmatch(r"/api/export/([A-Za-z0-9_-]+)", path)
            if m:
                job = MANAGER.get(m.group(1))
                if not job or not job.result:
                    return self._error(404, "No report for that job")
                report = job.result.get("oracle_report", "")
                return self._send(200, report.encode(), "text/plain; charset=utf-8",
                                  {"Content-Disposition": 'attachment; filename="nexcut-report.txt"'})
            return self._static(path)
        except Exception as exc:  # noqa: BLE001
            return self._error(500, f"Server error: {exc}")

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/api/extract":
                if not self._authorised():
                    return self._error(403, "Invite code required")
                try:
                    params = self._json_body()
                except ValueError as exc:
                    return self._error(400, str(exc))
                has_text = bool((params.get("transcript_text") or "").strip())
                has_url = bool((params.get("youtube_url") or "").strip())
                if not has_text and not has_url:
                    return self._error(
                        400, "Paste a YouTube link, or paste a transcript — one of the two is required."
                    )
                params["video_id"] = youtube_id(params.get("youtube_url") or "")
                job = MANAGER.submit(params)
                return self._json(200, {"job_id": job.id})
            if path == "/api/video-info":
                if not self._authorised():
                    return self._error(403, "Invite code required")
                try:
                    params = self._json_body()
                except ValueError as exc:
                    return self._error(400, str(exc))
                vid = parse_video_id(params.get("url") or "")
                try:
                    tr = fetch_transcript(params.get("url") or "", use_cache=True)
                    return self._json(200, {
                        "video_id": vid, "channel": tr.channel, "title": tr.title,
                        "has_transcript": True, "chars": len(tr.text),
                        "is_auto_captions": tr.is_auto, "source": tr.source,
                    })
                except IngestError as exc:
                    return self._json(200, {
                        "video_id": vid, "channel": "", "title": "",
                        "has_transcript": False,
                        "detail": str(exc), "hint": getattr(exc, "hint", ""),
                    })
            m = re.fullmatch(r"/api/jobs/([A-Za-z0-9_-]+)/cut", path)
            if m:
                if not self._authorised():
                    return self._error(403, "Invite code required")
                job = MANAGER.get(m.group(1))
                if not job or not job.result:
                    return self._error(404, "No finished session with that id")
                try:
                    params = self._json_body()
                except ValueError as exc:
                    return self._error(400, str(exc))
                clips = job.result.get("clips") or []
                if not clips:
                    return self._error(409, "That session has no clips to cut.")
                video_id = job.result.get("video_id") or ""
                if not video_id:
                    return self._error(409, "That session came from a pasted transcript, so there is no video to cut.")
                try:
                    height = int(params.get("height") or MIN_HEIGHT)
                except (TypeError, ValueError):
                    return self._error(400, "height must be a number")
                cut_job = CUT_MANAGER.submit(
                    video_id=video_id, clips=clips, height=height,
                    title=job.result.get("video_title", ""),
                )
                return self._json(200, {"cut_id": cut_job.id})
            if path == "/api/transcript":
                if not self._authorised():
                    return self._error(403, "Invite code required")
                try:
                    params = self._json_body()
                except ValueError as exc:
                    return self._error(400, str(exc))
                try:
                    tr = fetch_transcript(params.get("url") or "",
                                          language=params.get("language") or "en")
                except IngestError as exc:
                    return self._json(422, {"detail": str(exc), "hint": getattr(exc, "hint", "")})
                return self._json(200, {
                    "video_id": tr.video_id, "title": tr.title, "channel": tr.channel,
                    "text": tr.text, "lines": len(tr.lines), "chars": len(tr.text),
                    "seconds": round(tr.seconds, 1), "source": tr.source,
                    "language": tr.language, "is_auto": tr.is_auto,
                })
            if path == "/api/upload-transcript":
                if not self._authorised():
                    return self._error(403, "Invite code required")
                raw = self._body()
                ctype = self.headers.get("Content-Type") or ""
                text = _extract_upload(raw, ctype)
                if not text.strip():
                    return self._error(400, "Empty file")
                return self._json(200, {"text": text, "chars": len(text)})
            return self._error(404, "Not found")
        except Exception as exc:  # noqa: BLE001
            return self._error(500, f"Server error: {exc}")

    def _cut_file(self, cut_id: str, filename: str):
        if not re.fullmatch(r"[A-Za-z0-9._-]+", filename or ""):
            return self._error(400, "Bad filename")
        directory = CUT_MANAGER.directory(cut_id).resolve()
        target = (directory / filename).resolve()
        if not str(target).startswith(str(directory)) or not target.is_file():
            return self._error(404, "File not found")
        body = target.read_bytes()
        return self._send(200, body, "video/mp4", {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, max-age=3600",
        })

    # -- static ------------------------------------------------------------
    def _static(self, path: str) -> None:
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        if rel.startswith("static/"):
            rel = rel[len("static/"):]
        target = (WEB / rel).resolve()
        if not str(target).startswith(str(WEB.resolve())) or not target.is_file():
            return self._error(404, "Not found")
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)


def _extract_upload(raw: bytes, ctype: str) -> str:
    """Accept a raw text body or a single multipart file field."""
    if "multipart/form-data" not in ctype:
        return raw.decode("utf-8", "replace")
    m = re.search(r"boundary=([^;]+)", ctype)
    if not m:
        return raw.decode("utf-8", "replace")
    boundary = m.group(1).strip().strip('"').encode()
    for part in raw.split(b"--" + boundary):
        if b"filename=" not in part:
            continue
        _, _, content = part.partition(b"\r\n\r\n")
        return content.rstrip(b"\r\n-").decode("utf-8", "replace")
    return ""


def serve(port: int | None = None, host: str = "0.0.0.0") -> None:
    port = port or int(os.environ.get("NEXCUT_PORT", "8137"))
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"[nexcut] v{__version__} on http://{host}:{port}  provider={os.environ.get('NEXCUT_PROVIDER','stub')}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[nexcut] stopped")


if __name__ == "__main__":
    serve()
