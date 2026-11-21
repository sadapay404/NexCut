"""A model that answers in the wrong shape gets one repair attempt.

Regression this guards: cloudflare's llama answered `"longlist": 12` where a list
belongs, and the run died with "'int' object is not iterable" *after* the
captions had been fetched. Two layers now:

  * `parse.build_result` tolerates scalars wherever a list is expected, and
  * if the whole report is unusable, `jobs` re-asks once with a repair note.

Driven through a private JobManager so the module-level MANAGER (shared by the
HTTP tests) cannot interleave its jobs with ours.
"""

from __future__ import annotations

import json
import time
import unittest
from unittest import mock

from nexcut.jobs import JobManager
from nexcut.providers import CloudflareProvider, StubProvider

SAMPLE = """00:00:00 - Nobody talks about what happened on the third floor.
00:00:09 - The night manager logged the door as locked at 11:40.
00:00:17 - The camera shows it opening at 11:52.
00:00:26 - He told investigators he never left the desk.
00:00:34 - So who used his badge during the twelve minutes he cannot explain?
00:00:45 - A guest reported hearing two voices in an empty corridor.
00:00:54 - The badge reader logged a second entry at 12:04.
"""

PARAMS = {
    "transcript_text": SAMPLE,
    "niche": "True Crime",
    "window": "40-50",
    "num_clips": 5,
    "model": "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
    "cascade": False,
    "api_key": "",
}


def good_answer() -> str:
    return json.dumps(StubProvider()._compose(
        transcript=SAMPLE, window="40-50", num_clips=5))


class RepairPath(unittest.TestCase):
    def run_with(self, replies: list[str]):
        """Run one job against a provider that replays `replies` in order."""
        provider = CloudflareProvider("test-token")
        queue = list(replies)
        calls: list[str] = []

        def fake_attempt(model, system, user, key):
            provider.served_model = model
            calls.append("repair" if "your previous reply could not be used"
                         in user.lower() else "plain")
            return queue.pop(0) if queue else good_answer()

        with mock.patch.object(provider, "_attempt", side_effect=fake_attempt):
            manager = JobManager(lambda api_key: provider)
            job = manager.submit(dict(PARAMS))
            for _ in range(200):
                if job.status in ("done", "error"):
                    break
                time.sleep(0.01)
        return job, calls

    def test_count_instead_of_a_list_is_tolerated_without_a_second_call(self):
        answer = json.dumps({"sweep": {"longlist": 12}, "longlist": 12,
                             "clips": [json.loads(good_answer())["clips"][0]]})
        job, calls = self.run_with([answer])
        self.assertEqual(job.status, "done", job.error)
        # the scalar longlist is dropped, not fatal — and no repair was needed
        self.assertEqual(calls, ["plain"])

    def test_unusable_answer_triggers_one_repair(self):
        junk = json.dumps({"sweep": {"longlist": 3}, "longlist": 3, "clips": 3})
        job, calls = self.run_with([junk, good_answer()])
        self.assertEqual(job.status, "done", job.error)
        self.assertEqual(calls, ["plain", "repair"])
        self.assertTrue(any("malformed" in w.lower() for w in job.warnings), job.warnings)

    def test_repair_failing_twice_reports_the_format_error(self):
        junk = json.dumps({"sweep": {}, "longlist": 3, "clips": 3})
        job, calls = self.run_with([junk, junk])
        self.assertEqual(job.status, "error")
        self.assertIn("clip-report format", job.error)
        self.assertNotIn("TypeError", job.error)
        self.assertEqual(calls, ["plain", "repair"])

    def test_repair_is_not_attempted_twice(self):
        junk = "definitely not json"
        job, calls = self.run_with([junk, junk, junk, junk])
        self.assertEqual(job.status, "error")
        self.assertEqual(calls, ["plain", "repair"])


if __name__ == "__main__":
    unittest.main()
