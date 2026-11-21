"""Every provider must accept the keywords the pipeline actually passes.

Regression this guards: `jobs.py` called `provider.complete(..., ctx={...})`
while `_HttpProvider.complete()` had no `ctx` parameter. The offline stub did
have it, and the whole suite runs on the stub, so 219 tests stayed green while
every real run (cloudflare / openai / gemini) died the moment the model was
asked — "complete() got an unexpected keyword argument 'ctx'".

Two guards, because either side can drift:
  1. the call site in `nexcut/jobs.py` (read with `ast`, not a copy-paste);
  2. the signature of every concrete provider class.
"""

from __future__ import annotations

import ast
import inspect
import json
import pathlib
import unittest
from unittest import mock

from nexcut import providers

JOBS = pathlib.Path(__file__).resolve().parent.parent / "nexcut" / "jobs.py"


def pipeline_kwargs() -> set[str]:
    """The keyword names jobs.py uses when it calls provider.complete(...)."""
    tree = ast.parse(JOBS.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "complete":
            return {kw.arg for kw in node.keywords if kw.arg}
    raise AssertionError("jobs.py no longer calls .complete() — update this test")


def provider_classes() -> list[type]:
    found = []
    for name, obj in vars(providers).items():
        if inspect.isclass(obj) and obj.__module__ == providers.__name__:
            if callable(getattr(obj, "complete", None)):
                found.append(obj)
    return sorted(found, key=lambda c: c.__name__)


class CallSite(unittest.TestCase):
    def test_pipeline_passes_a_known_set(self):
        kwargs = pipeline_kwargs()
        self.assertIn("system", kwargs)
        self.assertIn("user", kwargs)
        self.assertIn("ctx", kwargs)

    def test_every_provider_accepts_the_call_site(self):
        kwargs = pipeline_kwargs()
        self.assertGreaterEqual(len(provider_classes()), 4, "provider classes vanished")
        for cls in provider_classes():
            params = inspect.signature(cls.complete).parameters
            takes_anything = any(
                p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
            )
            if takes_anything:
                continue
            missing = {k for k in kwargs if k not in params}
            with self.subTest(provider=cls.__name__):
                self.assertFalse(
                    missing,
                    f"{cls.__name__}.complete() does not accept {sorted(missing)} — "
                    "jobs.py passes them unconditionally",
                )


class RealProviderRun(unittest.TestCase):
    """A non-stub provider must survive the exact call the pipeline makes."""

    def test_cloudflare_completes_with_ctx(self):
        provider = providers.CloudflareProvider("tok")
        answer = json.dumps({"clips": []})
        with mock.patch.object(provider, "_attempt", return_value=answer) as attempt:
            text, model = provider.complete(
                system="S", user="U", model="@cf/meta/llama-3.3-70b-instruct-fp8-fast",
                cascade=False, ctx={"transcript": "t", "window": "40-50"},
            )
        self.assertEqual(text, answer)
        self.assertTrue(model)
        # ctx is transport-irrelevant for HTTP providers: it must not leak into the request
        self.assertNotIn("ctx", attempt.call_args.kwargs)
        self.assertEqual(attempt.call_count, 1)

    def test_stub_still_uses_ctx(self):
        ctx = {"transcript": "00:00:05 - hello", "window": "40-50", "num_clips": 5}
        text, model = providers.StubProvider().complete(
            system="S", user="U", model="", cascade=False, ctx=ctx,
        )
        self.assertIn("clips", json.loads(text))
        self.assertEqual(model, "offline-demo")

    def test_stub_without_ctx_reports_missing_material(self):
        # ctx is the stub's only input; leaving it out must fail loudly, not crash
        with self.assertRaises(providers.ExtractError):
            providers.StubProvider().complete(
                system="S", user="U", model="", cascade=False,
            )


if __name__ == "__main__":
    unittest.main()
