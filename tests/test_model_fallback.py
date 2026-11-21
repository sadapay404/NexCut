"""When the provider refuses a model id, ask it what it does serve.

Groq moved llama-3.3-70b-versatile (and llama-3.1-8b-instant) to Enterprise-only
plans without changing the id, so a working .env started returning
"model_not_found". Bumping model names in the source only postpones that; these
tests pin the behaviour that actually matters — the request recovers by itself,
and the user is never asked to edit .env to chase a rename.
"""

from __future__ import annotations

import io
import json
import os
import unittest
import urllib.error
from unittest import mock

from nexcut import providers

ENV = {"NEXCUT_PROVIDER": "groq", "GROQ_API_KEY": "gsk_test",
       "NEXCUT_MODELS": "", "NEXCUT_MODEL_MAP": ""}
GONE = "llama-3.3-70b-versatile"


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
    return urllib.error.HTTPError("https://api.groq.com", code, "err", {},
                                  io.BytesIO(body.encode()))


def served(*ids: str) -> dict:
    return {"data": [{"id": i, "object": "model"} for i in ids]}


NOT_FOUND = json.dumps({"error": {
    "message": f"The model `{GONE}` does not exist or you do not have access to it.",
    "type": "invalid_request_error", "code": "model_not_found"}})


class Router:
    """Stands in for urllib.request.urlopen, keyed by URL."""

    def __init__(self, *, models: dict | None = None, chat=None):
        self.models = models if models is not None else served(
            "whisper-large-v3", "openai/gpt-oss-120b", "openai/gpt-oss-20b")
        self.chat = chat or self.default_chat
        self.calls: list[tuple[str, dict | None]] = []

    @staticmethod
    def default_chat(body: dict):
        return respond({"choices": [{"message": {"content": '{"clips": []}'}}]})

    def __call__(self, request, timeout=None):
        url = request.full_url
        body = json.loads(request.data.decode()) if request.data else None
        self.calls.append((url, body))
        if url.endswith("/models"):
            if isinstance(self.models, Exception):
                raise self.models
            return respond(self.models)
        if body and body.get("model") == GONE:
            raise http_error(404, NOT_FOUND)
        return self.chat(body)

    def bodies(self) -> list[dict]:
        return [b for _, b in self.calls if b]

    def model_calls(self) -> list[str]:
        return [b.get("model") for b in self.bodies() if "messages" in b]


class Fallback(unittest.TestCase):
    def run_attempt(self, router: Router, model: str = GONE):
        with mock.patch.dict(os.environ, ENV, clear=False), \
                mock.patch("urllib.request.urlopen", router):
            provider = providers.OpenAIProvider("gsk_test", timeout=5)
            text = provider._attempt(model, "SYSTEM", "USER", "gsk_test")
        return text, provider

    def test_refused_model_switches_to_one_the_key_can_use(self):
        router = Router()
        text, provider = self.run_attempt(router)
        self.assertEqual(json.loads(text), {"clips": []})
        self.assertEqual(router.model_calls(), [GONE, "openai/gpt-oss-120b"])
        self.assertEqual(provider.served_model, "openai/gpt-oss-120b")

    def test_non_chat_models_are_never_picked(self):
        router = Router(models=served("whisper-large-v3", "openai/gpt-oss-20b"))
        _, provider = self.run_attempt(router)
        self.assertEqual(provider.served_model, "openai/gpt-oss-20b")

    def test_model_list_is_fetched_once_per_provider(self):
        router = Router()
        with mock.patch.dict(os.environ, ENV, clear=False), \
                mock.patch("urllib.request.urlopen", router):
            provider = providers.OpenAIProvider("gsk_test", timeout=5)
            provider._attempt(GONE, "S", "U", "k")
            provider._attempt(GONE, "S", "U", "k")
        self.assertEqual(len([u for u, _ in router.calls if u.endswith("/models")]), 1)

    def test_no_usable_model_surfaces_the_original_error(self):
        router = Router(models=served("whisper-large-v3"))
        with self.assertRaises(providers.ProviderError) as ctx:
            self.run_attempt(router)
        self.assertIn("was not found at this provider", str(ctx.exception))

    def test_discovery_failing_is_not_fatal(self):
        router = Router(models=http_error(500, "nope"))
        with self.assertRaises(providers.ProviderError) as ctx:
            self.run_attempt(router)
        self.assertIn("was not found at this provider", str(ctx.exception))

    def test_unknown_model_without_discovery_raises_cleanly(self):
        router = Router(models=urllib.error.URLError("offline"))
        with self.assertRaises(providers.ProviderError) as ctx:
            self.run_attempt(router)
        self.assertIn(GONE, str(ctx.exception))


class ParameterRenames(unittest.TestCase):
    """Providers disagree about max_tokens and response_format; retry, don't die."""

    def attempt_with(self, router: Router, model: str = "openai/gpt-oss-120b"):
        with mock.patch.dict(os.environ, ENV, clear=False), \
                mock.patch("urllib.request.urlopen", router):
            provider = providers.OpenAIProvider("k", timeout=5)
            return provider._attempt(model, "S", "U", "k"), provider

    def test_max_tokens_is_renamed_on_request(self):
        calls = {"n": 0}

        def chat(body):
            calls["n"] += 1
            if "max_tokens" in body:
                raise http_error(400, json.dumps({"error": {
                    "message": "Unsupported parameter: 'max_tokens'. Use "
                               "'max_completion_tokens' instead."}}))
            return respond({"choices": [{"message": {"content": "OK"}}]})

        router = Router(chat=chat)
        text, _ = self.attempt_with(router)
        self.assertEqual(text, "OK")
        self.assertEqual(calls["n"], 2)
        self.assertIn("max_completion_tokens", router.bodies()[-1])

    def test_response_format_is_dropped_when_rejected(self):
        def chat(body):
            if "response_format" in body:
                raise http_error(400, json.dumps({"error": {
                    "message": "response_format is not supported for this model"}}))
            return respond({"choices": [{"message": {"content": "OK"}}]})

        router = Router(chat=chat)
        text, _ = self.attempt_with(router)
        self.assertEqual(text, "OK")
        self.assertNotIn("response_format", router.bodies()[-1])
        self.assertEqual(len(router.bodies()), 2)

    def test_empty_content_is_an_error(self):
        router = Router(chat=lambda body: respond(
            {"choices": [{"message": {"content": ""}}]}))
        with self.assertRaises(providers.ProviderError):
            self.attempt_with(router)


if __name__ == "__main__":
    unittest.main()
