"""A caption failure must keep the reason, not collapse it to one sentence."""

from __future__ import annotations

import unittest
from unittest import mock

from nexcut import ingest


def boom(message: str, hint: str):
    def _raise(vid, language):
        raise ingest.IngestError(message, hint)
    return _raise


class Aggregation(unittest.TestCase):
    def test_every_strategy_and_its_hint_survives(self):
        patchers = [
            mock.patch.object(ingest, "_via_innertube",
                              boom("no identity", "android-vr: LOGIN_REQUIRED")),
            mock.patch.object(ingest, "_via_timedtext", boom("nothing", "en: empty")),
            mock.patch.object(ingest, "_via_watch_page", boom("consent page", "no player response")),
            mock.patch.object(ingest, "_via_ytdlp", boom("yt-dlp failed", "no caption file")),
            mock.patch.object(ingest, "_via_transcript_api", boom("not installed", "pip install")),
        ]
        for patcher in patchers:
            patcher.start()
        try:
            with self.assertRaises(ingest.IngestError) as ctx:
                ingest.fetch_transcript("https://youtu.be/abcdefghijk", use_cache=False)
        finally:
            for patcher in patchers:
                patcher.stop()
        hint = ctx.exception.hint
        for needle in ("innertube", "timedtext", "watch-page", "yt-dlp",
                       "transcript-api", "LOGIN_REQUIRED"):
            self.assertIn(needle, hint)

    def test_a_broken_strategy_does_not_hide_the_others(self):
        with mock.patch.object(ingest, "_via_innertube", side_effect=RuntimeError("boom")), \
             mock.patch.object(ingest, "_via_timedtext",
                               lambda vid, lang: ingest.Transcript(
                                   text="00:00:01 - hello", lines=[(1.0, "hello")],
                                   source="timedtext-unsigned", video_id=vid)), \
             mock.patch.object(ingest, "fetch_metadata",
                               return_value={"title": "t", "channel": "c"}):
            tr = ingest.fetch_transcript("https://youtu.be/abcdefghijk", use_cache=False)
        self.assertEqual(tr.source, "timedtext-unsigned")

    def test_metadata_failure_keeps_the_transcript(self):
        with mock.patch.object(ingest, "_via_innertube",
                               lambda vid, lang: ingest.Transcript(
                                   text="00:00:01 - hi", lines=[(1.0, "hi")],
                                   source="innertube:android-vr", video_id=vid,
                                   title="from player")), \
             mock.patch.object(ingest, "fetch_metadata",
                               side_effect=ingest.IngestError("watch page blocked")):
            tr = ingest.fetch_transcript("https://youtu.be/abcdefghijk", use_cache=False)
        self.assertEqual(tr.title, "from player")


class IpBlock(unittest.TestCase):
    def test_three_walls_out_of_five_is_a_network_block(self):
        errors = ["innertube: LOGIN_REQUIRED — Sign in to confirm you're not a bot",
                  "timedtext: empty", "watch-page: no track",
                  "yt-dlp: ERROR: Sign in to confirm you're not a bot",
                  "transcript-api: not installed"]
        self.assertTrue(ingest.looks_like_ip_block(errors))

    def test_one_mention_is_not_a_block(self):
        self.assertFalse(ingest.looks_like_ip_block(
            ["innertube: LOGIN_REQUIRED", "timedtext: empty",
             "watch-page: no track", "yt-dlp: no caption file", "api: missing"]))

    def test_unavailable_video_is_not_a_network_block(self):
        self.assertFalse(ingest.looks_like_ip_block(
            ["innertube: ERROR — This video is unavailable",
             "timedtext: empty", "watch-page: no track",
             "yt-dlp: ERROR: Private video", "api: missing"]))

    def test_empty_is_not_a_block(self):
        self.assertFalse(ingest.looks_like_ip_block([]))

    def test_pipeline_raises_the_network_message_not_a_wall_of_text(self):
        wall = boom("walled", "LOGIN_REQUIRED — Sign in to confirm you're not a bot")
        patchers = [mock.patch.object(ingest, name, wall) for name in
                    ("_via_innertube", "_via_timedtext", "_via_watch_page",
                     "_via_ytdlp", "_via_transcript_api")]
        for patcher in patchers:
            patcher.start()
        try:
            with self.assertRaises(ingest.IngestError) as ctx:
                ingest.fetch_transcript("https://youtu.be/abcdefghijk", use_cache=False)
        finally:
            for patcher in patchers:
                patcher.stop()
        self.assertIn("blocking this machine's IP", str(ctx.exception))
        for needle in ("own computer", "cookies.txt", "paste the transcript"):
            self.assertIn(needle, ctx.exception.hint)


class Inspection(unittest.TestCase):
    def test_report_covers_every_client(self):
        blocked = {"playabilityStatus": {"status": "LOGIN_REQUIRED",
                                         "reason": "Sign in to confirm"}}
        with mock.patch.object(ingest, "_post_json", lambda *a, **kw: blocked):
            rows = ingest.inspect_innertube("abcdefghijk")
        self.assertEqual(len(rows), len(ingest.INNERTUBE_CLIENTS))
        for row in rows:
            self.assertEqual(row["status"], "LOGIN_REQUIRED")
            self.assertEqual(row["tracks"], 0)
            self.assertIn("Sign in", row["reason"])

    def test_report_counts_lines_when_a_track_works(self):
        player = {
            "playabilityStatus": {"status": "OK"},
            "captions": {"playerCaptionsTracklistRenderer": {"captionTracks": [
                {"baseUrl": "https://x/timedtext?v=a&lang=en", "languageCode": "en"}]}},
        }
        body = b'{"events":[{"tStartMs":0,"segs":[{"utf8":"hello there"}]}]}'
        with mock.patch.object(ingest, "_post_json", lambda *a, **kw: player), \
             mock.patch.object(ingest, "_get", lambda url, **kw: body):
            rows = ingest.inspect_innertube("abcdefghijk")
        self.assertEqual(rows[0]["lines"], 1)
        self.assertEqual(rows[0]["format"], "json3")


if __name__ == "__main__":
    unittest.main()
