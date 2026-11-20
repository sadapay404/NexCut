# UI plan — v6 (reference-led rebuild)

## What changed and why

v5 was a dense cockpit. That was the wrong genre. The reference the user supplied
is a **framed hero**: wordmark left, two tabs centre, one link bar, everything
inside a single rounded panel with corner labels and a credits line. v6 adopts
that composition — not the reference's markup, copy or colours, its structure.

| Reference element | NexCut v6 |
|---|---|
| `NEXUS / DOWNLOADER` wordmark | `NEX**CUT** / Clip Studio` — NEX in ink, CUT in gold |
| Centred nav pills | `Cutter` · `Downloader` with a `soon` badge |
| `SIDE A — LINK INTAKE` corner label | same, plus live provider / prompt / cutting state on the right |
| Display heading with one italic word | `Sheikh Arsalan` + italic gold `Automation` |
| One-line tagline | replaced with mechanics: "Paste a YouTube link. Captions, model pass, rule check and the cut run on this machine." |
| Standard / Batch toggle | removed — there is nothing to toggle until batch exists |
| One URL bar with the action inside | one URL bar, `Extract` inside, `⌘↵` hint |
| Micro chips under the bar | `Options` `Transcript` `Sample` `History` — each opens a drawer |
| Bottom microcopy | live source line: `No source` → `Fetching captions…` → `Captions ready — auto · 214 lines · 12:04` |
| Credits line | `Proudly created by Sheikh Arsalan in collaboration with Mubashir` |

## Composition rules

- **One panel.** The stage is a single card, `min(1180px, 100%)` wide, capped at
  660px tall, centred in a grid. Top bar 58px, credits 34px (52/30 under 700px tall).
- **Nothing lives outside the card.** Progress, errors and results all render
  inside the same frame, so the composition never collapses.
- **Progressive disclosure.** Niche, audience, language, length, clips, model and
  key sit in an `Options` drawer. Transcript and history have their own drawers.
  Closed by default; the landing stays a hero.
- **Result state** replaces the hero with `Result` header, stats strip, clip table
  and a fixed inspector/export rail inside the same card. At 600px the table still
  shows ~12 rows.
- **Type.** Sans for the chrome, one serif italic word for the gold accent, mono
  for every number, timestamp and micro-label. No icon fonts, no web fonts, no CDN.
- **Decoration is one layer.** A soft warm radial plus concentric grooves at 4–7%
  opacity, under `pointer-events: none`, dimmed in the light theme.

## Verified

| Check | Command | Result |
|---|---|---|
| Boot, drawers, tab switch, full run, cut, back to landing | `node tools/ui_smoke.js` | 25 assertions pass |
| Backend | `python3 -m unittest discover -s tests` | 93 pass |
| Structure | id/class/CSS audit | 100 ids, no duplicates, every JS id exists, every class has a rule, braces balanced |
| Serving | `curl` `/`, `/static/style.css?v=7`, `/static/app.js?v=7` | 200 |

Not verified: pixels. There is no browser in this sandbox and Playwright's
Chromium download is blocked, so the preview must be judged by eye.

## Phases

**Phase 1 — this card.** Landing, drawers, progress, results, export rail,
Downloader placeholder, credits. Done.

**Phase 2 — result workspace.** Sortable columns, score filter, rejection reasons
as a filter, `youtu.be/<id>?t=<start>` links, copy-all titles, ZIP of all cuts
(stdlib `zipfile`).

**Phase 3 — cutting queue.** Per-clip cut from the inspector, per-file progress,
quality picker with estimated size, retention panel for `data/source` and
`data/cuts`.

**Phase 4 — Downloader.** Real second tab: video / audio, quality list from
`/api/video-quality`, one queue, same yt-dlp pipe. It shares the key field and the
history, so the card composition does not change.

**Phase 5 — real-run hardening.** Real key, real video, every failure class has a
written message; confirm the MP4 starts on the requested frame; test a ≥ 60-minute
source.

## Rules

1. No UI change ships without `node tools/ui_smoke.js` passing.
2. Design at 1366 × 600 first.
3. Labels, units, states — no marketing copy.
4. One accent, one decoration layer.
5. A disabled control says why.
6. Every error names the failure and the next action.
