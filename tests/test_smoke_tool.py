"""tools/smoke_run.py must report each stage, and stop with the failing one."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import pathlib
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("smoke_run", ROOT / "tools" / "smoke_run.py")
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class _Handler(BaseHTTPRequestHandler):
    state: dict = {}

    def log_message(self, *a):
        pass

    def _send(self, payload, code=200):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path
        if path == "/api/tools":
            return self._send({"ffmpeg": True, "yt_dlp": True, "can_cut": True})
        if path == "/api/jobs/j1":
            self.state["job_polls"] = self.state.get("job_polls", 0) + 1
            if self.state["job_polls"] < 2:
                return self._send({"status": "running", "progress": 40, "stage": "Model"})
            return self._send({"status": "done", "progress": 100, "stage": "Done"})
        if path == "/api/jobs/j1/results":
            return self._send({"clips": [{"start_stamp": "00:01:02", "title": "A hook"}],
                               "model": "test-model", "elapsed_s": 3})
        if path == "/api/cuts/c1":
            if self.state.get("cut_fail"):
                return self._send({"status": "error", "progress": 0,
                                   "error": "sign in to confirm you're not a bot",
                                   "error_hint": "use cookies.txt"})
            return self._send({"status": "done", "progress": 100, "quality": "1080p",
                               "files": [{"path": "clip-1.mp4", "bytes": 12_000_000}]})
        if path == "/api/jobs/bad":
            return self._send({"status": "error", "progress": 0,
                               "error": "NO TIMESTAMPS", "error_hint": "needs stamps"})
        return self._send({"detail": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        if self.path == "/api/transcript":
            return self._send({"title": "Test video", "text": "[00:00:05] hello",
                               "lines": 1, "kind": "auto"})
        if self.path == "/api/extract":
            return self._send({"job_id": "j1"})
        if self.path == "/api/jobs/j1/cut":
            return self._send({"cut_id": "c1"})
        if self.path == "/api/extract-bad":
            return self._send({"job_id": "bad"})
        return self._send({"detail": "not found"}, 404)


class SmokeToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def run_tool(self, *args):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = smoke.main(["smoke_run.py", *args, "--server", self.base])
        return code, buffer.getvalue()

    def test_happy_path_reports_every_stage(self):
        _Handler.state.clear()
        code, out = self.run_tool("https://youtu.be/x")
        self.assertEqual(code, 0, out)
        for needle in ("can_cut=True", "Test video", "1 clip(s)", "test-model",
                       "1080p", "clip-1.mp4", "/api/cuts/c1/zip", "everything green"):
            self.assertIn(needle, out)

    def test_cut_failure_points_at_cookies(self):
        _Handler.state.clear()
        _Handler.state["cut_fail"] = True
        code, out = self.run_tool("https://youtu.be/x")
        self.assertEqual(code, 1)
        self.assertIn("bot", out)
        self.assertIn("cookies.txt", out)

    def test_no_cut_stops_after_extraction(self):
        _Handler.state.clear()
        code, out = self.run_tool("https://youtu.be/x", "--no-cut")
        self.assertEqual(code, 0)
        self.assertNotIn("cutting at 1080p", out)

    def test_missing_url_prints_usage(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = smoke.main(["smoke_run.py"])
        self.assertEqual(code, 2)
        self.assertIn("smoke_run.py", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
