"""A list of keys must be tried in order: one dead key should never end a run."""

from __future__ import annotations

import io
import os
import unittest
import urllib.error
from unittest import mock

from nexcut import providers


def http_error(code: int, body: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://example", code, "err", {}, io.BytesIO(body.encode()))


def ok_response(text: str = "READY"):
    class R:
        def read(self):
            return ('{"choices":[{"message":{"content":"' + text + '"}}]}').encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return R()


class Parsing(unittest.TestCase):
    def test_mixed_separators_and_dedupe(self):
        keys = providers.parse_keys("a b", "b,c", "c\nd")
        self.assertEqual(keys, ["a", "b", "c", "d"])  # deduped, order kept

    def test_quotes_and_blanks(self):
        self.assertEqual(providers.parse_keys(' "k1" , ', "\n 'k2'\n"), ["k1", "k2"])

    def test_env_keys_order_single_backup_rotation(self):
        env = {"NEXCUT_API_KEY": "first", "NEXCUT_BACKUP_KEY": "second",
               "NEXCUT_API_KEYS": "third,first"}
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertEqual(providers.env_keys(), ["first", "second", "third"])

    def test_provider_keys_read_env(self):
        with mock.patch.dict(os.environ, {"NEXCUT_PROVIDER": "openai",
                                          "NEXCUT_API_KEY": "k1",
                                          "NEXCUT_API_KEYS": "k2,k3"}, clear=False):
            p = providers.make_provider("")
            self.assertEqual(p.keys(), ["k1", "k2", "k3"])


class Rotation(unittest.TestCase):
    def provider(self, keys):
        p = providers.OpenAIProvider(keys[0], timeout=5)
        p.extra = keys
        with mock.patch.dict(os.environ, {"NEXCUT_API_KEYS": ",".join(keys[1:])}, clear=False):
            pass
        return p

    def test_moves_past_a_dead_key(self):
        seen = []

        def fake(request, timeout=None):
            auth = request.get_header("Authorization")
            seen.append(auth)
            if len(seen) == 1:
                raise http_error(401, '{"error":{"message":"Invalid API Key"}}')
            return ok_response()

        with mock.patch.dict(os.environ, {"NEXCUT_PROVIDER": "openai",
                                          "NEXCUT_API_KEY": "dead",
                                          "NEXCUT_API_KEYS": "alive",
                                          "NEXCUT_BACKUP_KEY": ""}, clear=False), \
             mock.patch("urllib.request.urlopen", fake):
            provider = providers.make_provider("")
            text, model = provider.complete(system="s", user="u", model="m", cascade=False)
        self.assertEqual(text, "READY")
        self.assertEqual(seen, ["Bearer dead", "Bearer alive"])
        self.assertEqual(provider.served_key, 2)

    def test_all_keys_dead_reports_counts_not_keys(self):
        def fake(request, timeout=None):
            raise http_error(401, '{"error":{"message":"Invalid API Key"}}')

        env = {"NEXCUT_PROVIDER": "openai", "NEXCUT_API_KEY": "sk-secret-one",
               "NEXCUT_API_KEYS": "sk-secret-two", "NEXCUT_BACKUP_KEY": ""}
        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch("urllib.request.urlopen", fake):
            provider = providers.make_provider("")
            with self.assertRaises(providers.ProviderError) as ctx:
                provider.complete(system="s", user="u", model="m", cascade=False)
        message = str(ctx.exception)
        self.assertIn("2 key(s)", message)
        self.assertIn("2 attempt(s)", message)
        self.assertNotIn("sk-secret", message)

    def test_budget_stops_a_long_dead_list(self):
        calls = []

        def fake(request, timeout=None):
            calls.append(request)
            raise http_error(401, '{"error":{"message":"Invalid API Key"}}')

        keys = ",".join(f"sk-{i}" for i in range(50))
        env = {"NEXCUT_PROVIDER": "openai", "NEXCUT_API_KEY": "sk-first",
               "NEXCUT_API_KEYS": keys, "NEXCUT_MAX_ATTEMPTS": "5",
               "NEXCUT_BACKUP_KEY": ""}
        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch("urllib.request.urlopen", fake):
            provider = providers.make_provider("")
            with self.assertRaises(providers.ProviderError):
                provider.complete(system="s", user="u", model="m", cascade=False)
        self.assertEqual(len(calls), 5)

    def test_budget_also_applies_to_the_health_check(self):
        from nexcut import server
        calls = []

        def fake(request, timeout=None):
            calls.append(request)
            raise http_error(401, '{"error":{"message":"Invalid API Key"}}')

        env = {"NEXCUT_PROVIDER": "openai", "NEXCUT_API_KEY": "sk-a",
               "NEXCUT_API_KEYS": ",".join(f"sk-{i}" for i in range(30)),
               "NEXCUT_MODELS": "m1", "NEXCUT_MODEL": ""}
        with mock.patch.dict(os.environ, env, clear=False), \
             mock.patch("urllib.request.urlopen", fake):
            code, body = server.key_status()
        self.assertEqual(code, 502)
        self.assertLessEqual(len(calls), 6)
        self.assertEqual(body["keys"], 31)


if __name__ == "__main__":
    unittest.main()
