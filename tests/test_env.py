"""`.env` loading and env-key precedence.

Run: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nexcut.server import load_dotenv
from nexcut.providers import make_provider


class DotEnvTests(unittest.TestCase):
    def test_reads_pairs_quotes_and_comments(self):
        body = (
            "# comment\n"
            "\n"
            "NEXCUT_PROVIDER=gemini\n"
            'NEXCUT_API_KEY="abc123"\n'
            "export NEXCUT_MODELS='gemini-2.5-flash,gemini-2.5-pro'\n"
            "BROKEN_LINE\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text(body, encoding="utf-8")
            with mock.patch.dict(os.environ, {}, clear=True):
                load_dotenv(path)
                self.assertEqual(os.environ.get("NEXCUT_PROVIDER"), "gemini")
                self.assertEqual(os.environ.get("NEXCUT_API_KEY"), "abc123")
                self.assertEqual(os.environ.get("NEXCUT_MODELS"), "gemini-2.5-flash,gemini-2.5-pro")
                self.assertNotIn("BROKEN_LINE", os.environ)

    def test_real_environment_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("NEXCUT_API_KEY=from_file\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"NEXCUT_API_KEY": "from_shell"}, clear=True):
                load_dotenv(path)
                self.assertEqual(os.environ["NEXCUT_API_KEY"], "from_shell")

    def test_missing_file_is_ignored(self):
        load_dotenv(Path(tempfile.gettempdir()) / "definitely-not-here.env")


class ProviderKeyTests(unittest.TestCase):
    def test_key_falls_back_to_environment(self):
        with mock.patch.dict(os.environ, {"NEXCUT_PROVIDER": "gemini", "NEXCUT_API_KEY": "env-key"}, clear=True):
            self.assertEqual(make_provider("").api_key, "env-key")

    def test_explicit_key_wins(self):
        with mock.patch.dict(os.environ, {"NEXCUT_PROVIDER": "gemini", "NEXCUT_API_KEY": "env-key"}, clear=True):
            self.assertEqual(make_provider("given").api_key, "given")


if __name__ == "__main__":
    unittest.main()
