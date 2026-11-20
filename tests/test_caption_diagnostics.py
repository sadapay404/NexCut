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
            mock.patch.object(ingest, "_via_watch_page", boom("consent page", "bot wall")),
            mock.patch.object(ingest, "_via_ytdlp", boom("yt-dlp failed", "Sign in to confirm")),
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
                       "transcript-api", "LOGIN_REQUIRED", "Sign in to confirm"):
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
