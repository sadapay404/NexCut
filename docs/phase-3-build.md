# Phase 3 — The service, running

**Date:** 2026-11-20 · Goal was: wire the reconstructed core to a real HTTP
surface and prove the gate on actual output. Both done, no dependencies added.

---

## 1. What was built

```
web/            original UI (deck + stage, no framework)
nexcut/server.py   stdlib HTTP, contract-shaped routes
nexcut/jobs.py     threaded runner, real pipeline stages
nexcut/providers.py GeminiProvider (cascade, backup key) + StubProvider (offline)
tools/parity.py    acceptance harness for recorded model answers
```

`python3 -m nexcut.server` → `http://localhost:8137`. No pip install, no venv,
no bundler. **34 tests pass.**

## 2. Decision: stdlib instead of FastAPI

FastAPI was the obvious choice (the reference is FastAPI, and its `/openapi.json`
was our best intel). It isn't installed here, the interpreter is
externally-managed (PEP 668), and a `.venv` wouldn't survive into your checkout
anyway. Shipping a server you can't `python3 -m` is worse than shipping one
without autodocs.

The handlers are ordinary functions and the routes are `re.fullmatch` patterns,
so porting to a FastAPI adapter later is mechanical: same paths, same payloads,
same handler bodies. `GET /api/config` already returns the contract shape, so
the swap wouldn't even touch `web/app.js`.

## 3. Proof the pipeline runs

Live server, stub provider, one real HTTP round trip:

```
POST /api/extract  → {"job_id":"63c0aa04b2d6"}
GET  /api/jobs/…   → {"status":"done","progress":100,"stage":"Done","elapsed_s":0.0}

clips: 1  dropped: 0  sweep: {ranges: 00:00:00-00:00:54, longlist: 3, cleared: 1}
clip1: 00:00:00 → 00:00:54  00:00:54  avg 8.25
opens: "Nobody talks about what happened on the third floor."
```

## 4. Proof the gate rejects

The parity harness is the acceptance test. Given a report containing one honest
clip, one paraphrase and one too-short clip:

```
 #   avg       dur  verdict   reason
 1   8.6  00:00:54  keep      door logged locked, camera says otherwise
 2   8.1  00:00:54  DROP      start sentence is not verbatim in the transcript
 3   6.0  00:00:09  DROP      duration 00:00:09 (9s) is outside window E (45-325s)

kept 1 · dropped 2          (exit 3)
```

Note clip #2: it scores 8.1 — above the gate — and is still rejected, because
its sentence was paraphrased. That is the whole thesis. A model cannot talk its
way past a string that isn't in the transcript. Exit `3` on any drop makes it
usable in CI.

## 5. Bugs found while testing (both mine)

1. **Stub window targeting broke on short input.** It looked for a line ≥85 s
   away; on a 54 s transcript no such line exists, so it returned zero clips and
   the server test failed with `0 clips`. Fixed by falling back to the last
   available line and only then applying the window bound — *fewer honest clips
   beats no clips*. The test that caught it was worth its weight.
2. **Rule precedence surprised the test suite earlier** (Phase 2): arithmetic
   fires before stamp-mismatch. Kept as-is and documented — the user sees the
   cheapest-to-fix violation first.

## 6. Deliberate divergences from the reference

| Reference behaviour | NexCut |
|---|---|
| Model text injected with `innerHTML` (escaping applied ad hoc) | **`textContent` only** — model output is never parsed as HTML |
| Gemini key posted in the body of every extraction | same call shape, but key is per-request and never persisted server-side; `key_hash` is what we'd log |
| Failover implied by a toggle + undocumented server fallback | explicit ladder: try model → other models → backup key, each step named in `ProviderError` |
| `localStorage` history stores 15 full reports (5 MB quota risk) | history stores **metadata only** (niche, clip counts, title) |
| Client classified errors by English substring | typed exceptions; UI copy still maps for parity |
| yt-dlp quality probe open to the public | not implemented — transcript-first by design |

## 7. The one gap this sandbox cannot close

`generativelanguage.googleapis.com` is outside this environment's egress
allowlist, so the real `GeminiProvider` path is **written and reviewed but not
executed here**. Everything up to and including prompt assembly is exercised;
the HTTP call itself is not. If you run it with your own key, the two things to
watch are:

- a 429 (key exhausted) → does the cascade reach the backup key and *say so*?
- a slow model → does the timeout surface as the retryable class, not a generic
  failure?

Both are the exact behaviours the reference exposes in its UI, so a mismatch is
easy to spot.

## 8. Phase 4 options

1. **Parity run** — feed one real `oracle_report` through `tools/parity.py` and
   reconcile every disagreement. Highest value per minute; needs your artifact.
2. **Transcript ingestion** — yt-dlp/`.srt`/`.vtt` parsing server-side, which is
   the main thing our build still makes the user do by hand.
3. **Second-pass judge + per-axis retry** — re-ask only for a weak axis instead
   of re-running the whole clip; this is where hand-built beats the reference.
4. **Deploy** — `vercel` can't host this as-is (needs a long-lived process and
   ffmpeg-free cut is not implemented); Fly/Render/a VPS with the same env vars
   would. Phase 4 could shape the app for that.
