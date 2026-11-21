# Sheikh Arsalan Automation — Clip Studio

Paste a YouTube link. The studio fetches the captions, sends them to your AI
provider with your prompt, then verifies every answer against the transcript
before you see it. One button.

```bash
python3 -m nexcut.server      # http://localhost:8137
```

Windows: `start.bat` · Mac/Linux: `./start.sh`. No dependencies, no build step.

Runs in **demo mode** out of the box (offline provider, no key needed) so you can
click through the whole flow before wiring a real model.

## Cutting clips

Requires `ffmpeg` and `yt-dlp` on PATH — see `docs/cutting.md`.

```bash
pip install yt-dlp            # download
winget install Gyan.FFmpeg    # Windows (brew/apt on mac/linux)
```

The top bar reports `cutting ready` or `cutting unavailable`; extraction works
either way. Files land in `data/cuts/<cut_id>/` and are pruned after 3 days.

## Real model

```bash
export NEXCUT_PROVIDER=gemini          # or: openai (any OpenAI-compatible base)
export NEXCUT_MODELS=gemini-2.5-flash,gemini-2.5-pro
python3 -m nexcut.server
```

Your key comes from the environment — nothing is typed into the browser. The
server reads a `.env` in the repo root on start (real environment variables win):

```bash
cp .env.example .env    # then edit
# NEXCUT_PROVIDER=gemini
# NEXCUT_API_KEY=...
python3 -m nexcut.server
```

`NEXCUT_BACKUP_KEY` is the second key in the failover chain. The UI never sees or
stores a key.

## Your prompt

`prompts/master.md` — read fresh on every run, no restart. Placeholders
(`{{transcript}}`, `{{niche}}`, `{{window_min}}`, …) are filled from the run
settings. See `prompts/README.md`; start from `prompts/master.example.md`.

## Layout

| Path | What |
|---|---|
| `nexcut/ingest.py` | YouTube captions: watch-page tracks → yt-dlp → youtube-transcript-api, with actionable errors |
| `nexcut/prompts.py` | your prompt file + placeholder templating + machine contract |
| `nexcut/providers.py` | Gemini, OpenAI-compatible, offline stub; explicit failover chain |
| `nexcut/jobs.py` | threaded pipeline: captions → check → sweep → model → parse → gate |
| `nexcut/validate.py` | the six-rule gate — everything checked against the transcript |
| `nexcut/cutter.py` | yt-dlp download + ffmpeg frame-accurate cut, tool probing |
| `nexcut/cuts.py` | cut job queue: one download, then per-clip progress |
| `nexcut/server.py` | HTTP layer (stdlib), contract-shaped routes |
| `web/` | the studio UI — link → details → config → extract → cut → downloads; Cutter/Downloader tabs, no framework, no build step |
| `tools/parity.py` | gate any recorded model answer and see what survives |
| `docs/` | recon, contract, build notes, handover |

## Any screen, any device

The frame is designed for 1366×600, then it gets out of the way:

- **short viewports** (browser chrome eating a laptop screen, a phone in landscape)
  drop out of the fixed frame below 560px tall and let the page itself scroll —
  the bottom of the card is never unreachable;
- **≤1024 / 720 / 520 / 380px** restack the details panel, the clip rows and the
  length presets, and drop padding that no longer fits;
- **touch** (`pointer: coarse`) gets 40px targets, no hover-only affordances and
  `touch-action: manipulation` (no 300 ms iOS tap delay);
- **copy buttons work over plain HTTP.** `navigator.clipboard` is undefined on
  `http://192.168.x.x:8137`, so `copy()` falls back to a hidden textarea +
  `execCommand` — that was the one genuinely broken control on a LAN address;
- `100dvh` + safe-area insets keep it honest under mobile browser toolbars and notches;
- `node tools/ui_audit.js` fails the build if any of that regresses.

Other devices on the same network: the server already binds `0.0.0.0` and prints
the LAN URL it should be opened at, e.g. `http://192.168.1.24:8137`.

## Test

```bash
python3 -m unittest discover -s tests -v      # 254 backend/contract tests
npm install && npm run test:ui                # 54 UI assertions × 4 directions (jsdom, no browser)
node tools/ui_audit.js                        # static UI audit: handlers, breakpoints, a11y
```

**A refused model id fixes itself.** Groq moved `llama-3.3-70b-versatile` (and
`llama-3.1-8b-instant`) to Enterprise-only plans while keeping the id, so an
unchanged `.env` started answering `code: model_not_found`. On that error NexCut
asks the provider `GET /models` with your key, picks the best chat model it
actually serves (`openai/gpt-oss-120b` first), and retries — once, then it
reports the original error. The same path handles APIs that renamed
`max_tokens` to `max_completion_tokens` or reject `response_format`.

**The output budget is always stated explicitly.** Workers AI defaults
`max_tokens` to **256** — far too small for a clip report — so a run used to come
back cut off mid-JSON and look like "the answer has no clips key". NexCut now
sends `max_tokens: 4096` (Cloudflare), `max_tokens` (OpenAI-compatible) and
`maxOutputTokens` (Gemini). Override with `NEXCUT_MAX_TOKENS=6000` in `.env`.
A cut-off answer is now named as such, and the raw reply is printed in the
terminal and shown under "What the model returned" on the failure pane.

Model answers are treated as untrusted input: `parse.build_result` accepts a
scalar wherever a list belongs (`"longlist": 12`, `"scores": 9`) and never raises
a `TypeError`, and if the report is unusable the pipeline re-asks **once** with a
repair note before giving up (`tests/test_repair.py`). `"clips": 3` therefore
becomes "the answer was not in the clip-report format", not a crash after the
captions have already been fetched.

`tests/test_provider_contract.py` exists because the whole suite runs on the
offline stub: it reads the `provider.complete(...)` call site out of `jobs.py`
with `ast` and fails if any provider class cannot accept those keywords. That is
the bug that made every real run die with *"complete() got an unexpected keyword
argument 'ctx'"* while 219 stub-based tests stayed green.

The UI has four directions (see `docs/ui-directions.md`) that share one engine (`web/core.js`): **UI A**
(editorial), **UI B** (console, the default), **UI C** (cards) and **UI D**
(sleeve, the record one). Open `http://localhost:8137`, or
`http://localhost:8137/?ui=1`, `?ui=2`, `?ui=3`, `?ui=4` to pick one.
See `docs/ui-directions.md` for what each one optimises for.

The UI harness boots each direction in jsdom against a stubbed API and walks the
same flow for all four, failing on any exception, `console.error`, or missing
requirement (`node tools/ui_smoke.js`). The static audit checks what jsdom cannot:
every control has a handler, no CDN, the plain-http copy fallback, breakpoints,
focus rings and reduced motion (`node tools/ui_audit.js`). The data-role contract
both check lives in `tools/ui_contract.js`.

## API

`GET /api/config` · `POST /api/transcript` (link → captions) ·
`POST /api/extract` → `{job_id}` · `GET /api/jobs/{id}` · `GET /api/jobs/{id}/results` ·
`POST /api/upload-transcript` · `GET /api/export/{id}` · `GET /api/tools` ·
`GET /api/video-quality/{id}` · `POST /api/jobs/{id}/cut` · `GET /api/cuts/{id}` ·
`GET /api/cuts/{id}/file/{name}`

Env: `NEXCUT_PROVIDER`, `NEXCUT_API_KEY`, `NEXCUT_MODELS`, `NEXCUT_MODEL_MAP`, `NEXCUT_BACKUP_KEY`,
`NEXCUT_OPENAI_BASE`, `NEXCUT_PROMPT_DIR`, `NEXCUT_APPEND_CONTRACT`,
`NEXCUT_INVITE_CODES`, `NEXCUT_OFFLINE`, `NEXCUT_PORT`, `NEXCUT_COOKIES`.
