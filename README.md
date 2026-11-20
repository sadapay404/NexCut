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

Your key is typed in the app, used for that run, and never stored on the server.

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
| `web/` | the studio UI — framed hero card, Cutter/Downloader tabs, drawers, results split view; no framework, no build step |
| `tools/parity.py` | gate any recorded model answer and see what survives |
| `docs/` | recon, contract, build notes, handover |

## Test

```bash
python3 -m unittest discover -s tests -v      # 93 backend/contract tests
npm install && npm run test:ui                # 25 UI assertions (jsdom, no browser)
```

The UI harness boots `web/index.html` + `web/app.js` against a stubbed API and
fails on any exception, any `console.error`, or any empty critical node. It does
not do layout — see `docs/ui-plan.md` for what that means.

## API

`GET /api/config` · `POST /api/transcript` (link → captions) ·
`POST /api/extract` → `{job_id}` · `GET /api/jobs/{id}` · `GET /api/jobs/{id}/results` ·
`POST /api/upload-transcript` · `GET /api/export/{id}` · `GET /api/tools` ·
`GET /api/video-quality/{id}` · `POST /api/jobs/{id}/cut` · `GET /api/cuts/{id}` ·
`GET /api/cuts/{id}/file/{name}`

Env: `NEXCUT_PROVIDER`, `NEXCUT_MODELS`, `NEXCUT_MODEL_MAP`, `NEXCUT_BACKUP_KEY`,
`NEXCUT_OPENAI_BASE`, `NEXCUT_PROMPT_DIR`, `NEXCUT_APPEND_CONTRACT`,
`NEXCUT_INVITE_CODES`, `NEXCUT_OFFLINE`, `NEXCUT_PORT`.
