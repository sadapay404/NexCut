"""The shipped master prompt must render, resolve every placeholder, and keep the
machine contract appended (so the parser and the rule gate keep working).

Run: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import unittest
from pathlib import Path

from nexcut.prompts import PROMPT_DIR, compose, context, master_exists

TRANSCRIPT = "00:00:08 - The door was locked at 11:40.\n00:00:17 - It opened at 11:52."


class MasterPromptFileTests(unittest.TestCase):
    def test_master_prompt_ships_with_the_repo(self):
        self.assertTrue(master_exists(), "prompts/master.md is missing")

    def test_master_does_not_trigger_the_contract_switch(self):
        # compose() only appends the machine contract when the master never says "json"
        text = (Path(PROMPT_DIR) / "master.md").read_text(encoding="utf-8")
        self.assertNotIn("json", text.lower())

    def test_broll_prompt_ships_too(self):
        self.assertTrue((Path(PROMPT_DIR) / "broll.md").is_file())

    def test_every_placeholder_resolves(self):
        system, user, warnings = compose(
            transcript=TRANSCRIPT, niche="True Crime", window="E",
            num_clips=5, channel_show="Show", episode_title="Episode", video_id="abc123",
            ranges_text="00:00:00-00:01:00",
        )
        self.assertEqual(warnings, [])
        self.assertNotIn("{{", user)
        self.assertIn("MACHINE CONTRACT", user)          # contract appended
        self.assertIn("The door was locked at 11:40.", user)   # transcript injected
        self.assertTrue(system.strip())


class AutoModeTests(unittest.TestCase):
    def test_zero_clips_renders_auto(self):
        ctx = context(transcript=TRANSCRIPT, num_clips=0)
        self.assertIn("AUTO", str(ctx["num_clips"]))

    def test_blank_clips_is_auto(self):
        self.assertIn("AUTO", str(context(transcript=TRANSCRIPT, num_clips=0)["num_clips"]))

    def test_explicit_count_is_kept(self):
        self.assertEqual(context(transcript=TRANSCRIPT, num_clips=7)["num_clips"], 7)

    def test_niche_auto_asks_the_model_to_detect(self):
        ctx = context(transcript=TRANSCRIPT, niche="auto")
        self.assertIn("detect", str(ctx["niche"]).lower())
        self.assertIn("AUTO", str(ctx["niche"]).upper())

    def test_auto_run_prompt_says_auto(self):
        _, user, warnings = compose(transcript=TRANSCRIPT, niche="auto", num_clips=0)
        self.assertEqual(warnings, [])
        self.assertIn("AUTO — decide with Step 0", user)
        self.assertIn("detect it from the transcript", user)

    def test_window_bounds_reach_the_prompt(self):
        _, user, _ = compose(transcript=TRANSCRIPT, window="A", num_clips=4)
        self.assertIn("30", user)
        self.assertIn("60", user)


if __name__ == "__main__":
    unittest.main()
