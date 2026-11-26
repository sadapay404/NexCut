"""Ingestion: caption parsing, consolidation, id extraction (stdlib only)."""

from __future__ import annotations

import unittest

from nexcut.ingest import (
    IngestError,
    _pick_track,
    consolidate,
    fetch_transcript,
    parse_json3,
    parse_vtt,
    to_text,
    video_id,
)

VTT = """WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:03.120
The night manager logged the door

00:00:03.120 --> 00:00:06.480
as locked at eleven forty.

00:00:06.480 --> 00:00:09.000
The camera shows it opening later.
"""

VTT_ROLLING = """WEBVTT

00:00:01.000 --> 00:00:04.000
<v Host>So the door was locked</v>

00:00:01.000 --> 00:00:05.000
<v Host>So the door was locked</v>

00:00:05.000 --> 00:00:08.000
and nobody knew why.
"""

JSON3 = (b'{"events":[{"tStartMs":0,"segs":[{"utf8":"hello "},{"utf8":"world"}]},'
         b'{"tStartMs":2500,"segs":[{"utf8":"second line here"}]},'
         b'{"tStartMs":3000}]}')


class TestIds(unittest.TestCase):
    def test_watch_url(self):
        self.assertEqual(video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ"), "dQw4w9WgXcQ")

    def test_short_url_with_params(self):
        self.assertEqual(video_id("https://youtu.be/dQw4w9WgXcQ?t=42"), "dQw4w9WgXcQ")

    def test_shorts_and_live(self):
        self.assertEqual(video_id("https://youtube.com/shorts/abcdefghijk"), "abcdefghijk")
        self.assertEqual(video_id("https://youtube.com/live/abcdefghijk"), "abcdefghijk")

    def test_bare_id(self):
        self.assertEqual(video_id("dQw4w9WgXcQ"), "dQw4w9WgXcQ")

    def test_garbage(self):
        self.assertEqual(video_id("not a link"), "")
        self.assertEqual(video_id(""), "")


class TestVtt(unittest.TestCase):
    def test_parses_cues_with_seconds(self):
        lines = parse_vtt(VTT)
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0][0], 0.0)
        self.assertIn("night manager", lines[0][1])
        self.assertAlmostEqual(lines[2][0], 6.48, places=2)

    def test_strips_markup_and_entities(self):
        lines = parse_vtt(VTT_ROLLING)
        self.assertNotIn("<v", lines[0][1])
        self.assertIn("door was locked", lines[0][1])

    def test_collapses_rolling_duplicates(self):
        lines = parse_vtt(VTT_ROLLING)
        bodies = [b for _s, b in lines]
        self.assertEqual(len(bodies), len(set(bodies)))

    def test_srt_comma_decimals(self):
        srt = "1\n00:00:05,500 --> 00:00:08,000\nhello there\n"
        lines = parse_vtt(srt)
        self.assertAlmostEqual(lines[0][0], 5.5, places=2)

    def test_empty_input(self):
        self.assertEqual(parse_vtt(""), [])


class TestJson3(unittest.TestCase):
    def test_parses_events(self):
        lines = parse_json3(JSON3)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0][1], "hello world")
        self.assertAlmostEqual(lines[1][0], 2.5)

    def test_bad_json_is_empty(self):
        self.assertEqual(parse_json3(b"not json"), [])


class TestConsolidate(unittest.TestCase):
    def test_merges_until_sentence_end(self):
        cues = [(0, "the door was"), (2, "locked at eleven"), (4, "forty that night.")]
        merged = consolidate(cues)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0][0], 0)
        self.assertIn("locked at eleven", merged[0][1])

    def test_merges_until_word_target(self):
        cues = [(i, f"word{i}") for i in range(10)]
        merged = consolidate(cues, target_words=5)
        self.assertGreater(len(merged), 1)
        self.assertTrue(all(len(t.split()) >= 4 for _s, t in merged[:-1]))

    def test_keeps_first_stamp(self):
        merged = consolidate([(12, "a"), (14, "b"), (16, "c.")])
        self.assertEqual(merged[0][0], 12)

    def test_trailing_buffer_emitted(self):
        merged = consolidate([(0, "no terminal punctuation")])
        self.assertEqual(len(merged), 1)

    def test_to_text_format(self):
        text = to_text([(0, "first"), (63, "second")])
        self.assertEqual(text.splitlines()[0], "00:00:00 - first")
        self.assertEqual(text.splitlines()[1], "00:01:03 - second")


class TestTrackChoice(unittest.TestCase):
    def test_prefers_manual_english(self):
        tracks = [
            {"languageCode": "hi", "kind": ""},
            {"languageCode": "en", "kind": "asr"},
            {"languageCode": "en", "kind": ""},
        ]
        self.assertEqual(_pick_track(tracks)["kind"], "")

    def test_falls_back_to_any(self):
        self.assertEqual(_pick_track([{"languageCode": "de", "kind": ""}])["languageCode"], "de")

    def test_empty(self):
        self.assertIsNone(_pick_track([]))


class TestFetchGuards(unittest.TestCase):
    def test_bad_link_message_is_actionable(self):
        with self.assertRaises(IngestError) as ctx:
            fetch_transcript("https://example.com/not-a-video")
        self.assertIn("YouTube link", str(ctx.exception))
        self.assertTrue(ctx.exception.hint)


if __name__ == "__main__":
    unittest.main()
