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

## Robustness pass — 2026-11-20

A device-agnostic audit of the v9 studio, driven by `node tools/ui_audit.js`
(static) plus the jsdom smoke flow (behavioural). Layout is still unverified in
pixels — jsdom has no layout engine — so every rule below is a measured CSS
constraint, not a screenshot.

Found and fixed:

| Symptom | Cause | Fix |
|---|---|---|
| bottom of the card unreachable on short laptops | `body { overflow: hidden }` with the frame at `100vh` and no escape | below `560px` tall the page scrolls (`height:auto`, `grid-template-rows: … auto`); 600px keeps the fixed frame so the design target is unchanged |
| frame clipped under mobile browser toolbars | `100vh` is taller than the visible area on iOS/Android | `min-height: 100dvh` alongside the `vh` fallback, plus `env(safe-area-inset-*)` padding |
| copy buttons dead on a LAN address | `navigator.clipboard` is `undefined` outside a secure context | `copy()` falls back to a hidden `<textarea>` + `execCommand`, and the smoke test deletes `navigator.clipboard` to prove it |
| 27px tap targets, hover-only styling | no `pointer: coarse` rules | 36–40px targets, `:active` feedback, `touch-action: manipulation` |
| rows and the config panel overflowed on phones | desktop grid columns only | breakpoints at 1024 / 720 / 520 / 380 (single-column details, `.clip-row` becomes a flex stack, `.seg` wraps 2×2, labels unstick from fixed px) |
| no visible focus for keyboard users | `input:focus-visible` was reset to none with no replacement | one `:focus-visible` ring on every interactive element |
| link bar mangled by phone keyboards | `type=text` with OS autocorrect | `type=url`, `inputmode=url`, `autocomplete=off`, `autocapitalize=off`, `enterkeyhint=go` |
| 68 dead CSS rules | v8 markup renamed, rules left behind | removed (verified: the class name appears nowhere in `index.html` or `app.js`) |

Regressions now caught automatically by `tools/ui_audit.js` (exit 1 on any FAIL):
missing handler on any control, missing breakpoint, `overflow:hidden` with no
short-viewport escape, missing `pointer: coarse` / `:focus-visible` /
`prefers-reduced-motion` / safe-area rules, unstyled markup classes, and a
`#ytUrl` that is not URL-keyboard friendly.

## Copy and status pass — 2026-11-20

| Report | Fix |
|---|---|
| the Details badge showed the raw video id (`Y-ISI60GZ8K`) | badge is a state again (`ready` / `no captions`); the id lives in its tooltip |
| "1080p MP4s, cut frame-exact." read like a spec sheet | "The clips will be in 1080p quality." |
| the credits line was clipped at the bottom of the screen | the footer row sizes to its content (`auto`, `min-height` token) instead of a fixed 34px slot; both names are 700-weight in `--text`, the connectives stay dim |
| the home subtitle sold on-device processing | "Paste a YouTube link to pull its captions, plan the clips and cut them." |
| a failed run offered only "Back" (which threw the link away) | failure pane now has `Try again` (re-submits the payload, the transcript is already in hand), `New link`, and `Copy details` |
| a crashed run showed `Unexpected failure: TypeError: …` | the title is "NexCut hit a bug", the message is the exception only, and the full traceback is printed in the server terminal |
| an out-of-range clip count was clamped silently on the server | clamped in the field and badge too (`3` → `5`, `99` → `15`) |

Root cause of the toast the user saw: `jobs.py` passed `ctx=` to
`provider.complete()`; `StubProvider` accepted it, `_HttpProvider` (cloudflare /
openai / gemini) did not. Every real run failed after the captions had been
fetched — the most expensive possible point. Now guarded from both sides by
`tests/test_provider_contract.py` and an end-to-end API test in
`tests/test_server.py`.

## Model output is untrusted input — 2026-11-20

`TypeError: 'int' object is not iterable` from `parse.build_result`: cloudflare's
llama answered `"longlist": 12` (a count) where the contract asks for an array.

- `_as_list` / `_as_dict` coerce every shape the contract expects to be a
  container (`longlist`, `clips`, `overlays`, `scores`, `titles`, `sweep`), so a
  stray scalar is dropped instead of raising.
- `"clips"` as a scalar or a list of strings is a `FormatError` with the offending
  type in the message — never a `TypeError`.
- a single clip object under `"clips"` is wrapped into a list.
- an unusable report triggers exactly one repair call with an explicit "return
  only the JSON object, lists not counts" note (`REPAIR_SUFFIX`), and the warning
  is recorded on the job. A second failure surfaces the format error.
- `tests/test_repair.py` drives a private `JobManager` (the HTTP tests share a
  module-level one, which made the first version of that test flaky).
