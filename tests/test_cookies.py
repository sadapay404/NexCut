"""YouTube bot-checks on datacenter IPs: the cookies file must actually be passed."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nexcut import cutter, ingest


class CookieTests(unittest.TestCase):
    def test_no_file_means_no_flag(self):
        with mock.patch.dict(os.environ, {"NEXCUT_COOKIES": ""}, clear=False):
            self.assertEqual(cutter.cookies_arg(), [])
            self.assertEqual(ingest.cookie_path(), "")

    def test_env_points_at_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            jar = Path(tmp) / "jar.txt"
            jar.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"NEXCUT_COOKIES": str(jar)}):
                self.assertEqual(cutter.cookies_arg(), ["--cookies", str(jar)])
                self.assertEqual(ingest.cookies_arg(), ["--cookies", str(jar)])

    def test_empty_env_falls_back_to_repo_cookies_txt(self):
        with tempfile.TemporaryDirectory() as tmp:
            jar = Path(tmp) / "cookies.txt"
            jar.write_text("x", encoding="utf-8")
            with mock.patch.dict(os.environ, {"NEXCUT_COOKIES": ""}), \
                 mock.patch.object(cutter, "ROOT", Path(tmp)), \
                 mock.patch.object(ingest, "ROOT", Path(tmp)):
                self.assertEqual(cutter.cookies_arg(), ["--cookies", str(jar)])

    def test_empty_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            jar = Path(tmp) / "cookies.txt"
            jar.write_text("", encoding="utf-8")
            with mock.patch.dict(os.environ, {"NEXCUT_COOKIES": str(jar)}):
                self.assertEqual(cutter.cookies_arg(), [])


if __name__ == "__main__":
    unittest.main()
