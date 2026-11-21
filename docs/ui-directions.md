# NexCut UI directions

Four complete interfaces for the same tool, switchable without a rebuild:

| Direction | URL | Page |
|---|---|---|
| **A · Editorial / print** | `/?ui=1` or `/ui-a.html` | `web/ui-a.html` |
| **B · Console / tool** (default) | `/?ui=2` or `/ui-b.html` | `web/ui-b.html` |
| **C · Cards / consumer** | `/?ui=3` or `/ui-c.html` | `web/ui-c.html` |
| **D · Ledger / minimal** | `/?ui=4` or `/ui-d.html` | `web/ui-d.html` |

Each page has a small "Preview · A | B | C | D" strip above the product. It sits
outside the design. To ship a single direction, delete that one `<div class="switch">`
block and the other three pages.

All four share one engine, `web/core.js`: the API, the stage flow, polling, the 1080p
cut, the packaging fields, theme, icons and the clipboard fallback. A direction only
decides layout, type, colour and interaction. A bug fixed in the engine is fixed in
all four, and the owner gets the same content whichever layout he picks.

## A · Editorial / print

A printed issue on a screen. One reading measure, serif display type, hairline rules,
a numbered clip list and a single muted-gold accent. Stages are numbered sections
(`01 — Source`, `02 — Details`, `03 — Plan`, `04 — Run`, `05 — Clips`). Details and the
clip plan sit side by side on a laptop and stack on a phone. Each clip is a numbered
row; "More" opens its full packaging in place.

It optimises for reading and for a calm first impression. It suits someone who wants
the output to feel finished and who reviews clips one after another. It is the least
dense of the three, so a long clip list takes the most scrolling.

## B · Console / tool (the default)

A studio control panel. A command bar holds the link, a run rail holds the settings and
the one primary action, and a dense table lists the clips with mono numerals and a
range column. Selecting a clip shows its full packaging in an inspector beside the
table, so the owner can compare clips without losing the list. On a laptop it is three
columns; it folds to two, then to one, and the table becomes cards on a phone.

It optimises for repeat use: everything needed to run, review and download is visible
without scrolling, and the keyboard and dense layout stay quick. It suits daily use on
a PC, which is where this tool lives. The cost is density; it asks more of the reader
than A or C.

**Recommendation: ship B.** It is the strongest for the way the owner works (a link,
then many clips reviewed and downloaded), it keeps packaging out of the way until
asked, and it is the only layout where the run settings, the clip list and the packaging
are all visible at once. I'd keep A in the repo as the reference for a more
presentational look, or drop it.

## C · Cards / consumer

One thing at a time. A five-step stepper (Link, Details, Plan, Extract, Clips) sits
above one card per stage. The plan is its own card after details, so the primary
action is always large and the choices are short. The progress ring shows the percent,
and the stacked progress bar and the stage log sit under it. Results are clip cards
with a CSS thumbnail that carries the model's thumbnail text. "Details" opens the
packaging as a stack of small cards.

It optimises for a first-time user and for a phone. It suits someone who shares the
tool with others, or who wants each step to feel guided. It is the most spacious of the
three and the one that shows the least at once.

## D · Ledger / minimal

Nothing decorative. One column, one accent, hairline rules, and type that does the
work: a system sans, a mono for numbers, and no card, shadow or gradient anywhere.
The page opens light (dark is one tap away, and the choice is remembered). The header
is a single line: the mark, "Sheikh Arsalan Automation" with the institute line under
it, the two tabs, and the theme toggle. Below it a thin rail names the current stage
and carries the build tag.

Landing is a headline and one field with the button inside it. Details is a
label/value list; the plan sits to its right on a laptop and under it on a phone. A
run shows its stage name, a 3px progress line and the log. Results are a numbered
list with one hairline per row: index, title, score chip, download, More. Packaging
opens in place as a two-column grid of labelled fields. The credits line ends the page
and moves under the progress line while a run is in flight.

The mark is the owner's, redrawn rather than recoloured: the "D" of Digital Sheikh
Nexus as a solid geometric letter with the play triangle punched into its counter, in
ink and the theme's accent. It is one path and one triangle, so it holds at 30px in a
phone header and it inherits both themes. No waves, no rings, no crossed tools.

It optimises for restraint and for small screens: 44px minimum on every control, a
16px field text size so iOS never zooms, a two-column stat strip that becomes 2×2, a
clip row that gives its actions their own line under the title, and no fixed footer.
It is the direction to pick if the tool should look like a document, not an app.

## Requirements reinterpreted

The brief asked for the intent behind each requirement, so these are the places I
read it differently from the letter:

- **"One card frame" (§2).** A and B drop the card frame; the panes swap in one page.
  C keeps cards. The intent was one page with stages that swap in place, and all three
  do that.
- **"Clip rows with a More disclosure."** A and C keep More, which expands the
  packaging in place. B uses row selection: "inspect" shows the packaging in the
  inspector. The packaging is still hidden until asked, which is what the owner wanted.
- **"Five stages" (§6, C).** The brief lists five screens, which include Details and Plan
  as one stage. C shows Details and Plan as two cards, so its stepper has five steps
  (Link, Details, Plan, Extract, Clips). A failed run marks Extract.
- **Config.** B keeps the run settings in a rail that is always visible, not behind
  Details. The owner can see and change the clip count and length at any time.
- **Behaviour.** All four directions behave the same: same copy, same downloads, same
  error wording, same zero-clip message. Only the presentation differs.

Two additions the brief did not ask for, because the owner would hit them:

- A run that finds no clip now says why, using the server's own rejection reasons,
  instead of showing an empty list.
- Copy works on plain `http://<LAN-IP>:8137`, where `navigator.clipboard` does not
  exist. This was verified in a real browser on a non-localhost address, in all three
  that predate D; D reuses the same engine, so the fallback is the same code.

## What did not change

The backend, the model prompt, the clip-selection gate and the cutting behaviour are
untouched. No Python source changed. `tests/test_server.py` was updated for one thing:
it asserted that `/` loads `app.js`, which no longer exists, so it now checks the
redirect and that each direction page loads the shared engine.

## How the checks work

- `node tools/ui_smoke.js` runs the same flow against all four (link, details, plan,
  extract, results, packaging, copy, ZIP, failure, retry, empty run, downloader, reset,
  credits). Every direction must expose the same contract, listed in
  `tools/ui_contract.js`.
- `node tools/ui_audit.js` checks what jsdom cannot: every control has a handler, the
  scripts only reach elements that exist, nothing loads from a CDN, hidden panes really
  hide, breakpoints exist for tablets and phones, focus rings and reduced motion are
  present, and the credits names are bold.
- `python -m unittest discover -s tests` runs the backend suite (254 tests).

## Not verified yet

- Real Windows browsers and a real phone. Chromium was used, at the viewports in the
  brief (1366×768 and 1366×600, 1024×768, 768×1024, 390×844, 844×390).
- The full YouTube path and the 1080p cut against the real network and `yt-dlp`. The
  cut was exercised through stubs; the pasted-transcript path ran against the real
  server.
- The light theme was checked for contrast in the code but not screenshot by
  screenshot. D opens in the light theme; the audit and the smoke test do not paint.
- Own-transcript upload through a real file input.
- C's thumbnail is a generated tile carrying the model's text, not a video frame. The
  backend does not produce frames, and this does not invent one.
