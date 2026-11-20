# UI plan — v5 (short-viewport rebuild)

## The actual failure, named

The last three UIs were built as if the window were tall. They used one control
per row, folds for anything secondary, and no vertical budget at all. In the
frame that actually gets used — a Cloud Shell Web Preview at roughly
**1366 × 600** — that produced:

- a content pane that was mostly empty, holding one sentence;
- the transcript panel collapsed to a sliver;
- a **native** scrollbar in a 272 px sidebar (reads as a broken page);
- `Option E: 45s–5m…` truncated inside the Length select;
- three status pills and a status bar doing nothing for nobody.

None of that was a backend problem. It was a layout budget problem, and the
harness never caught it because jsdom proves behaviour, not pixels.

## What v5 changes

**The budget, written down.** A 600 px window is `48 (top) + 526 (shell) + 26
(status)`. The sidebar must therefore hold 3 panels plus the run button inside
526 px, and the content pane must fill 526 px with structure, not whitespace.

| Decision | Why |
|---|---|
| Shell is `grid-template-rows: 48px / 1fr / 26px`, page never scrolls | One scroll model. Only panes and inner lists scroll. |
| Sidebar 292 px, 30 px controls, `@media (max-height: 660px)` drops controls to 26 px and paddings to 4–7 px | Every field gets a full-width row so nothing truncates, while 5 selects + 2 numeric fields still fit. |
| Every select is full width, one per row | Niche labels reach 26 characters (`Relationship & Pop Culture`); half-width columns are what truncated them. |
| Length labels are rebuilt, not copied | Server sends `Option E: 45s–5m25s (wide range — default)`; the UI shows `45s–5m25s` and keeps the original in `title`. 11 characters cannot clip. |
| Scrollbars themed globally (`scrollbar-width`, `::-webkit-scrollbar`) | The OS scrollbar was the single most "unfinished" thing on screen. |
| Transcript is a `<details>` with a live `charBadge` and **closed by default** | It is optional input; the sidebar needs the height. Upload / Sample stay one click away inside it. |
| Dashboard is a real screen: config chips, 5-step pipeline, recent runs | The empty state was the dead space. It now shows what will happen, in order, with live state per step. |
| Results keep header → stats strip → split (table + 350 px inspector) | At 600 px the table still shows ~9 rows; the inspector and export stay visible without scrolling the page. |
| Status bar trimmed to: state · hint · provider · elapsed · version | Only facts that change. |
| `?v=` on CSS/JS plus `Cache-Control: no-cache` | A stale stylesheet is indistinguishable from a broken redesign. |

**Copy rule still holding:** labels, units, states. No slogans, no "AI-powered",
no second sentence where the first one is enough.

## What is verified, and how

| Check | Command | Result |
|---|---|---|
| Page boots against a stubbed API, full run, tabs, cut, back to dashboard | `node tools/ui_smoke.js` | 20 assertions pass |
| Backend contract unchanged | `python3 -m unittest discover -s tests` | 93 pass |
| Static/HTML integrity | id cross-check script | 98 ids, no duplicates, every JS id exists, every HTML class has a rule, CSS braces balanced |
| Serving | `curl` on `/`, `/static/style.css?v=6`, `/static/app.js?v=6` | 200, `no-cache` |
| Real render at 1366 × 600 | **not run — no browser in this sandbox** | open preview and look |

The last row is the honest gap. Playwright's Chromium download is blocked here
(`cdn.playwright.dev` is not reachable), and jsdom does no layout, so I can
prove that every control is wired and that no label can clip by length — I
cannot prove how it looks. That is exactly why the preview is left running.

## Phase plan from here

**Phase A — confirm the frame (now).** Look at the preview at the real size.
Anything wrong is reported as: which region, too tall / too cramped / clipped /
wrong order. Those are all one-line fixes now that every control owns a row.

**Phase B — results workspace.** Sortable columns (score, length, start), score
threshold filter, rejection reasons as a filter, `youtu.be/<id>?t=<start>` links,
"copy all titles", ZIP of all cuts (stdlib `zipfile`). Acceptance: 12-clip
session, sorting proven by assertion in the harness.

**Phase C — export.** Per-clip cut from the inspector, per-file progress queue,
quality picker showing resolution and estimated size before committing,
retention/size panel for `data/source` and `data/cuts`.

**Phase D — light theme parity and accessibility.** Focus order, `aria-live` on
progress and status, contrast pass in both themes, visible focus everywhere.

**Phase E — real-run hardening.** Real key, real video, every failure class gets
a written message; confirm the MP4 starts on the exact requested frame; a
≥ 60-minute video for token limits.

## Rules

1. No UI change ships without `node tools/ui_smoke.js` passing.
2. Design at 1366 × 600 first, then let taller windows breathe.
3. Labels, units, states. No marketing copy.
4. One accent. Gradients only in progress fills and the logo mark.
5. A disabled control says why.
6. Every error names the failure and the next action.
