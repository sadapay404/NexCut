# Phase 1 — Client Architecture & API Contract Recon
**Target:** `https://guruautomation.app/` (GURU AUTOMATION — ORACLE v25.0)
**Date:** 2026-11-20 · **Method:** public/client-side artifacts only, via out-of-band HTTP fetcher (sandbox egress to target is TLS-filtered; fetcher has independent egress).

Legend: **[V]** = verified by direct observation · **[H]** = hypothesis / inference, not yet proven.

---

## 0. Headline findings

1. **[V] There is no complex frontend.** No React/Next/Vite, no bundler, no sourcemaps. The entire client is 3 hand-written static files:
   - `index.html` — ~4,700 B
   - `static/app.js` — ~12,059 B (single IIFE-free top-level script, `"use strict"`)
   - `static/style.css` — ~8,070 B (pure CSS, custom-property theme, keyframe-only animation)
   Bundle inventory came from the Wayback CDX index for the domain (only 4 captured URLs incl. `/api/logo`). **[V]**
2. **[V] Backend is Python/FastAPI** (`openapi.json` → `{"openapi":"3.1.0","info":{"title":"GURU ORACLE v25","version":"0.1.0"}}`), serving the static frontend + `/api/*`, and by its own error copy it is designed to be **run locally via `start.bat`** and also deployed publicly. **[V]**
3. **[V] `GET /openapi.json` is publicly readable and enumerates the whole server contract** — including docstrings that leak real infrastructure decisions (SOCKS/residential proxy vendor, yt-dlp bot-check handling, caches). This is the single richest artifact we found.
4. **[V] All model calls are server-side.** The browser sends the member's Gemini key *in the request body* to `/api/extract`. The browser never talks to Google. Consequence: **prompt construction is 100% server-side and is NOT in any client artifact.** We must reconstruct it black-box (Phase 2/3).
5. **[V] ⚠️ Authorization gap on the admin API.** `GET /api/me` returned `{"member_gate":true,"admin_required":false,"admin_authed":true}` and boolean admin endpoints answered with real state (`/api/admin/cookies-status` → `{"exists":true}`, `/api/admin/server-key-status` → `{"set":false}`) **with no session cookie or password**. I deliberately did **not** call `/api/admin/members` or `/api/admin/activity` — those return invite codes (credentials) and member PII. Reported as architecture fact, not exploited.

---

## 1. Frontend & UI state architecture

### 1.1 Layout / panels
Single-page, split layout: fixed left **`.deck`** (372 px command deck) + right **`.stage`** which swaps four mutually exclusive panes via `showPane()`:

| Pane id | Shown when |
|---|---|
| `#welcomePane` | default / "← New extraction" |
| `#progressPane` | immediately on Launch; polled |
| `#errorPane` | any failure; content is rewritten by `showError()` |
| `#resultsPane` | `job.status === "done"` → `renderResults()` |

Two hard overlays sit above everything and gate interaction: `#authOverlay` (invite code) and `#lockOverlay` (local PIN). Plus two dynamically injected modals: quality picker (`.qmodal-ov`) and the 1080p cutter pane `#cutPane`. **[V]**

### 1.2 Controls (deck sections, from `buildControls()` + `wireEvents()`)
- **Niche chips** — built from `CFG.niches` (`{id, icon}`), click writes `#nicheInput.value`.
- **Sub-niche chips** — `CFG.subniches[niche]`; selecting one writes `nicheInput = "Niche — Sub"` (em-dash `\u2014`); re-clicking the active sub **clears back to the bare niche**. Sub-niche box is `display:none` when the niche has no subs (`Others: []`). **[V]**
- **Selects** — `#modelSel`, `#windowSel`, `#audienceSel`, `#langSel`, `#numClips`, all populated from `/api/config` and honouring `default_model` / `default_window`. **[V]**
- **Window `E`** toggles a hidden `#customWindow` block (`customMin` / `customMax` seconds). **[V]**
- **`#cascadeToggle`** — flips `#failoverBadge` between `FAILOVER ACTIVE` / `SINGLE ENGINE` (`.bad` class when off). Pure label; the semantic flag is `cascade` in the payload. **[V]**
- **SFX toggle / theme toggle / lock / show-hide key / remember-key / Test Connection / .txt upload / 3 sample loaders / Clear history.** **[V]**
- **Sample loaders** — three hardcoded timestamped transcripts in the bundle (`truecrime`, `sports`, `reddit`); they set niche + transcript and smooth-scroll to top. **[V]**

### 1.3 Validation rules (all client-side, all minimal)
- Launch: requires `youtube_url` **or** `transcript_text`, else `Missing input`. **[V]**
- Launch: requires a non-empty **Gemini key** (self-heals once from `localStorage.guru_api_key`), else hard-stops with "Your Gemini key is missing". A run *never* proceeds without a member key. **[V]**
- Lock PIN: first use must be ≥4 chars; afterwards plain string equality. **[V]**
- `#ytUrl` badge is cosmetic (`READY` / `AWAITING URL`) and independent of the real ID regex. **[V]**

### 1.4 Storage map — localStorage only (no sessionStorage, no IndexedDB, no app cookies) **[V]**

| Key | Written by | Contents | Notes |
|---|---|---|---|
| `guru_theme` | theme toggle | `"light"`/`"dark"` | applied as `body.light` |
| `guru_sfx` | sfx toggle | `"on"`/`"off"` | read on every `blip()` |
| `guru_lock_pin` | lock overlay | plaintext PIN | **cosmetic only** — grep/DevTools bypasses it |
| `guru_invite_code` | auth overlay | uppercased invite code | sent as `x-invite-code` on **every** API call |
| `guru_device_tag` | `getDeviceTag()` | `dev-<8 hex>` from `crypto.randomUUID()` | sent as `x-device-tag`; matches "Device" column in admin activity log |
| `guru_api_key` | remember-key checkbox | **plaintext Gemini API key** | only if "remember" checked |
| `guru_history` | `saveHistory()` | array, `slice(0,15)`, unshifted | stores full `clips[]` + `oracle_report` per run |

**Risk notes:** `guru_history` persists up to 15 complete oracle reports inline — realistically 200–600 KB+, with a hard 5 MB origin quota and no eviction strategy beyond count. `guru_api_key` is plaintext and readable by any XSS or extension; "remember" is opt-out-by-checkbox, and `restoreKey()` re-checks it automatically on load. **[V]**

### 1.5 Transport wrapper — one chokepoint
Every JSON call goes through `api(path, opts)`: adds `Content-Type: application/json`, `x-invite-code` (if stored), `x-device-tag`; parses `{detail}` for errors; and on **HTTP 403** (except from `/api/auth/verify`) it wipes `guru_invite_code`, re-shows the gate, and throws `"Invite code rejected — enter a valid code."` → mid-session revoke is handled. Non-JSON bodies degrade to `{}`. Two calls bypass `api()`: `/api/upload-transcript` (FormData, headers set by hand) and `/api/export-pdf` (blob response, headers duplicated by hand). **[V]**

---

## 2. Input ingestion

- **YouTube URL → video id:** client regex `/(?:v=|youtu\.be\/|shorts\/|live\/|embed\/)([\w-]{11})/`, guarded by `infoForId` so one fetch fires per id. 700 ms debounce on `input`, plus `change`. **[V]**
- **Metadata:** `POST /api/video-info {url}` → `{channel, title}`. Server-side uses **YouTube oEmbed** (per FastAPI docstring) — no API key, no yt-dlp. Best-effort: any failure silently leaves fields manual. **[V]**
- **Auto-fill race (fixed 2026-11-08, comment in bundle):** earlier the first fetched channel "stuck" for every later video. Now the bundle tracks `autoChannelVal`/`autoTitleVal` and clears them **only if the current value still equals what auto-fill wrote** — member-typed values are never overwritten. This is a genuinely well-designed dirty-check; worth copying. **[V]**
- **Transcript .txt/.srt/.vtt upload:** `POST /api/upload-transcript` multipart → `{text}` replaces `#transcript`. Conversion/timestamping happens **server-side**. **[V]**
- **Transcript by URL:** `POST /api/fetch-transcript {…}` exists in the API but is **not called anywhere in `app.js`** — an orphaned/legacy or admin-only route. **[V]** *(good to confirm in your HAR whether the server auto-fetches transcripts during `/api/extract`)*
- **Char counter** `updateCharBadge()` → `n.toLocaleString() CHARS`, no max length enforced. **[V]**

---

## 3. Model routing, failover, payloads

### 3.1 `POST /api/extract` — exact request body (only 14 fields) **[V]**
```json
{
  "youtube_url": "", "transcript_text": "", "niche": "True Crime",
  "audience": "U.S. English", "language": "U.S. English",
  "channel_show": "", "host_guest": "", "episode_title": "",
  "num_clips": 5, "window": "E", "custom_min_sec": null, "custom_max_sec": null,
  "model": "gemini-4-hydrogen", "cascade": true, "already_extracted": "",
  "api_key": "..."
}
```
Notes: `niche` already contains `"Niche — Sub"` when a sub-chip is picked, so the server does no sub-niche logic. `custom_*_sec` are only non-null when `window === "E"`. `already_extracted` is a free-text field we haven't mapped to UI semantics yet.

### 3.2 Job lifecycle — **polling, not SSE/WebSocket** **[V]**
`POST /api/extract` → `{job_id}` · then `setInterval(… , 2500)` on `GET /api/jobs/{job_id}` → `{progress, stage, status: "done"|"error", error}` · on done → `GET /api/jobs/{job_id}/results`. No `EventSource`, no `WebSocket` anywhere in the bundle. `stage` is rendered verbatim into `#stageText` — the server literally drives the UX copy.

### 3.3 Failover, as observable
- **Two layers.** Client has exactly one retry rule; the server does the model cascade (`cascade: true`). **[V]**
- **Client retry:** only when `error` contains the substring **`"Gemini is slow right now"`** → wait 3 s, call `launch(true)` **once** per manual press (`AUTO_RETRY_USED` latch). Dead key / bad transcript / unparseable answer never auto-retry. **[V]**
- **Server failover:** admin panel documents a **"Server Backup Gemini Key"** used automatically when a member's own key hits its daily limit ("so nobody goes back empty-handed"), and `/api/admin/server-key-status` currently reports `{"set": false}`. Together with the `cascade` flag this is our best evidence for 429/quota failover and cross-model retry. **[V]** for the mechanism's existence, **[H]** for the exact retry ladder.
- **CFG model list (live, `/api/config`):** `gemini-4-hydrogen` (default), `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`, `gemini-3.6-flash`, `gemini-3.8-flash`, `gemini-3.1-pro-preview`. **[H]** these are almost certainly **server-side aliases** mapped to real model IDs (naming is inconsistent with public Gemini naming); needs confirming via `/api/diag` output or a 404-style error that names the real model.

### 3.4 Error taxonomy — string matching, not codes **[V]**
The client classifies failures by substring, which means these strings are a **server contract** and a good fingerprint of the server's internal checks:

| Matcher | Meaning | What it proves about the server |
|---|---|---|
| `"Gemini is slow right now"` | timeout | request timeout wrapper exists |
| `"NO TIMESTAMPS"` / `"no timestamps in the transcript"` | pre-flight transcript check | server validates timestamp presence before spending tokens |
| `"not in the clip-report format"` | JSON/shape parse failure | server enforces a "clip-report" output format |

---

## 4. Output shape, parsing, post-processing

`GET /api/jobs/{id}/results` returns **[V]**:
```json
{ "sweep": {"window": "", "ranges": "", "longlist": "", "cleared": ""},
  "longlist": [{"start": "", "gist": ""}],
  "clips": [ { "n": 1, "hook_summary": "", "start_sec": 0, "start_stamp": "", "start_sentence": "",
               "end_stamp": "", "end_sentence": "", "duration_str": "", "duration_line": "",
               "titles": {"clickbait": "", "search": "", "debate": ""},
               "scores": {"curiosity": 0, "stakes": 0, "specificity": 0, "speed": 0, "avg": 0},
               "verbal_hook": "", "ending": "", "why_it_works": "", "share_trigger": "",
               "safety": "none", "overlays": [{"offset": "", "text": ""}],
               "sfx": "", "captions": "", "upload_caption": "", "hashtags": "",
               "pinned_comment": "", "transcript_ts": "", "transcript": "" } ],
  "dropped": [{"clip": 1, "reason": ""}],
  "oracle_report": "", "video_id": "", "video_title": "", "window_label": "" }
```

- **The server does the parsing/validation**, not the client. `clips[]` arrives pre-structured; `dropped[]` is the server's own rule-check rejections with human-readable reasons; `oracle_report` is the **raw model text** kept for transparency and dumped into a `<pre>` on both results and error screens. **[V]**
- **Two-stage discriminator:** `sweep.longlist` (candidates found) vs `sweep.cleared` (passed the gate) vs `clips.length` (delivered) vs `dropped.length` — i.e. the server pipeline is **sweep → longlist → 8.0 gate → rule check → deliver**. Marketing copy corroborates: *"3-Second Deletion Gate, stranger tests, exact timestamp copying, duration arithmetic locks"* and *"8.0 QUALITY GATE"*. **[V]** for the counters, **[H]** for the exact gate math.
- **Rendering** is `innerHTML` template strings with an `esc()` helper applied to nearly every interpolated value — **but not universally**: `frow(label, value, copyText)` inserts `copyText` into `data-copy="…"` unescaped, `overlays` injects `esc(o.offset)`+`esc(o.text)` inside markup, and hashtags are split on `/[\s,]+/` then re-prefixed with `#`. Model-generated text is therefore treated as semi-trusted markup. **[V]**
- **Exports:** PDF is a **server render** (`POST /api/export-pdf` with the whole results object + niche + locale date → blob); report `.txt` and clip-transcript `.txt` are client-side `Blob` downloads; "Copy all" copies `oracle_report`. Plus `GET /api/export/{job_id}` on the server. **[V]**
- **1080p cutter (separate pipeline, own state machine):** `GET /api/video-quality/{video_id}` → `{qualities:[int]}`, **never below 1080**, one retry 800 ms apart, falls back to `[1080]` server-side instead of erroring; picker labels `2160+` as "4K"; `POST /api/jobs/{id}/cut {height}` → `cut_id` (or `/cut-one {clip_n, height}`) then poll `GET /api/cuts/{cut_id}` every 2000 ms → `{progress, stage, quality, status, files:[{clip,name,start,end,size_mb}]}`; download via `GET /api/cuts/{cut_id}/file/{name}?code=<invite>` because plain `<a>` can't send headers. Files retained **14 days**. Source video is downloaded once per YouTube video and cached. **[V]**

---

## 5. Full recovered API surface (from `openapi.json`) **[V]**

| Area | Endpoints |
|---|---|
| Auth | `GET /api/me` · `POST /api/login` (admin, `APP_PASSWORD`) · `POST /api/logout` · `POST /api/auth/verify` |
| Config | `GET /api/config` (public, no code) |
| Ingest | `POST /api/video-info` (oEmbed) · `POST /api/fetch-transcript` (unused by UI) · `POST /api/upload-transcript` (multipart) · `POST /api/diag` (DNS→TCP→TLS→key) |
| Extract | `POST /api/extract` · `GET /api/jobs/{id}` · `GET /api/jobs/{id}/results` · `GET /api/export/{id}` · `POST /api/export-pdf` |
| Cut | `GET /api/video-quality/{video_id}` · `POST /api/jobs/{id}/cut` · `POST /api/jobs/{id}/cut-one` · `GET /api/cuts/{id}` · `GET /api/cuts/{id}/file/{filename}?code=` |
| Admin | `GET/POST /api/admin/members` · `…/{code}/revoke` · `…/{code}/unrevoke` · `POST /api/admin/cookies` · `GET /api/admin/cookies-status` · `POST/DELETE /api/admin/logo` · `GET /api/admin/logo-status` · `GET/POST /api/admin/server-key` (+`-status`) · `GET /api/admin/activity?member&day&limit=200` · `GET /api/admin/summary` · `GET /api/admin/sheet` · `POST /api/admin/sheet-webhook` · `GET/POST /api/admin/proxy` · `POST /api/admin/sync-now` |
| Pages | `GET /` · `GET /admin` (separate console UI) · `GET /api/logo` (+`HEAD` — added 2026-11-08 because HEAD returned 405 and hid the header avatar) |

**Infrastructure leaked by docstrings** (this is the most valuable server intel we have, all **[V]** as quoted text):
- **Residential proxy** for YouTube (`"IPRoyal etc. Format: http://user:pass@host:port"`), settable at runtime via `/api/admin/proxy` — no restart.
- **`cookies.txt` upload** to defeat `LOGIN_REQUIRED` / "Sign in to confirm you're not a bot"; `/api/admin/cookies-status` currently `exists: true`.
- Named caches: **`QUALITY_CACHE`** (never stores the 1080p fallback) and **`BOT_CACHE`** ("the retry takes the BOT_CACHE → browser path"), implying a headless-browser download fallback path after yt-dlp fails.
- **Google Sheets sync**: Apps Script Web App webhook + `SHEET_SECRET` + `DIGEST_EMAIL`, `sendDailyDigest` trigger 9–10 pm, `POST /api/admin/sync-now`.
- **Telemetry per run** (admin activity table columns): `Time (PKT) | Member | Video | Niche | Wanted/Kept | Model | Key | IP | Device | Flags` → server logs IP + `x-device-tag` + which key tier was used + wanted-vs-kept clip counts. `Wanted/Kept` confirms the drop-by-rule-check is a first-class metric.

---

## 6. Verification status of the big open question: the prompt

**Not recoverable from the client — by construction.** The browser never sees the prompt; the key, transcript, and parameters go to the server, and only structured results + raw model text come back. Three indirect routes remain:

1. **`oracle_report`** — raw model output. Its exact headings/ordering is the output contract the prompt demands; reversing that gives us ~70% of the prompt skeleton. Needs one real run.
2. **`dropped[].reason` strings** — the server's own rule-check vocabulary; each reason maps to a prompt instruction.
3. **Error strings** (`NO TIMESTAMPS`, `not in the clip-report format`) — confirm a strict format contract and a pre-flight check.

The three "sweep/longlist/gate" stages plus the marketing rules ("3-Second Deletion Gate", "stranger tests", "exact timestamp copying", "duration arithmetic locks", "8.0 quality gate") give us the required *behaviour*, which is what we actually need to re-implement — clean-room, from behaviour, not from copied text.

---

## 7. What I need from you (Phase 1 asks)

Priority order — even **1–3** unblocks Phase 2 entirely.

1. **One real run HAR** (DevTools → Network → "Preserve log" → run one small extraction → right-click → *Save all as HAR*). I need the bodies of `POST /api/extract`, every `GET /api/jobs/*`, and `GET /api/jobs/*/results`. Redact your API key and invite code — I need shape, not secrets.
2. **One clip's raw JSON** from `/api/jobs/{id}/results` + the **full `oracle_report`** (trim the middle if long). This is the highest-value artifact in the whole project: it defines the output contract the prompt enforces.
3. **Confirm the key never leaves for Google:** after a run, filter Network by `googleapis` — expect **zero** requests. I want that verified, not assumed.
4. **Console dump:** `Object.entries(localStorage)` (mask the key) — confirms no storage keys beyond the 7 mapped above.
5. **Raw `index.html`:** Ctrl+U → select all → save as `index.raw.html` and drop it in this repo. My fetcher re-renders HTML to markdown, so I have every element **id** from `app.js`/CSS but not the literal markup/copy. Also: full-page screenshot of the deck at 1440 px for clone fidelity.
6. **Response headers** of `/` (DevTools → Network → Headers): looking for `server:`, `cf-ray`, `via` — confirms Cloudflare Tunnel vs VPS vs PaaS.
7. **`/api/diag` output** with a real key (it prints one step per DNS/TCP/TLS/key check) — this is our only lens on the model aliases; I want the literal step names/details.
8. **Test the gate from a clean profile:** in a fresh incognito window, does `POST /api/extract` return **403** without an invite code? Paste the status + `detail`.
9. **[Security, non-urgent]** Please tell the site owner: `/api/me` reports `admin_authed: true` and boolean `/api/admin/*` endpoints answer unauthenticated. I stopped at booleans and did **not** touch `/api/admin/members` or `/api/admin/activity` (invite codes + member PII). A one-line "is the admin gate actually enforced?" probe from *your* browser with a clean profile would confirm it without us pulling any data.

---

## 8. Phase 2 preview (after your go-ahead)
Black-box prompt/behaviour reconstruction: build the output contract from `oracle_report` + `dropped[]`, derive the sweep→gate→clip pipeline as explicit rules, and specify a clean-room schema + validation layer for NexCut. Plus resolve the two open hypotheses: model alias mapping and the real cascade ladder.
