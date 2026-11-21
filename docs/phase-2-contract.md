# Phase 2 — Behavioural Reconstruction & Clean-Room Core
**Date:** 2026-11-20 · **Scope:** reconstruct the *rules*, not the code. Every claim below is tagged.

**[V]** observed directly · **[H]** inference · **[O]** our own design decision (deliberate divergence)

---

## 0. What changed in Phase 2

Three new artifacts landed, all public/client-side:

1. **`static/admin.js`** — the entire admin console logic (2 chunks). This is the biggest new source: it reveals the server's **telemetry schema**, the **member/invite model**, the **key-hash** discipline, and the **activity row** shape.
2. **`GET /api/video-quality/{id}` answered with no invite code** → `{"qualities":[2160,1440,1080]}` for a real video. **Gating is per-route, not global** [V]. (Also proves the yt-dlp/quality probe works unauthenticated — worth noting for abuse surface, and a deliberate thing *not* to copy.)
3. A refinement of yesterday's admin-auth finding: `admin.js` says on failure *"Wrong password (or `APP_PASSWORD` not set in .env)"*. So **[H]** the most likely explanation for `/api/me → admin_authed:true` is that **`APP_PASSWORD` is unset and the gate fails open**, not that a session leaked. Still a real vulnerability, but now with a specific, checkable cause.

I did not touch `/api/admin/members` or `/api/admin/activity` (invite codes + member PII). Everything below about those comes from `admin.js` rendering code, which is public.

---

## 1. Recovered admin surface & telemetry schema [V]

`GET /api/admin/summary` → `{total_runs, day, members:[{member_name, runs, clips, videos, failed, flagged}]}`
`GET /api/admin/members` → `{members:[{name, code, created_at, revoked}]}`
`POST /api/admin/members {name}` → `{name, code}` (code generated server-side)
`GET /api/admin/activity?member&day&limit=200` → `{rows:[…], members:[…]}` where **each row is**:

| Field | Meaning | Why it matters for us |
|---|---|---|
| `ts` | timestamp, displayed as **PKT** | server localises to Asia/Karachi |
| `member_name` | resolved from invite code | member↔code join happens server-side |
| `video_title` / `video_id` | from oEmbed / URL parse | — |
| `niche` | the `"Niche — Sub"` string | confirms sub-niche is just a label |
| `clips_wanted` / `clips_kept` | requested vs. survived the gate | **the gate's drop rate is a first-class product metric** |
| `model` | rendered with `"gemini-"` stripped | stored as the full alias, e.g. `gemini-4-hydrogen` |
| `key_hash` | **hashed** member key | the raw key is never persisted — good pattern, copy it |
| `ip` | client IP | — |
| `device_tag` | the `x-device-tag` header | our `dev-<8hex>` localStorage value |
| `flags` | comma-separated list, rendered as chips | free-form: almost certainly things like fallback/failed/flagged |
| `error` | present only on failed rows | powers the ⚠ prefix in the activity table |

Other admin state shapes: `sheet → {webhook_configured, unsynced, secret}` (the Apps Script `SHEET_SECRET` is *displayed* in the console), `sync-now → {pushed, total, error}`, `server-key-status → {set}`, cookies/logo `→ {exists}`.

**Two bugs visible in `admin.js`** [V]:
- `await api("/api/admin/logo", "DELETE")` passes a **string** as `opts`, so `fetch` never gets `method:"DELETE"` — "Remove Logo" fires a GET and silently fails. Classic.
- `loadActivity()` populates the member filter only `if (sel.options.length <= 1)`, so a member created later never appears in the filter without a reload.

---

## 2. The reconstructed pipeline

```
URL ──► /api/video-info (oEmbed: channel+title, best-effort)
      ──► transcript source: paste | .srt/.vtt upload | (fetch-transcript, unused by UI)
      ──► PRE-FLIGHT: timestamps present?  ──no──► "NO TIMESTAMPS" (never spends tokens) [V]
      ──► SWEEP: chunked coverage over the transcript ──► sweep.ranges      [H]
      ──► LONGLIST: candidate moments (start + gist)   ──► sweep.longlist   [V]
      ──► SCORE: curiosity/stakes/specificity/speed    ──► 8.0 gate         [V]+[H]
      ──► RULE CHECK: verbatim, arithmetic, 3-sec, safety ─► dropped[]     [H, strong]
      ──► DELIVER: top-N clips ──► results + oracle_report + admin activity row [V]
```
`models × cascade`, with a **server backup key** consumed when the member's key hits its daily limit, and one client-side timeout retry (substring `"Gemini is slow right now"`, 3 s, once per press). [V]

---

## 3. Rule-by-rule reconstruction

| Rule (their words) | Evidence | Our implementation |
|---|---|---|
| **Exact timestamp copying** | `start_sentence`/`end_stamp` are rendered as *citations*; `dropped[]` exists at all | `check_clip` normalises and requires each sentence to be a **substring of the transcript**, and stamps to agree with the numeric fields within 2 s |
| **Duration arithmetic locks** | `duration_str` computed client-side from `start_sec`/`end_sec`, yet `duration_line` (the model's own sum) is *also* kept | both are checked: seconds span vs. window, plus the model's stated duration vs. the real span (±1 s) |
| **3-Second Deletion Gate** | named in marketing copy; the UI never shows a clickbait title for a clip whose opener is contextless | opener must not start with housekeeping (`welcome back`, `before we start`…), and must be ≥4 words |
| **Stranger test** | named in copy | prompt rule 4 + (Phase 3) an optional second-pass judge |
| **8.0 QUALITY GATE** | `"8.0 QUALITY GATE"` badge; `sweep.cleared` vs `sweep.longlist` | `avg` of the four axes ≥ 8.0, configurable `QUALITY_GATE` |
| **Wanted/Kept** | admin column | `apply_rules(..., limit=n)` returns overflow as dropped-with-reason rather than silently truncating |

**Deliberate divergence [O]:** their client classifies errors by substring (`isTimeoutError`, `isNoTimestampsError`, `isEmptyParseError`). We keep the *strings* for UI parity but expose typed exceptions (`TimeoutError_`, `NoTimestampsError`, `FormatError`) so retry logic is not coupled to English copy.

---

## 4. Prompt contract (clean-room, original wording)

Their prompt was never observable — it lives server-side and is never echoed. What we *can* pin down is the contract it must produce: the exact clip field set, four named score axes, three title flavours, `overlays[{offset,text}]`, `safety:"none"`, plus `sweep` and `longlist`. `nexcut/prompt.py` encodes exactly that contract in our own words, and makes four defensible choices:

1. **Verbatim-only citation** — the checkable rules (verbatim, arithmetic) are only enforceable if the model *copies*. Every rule we then verify is bought with that one instruction.
2. **Overlapping chunk sweep** — `plan_sweep()` walks a long video in `chunk_sec` windows with `overlap_sec` (default 600/30), which explains `sweep.ranges` as a coverage report rather than a token-truncation artefact. **[H]** but the only reading that makes `ranges` a *plural* string.
3. **Per-axis scores, not one number** — `scores.{curiosity,stakes,specificity,speed,avg}` is the observed shape; keeping it lets us retry a single weak axis instead of re-running a whole clip.
4. **Fewer clips beats padding** — explicit instruction, because the gate will drop padded clips anyway and each one costs tokens.

---

## 5. Clean-room code (all stdlib, zero dependencies)

| File | Contents |
|---|---|
| `nexcut/schema.py` | `Clip`, `Scores`, `Overlay`, `Dropped`, `SweepReport`, `OracleResult`, `WINDOWS` (A–E incl. 45–325 s), `hms()` |
| `nexcut/parse.py` | fenced/balanced-JSON extraction, `ensure_timestamps()`, tolerant `build_result()`, typed errors carrying their contract strings |
| `nexcut/validate.py` | `check_clip()` — six ordered rules returning a human drop reason; `apply_rules()` — gate + top-N + renumber + counter annotation; transcript normaliser |
| `nexcut/prompt.py` | `split_transcript()`, `plan_sweep()`, `slice_transcript()`, `build_prompt()` → `(system, user)` with the JSON output schema |
| `tests/test_pipeline.py` | 22 tests, all passing |

```
$ python3 -m unittest discover -s tests
Ran 22 tests in 0.005s — OK
```
Covered: fenced/bare JSON, prose-wrapped answers, format/no-timestamp errors, stamps without `_sec` fields, paraphrase rejection, window bound, arithmetic lock, stamp/field mismatch, 3-second gate, 8.0 gate, top-N overflow, reference-shape serialisation, chunk overlap with no gaps, chunk slicing bounds, prompt context injection.

Two rules now have **precedence** that matters operationally: arithmetic → stamps → verbatim → gate. A clip that violates two shows the first; that ordering was chosen so the reason a user sees is the one that costs least to fix.

---

## 6. What we still cannot know (and the exact test that settles it)

| Open question | Test | Who |
|---|---|---|
| Are `gemini-4-hydrogen` etc. **aliases** mapped server-side? | run `/api/diag` with a valid key and paste the literal step names/details; or trigger a model-level 404 and read the message | you |
| Exact 8.0 math: mean-of-4 vs. weighted vs. min-axis | one `oracle_report` where a clip has `avg ≥ 8` but one axis is 6 → does the server keep it? | you (one run) |
| Sweep chunk size / overlap | `sweep.ranges` from a ≥20-min video: count the ranges and compare against duration | you (one run) |
| `already_extracted` semantics | is it pasted clip titles, or timestamps, or both? its position in the deck implies "don't reuse these" | screenshot of that field's label/hint |
| Cascade ladder order & budget | HAR of a run with `cascade: true` + a deliberately bad key → watch which model/keys appear across retries | you |
| Does the server re-validate verbatim, or trust the model? | submit a clip whose sentence was paraphrased — accepted or `dropped[]`? | needs a writable path; skip unless curious |

---

## 7. Phase 3 proposal (~25 min)
**Wire it up and prove parity on real output.** A minimal FastAPI service (`/api/config`, `/api/extract`, `/api/jobs/{id}`, `/api/jobs/{id}/results`) over this core, a deliberately plain frontend shell, and a hard requirement: **feed one real `oracle_report` through our parser + gate and show what we keep vs. what they kept.** That single comparison is the acceptance test for the whole reconstruction — and it's also the thing that will tell us, empirically, how close the 8.0 math and the rule ordering are to theirs.
