"""Pasted credentials should work under the providers' own variable names."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from nexcut import providers

CLEAR = {name: "" for name in
         ("NEXCUT_API_KEY", "NEXCUT_BACKUP_KEY", "NEXCUT_API_KEYS",
          "CLOUDFLARE_API_TOKEN", "GEMINI_API_KEY", "GOOGLE_API_KEY",
          "GROQ_API_KEY", "OPENAI_API_KEY")}


class NativeVariables(unittest.TestCase):
    def check(self, provider_name: str, var: str, value: str) -> None:
        env = {**CLEAR, "NEXCUT_PROVIDER": provider_name, var: value}
        with mock.patch.dict(os.environ, env, clear=False):
            keys = providers.env_keys()
            made = providers.make_provider("")
        self.assertIn(value, keys)
        self.assertEqual(made.api_key, value, f"{provider_name} ignored {var}")

    def test_cloudflare_token(self):
        self.check("cloudflare", "CLOUDFLARE_API_TOKEN", "cfat_x")

    def test_cloudflare_alias(self):
        self.check("workers-ai", "CLOUDFLARE_API_TOKEN", "cfat_y")

    def test_groq(self):
        self.check("groq", "GROQ_API_KEY", "gsk_x")

    def test_openai(self):
        self.check("openai", "OPENAI_API_KEY", "sk-x")

    def test_gemini(self):
        self.check("gemini", "GEMINI_API_KEY", "AQ.x")

    def test_google_alias(self):
        self.check("gemini", "GOOGLE_API_KEY", "AIza-x")

    def test_nexcut_api_key_still_wins(self):
        env = {**CLEAR, "NEXCUT_PROVIDER": "cloudflare",
               "NEXCUT_API_KEY": "explicit", "CLOUDFLARE_API_TOKEN": "native"}
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertEqual(providers.make_provider("").api_key, "explicit")
            self.assertEqual(providers.env_keys()[0], "explicit")

    def test_explicit_argument_wins_over_everything(self):
        env = {**CLEAR, "NEXCUT_PROVIDER": "cloudflare", "NEXCUT_API_KEY": "env"}
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertEqual(providers.make_provider("arg").api_key, "arg")

    def test_account_id_native_name(self):
        env = {**CLEAR, "NEXCUT_CF_ACCOUNT": "", "CLOUDFLARE_ACCOUNT_ID": "abc123"}
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertEqual(providers.cloudflare_account(), "abc123")


if __name__ == "__main__":
    unittest.main()
