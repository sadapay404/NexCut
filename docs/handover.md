# Handover

## What this is

`Sheikh Arsalan Automation — Clip Studio`. A local web app: one YouTube link in,
checked clip reports and cut MP4s out.

## Run

Windows: `start.bat` · macOS/Linux: `./start.sh` → http://localhost:8137

No dependencies for extraction. It starts on the offline demo provider, so the
whole flow runs before you add a key.

Real model:

```bat
set NEXCUT_PROVIDER=gemini
set NEXCUT_MODELS=gemini-2.5-flash,gemini-2.5-pro
python -m nexcut.server
```

`NEXCUT_PROVIDER=openai` plus `NEXCUT_OPENAI_BASE` covers OpenAI, OpenRouter,
Groq, Together, Ollama.

## Cutting

Needs two programs on PATH:

```
pip install yt-dlp
winget install Gyan.FFmpeg     (brew install ffmpeg / apt install ffmpeg)
```

Top bar reports `cutting ready` / `cutting unavailable`. Extraction is
unaffected either way. Mechanism and API in `docs/cutting.md`.

## Your prompt

`prompts/master.md`, read fresh every run. Placeholders in `prompts/README.md`.
`NEXCUT_APPEND_CONTRACT=0` if your prompt already defines the JSON shape.

## Interface

- Left rail: source, output settings, model, two actions.
- Main area: session results — clips table on the left, selected clip's full
  metadata on the right, rejects and raw answer collapsed below.
- Cut bar appears with results: quality selector, cut action, file list.

## What has not been executed here

No network egress to YouTube or Google in the build environment, and no
ffmpeg/yt-dlp binaries. So:

| Item | Status |
|---|---|
| Caption fetching | three strategies implemented; runs against fixtures in tests only |
| Gemini / OpenAI calls | transport, failover and error mapping implemented; not executed |
| Download + cut | command construction unit-tested; full HTTP chain exercised with stub binaries writing placeholder files |
| Real MP4 output | not produced here — needs ffmpeg on your machine |

First run on your machine is the actual verification. If captions fail, the
status line names which of the three methods failed.

## Files

| Path | What |
|---|---|
| `nexcut/ingest.py` | captions: watch page → yt-dlp → youtube-transcript-api |
| `nexcut/cutter.py` | download, quality probe, ffmpeg cut |
| `nexcut/cuts.py` | cut jobs, progress, file listing |
| `nexcut/jobs.py` | extraction pipeline |
| `nexcut/validate.py` | rule gate |
| `nexcut/prompts.py` | your prompt + templating |
| `nexcut/providers.py` | Gemini, OpenAI-compatible, offline |
| `nexcut/server.py` | HTTP layer |
| `web/` | UI |
| `prompts/` | your prompt |
| `data/` | source cache and cut output (git-ignored, pruned after 3 days) |

93 tests: `python3 -m unittest discover -s tests`
