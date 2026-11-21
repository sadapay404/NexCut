"""Behavioural tests for the clean-room pipeline (stdlib unittest, no deps).

Run: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import unittest

from nexcut.parse import (
    FormatError,
    NoTimestampsError,
    build_result,
    ensure_timestamps,
    extract_json,
    parse_stamp,
)
from nexcut.prompt import build_prompt, format_ranges, plan_sweep, slice_transcript
from nexcut.schema import Clip, OracleResult, Scores, hms
from nexcut.validate import apply_rules, check_clip, normalize_transcript

TRANSCRIPT = """00:00:00 - Nobody talks about what happened that night in the Miller house.
00:00:08 - The detective arrived at midnight and the porch light was still on.
00:00:16 - He knocked three times before anyone answered the door.
00:00:24 - What he found inside changed the entire investigation.
00:00:33 - The phone records told a completely different story.
00:00:42 - Why did the neighbor lie about hearing the car?
00:00:51 - She had no reason to protect him, or did she?
00:01:00 - The alibi collapsed in under four minutes of questioning.
00:01:09 - And that is when everything changed for the whole family.
"""

GOOD_CLIP = {
    "n": 1,
    "hook_summary": "Detective arrives, house is wrong",
    "start_sec": 8,
    "start_stamp": "00:00:08",
    "start_sentence": "The detective arrived at midnight and the porch light was still on.",
    "end_sec": 63,
    "end_stamp": "00:01:03",
    "end_sentence": "The alibi collapsed in under four minutes of questioning.",
    "duration_line": "55 seconds",
    "titles": {"clickbait": "The porch light was still on", "search": "miller house case", "debate": "did the neighbor lie?"},
    "scores": {"curiosity": 9, "stakes": 8, "specificity": 9, "speed": 8, "avg": 8.5},
    "verbal_hook": "the porch light was still on",
    "ending": "open loop",
    "why_it_works": "concrete detail plus unresolved question",
    "share_trigger": "theory bait",
    "safety": "none",
    "overlays": [{"offset": "00:02", "text": "porch light on"}],
    "sfx": "low drone",
    "captions": "bold yellow",
    "upload_caption": "nobody talks about this",
    "hashtags": "#truecrime #coldcase",
    "pinned_comment": "who lied?",
    "transcript_ts": "00:00:08 - The detective arrived at midnight.",
    "transcript": "The detective arrived at midnight.",
}

PAYLOAD = {
    "sweep": {"window": "E", "ranges": "00:00:00-00:09:00", "longlist": 4, "cleared": 1},
    "longlist": [{"start": "00:00:08", "gist": "detective at the door"}],
    "clips": [GOOD_CLIP],
}


def result_from(clip: dict) -> OracleResult:
    return build_result(json.dumps({"clips": [clip], "longlist": [], "sweep": {}}))


class TestMalformedShapes(unittest.TestCase):
    """Models answer with scalars where lists belong — never a TypeError.

    Regression: cloudflare's llama answered `"longlist": 12` and the whole run
    died with "'int' object is not iterable" *after* the captions were fetched.
    """

    def answer(self, payload: dict) -> OracleResult:
        return build_result(json.dumps(payload))

    def test_longlist_as_count(self):
        res = self.answer({"longlist": 12, "clips": [GOOD_CLIP],
                           "sweep": {"longlist": 12, "cleared": 4}})
        self.assertEqual(len(res.clips), 1)
        self.assertEqual(res.longlist, [])
        self.assertEqual(res.sweep.longlist, 12)

    def test_scores_as_scalar(self):
        res = self.answer({"clips": [dict(GOOD_CLIP, scores=9)], "longlist": []})
        self.assertIsNone(res.clips[0].scores.curiosity)

    def test_overlays_as_scalar(self):
        res = self.answer({"clips": [dict(GOOD_CLIP, overlays=3)], "longlist": []})
        self.assertEqual(res.clips[0].overlays, [])

    def test_titles_as_string(self):
        res = self.answer({"clips": [dict(GOOD_CLIP, titles="one title")], "longlist": []})
        self.assertEqual(res.clips[0].titles, {})

    def test_swing_sweep_as_list(self):
        res = self.answer({"sweep": [1, 2], "clips": [GOOD_CLIP], "longlist": []})
        self.assertEqual(len(res.clips), 1)

    def test_single_clip_object_is_wrapped(self):
        res = self.answer({"clips": GOOD_CLIP, "longlist": []})
        self.assertEqual(len(res.clips), 1)
        self.assertEqual(res.clips[0].start_sec, 8)

    def test_clip_count_instead_of_clips_is_a_format_error(self):
        with self.assertRaises(FormatError) as ctx:
            self.answer({"clips": 5, "longlist": []})
        self.assertIn("clips came back as int", str(ctx.exception))

    def test_missing_clips_key_is_a_format_error(self):
        with self.assertRaises(FormatError) as ctx:
            self.answer({"longlist": []})
        self.assertIn("no clips key", str(ctx.exception))

    def test_list_of_strings_is_a_format_error(self):
        with self.assertRaises(FormatError):
            self.answer({"clips": ["clip one", "clip two"], "longlist": []})


class TestParsing(unittest.TestCase):
    def test_parses_fenced_json(self):
        answer = "Here you go:\n```json\n" + json.dumps(PAYLOAD) + "\n```\n"
        res = build_result(answer)
        self.assertEqual(len(res.clips), 1)
        self.assertEqual(res.clips[0].start_sec, 8)
        self.assertEqual(res.clips[0].scores.avg, 8.5)

    def test_tolerates_prose_around_bare_json(self):
        answer = "Sure! " + json.dumps(PAYLOAD) + " Hope that helps."
        self.assertEqual(extract_json(answer)["sweep"]["longlist"], 4)

    def test_format_error_message_matches_contract(self):
        with self.assertRaises(Exception) as ctx:
            build_result("I could not find any good clips, sorry.")
        self.assertIn("not in the clip-report format", str(ctx.exception))

    def test_no_timestamps_preflight(self):
        with self.assertRaises(NoTimestampsError) as ctx:
            ensure_timestamps("just a wall of text with no stamps at all")
        self.assertIn("NO TIMESTAMPS", str(ctx.exception))

    def test_bracketed_and_short_stamps(self):
        self.assertEqual(parse_stamp("00:01:03"), 63)
        self.assertEqual(parse_stamp("01:03"), 63)
        self.assertEqual(parse_stamp("junk"), None)
        ensure_timestamps("[00:12:30] fine")

    def test_missing_seconds_falls_back_to_stamp(self):
        clip = dict(GOOD_CLIP)
        clip.pop("start_sec")
        clip.pop("end_sec")
        res = result_from(clip)
        self.assertEqual(res.clips[0].start_sec, 8)
        self.assertEqual(res.clips[0].duration_sec, 55)


class TestRuleGate(unittest.TestCase):
    def setUp(self):
        self.norm = normalize_transcript(TRANSCRIPT)

    def test_good_clip_passes(self):
        self.assertIsNone(check_clip(result_from(GOOD_CLIP).clips[0], self.norm, window="E"))

    def test_paraphrase_is_caught(self):
        clip = dict(GOOD_CLIP, start_sentence="The detective showed up at midnight.")
        reason = check_clip(result_from(clip).clips[0], self.norm, window="E")
        self.assertIn("not verbatim", reason)

    def test_duration_outside_window(self):
        clip = dict(GOOD_CLIP, end_sec=20, end_stamp="00:00:20", end_sentence="He knocked three times before anyone answered the door.")
        reason = check_clip(result_from(clip).clips[0], self.norm, window="E")
        self.assertIn("outside window", reason)

    def test_arithmetic_lock(self):
        clip = dict(GOOD_CLIP, duration_line="90 seconds")
        reason = check_clip(result_from(clip).clips[0], self.norm, window="E")
        self.assertIn("arithmetic lock", reason)

    def test_stamp_field_mismatch(self):
        # duration_line is kept consistent with the (wrong) numeric fields so the
        # arithmetic lock passes and the stamp/field agreement rule is reached.
        clip = dict(GOOD_CLIP, start_sec=0, duration_line="63 seconds")
        reason = check_clip(result_from(clip).clips[0], self.norm, window="E")
        self.assertIn("timestamp mismatch", reason)

    def test_three_second_gate_blocks_housekeeping(self):
        clip = dict(GOOD_CLIP, start_sentence="Welcome back to the channel everybody")
        reason = check_clip(result_from(clip).clips[0], self.norm, window="E")
        self.assertTrue("3-second gate" in reason or "not verbatim" in reason)

    def test_quality_gate(self):
        clip = dict(GOOD_CLIP, scores={"curiosity": 6, "stakes": 6, "specificity": 6, "speed": 6})
        reason = check_clip(result_from(clip).clips[0], self.norm, window="E")
        self.assertIn("below the 8.0 quality gate", reason)

    def test_apply_rules_renumbers_and_counts(self):
        weak = dict(GOOD_CLIP, n=2, scores={"curiosity": 5, "stakes": 5, "specificity": 5, "speed": 5})
        res = build_result(json.dumps({"clips": [weak, GOOD_CLIP], "longlist": [{"start": "00:00:08", "gist": None}]}))
        out = apply_rules(res, TRANSCRIPT, window="E")
        self.assertEqual(len(out.clips), 1)
        self.assertEqual(out.clips[0].n, 1)
        self.assertEqual(len(out.dropped), 1)
        self.assertEqual(out.sweep.cleared, 2)
        self.assertIn("8.0", out.dropped[0].reason)

    def test_top_n_limit_drops_overflow(self):
        res = build_result(json.dumps({"clips": [GOOD_CLIP, dict(GOOD_CLIP, n=2)]}))
        out = apply_rules(res, TRANSCRIPT, window="E", limit=1)
        self.assertEqual(len(out.clips), 1)
        self.assertIn("ranked below the top 1", out.dropped[0].reason)

    def test_serialised_clip_carries_both_numeric_ends(self):
        """Guards a real bug: end_sec was serialised away, silently breaking cutting."""
        out = apply_rules(result_from(GOOD_CLIP), TRANSCRIPT, window="E").to_dict()
        clip = out["clips"][0]
        self.assertEqual(clip["start_sec"], 8)
        self.assertEqual(clip["end_sec"], 63)
        self.assertEqual(clip["end_sec"] - clip["start_sec"], 55)

    def test_serializes_to_reference_shape(self):
        out = apply_rules(result_from(GOOD_CLIP), TRANSCRIPT, window="E")
        d = out.to_dict()
        for key in ("sweep", "longlist", "clips", "dropped", "oracle_report", "video_id", "video_title", "window_label"):
            self.assertIn(key, d)
        self.assertEqual(d["clips"][0]["duration_str"], "00:00:55")
        self.assertEqual(set(d["clips"][0]["scores"]), {"curiosity", "stakes", "specificity", "speed", "avg"})


class TestSweepAndPrompt(unittest.TestCase):
    def test_single_window_for_short_transcript(self):
        self.assertEqual(plan_sweep(TRANSCRIPT), [(0, 69)])

    def test_overlapping_chunks_cover_long_transcript(self):
        long_ts = "\n".join(f"00:{m:02d}:00 - line {m}" for m in range(0, 40))
        ranges = plan_sweep(long_ts, chunk_sec=600, overlap_sec=30)
        self.assertGreater(len(ranges), 1)
        self.assertEqual(ranges[0][0], 0)
        self.assertEqual(ranges[-1][1], 39 * 60)
        # consecutive chunks must overlap, never leave a gap
        for (a1, b1), (a2, _b2) in zip(ranges, ranges[1:]):
            self.assertLess(a2, b1)
        self.assertIn("-", format_ranges(ranges))

    def test_chunk_slicing_is_bounded(self):
        long_ts = "\n".join(f"00:{m:02d}:00 - line {m}" for m in range(0, 40))
        body = slice_transcript(long_ts, 0, 60)
        self.assertEqual(len(body.splitlines()), 2)

    def test_prompt_carries_context_and_rules(self):
        system, user = build_prompt(
            transcript=TRANSCRIPT, niche="True Crime — Cult", audience="U.S. English",
            language="U.S. English", window="A", num_clips=3, channel_show="Smosh Pit",
        )
        self.assertIn("short-form video editor", system)
        self.assertIn("True Crime — Cult", user)
        self.assertIn("30-60s", user)
        self.assertIn("Smosh Pit", user)
        self.assertIn("THREE-SECOND GATE", user)
        self.assertIn("8.0", user)
        self.assertIn("00:00:08", user)

    def test_prompt_chunk_limits_transcript(self):
        long_ts = "\n".join(f"00:{m:02d}:00 - line {m}" for m in range(0, 40))
        _, user = build_prompt(
            transcript=long_ts, niche="Sports", audience="U.S. English",
            language="U.S. English", chunk=(0, 120),
        )
        self.assertIn("line 1", user)
        self.assertNotIn("line 30", user)

    def test_hms(self):
        self.assertEqual(hms(63), "00:01:03")
        self.assertEqual(hms(3725), "01:02:05")
        self.assertEqual(Clip(n=1, start_sec=8, end_sec=63).duration_str, "00:00:55")


if __name__ == "__main__":
    unittest.main()
