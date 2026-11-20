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
        import os
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            empty = pathlib.Path(tmp) / ".env"
            empty.write_text("NEXCUT_PROVIDER=gemini\n", encoding="utf-8")
            original = check_key.ROOT
            check_key.ROOT = pathlib.Path(tmp)
            try:
                # load_env() writes into os.environ; patch.dict rolls it back
                with mock.patch.dict(os.environ, {}, clear=False):
                    code = check_key.main(["check_key.py"])
            finally:
                check_key.ROOT = original
        self.assertEqual(code, 2)


class ListModelsTests(unittest.TestCase):
    def test_lists_openai_style_ids_for_groq(self):
        import io as _io
        import json as _json
        import contextlib
        from unittest import mock

        payload = {"data": [{"id": "llama-3.3-70b-versatile"}, {"id": "openai/gpt-oss-120b"}]}

        class R:
            def read(self):
                return _json.dumps(payload).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        seen = {}

        def fake_get(url, headers):
            seen["url"] = url
            seen["headers"] = headers
            return payload

        buffer = _io.StringIO()
        import os
        with mock.patch.dict(os.environ, {"NEXCUT_PROVIDER": "groq"}), \
             mock.patch.object(check_key, "_get", fake_get), \
             contextlib.redirect_stdout(buffer):
            code = check_key.list_models("gsk_key")
        out = buffer.getvalue()
        self.assertEqual(code, 0)
        self.assertEqual(seen["url"], "https://api.groq.com/openai/v1/models")
        self.assertEqual(seen["headers"]["Authorization"], "Bearer gsk_key")
        self.assertIn("llama-3.3-70b-versatile", out)
        self.assertIn("NEXCUT_MODELS=", out)

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


class NativeKeyDiscovery(unittest.TestCase):
    """The tool must find CLOUDFLARE_API_TOKEN and friends, like the server does."""

    def run_main(self, env_text: str):
        import contextlib
        import io as _io
        import os
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            (pathlib.Path(tmp) / ".env").write_text(env_text, encoding="utf-8")
            original = check_key.ROOT
            check_key.ROOT = pathlib.Path(tmp)
            buffer = _io.StringIO()
            calls = {}

            def fake_post(url, body, headers):
                calls["url"] = url
                calls["headers"] = headers
                return {"result": {"response": "READY"}}

            try:
                with mock.patch.dict(os.environ, {}, clear=False):
                    for name in ("NEXCUT_API_KEY", "CLOUDFLARE_API_TOKEN"):
                        os.environ.pop(name, None)
                    with mock.patch.object(check_key, "_post", fake_post), \
                         contextlib.redirect_stdout(buffer):
                        code = check_key.main(["check_key.py"])
            finally:
                check_key.ROOT = original
        return code, buffer.getvalue(), calls

    def test_cloudflare_token_is_found(self):
        code, out, calls = self.run_main(
            "NEXCUT_PROVIDER=cloudflare\n"
            "CLOUDFLARE_ACCOUNT_ID=acct\n"
            "CLOUDFLARE_API_TOKEN=cfat_abc\n"
            "NEXCUT_MODELS=@cf/meta/llama-3.3-70b-instruct-fp8-fast\n")
        self.assertEqual(code, 0, out)
        self.assertIn("READY", out)
        self.assertEqual(calls["headers"]["Authorization"], "Bearer cfat_abc")
        self.assertIn("/accounts/acct/ai/run/", calls["url"])

    def test_missing_key_lists_the_accepted_names(self):
        code, out, _ = self.run_main("NEXCUT_PROVIDER=gemini\n")
        self.assertEqual(code, 2)
        self.assertIn("CLOUDFLARE_API_TOKEN", out)
        self.assertIn("GROQ_API_KEY", out)


class CloudflareSpecTests(unittest.TestCase):
    def test_url_headers_and_result_shape(self):
        import os
        from unittest import mock
        env = {"NEXCUT_PROVIDER": "cloudflare", "NEXCUT_CF_ACCOUNT": "acct9"}
        with mock.patch.dict(os.environ, env, clear=False):
            url, body, extract, headers = check_key.request_spec(
                "@cf/meta/llama-3.3-70b-instruct-fp8-fast")
        self.assertIn("/accounts/acct9/ai/run/", url)
        self.assertEqual(headers("tok")["Authorization"], "Bearer tok")
        self.assertFalse(body["stream"])
        self.assertEqual(extract({"result": {"response": "READY"}}), "READY")
        self.assertIn("refused", extract({"success": False,
                                          "errors": [{"code": 7000, "message": "x"}]}))


class EnvDrivesResolution(unittest.TestCase):
    def test_dotenv_provider_makes_the_default_a_gemini_id(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            env = check_key.read_env(pathlib.Path(tmp) / "missing.env")
            env.update({"NEXCUT_PROVIDER": "gemini"})
            from unittest import mock
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("NEXCUT_MODELS", None)
                check_key.load_env(env)
                self.assertTrue(check_key.shipped_default_model().startswith("gemini-"))


if __name__ == "__main__":
    unittest.main()
