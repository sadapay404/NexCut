"""End-to-end tests against the real HTTP server (stdlib, no test client).

Run: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import os
import threading
import time
import unittest
import urllib.error
from unittest import mock
import urllib.request
from http.server import ThreadingHTTPServer

from nexcut.server import Handler

SAMPLE = """00:00:00 - Nobody talks about what happened on the third floor.
00:00:09 - The night manager logged the door as locked at 11:40.
00:00:17 - The camera shows it opening at 11:52.
00:00:26 - He told investigators he never left the desk.
00:00:34 - So who used his badge during the twelve minutes he cannot explain?
00:00:45 - A guest reported hearing two voices in an empty corridor.
00:00:54 - The badge reader logged a second entry at 12:04.
"""


class ServerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    # -- helpers -----------------------------------------------------------
    def get(self, path, headers=None):
        req = urllib.request.Request(self.base + path, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode() or "{}")

    def post(self, path, payload, headers=None):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        req = urllib.request.Request(
            self.base + path, data=body, method="POST",
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode() or "{}")

    def run_job(self, **overrides):
        params = {
            "transcript_text": SAMPLE, "niche": "True Crime", "window": "E",
            "num_clips": 3, "model": "stub-model", "cascade": True, "api_key": "",
        }
        params.update(overrides)
        status, body = self.post("/api/extract", params)
        self.assertEqual(status, 200, body)
        job_id = body["job_id"]
        for _ in range(100):
            st, job = self.get(f"/api/jobs/{job_id}")
            if job.get("status") in ("done", "error"):
                return job_id, job
            time.sleep(0.05)
        self.fail("job never finished")

    # -- tests -------------------------------------------------------------
    def test_config_shape(self):
        status, cfg = self.get("/api/config")
        self.assertEqual(status, 200)
        for key in ("models", "default_model", "windows", "niches", "subniches",
                    "audiences", "languages", "version"):
            self.assertIn(key, cfg)
        self.assertEqual(cfg["default_window"], "40-50")
        self.assertEqual([w["id"] for w in cfg["windows"]], ["40-50", "60-90", "90-180", "custom"])
        self.assertEqual((cfg["min_clips"], cfg["max_clips"]), (5, 15))
        self.assertIn("True Crime", cfg["subniches"])

    def test_health(self):
        status, body = self.get("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])

    def test_index_is_served(self):
        # / is a redirect page: it sends the browser to a UI direction.
        with urllib.request.urlopen(self.base + "/", timeout=10) as r:
            html = r.read().decode()
        self.assertIn("Sheikh Arsalan Automation", html)
        self.assertIn("ui-a.html", html)

    def test_direction_pages_load_the_engine(self):
        # each direction page loads the shared engine and its own script
        for page, script in [("/ui-a.html", "ui-a.js"), ("/ui-b.html", "ui-b.js"),
                              ("/ui-c.html", "ui-c.js"), ("/ui-d.html", "ui-d.js")]:
            with urllib.request.urlopen(self.base + page, timeout=10) as r:
                html = r.read().decode()
            self.assertIn("/static/core.js", html, page)
            self.assertIn("/static/" + script, html, page)
            with urllib.request.urlopen(self.base + "/static/" + script, timeout=10) as r:
                self.assertEqual(r.status, 200)

    def test_static_traversal_blocked(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(self.base + "/static/../nexcut/server.py", timeout=10)
        self.assertIn(ctx.exception.code, (404, 400))

    def test_unknown_job_404(self):
        status, body = self.get("/api/jobs/deadbeef")
        self.assertEqual(status, 404)
        self.assertIn("detail", body)

    def test_extract_requires_transcript(self):
        status, body = self.post("/api/extract", {"transcript_text": ""})
        self.assertEqual(status, 400)
        self.assertIn("YouTube link", body["detail"])

    def test_full_run_produces_gated_clips(self):
        job_id, job = self.run_job()
        self.assertEqual(job["status"], "done", job.get("error"))
        self.assertEqual(job["progress"], 100)
        status, res = self.get(f"/api/jobs/{job_id}/results")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(res["clips"]), 1)
        self.assertIn("sweep", res)
        self.assertIn("oracle_report", res)
        clip = res["clips"][0]
        for key in ("n", "start_sec", "start_stamp", "start_sentence", "end_stamp",
                    "duration_str", "titles", "scores", "overlays", "transcript"):
            self.assertIn(key, clip)
        self.assertEqual(set(clip["scores"]), {"curiosity", "stakes", "specificity", "speed", "avg"})

    def test_results_expose_usable_cut_span(self):
        job_id, _ = self.run_job()
        _status, res = self.get(f"/api/jobs/{job_id}/results")
        clip = res["clips"][0]
        self.assertIsNotNone(clip["end_sec"])
        self.assertGreater(clip["end_sec"], clip["start_sec"])

    def test_untimestamped_transcript_errors_cleanly(self):
        job_id, job = self.run_job(transcript_text="just words with no stamps at all")
        self.assertEqual(job["status"], "error")
        self.assertIn("NO TIMESTAMPS", job["error"])
        status, res = self.get(f"/api/jobs/{job_id}/results")
        self.assertEqual(status, 200)
        self.assertEqual(res["clips"] if "clips" in res else [], [])

    def test_report_export(self):
        job_id, _job = self.run_job()
        with urllib.request.urlopen(self.base + f"/api/export/{job_id}", timeout=10) as r:
            self.assertEqual(r.status, 200)
            self.assertIn("clips", r.read().decode())

    def test_upload_raw_text(self):
        body = b"00:00:05 - a line\n00:00:15 - another line\n"
        req = urllib.request.Request(
            self.base + "/api/upload-transcript", data=body, method="POST",
            headers={"Content-Type": "text/plain"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            payload = json.loads(r.read().decode())
        self.assertIn("a line", payload["text"])

    def test_invite_gate_enforced_when_configured(self):
        old = os.environ.get("NEXCUT_INVITE_CODES")
        os.environ["NEXCUT_INVITE_CODES"] = "ABC123"
        try:
            status, _ = self.post("/api/extract", {"transcript_text": SAMPLE})
            self.assertEqual(status, 403)
            status, _ = self.post(
                "/api/extract", {"transcript_text": SAMPLE},
                headers={"X-Invite-Code": "abc123"},
            )
            self.assertEqual(status, 200)
        finally:
            if old is None:
                os.environ.pop("NEXCUT_INVITE_CODES", None)
            else:
                os.environ["NEXCUT_INVITE_CODES"] = old

    def test_tools_endpoint_reports_capability(self):
        status, body = self.get("/api/tools")
        self.assertEqual(status, 200)
        for key in ("ffmpeg", "yt_dlp", "can_cut"):
            self.assertIn(key, body)
            self.assertIsInstance(body[key], bool)

    def test_quality_probe_failure_is_actionable(self):
        from nexcut.cutter import CutterError
        with mock.patch("nexcut.server.probe_heights",
                        side_effect=CutterError("yt-dlp is not installed.", "pip install yt-dlp")):
            status, body = self.get("/api/video-quality/dQw4w9WgXcQ")
        self.assertEqual(status, 422)
        self.assertIn("yt-dlp", body["detail"])
        self.assertEqual(body["hint"], "pip install yt-dlp")

    def test_quality_probe_success_shape(self):
        with mock.patch("nexcut.server.probe_heights", return_value=[2160, 1440, 1080]):
            status, body = self.get("/api/video-quality/dQw4w9WgXcQ")
        self.assertEqual(status, 200)
        self.assertEqual(body["qualities"], [2160, 1440, 1080])

    def test_cut_requires_a_video(self):
        job_id, job = self.run_job()          # pasted transcript -> no video_id
        self.assertEqual(job["status"], "done")
        status, body = self.post(f"/api/jobs/{job_id}/cut", {"height": 1080})
        self.assertEqual(status, 409)
        self.assertIn("no video", body["detail"])

    def test_zip_bundles_mp4s_and_details(self):
        import io
        import time
        import zipfile
        from nexcut.cutter import CutJob
        from nexcut.cuts import CutManager
        from nexcut.server import CUT_MANAGER

        cut_id = "ziptest1"
        directory = CUT_MANAGER.directory(cut_id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "clip-01.mp4").write_bytes(b"not-really-a-video")
        (directory / "details.md").write_text("# run", encoding="utf-8")
        with CUT_MANAGER._lock:
            CUT_MANAGER._cuts[cut_id] = CutJob(id=cut_id, created=time.time(), quality="1080p")

        with urllib.request.urlopen(self.base + f"/api/cuts/{cut_id}/zip", timeout=10) as res:
            self.assertEqual(res.status, 200)
            self.assertIn("application/zip", res.headers.get("Content-Type", ""))
            blob = res.read()
        names = zipfile.ZipFile(io.BytesIO(blob)).namelist()
        self.assertIn("clip-01.mp4", names)
        self.assertIn("details.md", names)
        with CUT_MANAGER._lock:
            CUT_MANAGER._cuts.pop(cut_id, None)

    def test_zip_unknown_cut(self):
        status, _ = self.get("/api/cuts/nope/zip")
        self.assertEqual(status, 404)

    def test_cut_unknown_job(self):
        status, _ = self.post("/api/jobs/nope/cut", {"height": 1080})
        self.assertEqual(status, 404)

    def test_cut_file_traversal_blocked(self):
        status, _ = self.get("/api/cuts/abc/file/..%2F..%2Fserver.py")
        self.assertIn(status, (400, 404))

    def test_results_public_when_no_codes_configured(self):
        job_id, _ = self.run_job()
        status, _ = self.get(f"/api/jobs/{job_id}/results")
        self.assertEqual(status, 200)


    # The pipeline must run against an HTTP provider, not just the offline stub.
    # Regression: jobs.py passed ctx=... to provider.complete(); the stub accepted
    # it, _HttpProvider did not, so every real run died with a TypeError after the
    # captions had already been fetched.
    def test_cloudflare_shaped_provider_finishes_a_job(self):
        from nexcut import server as server_module
        from nexcut.providers import CloudflareProvider, StubProvider

        answer = StubProvider()._compose(transcript=SAMPLE, window="40-50", num_clips=5)
        provider = CloudflareProvider("test-token")

        def fake_attempt(model, system, user, key):
            provider.served_model = model
            return json.dumps(answer)

        with mock.patch.object(provider, "_attempt", side_effect=fake_attempt), \
                mock.patch.object(server_module.MANAGER, "_provider_factory",
                                  lambda api_key: provider):
            job_id, job = self.run_job(num_clips=5)

        self.assertEqual(job["status"], "done", job.get("error"))
        self.assertNotIn("unexpected keyword", (job.get("error") or ""))
        status, result = self.get(f"/api/jobs/{job_id}/results")
        self.assertEqual(status, 200)
        self.assertTrue(result["clips"], "the gate kept nothing")

    def test_internal_error_is_reported_without_a_traceback_dump(self):
        from nexcut import server as server_module

        class Exploding:
            def complete(self, **kwargs):
                raise TypeError("complete() got an unexpected keyword argument 'ctx'")

        with mock.patch.object(server_module.MANAGER, "_provider_factory",
                               lambda api_key: Exploding()), \
                mock.patch("nexcut.jobs.traceback.print_exc") as printed:
            job_id, job = self.run_job()

        self.assertEqual(job["status"], "error")
        self.assertTrue(job["error"].startswith("TypeError:"))
        self.assertIn("traceback", job["error_hint"].lower())
        self.assertEqual(printed.call_count, 1, "the traceback must reach the terminal")


    def test_two_bad_answers_surface_a_format_error(self):
        from nexcut import server as server_module
        from nexcut.providers import CloudflareProvider

        junk = json.dumps({"sweep": {}, "longlist": 3, "clips": 3})
        provider = CloudflareProvider("test-token")

        with mock.patch.object(provider, "_attempt", return_value=junk), \
                mock.patch.object(server_module.MANAGER, "_provider_factory",
                                  lambda api_key: provider):
            job_id, job = self.run_job()

        self.assertEqual(job["status"], "error")
        self.assertIn("clip-report format", job["error"])
        self.assertNotIn("TypeError", job["error"])


if __name__ == "__main__":
    unittest.main()
