#!/usr/bin/env python3
"""Why did caption fetching fail? Ask every strategy and every client identity.

    python3 tools/caption_probe.py <url-or-id> [<url-or-id> ...]

Prints, per client identity: playability status, caption-track count, how many
lines the signed track returned. Then each whole strategy with its own reason.
Run it on a video that definitely has captions (a TED talk, any news clip) next
to the one that fails — that separates "this video has none" from "we are blocked".
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nexcut import ingest  # noqa: E402

STRATEGIES = (
    ("timedtext-unsigned", ingest._via_timedtext),
    ("watch-page", ingest._via_watch_page),
    ("yt-dlp", ingest._via_ytdlp),
    ("transcript-api", ingest._via_transcript_api),
)


def probe(target: str) -> None:
    vid = ingest.video_id(target)
    print(f"\n=== {target}")
    if not vid:
        print("  not a YouTube link or id")
        return
    print(f"  video id {vid}")
    cookies = ingest.cookie_path()
    print(f"  cookies.txt {'found: ' + cookies if cookies else 'not found'}")

    print("\n  client identities (innertube /player)")
    rows = ingest.inspect_innertube(vid)
    width = max(len(r["client"]) for r in rows)
    for row in rows:
        verdict = row["error"] or (
            f"{row['status']}"
            + (f" — {row['reason']}" if row["reason"] else "")
            + f" · tracks={row['tracks']} lines={row['lines']}"
            + (f" ({row['format']})" if row["format"] else ""))
        print(f"    {row['client']:<{width}}  {verdict}")

    print("\n  whole strategies")
    for name, fn in STRATEGIES:
        try:
            tr = fn(vid, "en")
        except ingest.IngestError as exc:
            print(f"    {name:<18} FAIL  {exc}" + (f"\n       └ {exc.hint}" if exc.hint else ""))
        except Exception as exc:  # noqa: BLE001 - the point is to see everything
            print(f"    {name:<18} ERROR {type(exc).__name__}: {exc}")
        else:
            print(f"    {name:<18} OK    {len(tr.lines)} lines via {tr.source}, "
                  f"lang={tr.language or '?'}")
            print(f"       first: {tr.lines[0][1][:70] if tr.lines else '(none)'}")

    print("\n  full pipeline")
    try:
        tr = ingest.fetch_transcript(f"https://www.youtube.com/watch?v={vid}", use_cache=False)
    except ingest.IngestError as exc:
        print(f"    FAIL {exc}\n    {exc.hint}")
    else:
        print(f"    OK   {len(tr.lines)} lines, source={tr.source}, "
              f"{tr.title!r} / {tr.channel!r}")


def main(argv: list[str]) -> int:
    targets = argv[1:] or []
    if not targets:
        print(__doc__)
        return 2
    for target in targets:
        probe(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
