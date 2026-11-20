"""tools/check_key.py is the ground-truth path: it must parse .env correctly."""

from __future__ import annotations

import importlib.util
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("check_key", ROOT / "tools" / "check_key.py")
check_key = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_key)


class ReadEnvTests(unittest.TestCase):
    def write(self, text: str) -> pathlib.Path:
        tmp = tempfile.NamedTemporaryFile("w", suffix=".env", delete=False, encoding="utf-8")
        tmp.write(text)
        tmp.close()
        return pathlib.Path(tmp.name)

    def test_values_comments_and_blanks(self):
        path = self.write("# comment\nNEXCUT_API_KEY=AQ.abc_def-ghi\n\nNEXCUT_PROVIDER = gemini\n")
        env = check_key.read_env(path)
        self.assertEqual(env["NEXCUT_API_KEY"], "AQ.abc_def-ghi")
        self.assertEqual(env["NEXCUT_PROVIDER"], "gemini")

    def test_quotes_are_stripped(self):
        path = self.write('NEXCUT_API_KEY="AQ.quoted"\n')
        self.assertEqual(check_key.read_env(path)["NEXCUT_API_KEY"], "AQ.quoted")

    def test_missing_file_is_empty_not_an_error(self):
        self.assertEqual(check_key.read_env(pathlib.Path("/nope/.env")), {})

    def test_no_key_exits_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = pathlib.Path(tmp) / ".env"
            empty.write_text("NEXCUT_PROVIDER=gemini\n", encoding="utf-8")
            original = check_key.ROOT
            check_key.ROOT = pathlib.Path(tmp)
            try:
                code = check_key.main(["check_key.py"])
            finally:
                check_key.ROOT = original
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
