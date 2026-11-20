# UI plan

## Why it broke, honestly

I changed the UI four times with **no check that the page actually runs**. JavaScript
was syntax-checked, the server returned 200s, and that was the whole test. Two
consequences:

1. I also **killed the dev server twice while testing cutting**, so the preview
   URL was dead at least once. A dead preview looks identical to a broken UI.
2. Layout was hand-rolled per screen (sticky sidebar, sticky action bar, page-level
   scrolling for some panes and inner scrolling for others) instead of one shell
   with one scroll model. That is exactly the kind of thing that looks fine in a
   diff and collapses in a real viewport.

Both are fixed as of this phase. `node tools/ui_smoke.js` now boots the real page
in jsdom, drives a full extraction and a cut, and fails on any exception, any
`console.error`, or any empty critical node.

## What Phase 1 delivered (now)

| Area | State |
|---|---|
| App shell | CSS Grid: 52 px header / sidebar + content / 30 px status bar. One scroll model: the page never scrolls, panes do. |
| Design tokens | surface, line, text and semantic scales; 4 px spacing; 4/6/10 radii; one accent. Dark + light. |
| Components | buttons (primary/secondary/ghost, sizes, disabled), fields, selects with drawn chevron, checkboxes, segmented tabs, data grid, inspector rows, progress bar, stage log, toasts, badges, error card, empty state, key-value table. |
| Results | sticky header with identity + actions; stats strip; tabs (Clips / Rejected / Response); data grid with score pills; inspector for the selected clip; export panel with quality picker, cut progress and file list. |
| Keyboard | `Ctrl/⌘ + Enter` runs. |
| Resilience | every render path catches; a bad payload shows a readable error card, never a blank screen. |
| Verification | `node tools/ui_smoke.js` → 15 assertions, including tab switching and cut. |

## Verification I cannot do from here

I have no browser in this environment, so **pixels are unverified** — only
behaviour is. That gap is the reason this broke. Two ways to close it:

- **You send one screenshot** of the app as you see it now. I will fix what it shows.
- Or tell me what "broken" means specifically: blank page / unstyled page / controls
  dead / layout overlapping / wrong proportions. Each points at a different cause.

---

## Phase 2 — Source and settings UX (25 min)

**Goal:** the left column stops being a form and becomes a state machine.

- Caption state machine: `idle → fetching → ready → failed`, with the failure
  carrying the retry affordance and the winning strategy (`watch-page`, `yt-dlp`,
  `transcript-api`) shown as a quiet detail line.
- Live transcript validation: line count, first/last stamp, "n lines without a
  timestamp" warning before a run is attempted — the server error becomes
  something you see while typing.
- Saveable presets: name a settings combination, reload it in one click
  (niche + audience + language + clips + length).
- Field-level validation and disabled-run reasoning: the run button says *why* it
  is disabled rather than going grey silently.

**Acceptance:** paste an invalid URL → failure state with retry, no console errors;
save/load a preset; attempt a run with a timestamp-less transcript → warning
appears before the network call.

## Phase 3 — Results workspace (30 min)

**Goal:** make the output the best part of the app.

- Sortable columns (score, length, start), and a filter for score threshold.
- Row selection that works on mobile (tabs within the inspector).
- Timestamp links: each clip opens `youtu.be/<id>?t=<start>` in a new tab.
- Copy sets: "copy all titles", "copy caption + hashtags bundle", per-field copy
  already exists.
- Rejected view gains the reason category (verbatim / duration / gate / safety)
  as a filter.
- Empty and single-clip states designed, not defaulted.

**Acceptance:** 12-clip session; sorting and filtering verified in the smoke
harness by assertion, not by eye.

## Phase 4 — Export and cutting UX (25 min)

**Goal:** cutting stops being one all-or-nothing button.

- Per-clip cut button in the inspector; queue shows per-file progress.
- "Download all" as a single ZIP (stdlib `zipfile`, no dependency).
- Storage panel: cached source size per video, cut output size, days retained.
- Quality picker shows resolution + estimated size before committing.

**Acceptance:** cut one clip, then cut a second from cache instantly; ZIP contains
both; storage numbers match `data/`.

## Phase 5 — Polish and QA (30 min)

- Motion: 120–180 ms transitions only, all behind `prefers-reduced-motion`.
- Loading skeletons for table and inspector (nothing jumps).
- Responsive pass at 1440 / 1280 / 1024 / 820 / 390 with a written checklist.
- Accessibility: focus order, `aria-live` on progress and status, contrast check
  in both themes, visible focus on every interactive element.
- Light theme parity — currently the weaker of the two.

**Acceptance:** the checklist, run by you on a real browser, comes back with no
failed rows.

## Phase 6 — Real-run hardening (ongoing)

- Run with a real key and a real video; capture every failure class and give each
  a written message.
- Confirm the exported MP4 starts on the exact frame.
- Long-video pass (≥ 60 min) for token limits and chunking.

---

## Rules I am holding myself to

1. No UI change ships without `node tools/ui_smoke.js` passing.
2. No marketing copy in the interface. Labels, units, states only.
3. One accent colour. No gradients except progress fills. No decorative graphics.
4. If a control can be disabled, it says why.
5. Every error names what failed and what to do next.
