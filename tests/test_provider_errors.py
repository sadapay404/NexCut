"""Every HTTP failure path must name the model, not explode in a NameError."""

from __future__ import annotations

import io
import os
import unittest
import urllib.error
from unittest import mock

from nexcut import providers


def http_error(code: int, body: str = '{"error":{"message":"nope"}}') -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://example", code, "err", {},
                                  io.BytesIO(body.encode()))


class PostErrorPaths(unittest.TestCase):
    def provider(self) -> providers.GeminiProvider:
        return providers.GeminiProvider("k", timeout=5)

    def attempt_with(self, err, model="gemini-2.5-flash"):
        with mock.patch("urllib.request.urlopen", side_effect=err):
            return self.provider()._attempt(model, "s", "u", "k")

    def test_429_names_the_model_and_is_retryable(self):
        with self.assertRaises(providers.ProviderError) as ctx:
            self.attempt_with(http_error(429), model="gemini-2.5-pro")
        self.assertIn("gemini-2.5-pro", str(ctx.exception))
        self.assertTrue(ctx.exception.retryable)

    def test_503_names_the_model_and_is_retryable(self):
        with self.assertRaises(providers.ProviderError) as ctx:
            self.attempt_with(http_error(503))
        self.assertIn("gemini-2.5-flash", str(ctx.exception))
        self.assertTrue(ctx.exception.retryable)

    def test_403_is_a_key_problem_not_a_model_problem(self):
        with self.assertRaises(providers.ProviderError) as ctx:
            self.attempt_with(http_error(403))
        self.assertIn("key was rejected", str(ctx.exception))
        self.assertFalse(ctx.exception.retryable)

    def test_404_points_at_nexcut_models(self):
        with self.assertRaises(providers.ProviderError) as ctx:
            self.attempt_with(http_error(404))
        self.assertIn("NEXCUT_MODELS", ctx.exception.hint)

    def test_400_surfaces_the_provider_body(self):
        with self.assertRaises(providers.ProviderError) as ctx:
            self.attempt_with(http_error(400, '{"error":{"message":"API key not valid"}}'))
        self.assertIn("API key not valid", str(ctx.exception))

    def test_bad_model_name_gets_a_list_hint(self):
        with mock.patch("urllib.request.urlopen", side_effect=http_error(
            400, '{"error":{"message":"* GenerateContentRequest.model: unexpected model name format"}}')
        ):
            with self.assertRaises(providers.ProviderError) as ctx:
                providers.GeminiProvider("k", timeout=5)._attempt("x", "s", "u", "k")
        self.assertIn("--list", ctx.exception.hint)

    def test_every_path_raises_provider_error_not_nameerror(self):
        for code in (400, 401, 403, 404, 429, 500, 502, 503, 504):
            with self.subTest(code=code):
                with self.assertRaises(providers.ProviderError):
                    self.attempt_with(http_error(code))


class HealthCheckReportsRealErrors(unittest.TestCase):
    def test_5xx_message_reaches_the_health_check(self):
        from nexcut import server

        class Fake:
            name = "gemini"

            def complete(self, **kw):
                raise providers.ProviderError("gemini-2.5-flash was unavailable (HTTP 503).",
                                              retryable=True)

        env = {"NEXCUT_PROVIDER": "gemini", "NEXCUT_MODELS": "gemini-3.8-flash",
               "NEXCUT_MODEL": ""}
        with mock.patch.dict(os.environ, env), \
             mock.patch("nexcut.providers.make_provider", return_value=Fake()):
            code, body = server.key_status()
        self.assertEqual(code, 502)
        self.assertIn("503", body["detail"])


if __name__ == "__main__":
    unittest.main()
