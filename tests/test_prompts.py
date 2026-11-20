"""Prompt templating: your master prompt drives the run, not our code."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from nexcut import prompts as P

TRANSCRIPT = "00:00:08 - The door was locked.\n00:00:20 - It opened anyway."


class TestRender(unittest.TestCase):
    def test_substitutes_known_tokens(self):
        out, unknown = P.render("Niche: {{niche}} / {{num_clips}}", {"niche": "Sports", "num_clips": 4})
        self.assertEqual(out, "Niche: Sports / 4")
        self.assertEqual(unknown, [])

    def test_reports_unknown_tokens_and_keeps_them(self):
        out, unknown = P.render("{{nope}} and {{niche}}", {"niche": "Finance"})
        self.assertIn("{{nope}}", out)
        self.assertEqual(unknown, ["nope"])

    def test_multiline_transcript_injected(self):
        ctx = P.context(transcript=TRANSCRIPT, niche="True Crime — Cult")
        out, _ = P.render("T:\n{{transcript}}", ctx)
        self.assertIn("00:00:20 - It opened anyway.", out)

    def test_niche_split(self):
        ctx = P.context(transcript="x", niche="True Crime — Cult")
        self.assertEqual(ctx["niche_base"], "True Crime")
        self.assertEqual(ctx["subniche"], "Cult")

    def test_niche_without_sub(self):
        ctx = P.context(transcript="x", niche="Sports")
        self.assertEqual(ctx["subniche"], "")

    def test_window_bounds_from_config(self):
        ctx = P.context(transcript="x", window="C")
        self.assertEqual((ctx["window_min"], ctx["window_max"]), (90, 180))

    def test_custom_window_overrides(self):
        ctx = P.context(transcript="x", window="E", custom_min=40, custom_max=75)
        self.assertEqual((ctx["window_min"], ctx["window_max"]), (40, 75))


class TestCompose(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = P.PROMPT_DIR
        P.PROMPT_DIR = Path(self.tmp.name)

    def tearDown(self):
        P.PROMPT_DIR = self._old
        self.tmp.cleanup()

    def test_builtin_when_no_master(self):
        system, user, warnings = P.compose(transcript=TRANSCRIPT, niche="Sports")
        self.assertIn("short-form video editor", system)
        self.assertIn("## JOB", user)  # built-in prompt heading
        self.assertTrue(any("master.md not found" in w for w in warnings))

    def test_master_file_is_used_and_contract_appended(self):
        (Path(self.tmp.name) / "master.md").write_text(
            "MY PROMPT for {{niche}} at {{audience}}.\n{{transcript}}"
        )
        system, user, warnings = P.compose(
            transcript=TRANSCRIPT, niche="Finance — Crypto", audience="UK English"
        )
        self.assertIn("MY PROMPT for Finance — Crypto at UK English.", user)
        self.assertIn("MACHINE CONTRACT", user)
        self.assertEqual(warnings, [])

    def test_contract_not_duplicated_when_master_mentions_json(self):
        (Path(self.tmp.name) / "master.md").write_text("Return JSON like this. {{transcript}}")
        _system, user, _w = P.compose(transcript=TRANSCRIPT)
        self.assertNotIn("MACHINE CONTRACT", user)

    def test_contract_forced_by_env(self):
        import os
        (Path(self.tmp.name) / "master.md").write_text("Return JSON. {{transcript}}")
        os.environ["NEXCUT_APPEND_CONTRACT"] = "1"
        try:
            _system, user, _w = P.compose(transcript=TRANSCRIPT)
        finally:
            os.environ.pop("NEXCUT_APPEND_CONTRACT", None)
        self.assertIn("MACHINE CONTRACT", user)

    def test_system_file_overrides_default(self):
        (Path(self.tmp.name) / "system.md").write_text("You are a strict editor.")
        (Path(self.tmp.name) / "master.md").write_text("{{transcript}}")
        system, _user, _w = P.compose(transcript=TRANSCRIPT)
        self.assertEqual(system, "You are a strict editor.")

    def test_unknown_placeholder_becomes_warning(self):
        (Path(self.tmp.name) / "master.md").write_text("{{typo_here}} {{transcript}}")
        _system, user, warnings = P.compose(transcript=TRANSCRIPT)
        self.assertIn("{{typo_here}}", user)
        self.assertTrue(any("typo_here" in w for w in warnings))


if __name__ == "__main__":
    unittest.main()
