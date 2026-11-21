"""details.md must carry every packaging field the master prompt asks for."""

from __future__ import annotations

import unittest

from nexcut.report import run_markdown

PAYLOAD = {
    "video_title": "The Third Floor",
    "video_id": "dQw4w9WgXcQ",
    "channel": "Cold Case Files",
    "transcript_source": "youtube-captions",
    "model_used": "offline-demo",
    "ranges_planned": "00:00:00-00:09:00",
    "sweep": {"longlist": 6},
    "clips": [{
        "n": 1, "hook_summary": "door logged locked",
        "start_stamp": "00:00:08", "end_stamp": "00:01:03",
        "duration_str": "00:00:55", "duration_line": "0 min 55 sec",
        "start_sentence": "The detective arrived at midnight.",
        "end_sentence": "The alibi collapsed.",
        "ending": "Cliffhanger",
        "scores": {"curiosity": 9, "stakes": 8, "specificity": 9, "speed": 8, "avg": 8.5},
        "titles": {"clickbait": "HE PRESSED IT 💀", "search": "Who used his badge?",
                   "debate": "Accident… or murder? 😳"},
        "verbal_hook": "vh", "upload_caption": "uc", "hashtags": "#a #b",
        "pinned_comment": "pc", "why_it_works": "why", "share_trigger": "st",
    }],
    "dropped": [{"clip": 2, "reason": "average score 6.0 is below the 8.0 quality gate"}],
}


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.md = run_markdown(PAYLOAD, requested=5)

    def test_header_and_counts(self):
        self.assertTrue(self.md.startswith("# The Third Floor"))
        self.assertIn("https://youtu.be/dQw4w9WgXcQ", self.md)
        self.assertIn("**Clips delivered:** 1 of 5 requested", self.md)

    def test_every_packaging_field_is_written(self):
        for needle in ("HE PRESSED IT 💀", "Who used his badge?", "Accident… or murder? 😳",
                       "**Hashtags:** #a #b", "**Upload caption:** uc", "**Pinned comment:** pc",
                       "**Ending type:** Cliffhanger", "**Verbal hook:** vh"):
            self.assertIn(needle, self.md)

    def test_rejections_are_listed(self):
        self.assertIn("## Rejected candidates", self.md)
        self.assertIn("quality gate", self.md)

    def test_missing_fields_are_skipped_not_printed_empty(self):
        md = run_markdown({"clips": [{"n": 1, "start_stamp": "00:00:01"}]})
        self.assertNotIn("**Hashtags:**", md)
        self.assertIn("## Clip 1", md)


if __name__ == "__main__":
    unittest.main()
