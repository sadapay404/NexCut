"""Google retires model ids for accounts that never used them. A 404 that names a
replacement must retry once with it — this is what a fresh AI Studio key hits."""

from __future__ import annotations

import io
import json
import os
import unittest
import urllib.error
from unittest import mock

from nexcut import providers


GOOGLE_404 = json.dumps({"error": {
    "code": 404,
    "message": "This model models/gemini-2.5-flash is no longer available to new "
               "users. Please update your code to use models/gemini-3.8-flash for the "
               "latest features and improvements.",
    "status": "NOT_FOUND",
}})


def http_error(code: int, body: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://example", code, "err", {}, io.BytesIO(body.encode()))


def ok_response(text: str = "READY"):
    class _R:
        status = 200

        def read(self):
            return json.dumps({"candidates": [{"content": {"parts": [{"text": text}]}}]}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return _R()


class SuggestionParsing(unittest.TestCase):
    def test_real_google_message(self):
        self.assertEqual(providers._suggested_model(GOOGLE_404), "gemini-3.8-flash")

    def test_no_suggestion_means_empty(self):
        self.assertEqual(providers._suggested_model("API key not valid"), "")

    def test_catalog_leads_with_the_newest_id(self):
        self.assertEqual(providers.GEMINI_MODELS[0], "gemini-3.8-flash")

    def test_default_model_follows_nexcut_models(self):
        with mock.patch.dict(os.environ, {"NEXCUT_MODELS": "custom-1,custom-2",
                                          "NEXCUT_MODEL": ""}):
            self.assertEqual(providers.default_model(), "custom-1")

    def test_nexcut_model_wins(self):
        with mock.patch.dict(os.environ, {"NEXCUT_MODELS": "custom-1",
                                          "NEXCUT_MODEL": "explicit-9"}):
            self.assertEqual(providers.default_model(), "explicit-9")


class RetiredModelRetry(unittest.TestCase):
    def test_retries_once_with_the_named_model(self):
        calls = []

        def fake(request, timeout=None):
            calls.append(request.full_url)
            if len(calls) == 1:
                raise http_error(404, GOOGLE_404)
            return ok_response()

        provider = providers.GeminiProvider("AQ.key", timeout=5)
        with mock.patch("urllib.request.urlopen", fake):
            text = provider._attempt("gemini-2.5-flash", "s", "u", "AQ.key")
        self.assertEqual(text, "READY")
        self.assertEqual(len(calls), 2)
        self.assertIn("gemini-3.8-flash", calls[1])
        self.assertEqual(provider.served_model, "gemini-3.8-flash")

    def test_complete_reports_the_model_that_answered(self):
        calls = []

        def fake(request, timeout=None):
            calls.append(request.full_url)
            if len(calls) == 1:
                raise http_error(404, GOOGLE_404)
            return ok_response()

        provider = providers.GeminiProvider("AQ.key", timeout=5)
        with mock.patch("urllib.request.urlopen", fake):
            text, used = provider.complete(system="s", user="u",
                                           model="gemini-2.5-flash", cascade=False)
        self.assertEqual(text, "READY")
        self.assertEqual(used, "gemini-3.8-flash")

    def test_404_without_a_suggestion_still_raises(self):
        provider = providers.GeminiProvider("AQ.key", timeout=5)
        with mock.patch("urllib.request.urlopen",
                        side_effect=http_error(404, '{"error":{"message":"nope"}}')):
            with self.assertRaises(providers.ProviderError):
                provider._attempt("gemini-2.5-flash", "s", "u", "AQ.key")

    def test_only_one_retry(self):
        calls = []

        def fake(request, timeout=None):
            calls.append(request.full_url)
            raise http_error(404, GOOGLE_404.replace("gemini-3.8-flash", "gemini-4.0-flash"))

        provider = providers.GeminiProvider("AQ.key", timeout=5)
        with mock.patch("urllib.request.urlopen", fake):
            with self.assertRaises(providers.ProviderError):
                provider._attempt("gemini-2.5-flash", "s", "u", "AQ.key")
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
