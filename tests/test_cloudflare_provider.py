"""Cloudflare Workers AI: account-scoped URL, bearer token, {result:{response}}."""

from __future__ import annotations

import io
import json
import os
import unittest
import urllib.error
from unittest import mock

from nexcut import providers


def respond(payload: dict):
    class R:
        def read(self):
            return json.dumps(payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return R()


def http_error(code: int, body: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://example", code, "err", {}, io.BytesIO(body.encode()))


ENV = {"NEXCUT_PROVIDER": "cloudflare", "NEXCUT_API_KEY": "tok",
       "NEXCUT_CF_ACCOUNT": "acct123", "NEXCUT_MODEL_MAP": ""}
MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"


class ProviderShape(unittest.TestCase):
    def test_kind_and_alias(self):
        for name in ("cloudflare", "workers-ai", "cf", "workersai"):
            with mock.patch.dict(os.environ, {"NEXCUT_PROVIDER": name}, clear=False):
                self.assertEqual(providers.provider_kind(), "cloudflare")

    def test_make_provider_returns_cloudflare(self):
        with mock.patch.dict(os.environ, ENV, clear=False):
            self.assertEqual(providers.make_provider("").name, "cloudflare")

    def test_catalogue_is_cloudflare_ids(self):
        with mock.patch.dict(os.environ, {**ENV, "NEXCUT_MODELS": ""}, clear=False):
            ids = [m["id"] for m in providers.model_catalog()]
        self.assertTrue(all(i.startswith("@cf/") for i in ids))

    def test_account_env_aliases(self):
        with mock.patch.dict(os.environ,
                             {"NEXCUT_CF_ACCOUNT": "", "CLOUDFLARE_ACCOUNT_ID": "from-cf"},
                             clear=False):
            self.assertEqual(providers.cloudflare_account(), "from-cf")


class RequestShape(unittest.TestCase):
    def attempt(self, payload):
        seen = {}

        def fake(request, timeout=None):
            seen["url"] = request.full_url
            seen["auth"] = request.get_header("Authorization")
            seen["body"] = json.loads(request.data.decode())
            return respond(payload)

        with mock.patch.dict(os.environ, ENV, clear=False), \
             mock.patch("urllib.request.urlopen", fake):
            provider = providers.CloudflareProvider("tok", timeout=5)
            text = provider._attempt(MODEL, "SYSTEM", "USER", "tok")
        return text, seen

    def test_url_account_scoped_and_bearer(self):
        text, seen = self.attempt({"success": True, "result": {"response": "READY"}})
        self.assertEqual(text, "READY")
        self.assertIn("/accounts/acct123/ai/run/", seen["url"])
        self.assertIn(MODEL, seen["url"])
        self.assertEqual(seen["auth"], "Bearer tok")

    def test_messages_shape(self):
        _, seen = self.attempt({"result": {"response": "ok"}})
        self.assertEqual(seen["body"]["messages"][0], {"role": "system", "content": "SYSTEM"})
        self.assertEqual(seen["body"]["messages"][1], {"role": "user", "content": "USER"})
        self.assertFalse(seen["body"]["stream"])

    def test_max_tokens_is_sent_explicitly(self):
        """Workers AI defaults max_tokens to 256 — a report never fits, and the
        answer comes back cut off in the middle of the JSON."""
        _, seen = self.attempt({"result": {"response": "ok"}})
        self.assertEqual(seen["body"]["max_tokens"], 4096)

    def test_max_tokens_is_configurable(self):
        with mock.patch.dict(os.environ, {"NEXCUT_MAX_TOKENS": "6000"}, clear=False):
            _, seen = self.attempt({"result": {"response": "ok"}})
        self.assertEqual(seen["body"]["max_tokens"], 6000)

    def test_bad_max_tokens_falls_back_to_the_default(self):
        with mock.patch.dict(os.environ, {"NEXCUT_MAX_TOKENS": "lots"}, clear=False):
            _, seen = self.attempt({"result": {"response": "ok"}})
        self.assertEqual(seen["body"]["max_tokens"], 4096)

    def test_choices_result_is_accepted_too(self):
        text, _ = self.attempt({"result": {"choices": [{"message": {"content": "HI"}}]}})
        self.assertEqual(text, "HI")

    def test_missing_account_says_what_to_set(self):
        with mock.patch.dict(os.environ,
                             {"NEXCUT_CF_ACCOUNT": "", "CLOUDFLARE_ACCOUNT_ID": ""}, clear=False):
            provider = providers.CloudflareProvider("tok", timeout=5)
            with self.assertRaises(providers.ProviderError) as ctx:
                provider._attempt(MODEL, "s", "u", "tok")
        self.assertIn("NEXCUT_CF_ACCOUNT", ctx.exception.hint)

    def test_success_false_surfaces_the_error_code(self):
        with mock.patch.dict(os.environ, ENV, clear=False):
            provider = providers.CloudflareProvider("tok", timeout=5)
            with mock.patch("urllib.request.urlopen", lambda r, timeout=None: respond(
                    {"success": False, "errors": [{"code": 7000, "message": "No such model"}]})):
                with self.assertRaises(providers.ProviderError) as ctx:
                    provider._attempt(MODEL, "s", "u", "tok")
        self.assertIn("7000", str(ctx.exception))
        self.assertIn("No such model", str(ctx.exception))

    def test_empty_text_is_an_error_not_an_empty_prompt(self):
        with mock.patch.dict(os.environ, ENV, clear=False):
            provider = providers.CloudflareProvider("tok", timeout=5)
            with mock.patch("urllib.request.urlopen",
                            lambda r, timeout=None: respond({"result": {}})):
                with self.assertRaises(providers.ProviderError) as ctx:
                    provider._attempt(MODEL, "s", "u", "tok")
        self.assertIn("--list", ctx.exception.hint)

    def test_403_is_a_dead_key_so_rotation_moves_on(self):
        with mock.patch.dict(os.environ, ENV, clear=False), \
             mock.patch("urllib.request.urlopen",
                        side_effect=http_error(403, '{"success":false}')):
            provider = providers.CloudflareProvider("tok", timeout=5)
            with self.assertRaises(providers.ProviderError) as ctx:
                provider._attempt(MODEL, "s", "u", "tok")
        self.assertTrue(ctx.exception.key_dead)


if __name__ == "__main__":
    unittest.main()
