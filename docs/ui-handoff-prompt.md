# NexCut — UI rebuild brief (hand this whole file to the AI)

## 0 · One-paragraph summary

You are redesigning the entire front end of **NexCut**, a local/self-hosted tool that turns
a YouTube link into ready-to-cut short clips. The backend works and must not change
behaviourally. The UI does not meet the owner's bar: it is cramped, controls break on
unknown screen sizes, and it crams too much into too little space. Your job is to produce
**three genuinely different, complete UI directions** so the owner can pick one.

- **Repo:** https://github.com/sadapay404/NexCut
- **Work on the branch:** `arena/5c0868a5-nexcut` (the `main` branch contains only a
  README — a plain clone of `main` is not a working app)
- **Run it:** `python -m nexcut.server` → http://localhost:8137 (Windows: `start.bat`)
- **Tests that must stay green:**
  - `python3 -m unittest discover -s tests` → currently **253 pass**
  - `node tools/ui_smoke.js` → currently **54 checks pass** (jsdom, no browser)
  - `node tools/ui_audit.js` → currently **0 fail / 0 warn** (static audit)
- **No framework. No build step. No CDN.** Plain HTML + CSS + vanilla JS, served
  statically by a Python `http.server` subclass from `web/`.

You have **no restrictions** on how you do it. Rewrite `web/index.html`,
`web/style.css`, `web/app.js` from scratch if you want. You may change the static-file
plumbing in `nexcut/server.py`. You may add pages, fonts bundled as files, SVG, canvas,
CSS-only illustrations. You may not change the public API contract, the model prompt, the
clip-selection gate, or the cutting behaviour — that part works and is load-bearing.

---

## 1 · What the product actually does

One input: a YouTube link.

2. The app pulls the video's captions (with a fallback chain: InnerTube clients →
   timedtext → watch page → yt-dlp; if captions are unavailable the user can paste or
   upload their own `.txt` / `.srt` / `.vtt`).
3. The transcript is sent to a language model with a long master prompt. The model returns
   a **clip report**: candidate ranges, then N clips, each with start/end timestamps,
   scores, hook line, titles, overlays, caption text, hashtags, pinned comment, etc.
4. The app validates every clip against the transcript (timestamps must exist, quotes must
   appear, duration must fit the requested window, score threshold), drops what fails, and
   renumbers what survives.
5. It then downloads the source once with `yt-dlp` and cuts each clip with `ffmpeg`
   (frame-accurate re-encode), producing 1080p MP4s.
6. Each clip row offers one download, or — if "Download as ZIP" is on — a single archive
   containing every MP4 plus a `details.md` summary.

There is a second tab, **Downloader**, which is deliberately a non-functional placeholder
("soon"). Do not invent features for it; make it look intentional and quiet.

**Target user:** one person, on his own PC (Windows, Python 3.15), opening the app at
`localhost:8137`. He also opens it from his phone over the LAN at
`http://192.168.x.x:8137` — which is **plain HTTP**, so `navigator.clipboard` does not
exist there. Any copy feature must fall back to `execCommand`.

---

## 2 · The five screens (all in one page, no routing)

The app is a single page with panes that swap in place. Every pane lives inside one
"card" frame; a small label in the card's top-left says which stage you are in.

| Pane | What must be on it |
|---|---|
| **Landing** | Real heading (h1). One short sentence, not marketing copy. A link input that starts fetching as you paste, plus a Fetch button. A one-line status under it ("No source" / "Reading the link…" / error). |
| **Details + Config** | Left: title, channel, length, caption type, transcript size (lines · characters), niche ("detected by the model on extract"), and two secondary actions: *View transcript* (downloads a `.txt`) and *Provide own transcript* (opens a textarea + file upload). Right: clip count (blank = AUTO, min 5, max 15), clip length presets `40–50 s` `60–90 s` `90–180 s` `Custom` (Custom reveals min/max seconds), the **Extract Clips** primary button, and one hint line: "The clips will be in 1080p quality." |
| **Working** | Stage headline, a progress bar with percent, a scrolling log of stages, and the credits line directly under the progress bar while a run is in flight. |
| **Failure** | A serious, calm panel: title, the message, an optional hint, **Try again** (re-submits the same payload), **New link**, **Copy details**, and — when the server sends one — a collapsed "What the model returned" block with the raw model answer. |
| **Results** | Title + meta line (channel · caption source · model · coverage). Stats: found / clips / rejected / asked-for. "Download as ZIP" toggle, "Answer" (copies the raw model JSON), "New link". Then the clip list. Each row: `Clip N`, its title, its score, a **More** disclosure that expands the full packaging (in/out timestamps, length, the four scores, thumbnail text, search title, on-screen question, caption, hashtags, pinned comment, why it works, overlays, SFX, safety), and a download button. Cutting progress shows in a slim bar under the list. |

Functional requirements that are not negotiable (they came from the owner, several times):

- **Exactly two tabs:** `Cutter` and `Downloader`. Nothing else in the top bar except the
  wordmark, a repo link and a theme toggle.
- **The credits line is mandatory:** *"Proudly Created by **Sheikh Arsalan** in
  Collaboration with **Mubashir**"* — both names bold and visually distinct, never clipped
  at any width. It sits in the footer, and moves directly under the loading bar during a run.
- **Never show the transcript inline.** It is downloadable and replaceable only.
- **No API-key field anywhere.** The key lives in `.env`.
- **No filler copy.** No taglines, no "fast, private, powerful". Every string either
  states a fact or labels a control.
- **One accent colour.** The current one is a muted gold on near-black. Keep a single
  accent; do not add a second hue for decoration.
- **Clip count 5–15**, blank = AUTO. **Lengths** `40–50`, `60–90`, `90–180`, `Custom`.
- **Niche is auto-detected.** There is no niche picker.
- Rows are `Clip N` + title + a More disclosure — the owner explicitly does not want the
  full packaging always visible.

---

## 3 · The API you build against (do not change it)

```
GET  /api/config                       → { version, provider, min_clips, max_clips,
                                           default_window, windows[], tools{}, prompt{} }
POST /api/transcript      {youtube_url} → { title, channel, seconds, video_id, text,
                                           lines, is_auto, source }
POST /api/upload-transcript  (multipart) → { text, chars }
POST /api/extract   { youtube_url, transcript_text, niche:"auto", language,
                      num_clips (0 = AUTO), window ("40-50"|"60-90"|"90-180"|"custom"),
                      custom_min_sec, custom_max_sec, cascade:true, model:"" }
                                        → { job_id }
GET  /api/jobs/<id>                    → { status: pending|running|done|error, progress,
                                           stage, error, error_hint, warnings,
                                           raw_answer, elapsed_s }
GET  /api/jobs/<id>/results            → { video_id, video_title, channel,
                                           transcript_source, model_used,
                                           ranges_planned, sweep{longlist,cleared,window,ranges},
                                           clips[], dropped[], oracle_report }
POST /api/jobs/<id>/cut  { height:1080 } → { cut_id }
GET  /api/cuts/<id>                    → { status, progress, stage, quality, files[],
                                           error }
GET  /api/cuts/<id>/zip                → the ZIP
GET  /api/cuts/<id>/file/<name>        → one MP4
GET  /api/tools, /api/health, /api/health/key
```

Poll `/api/jobs/<id>` about once a second; extraction owns 0–70 % of the progress bar and
cutting owns the rest. A job error is `{ error, error_hint, raw_answer }` — show all three,
never a bare stack trace.

---

## 4 · What is wrong with the current UI (do not reproduce any of this)

These are the owner's actual complaints, with screenshots, after using it for real:

1. **Cramming.** The results pane stuffs nine packaging fields into every clip row, with
   oversized IN/OUT/LENGTH boxes, full-width score bars that carry no information, and a
   nested scrollbar inside a scrollbar. It reads as a debug view, not a product.
2. **Clipped content.** The bottom of the card gets cut off on a 1366×600 laptop; the
   credits line was sliced in half. Nothing may be unreachable at any viewport.
3. **Buttons that lie.** A "Cutting…" chip appears squashed inside a row; some controls
   only respond to hover; copy buttons died on the LAN address because they relied on
   `navigator.clipboard`.
4. **Empty space is spent, not used.** The working screen is a vast empty card with a tiny
   log at the top and a headline shouting "Answer was malformed — asking once more…".
5. **Type hierarchy fights itself.** Micro-caps labels, monospace numbers, bold headlines
   and gold badges all compete at once; nothing is clearly primary.
6. **Version/build tags drift and get shown as decoration** (`V0.1.1`, `v0.1.3` inside a
   0.1.5 build). Show the real `/api/config` version, once.
7. **The hero reads like an advertisement.** The subtitle once said the pipeline "runs on
   this machine" — the owner called it out as Apple-style marketing. Describe the tool, do
   not sell it.

---

## 5 · The bar you are being held to

- **Professional, not busy.** If a fact is not needed to decide or act, it belongs inside
  the More disclosure — or nowhere.
- **Whitespace is a feature.** The card may be large and mostly calm. Not every pixel must
  carry a widget.
- **Legibility beats density.** One clear primary action per screen. Secondary actions are
  quiet. Body text ≥ 13 px, labels ≥ 10 px, no 9 px micro-caps on anything the user must
  read.
- **Works on any device the owner might open it on**, including ones you cannot predict:
  1366×600 laptop with browser chrome, 1920×1080, a 1024×768 projector, a phone in
  portrait and landscape, an iPad, a 4K TV with 200 % scaling. Requirements:
  - no horizontal scrolling at 320 px;
  - nothing clipped at 560 px tall — the page scrolls instead;
  - tap targets ≥ 40 px and `touch-action: manipulation` under `pointer: coarse`;
  - `min-height: 100dvh` + safe-area insets;
  - a visible `:focus-visible` ring on every interactive element;
  - honours `prefers-reduced-motion`;
  - no native scrollbars on the main frame at 1366×600 (inner lists may scroll, subtly).
- **Keyboard:** Enter in the link field fetches; tab order follows the visual order; Escape
  closes the More disclosure and the own-transcript drawer.
- **Empty, loading and error states for every pane.** A spinner is not a design.
- **Copy must work on plain HTTP** (hidden textarea + `document.execCommand("copy")`).
- **No layout shift** when data arrives: reserve space for stats, titles and lists.
- **Accessibility:** real `<h1>`/`<h2>`, `aria-live` for progress and toasts, labelled
  inputs, `aria-expanded` on disclosures, no colour-only meaning.

---

## 6 · The deliverable — three UI directions, not one

Build **three distinct, fully finished UI directions** and ship them **at the same time**,
switchable without a rebuild, so the owner can compare them himself:

- `web/index.html?ui=1`, `?ui=2`, `?ui=3` (or three real files — your call, but all three
  must exist and be reachable from a visible switcher while he is deciding).
- The switcher is a small, unobtrusive control (top-right is fine), labelled
  `UI A | B | C`, that does not become part of the product design.
- **Three different directions, not three colourways.** Suggested axes, pick three that
  actually differ:
  - **A — Editorial / print:** strong type scale, generous margins, hairline rules, a
    near-monochrome palette with one accent, dense information only on demand.
  - **B — Console / tool:** compact, precise, monospaced numerals, a real table for clips,
    a detail rail instead of per-row expansion, built for repeat use.
  - **C — Card / consumer:** soft surfaces, one thing at a time, big primary action,
    a stepper through the five stages, thumbnails and packaging presented as a stack of
    small cards.
- All three must implement **every** functional requirement in §2 and pass §5. All three
  must be complete; do not leave one as a sketch.
- Include `docs/ui-directions.md`: for each direction, one paragraph on the idea, what it
  optimises for, and who it would suit — plus a note on which one you would ship and why.

---

## 7 · Definition of done

You are finished when, on your own machine:

```bash
python3 -m unittest discover -s tests      # 253 pass, unchanged
node tools/ui_smoke.js                     # all checks pass (update it for your markup)
node tools/ui_audit.js                     # 0 fail, 0 warn   (update it for your markup)
python -m nexcut.server                    # open :8137, walk all three directions
```

and each direction:

- [ ] completes the whole flow: paste link → details → config → extract → results → cut →
      download (with the backend stubbed or real — the flow must not dead-end);
- [ ] looks deliberate at 1366×600, 1280×800, 1024×768, 768×1024, 390×844 and 844×390;
- [ ] nothing clipped, nothing hidden behind an unreachable scroll area;
- [ ] every control has a visible handler — no dead buttons, no hover-only affordances;
- [ ] copy, transcript download, ZIP toggle and per-clip download all work over
      `http://<lan-ip>:8137`;
- [ ] the credits line renders on one or two lines, both names bold, never cut;
- [ ] no console errors.

`tools/ui_smoke.js` boots the real `index.html` + `app.js` in jsdom against a stubbed API
and fails on any exception, `console.error`, or empty critical node; `tools/ui_audit.js`
checks that every control has a handler, every breakpoint exists, dead CSS is gone and the
clipboard fallback survives. **Keep both honest** — if you change the markup, update the
checks rather than deleting them, and state in your summary which assertions you changed
and why.

---

## 8 · How to report back

1. The three URLs / switcher labels and one paragraph each on the idea.
2. A list of every file you added, changed or deleted.
3. Which of the owner's requirements you reinterpreted, and why — he cares about the intent
   behind them more than the letter.
4. What you deliberately left alone (backend, prompt, gate, cutting) and confirmation that
   the three test commands above pass.
5. Anything you think is still weak.
