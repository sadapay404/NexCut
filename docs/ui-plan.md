# UI plan — v7

## What the user rejected, and the fix

| Complaint | Cause | Fix |
|---|---|---|
| "Same link, same key. Video or audio, at the quality you pick." | a tagline I wrote on the Downloader tab | deleted; the tab now shows only the heading, the disabled bar, the format pills and one factual line |
| "demo provider · built-in prompt · cutting unavailable" in the card corner | three status pills carried over from the cockpit design | deleted. The corner now shows `v0.1.0`. Missing ffmpeg is reported in the export strip, where it stops you, not as chrome |
| "Don't ask for API key — it comes from .env" | the key field was in Options | field, Show/Hide and Remember are gone. The server reads `NEXCUT_API_KEY` (payload key still wins if one is ever sent) |
| "Results were unreadable, everything cluttered" | 6-column table of 11.5px text + a 342px rail with 16 tiny label/value rows | results rebuilt: 4-column table with a 13px hook line, a 404px detail rail grouped into 7 titled sections, and a full-width cut strip |

## Results screen, in detail

**Table** — `#`, `Clip`, `Length`, `Score`. The clip cell carries the range in mono
(`00:00:08 → 00:01:03`) above the hook in 13px body text, so each row is one thing
to read, not six. Rows are 54px tall; five clips fit a 600px frame, longer lists
scroll under a sticky header.

**Detail rail** — header (`Clip n`, range, `Open` → the moment on YouTube, score
badge), then titled sections, each omitted when empty:

1. Timing — In / Out / Length as three cells
2. Scores — one bar per dimension with the number
3. Titles — clickbait, search, debate, each copyable
4. Dialogue — the opening and closing line, quoted
5. Why it works — reason, share trigger, verbal hook
6. On screen — overlays, sfx, captions
7. Post — upload text, hashtags, pinned comment, safety

Body text is 12.5px with 1.55 line-height; labels are 9px caps, used once per
section instead of once per row.

**Cut strip** — full width under both panes: `Cut` label, quality select, `Cut MP4s`,
a progress track that appears only while cutting, the state line, and the produced
files as chips with a `save` link.

## Composition (unchanged from v6)

Wordmark · `Cutter / Downloader` tabs · one framed card · `Side A — Link intake`
corner label with the live state word (`Link intake` → `Working` → `Clips`) ·
hero heading with one italic gold word · one link bar with `Extract` inside ·
`Options` `Transcript` `Sample` `History` drawers · credits line.

At 1366 × 600: top bar 52, credits 30, card 496 tall, results body 315 → 5 table
rows, detail rail scrolls, cut strip 47.

## Verified

| Check | Result |
|---|---|
| `node tools/ui_smoke.js` | 27 assertions pass — boot, drawers, tab switch, captions, run, 4-column rows, 7 detail sections, 4 score bars, clip link, cut, files, back to landing |
| `python3 -m unittest discover -s tests` | 93 pass |
| id / class / CSS audit | 94 ids, no duplicates, every JS id exists, every class has a rule, braces balanced |
| `curl` on `/`, CSS, JS | 200, `no-cache`, `?v=8` |

Pixels remain unverified here: no browser in the sandbox (Playwright's download is
blocked, and a bundled Chromium needs `libnss3`, which this image lacks and cannot
install without root).

## Next

1. Multi-clip cutting: per-clip button in the detail rail, queue, ZIP of all cuts.
2. Sort/filter on the table (score, length) once lists exceed one screen.
3. Downloader tab: video / audio, quality from `/api/video-quality`, same queue.
4. Real run with an env key: confirm the MP4 starts on the requested frame.
