"""`/api/health/key` and the Gemini auth header — the two things that decide
whether a pasted AI Studio key works before a real run is attempted."""

from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from nexcut import providers, server


def fake_response(payload):
    class _R:
        def read(self):
            return json.dumps(payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return _R()


class GeminiHeaderTests(unittest.TestCase):
    def test_key_goes_in_query_and_header(self):
        seen = {}

        def fake_post(self, url, body, headers, **kw):
            seen["url"] = url
            seen["headers"] = headers
            return {"candidates": [{"content": {"parts": [{"text": "READY"}]}}]}

        provider = providers.GeminiProvider("AQ.test-key", timeout=5)
        with mock.patch.object(providers._HttpProvider, "_post", fake_post):
            text = provider._attempt("gemini-2.5-flash", "sys", "hi", "AQ.test-key")
        self.assertEqual(text, "READY")
        self.assertIn("key=AQ.test-key", seen["url"])
        self.assertEqual(seen["headers"].get("x-goog-api-key"), "AQ.test-key")

    def test_model_map_is_applied_to_the_url(self):
        seen = {}
        with mock.patch.dict(os.environ, {"NEXCUT_MODEL_MAP": '{"flash":"gemini-2.5-flash"}'}):
            provider = providers.GeminiProvider("k", timeout=5)
            with mock.patch.object(providers._HttpProvider, "_post",
                                   lambda self, url, body, headers, **kw: seen.setdefault("url", url)
                                   and {"candidates": [{"content": {"parts": [{"text": "x"}]}}]}):
                provider._attempt("flash", "s", "u", "k")
        self.assertIn("models/gemini-2.5-flash:generateContent", seen["url"])


class KeyCheckRouteTests(unittest.TestCase):
    def test_stub_short_circuits(self):
        with mock.patch.dict(os.environ, {"NEXCUT_PROVIDER": "stub"}):
            code, body = server.key_status()
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["provider"], "stub")

    def test_ok_path_reports_model_and_latency(self):
        class Fake:
            name = "gemini"

            def complete(self, **kw):
                self.kw = kw
                return "READY", "gemini-2.5-flash"

        fake = Fake()
        with mock.patch("nexcut.providers.make_provider", return_value=fake):
            code, body = server.key_status()
        self.assertEqual(code, 200)
        self.assertEqual(body["model"], "gemini-2.5-flash")
        self.assertEqual(body["reply"], "READY")
        self.assertIn("ms", body)
        self.assertFalse(fake.kw["cascade"])

    def test_rejected_key_is_a_502_with_the_provider_message(self):
        class Fake:
            name = "gemini"

            def complete(self, **kw):
                raise providers.ProviderError("That API key was rejected.")

        with mock.patch("nexcut.providers.make_provider", return_value=Fake()):
            code, body = server.key_status()
        self.assertEqual(code, 502)
        self.assertFalse(body["ok"])
        self.assertIn("rejected", body["detail"])
        self.assertIn("restart the server", body["hint"])

    def test_models_env_decides_which_model_is_tested(self):
        seen = {}

        class Fake:
            name = "gemini"

            def complete(self, **kw):
                seen.update(kw)
                return "READY", kw["model"]

        env = {"NEXCUT_MODELS": "gemini-2.5-pro,gemini-2.5-flash", "NEXCUT_MODEL": ""}
        with mock.patch.dict(os.environ, env), \
             mock.patch("nexcut.providers.make_provider", return_value=Fake()):
            code, body = server.key_status()
        self.assertEqual(code, 200)
        self.assertEqual(seen["model"], "gemini-2.5-pro")
        self.assertEqual(body["model"], "gemini-2.5-pro")

    def test_route_exists(self):
        with open(server.__file__, encoding="utf-8") as fh:
            self.assertIn("/api/health/key", fh.read())


if __name__ == "__main__":
    unittest.main()
