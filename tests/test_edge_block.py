"""Cloudflare error 1010 is a client-signature ban, not a bad key — Groq's edge
does this to the stdlib's default User-Agent."""

from __future__ import annotations

import io
import os
import unittest
import urllib.error
from unittest import mock

from nexcut import providers


def http_error(code: int, body: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://example", code, "err", {}, io.BytesIO(body.encode()))


class UserAgentTests(unittest.TestCase):
    def test_default_is_not_python_urllib(self):
        with mock.patch.dict(os.environ, {"NEXCUT_USER_AGENT": ""}):
            self.assertIn("Mozilla/5.0", providers.user_agent())

    def test_env_overrides(self):
        with mock.patch.dict(os.environ, {"NEXCUT_USER_AGENT": "MyClient/2"}):
            self.assertEqual(providers.user_agent(), "MyClient/2")

    def test_header_is_sent(self):
        seen = {}

        def fake_urlopen(request, timeout=None):
            seen["ua"] = request.get_header("User-agent")
            seen["accept"] = request.get_header("Accept")
            raise http_error(400, "{}")

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            with self.assertRaises(providers.ProviderError):
                providers.GeminiProvider("k", timeout=5)._attempt("m", "s", "u", "k")
        self.assertIn("Mozilla/5.0", seen["ua"])
        self.assertEqual(seen["accept"], "application/json")


class EdgeBlockClassification(unittest.TestCase):
    def test_1010(self):
        self.assertTrue(providers.is_edge_block("error code: 1010"))

    def test_cloudflare_html(self):
        self.assertTrue(providers.is_edge_block("<html><body>Just a moment...</body></html>"))

    def test_a_real_auth_error_is_not_an_edge_block(self):
        self.assertFalse(providers.is_edge_block('{"error":{"message":"Invalid API Key"}}'))

    def test_403_edge_block_does_not_blame_the_key(self):
        with mock.patch.dict(os.environ, {"NEXCUT_PROVIDER": "groq"}), \
             mock.patch("urllib.request.urlopen",
                        side_effect=http_error(403, "error code: 1010")):
            with self.assertRaises(providers.ProviderError) as ctx:
                providers.GeminiProvider("k", timeout=5)._attempt("m", "s", "u", "k")
        self.assertIn("not your key", str(ctx.exception))
        self.assertNotIn("was rejected", str(ctx.exception))
        self.assertIn("NEXCUT_USER_AGENT", ctx.exception.hint)

    def test_403_auth_error_names_the_right_console(self):
        with mock.patch.dict(os.environ, {"NEXCUT_PROVIDER": "groq"}), \
             mock.patch("urllib.request.urlopen",
                        side_effect=http_error(403, '{"error":{"message":"Invalid API Key"}}')):
            with self.assertRaises(providers.ProviderError) as ctx:
                providers.GeminiProvider("k", timeout=5)._attempt("m", "s", "u", "k")
        self.assertIn("console.groq.com", ctx.exception.hint)


if __name__ == "__main__":
    unittest.main()
