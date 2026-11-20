"""Cutting pipeline: command construction, caching, failure text.

Processes are mocked — nothing here downloads or encodes. The point is that the
command lines, the guards and the error messages are right before a user meets
them with a 2-hour video.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from nexcut import cutter
from nexcut.cuts import CutManager


def fake_proc(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=["x"], returncode=returncode,
                                       stdout=stdout, stderr=stderr)


class TestNaming(unittest.TestCase):
    def test_safe_name_shape(self):
        self.assertEqual(cutter.safe_name(3, 8, 63), "clip-03_00-00-08_00-01-03.mp4")

    def test_safe_name_handles_hours(self):
        self.assertIn("01-02-03", cutter.safe_name(1, 3723, 3800))


class TestTools(unittest.TestCase):
    def test_status_reports_missing_binaries(self):
        with mock.patch.object(cutter.shutil, "which", return_value=None), \
             mock.patch.dict("sys.modules", {"yt_dlp": None}):
            status = cutter.tool_status()
        self.assertFalse(status["can_cut"])
        self.assertTrue(status["hints"]["ffmpeg"])
        self.assertTrue(status["hints"]["yt_dlp"])

    def test_require_tools_names_what_is_missing(self):
        with mock.patch.object(cutter.shutil, "which", return_value=None), \
             mock.patch.dict("sys.modules", {"yt_dlp": None}):
            with self.assertRaises(cutter.CutterError) as ctx:
                cutter._require_cut_tools()
        self.assertIn("yt-dlp", str(ctx.exception))
        self.assertTrue(ctx.exception.hint)

    def test_ffmpeg_missing_after_ytdlp_present(self):
        def which(name):
            return "/usr/bin/yt-dlp" if name == "yt-dlp" else None
        with mock.patch.object(cutter.shutil, "which", side_effect=which):
            with self.assertRaises(cutter.CutterError) as ctx:
                cutter._require_cut_tools()
        self.assertIn("ffmpeg", str(ctx.exception))


class TestProbe(unittest.TestCase):
    def _tools_ok(self):
        return mock.patch.object(cutter, "_require_cut_tools", return_value=["yt-dlp"])

    def test_parses_heights_and_dedupes(self):
        info = {"formats": [
            {"height": 2160}, {"height": 1440}, {"height": 1080},
            {"height": 720}, {"height": None}, {"width": 1920},
        ]}
        with self._tools_ok(), mock.patch.object(cutter, "_run",
                                                 return_value=fake_proc(stdout=json.dumps(info))):
            self.assertEqual(cutter.probe_heights("dQw4w9WgXcQ"), [2160, 1440, 1080])

    def test_always_offers_1080_minimum(self):
        with self._tools_ok(), mock.patch.object(cutter, "_run",
                                                 return_value=fake_proc(stdout='{"formats": []}')):
            self.assertEqual(cutter.probe_heights("dQw4w9WgXcQ"), [1080])

    def test_failure_is_actionable(self):
        with self._tools_ok(), mock.patch.object(cutter, "_run",
                                                 return_value=fake_proc(returncode=1, stderr="boom")):
            with self.assertRaises(cutter.CutterError) as ctx:
                cutter.probe_heights("dQw4w9WgXcQ")
        self.assertIn("formats", str(ctx.exception))


class TestDownload(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        patcher = mock.patch.object(cutter, "CACHE", self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_second_call_uses_cache(self):
        with mock.patch.object(cutter, "_require_cut_tools", return_value=["yt-dlp"]):
            (self.dir / "abc_1080.mp4").write_bytes(b"x" * 10)
            with mock.patch.object(cutter, "_run") as run:
                path = cutter.download("abc", 1080)
        run.assert_not_called()
        self.assertTrue(path.is_file())

    def test_download_command_and_output(self):
        target = self.dir / "abc_1080.mp4"

        def fake_run(cmd, timeout=3600):
            target.write_bytes(b"video")
            return fake_proc()
        with mock.patch.object(cutter, "_require_cut_tools", return_value=["yt-dlp"]), \
             mock.patch.object(cutter, "_run", side_effect=fake_run) as run:
            path = cutter.download("abc", 1080)
        cmd = run.call_args[0][0]
        self.assertIn("-f", cmd)
        self.assertTrue(any("height<=1080" in part for part in cmd))
        self.assertIn("--merge-output-format", cmd)
        self.assertEqual(path, target)

    def test_failure_mentions_bot_check(self):
        with mock.patch.object(cutter, "_require_cut_tools", return_value=["yt-dlp"]), \
             mock.patch.object(cutter, "_run",
                               return_value=fake_proc(returncode=1, stderr="ERROR: sign in required")):
            with self.assertRaises(cutter.CutterError) as ctx:
                cutter.download("abc", 1080)
        self.assertIn("cookies.txt", ctx.exception.hint)


class TestCut(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_rejects_backwards_span(self):
        with self.assertRaises(cutter.CutterError):
            cutter.cut(self.dir / "src.mp4", 60, 60, self.dir / "o.mp4", height=1080)

    def test_command_encodes_accuracy_choices(self):
        out = self.dir / "clip.mp4"

        def fake_run(cmd, timeout=3600):
            out.write_bytes(b"clip")
            return fake_proc()
        with mock.patch.object(cutter, "_run", side_effect=fake_run) as run:
            cutter.cut(self.dir / "src.mp4", 8.5, 63, out, height=1440)
        cmd = " ".join(run.call_args[0][0])
        self.assertIn("-ss 8.500", cmd)
        self.assertIn("-t 54.500", cmd)
        self.assertIn("libx264", cmd)
        self.assertIn("-movflags +faststart", cmd)
        self.assertIn("scale=-2:1440", cmd)

    def test_ffmpeg_failure_reported(self):
        with mock.patch.object(cutter, "_run", return_value=fake_proc(returncode=1, stderr="bad frame")):
            with self.assertRaises(cutter.CutterError) as ctx:
                cutter.cut(self.dir / "src.mp4", 0, 30, self.dir / "o.mp4", height=1080)
        self.assertIn("could not cut", str(ctx.exception))


class TestCutManager(unittest.TestCase):
    def test_runs_download_then_cuts_each_clip(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out_root = Path(tmp.name)
        clips = [
            {"n": 1, "start_sec": 8, "end_sec": 63},
            {"n": 2, "start_sec": 70, "end_sec": 130},
        ]
        with mock.patch("nexcut.cuts.CUTS", out_root), \
             mock.patch("nexcut.cuts.download", return_value=out_root / "src.mp4") as dl, \
             mock.patch("nexcut.cuts.cut", side_effect=self._fake_cut) as cut_fn:
            mgr = CutManager()
            job = mgr.submit(video_id="abc", clips=clips, height=1080)
            for _ in range(200):
                if job.status in ("done", "error"):
                    break
                time.sleep(0.02)
        self.assertEqual(job.status, "done", job.error)
        self.assertEqual(dl.call_count, 1)
        self.assertEqual(cut_fn.call_count, 2)
        self.assertEqual(len(job.files), 2)
        self.assertTrue(all(f["size_mb"] >= 0 for f in job.files))
        self.assertEqual(job.progress, 100)

    @staticmethod
    def _fake_cut(source, start, end, out, height=1080):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"0" * 2048)
        return out

    def test_error_surfaces_hint(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with mock.patch("nexcut.cuts.CUTS", Path(tmp.name)), \
             mock.patch("nexcut.cuts.download",
                        side_effect=cutter.CutterError("no source", "install yt-dlp")):
            mgr = CutManager()
            job = mgr.submit(video_id="abc", clips=[{"n": 1, "start_sec": 0, "end_sec": 10}], height=1080)
            for _ in range(200):
                if job.status == "error":
                    break
                time.sleep(0.02)
        self.assertEqual(job.status, "error")
        self.assertEqual(job.error_hint, "install yt-dlp")

    def test_empty_clip_list_fails_cleanly(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with mock.patch("nexcut.cuts.CUTS", Path(tmp.name)):
            mgr = CutManager()
            job = mgr.submit(video_id="abc", clips=[{"n": 1, "start_sec": 10, "end_sec": 10}], height=1080)
            for _ in range(200):
                if job.status == "error":
                    break
                time.sleep(0.02)
        self.assertEqual(job.status, "error")
        self.assertIn("usable time range", job.error)


if __name__ == "__main__":
    unittest.main()
