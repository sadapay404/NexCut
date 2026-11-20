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


class ListModelsTests(unittest.TestCase):
    def test_lists_only_generate_content_ids(self):
        import io as _io
        import json as _json

        payload = {"models": [
            {"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/embedding-001", "supportedGenerationMethods": ["embedContent"]},
            {"name": "models/gemini-2.5-pro", "supportedGenerationMethods": ["generateContent"]},
        ]}

        class R:
            def read(self):
                return _json.dumps(payload).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        from unittest import mock
        import contextlib
        buffer = _io.StringIO()
        with mock.patch("urllib.request.urlopen", return_value=R()), \
             contextlib.redirect_stdout(buffer):
            code = check_key.list_models("AQ.key")
        out = buffer.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("gemini-3.8-flash", out)
        self.assertIn("gemini-2.5-pro", out)
        self.assertNotIn("embedding-001", out)
        self.assertIn("NEXCUT_MODELS=", out)


class EnvDrivesResolution(unittest.TestCase):
    def test_dotenv_provider_makes_the_default_a_gemini_id(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            env = check_key.read_env(pathlib.Path(tmp) / "missing.env")
            env.update({"NEXCUT_PROVIDER": "gemini"})
            original = {k: os.environ.get(k) for k in ("NEXCUT_PROVIDER", "NEXCUT_MODELS")}
            os.environ.pop("NEXCUT_MODELS", None)
            try:
                check_key.load_env(env)
                self.assertTrue(check_key.shipped_default_model().startswith("gemini-"))
            finally:
                for k, v in original.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
