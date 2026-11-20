"""Captions must survive a bot-walled watch page: the player API, then timedtext."""

from __future__ import annotations

import json
import unittest
from unittest import mock

from nexcut import ingest

PLAYER_WITH_TRACKS = {
    "playabilityStatus": {"status": "OK"},
    "videoDetails": {"title": "Real title", "author": "Real channel"},
    "captions": {"playerCaptionsTracklistRenderer": {"captionTracks": [
        {"baseUrl": "https://www.youtube.com/api/timedtext?v=abc&lang=en",
         "languageCode": "en", "kind": "asr"},
    ]}},
}
PLAYER_NO_TRACKS = {
    "playabilityStatus": {"status": "LOGIN_REQUIRED", "reason": "Sign in to confirm"},
}
JSON3 = json.dumps({"events": [
    {"tStartMs": 0, "segs": [{"utf8": "This is the first sentence of the video, spoken slowly."}]},
    {"tStartMs": 9000, "segs": [{"utf8": "And here is the second one, also complete."}]},
]}).encode()
XML = (b'<?xml version="1.0"?><transcript>'
       b'<text start="1.5" dur="2">hello &amp; welcome</text>'
       b'<text start="4.0" dur="2">second cue</text></transcript>')


class ParseTests(unittest.TestCase):
    def test_timedtext_xml(self):
        lines = ingest.parse_timedtext_xml(XML)
        self.assertEqual(lines[0], (1.5, "hello & welcome"))
        self.assertEqual(lines[1][0], 4.0)

    def test_captions_from_player(self):
        self.assertEqual(len(ingest._captions_from_player(PLAYER_WITH_TRACKS)), 1)
        self.assertEqual(ingest._captions_from_player(PLAYER_NO_TRACKS), [])


class InnertubeStrategy(unittest.TestCase):
    def test_uses_the_player_api_and_returns_sentences(self):
        calls = []

        def fake_post(url, payload, **kw):
            calls.append(payload["context"]["client"]["clientName"])
            return PLAYER_WITH_TRACKS

        with mock.patch.object(ingest, "_post_json", fake_post), \
             mock.patch.object(ingest, "_get", lambda url, **kw: JSON3):
            tr = ingest._via_innertube("abc", "en")
        self.assertEqual(tr.source, "innertube")
        self.assertIn("00:00:00 - This is the first sentence", tr.text)
        self.assertEqual(tr.title, "Real title")
        self.assertEqual(tr.channel, "Real channel")
        self.assertEqual(calls, ["ANDROID"])

    def test_falls_through_clients_when_blocked(self):
        clients = []

        def fake_post(url, payload, **kw):
            clients.append(payload["context"]["client"]["clientName"])
            return PLAYER_NO_TRACKS if len(clients) < 3 else PLAYER_WITH_TRACKS

        with mock.patch.object(ingest, "_post_json", fake_post), \
             mock.patch.object(ingest, "_get", lambda url, **kw: JSON3):
            tr = ingest._via_innertube("abc", "en")
        self.assertEqual(clients, ["ANDROID", "IOS", "TVHTML5_SIMPLY_EMBEDDED_PLAYER"])
        self.assertTrue(tr.lines)

    def test_every_client_blocked_reports_each_reason(self):
        with mock.patch.object(ingest, "_post_json",
                               lambda *a, **kw: PLAYER_NO_TRACKS):
            with self.assertRaises(ingest.IngestError) as ctx:
                ingest._via_innertube("abc", "en")
        self.assertIn("ANDROID", ctx.exception.hint)
        self.assertIn("LOGIN_REQUIRED", ctx.exception.hint)

    def test_empty_track_is_not_a_success(self):
        with mock.patch.object(ingest, "_post_json", lambda *a, **kw: PLAYER_WITH_TRACKS), \
             mock.patch.object(ingest, "_get", lambda url, **kw: b""):
            with self.assertRaises(ingest.IngestError):
                ingest._via_innertube("abc", "en")


class TimedtextStrategy(unittest.TestCase):
    def test_parses_legacy_xml(self):
        with mock.patch.object(ingest, "_get", lambda url, **kw: XML):
            tr = ingest._via_timedtext("abc", "en")
        self.assertEqual(tr.source, "timedtext")
        self.assertIn("hello & welcome", tr.text)

    def test_empty_response_is_an_error(self):
        with mock.patch.object(ingest, "_get", lambda url, **kw: b""):
            with self.assertRaises(ingest.IngestError):
                ingest._via_timedtext("abc", "en")


class YtdlpDiagnosis(unittest.TestCase):
    def test_bot_check_text_reaches_the_user(self):
        done = mock.Mock(returncode=1, stderr=b"ERROR: Sign in to confirm you're not a bot",
                         stdout=b"")
        with mock.patch.object(ingest.shutil, "which", return_value="/usr/bin/yt-dlp"), \
             mock.patch.object(ingest.subprocess, "run", return_value=done):
            with self.assertRaises(ingest.IngestError) as ctx:
                ingest._via_ytdlp("abc", "en")
        self.assertIn("Sign in to confirm", ctx.exception.hint)


class Ordering(unittest.TestCase):
    def test_innertube_is_tried_first(self):
        calls = []

        def fake(vid, language):
            calls.append("innertube")
            raise ingest.IngestError("nope", "")

        with mock.patch.object(ingest, "_via_innertube", fake), \
             mock.patch.object(ingest, "_via_watch_page",
                               lambda v, l: calls.append("watch") or (_ for _ in ()).throw(
                                   ingest.IngestError("nope", ""))), \
             mock.patch.object(ingest, "_via_ytdlp",
                               lambda v, l: calls.append("ytdlp") or (_ for _ in ()).throw(
                                   ingest.IngestError("nope", ""))), \
             mock.patch.object(ingest, "_via_timedtext",
                               lambda v, l: calls.append("timedtext") or (_ for _ in ()).throw(
                                   ingest.IngestError("nope", ""))), \
             mock.patch.object(ingest, "_via_transcript_api",
                               lambda v, l: calls.append("api") or (_ for _ in ()).throw(
                                   ingest.IngestError("nope", ""))), \
             mock.patch.object(ingest, "fetch_metadata", lambda v: {"title": "t", "channel": "c"}):
            with self.assertRaises(ingest.IngestError):
                ingest.fetch_transcript("https://youtu.be/abcdefghijk", use_cache=False)
        self.assertEqual(calls[0], "innertube")
        self.assertEqual(calls, ["innertube", "watch", "ytdlp", "timedtext", "api"])


if __name__ == "__main__":
    unittest.main()
