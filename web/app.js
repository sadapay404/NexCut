/* SAA Clip Studio — client
   Plain DOM, no framework. Model output is written with textContent only.
   Every render path is wrapped so a bad payload shows a readable error instead
   of a blank screen. */
"use strict";

const $ = (id) => document.getElementById(id);

const SAMPLE = `00:00:00 - Nobody talks about what happened on the third floor.
00:00:09 - The night manager logged the door as locked at 11:40.
00:00:17 - The camera shows it opening at 11:52.
00:00:26 - He told investigators he never left the desk.
00:00:34 - So who used his badge during the twelve minutes he cannot explain?
00:00:45 - A guest reported hearing two voices in an empty corridor.
00:00:54 - The badge reader logged a second entry at 12:04.
00:01:03 - That badge belonged to a man who had been off shift for two weeks.
00:01:12 - Nobody has been able to explain that part.
00:01:21 - The hotel settled the case before it reached a courtroom.`;

const STATE = {
  cfg: null,
  tools: null,
  jobId: null,
  result: null,
  payload: null,
  selected: 0,
  view: "clips",
  timers: { fetch: null, poll: null, cut: null },
};

/* ── small helpers ───────────────────────────────────── */
async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.detail || `HTTP ${res.status}`);
    err.hint = data.hint || "";
    throw err;
  }
  return data;
}

function hms(sec) {
  const s = Math.max(0, Math.round(Number(sec) || 0));
  return [Math.floor(s / 3600), Math.floor((s % 3600) / 60), s % 60]
    .map((n) => String(n).padStart(2, "0")).join(":");
}

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = String(text);
  return n;
}

function hint(node, text, kind) {
  node.textContent = text;
  node.className = "hint" + (kind ? " " + kind : "");
}

function badge(wrap, textNode, text, kind) {
  textNode.textContent = text;
  wrap.className = "badge" + (kind ? " " + kind : "");
}

function status(text, detail) {
  $("statusText").textContent = text;
  $("statusHint").textContent = detail || "";
}

function toast(message) {
  const box = $("toasts");
  const node = el("div", "toast", message);
  box.appendChild(node);
  setTimeout(() => node.remove(), 1900);
}

function copy(text) {
  navigator.clipboard.writeText(text).then(
    () => toast("Copied"),
    () => toast("Copy blocked by browser")
  );
}

/* ── boot ────────────────────────────────────────────── */
document.addEventListener("DOMContentLoaded", boot);

async function boot() {
  if (localStorage.getItem("saa_theme") === "light") document.body.classList.add("light");

  try {
    STATE.cfg = await api("/api/config");
  } catch (e) {
    renderFatal("Server unreachable", e.message,
      "Start the studio with: python3 -m nexcut.server");
    return;
  }

  STATE.tools = STATE.cfg.tools || { can_cut: false, hints: {} };

  const stub = STATE.cfg.provider === "stub";
  badge($("providerBadge"), $("providerText"), stub ? "offline demo" : STATE.cfg.provider,
    stub ? "warn" : "ok");
  const master = !!(STATE.cfg.prompt && STATE.cfg.prompt.master_loaded);
  badge($("promptBadge"), $("promptText"), master ? "master.md" : "built-in", master ? "ok" : "warn");
  badge($("toolsBadge"), $("toolsText"), STATE.tools.can_cut ? "ready" : "unavailable",
    STATE.tools.can_cut ? "ok" : "bad");

  $("statusProvider").textContent = STATE.cfg.provider || "";
  $("statusVersion").textContent = STATE.cfg.version || "";
  hint($("providerNote"), stub
    ? "Offline demo provider — no key required."
    : "Key is used for this run only.");

  buildControls();
  wire();
  restoreKey();
  updateCounts();
  renderEmpty();
  status("Ready");
}

function buildControls() {
  const niche = $("nicheSel");
  (STATE.cfg.niches || []).forEach((n) => niche.appendChild(new Option(n.id, n.id)));
  if (niche.options.length) { niche.value = niche.options[0].value; fillSubs(niche.value); }

  (STATE.cfg.audiences || []).forEach((x) => $("audienceSel").appendChild(new Option(x, x)));
  (STATE.cfg.languages || []).forEach((x) => $("langSel").appendChild(new Option(x, x)));
  (STATE.cfg.models || []).forEach((x) => $("modelSel").appendChild(new Option(x.label || x.id, x.id)));
  (STATE.cfg.windows || []).forEach((x) => $("windowSel").appendChild(new Option(x.label || x.id, x.id)));

  if (STATE.cfg.default_window) $("windowSel").value = STATE.cfg.default_window;
  if (STATE.cfg.default_model) $("modelSel").value = STATE.cfg.default_model;
}

function fillSubs(base) {
  const sel = $("subSel");
  const subs = (STATE.cfg.subniches || {})[base] || [];
  sel.textContent = "";
  sel.appendChild(new Option("—", ""));
  subs.forEach((s) => sel.appendChild(new Option(s, s)));
  $("subWrap").hidden = subs.length === 0;
  sel.value = "";
}

function nicheValue() {
  const base = $("nicheSel").value;
  const sub = $("subSel").value;
  return sub ? `${base} — ${sub}` : base;
}

/* ── wiring ──────────────────────────────────────────── */
function wire() {
  $("themeBtn").onclick = () => {
    const light = document.body.classList.toggle("light");
    localStorage.setItem("saa_theme", light ? "light" : "dark");
  };

  $("nicheSel").onchange = () => fillSubs($("nicheSel").value);

  $("ytUrl").addEventListener("input", () => {
    clearTimeout(STATE.timers.fetch);
    const url = $("ytUrl").value.trim();
    if (!url) { hint($("sourceState"), "No source"); return; }
    hint($("sourceState"), "Reading link…");
    STATE.timers.fetch = setTimeout(() => fetchCaptions(url), 700);
  });

  $("transcript").addEventListener("input", updateCounts);
  $("sampleBtn").onclick = () => {
    $("transcript").value = SAMPLE;
    $("transcriptFold").open = true;
    updateCounts();
    hint($("sourceState"), "Sample transcript loaded", "ok");
  };
  $("uploadBtn").onclick = () => $("fileInput").click();
  $("fileInput").onchange = uploadFile;

  $("showKey").onclick = () => {
    const field = $("apiKey");
    const hidden = field.type === "password";
    field.type = hidden ? "text" : "password";
    $("showKey").textContent = hidden ? "Hide" : "Show";
  };
  $("apiKey").addEventListener("input", () => {
    if ($("rememberKey").checked) localStorage.setItem("saa_key", $("apiKey").value);
  });
  $("rememberKey").onchange = () => {
    if ($("rememberKey").checked) localStorage.setItem("saa_key", $("apiKey").value);
    else localStorage.removeItem("saa_key");
  };

  $("windowSel").onchange = () => {
    const custom = $("windowSel").value === "E";
    $("customMinWrap").hidden = !custom;
    $("customMaxWrap").hidden = !custom;
  };

  $("runBtn").onclick = run;
  $("cutBtn").onclick = startCut;
  $("newRunBtn").onclick = () => { showPane("emptyPane"); renderEmpty(); };

  $("copyJsonBtn").onclick = () => {
    if (STATE.result) copy(STATE.result.oracle_report || "");
  };
  $("downloadBtn").onclick = () => {
    if (!STATE.result) return;
    const blob = new Blob([STATE.result.oracle_report || ""], { type: "text/plain" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `clips-${STATE.result.video_id || "session"}.txt`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 3000);
    toast("Download started");
  };

  $("segTabs").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-view]");
    if (btn) setView(btn.dataset.view);
  });

  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-copy]");
    if (!btn) return;
    copy(btn.dataset.copy);
  });

  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      if (!$("runBtn").disabled) run();
    }
  });
}

function restoreKey() {
  const key = localStorage.getItem("saa_key");
  if (!key) return;
  $("apiKey").value = key;
  $("rememberKey").checked = true;
}

function updateCounts() {
  const text = $("transcript").value;
  const lines = text ? text.split(/\r?\n/).filter((x) => x.trim()).length : 0;
  $("charBadge").textContent = text ? `${lines} lines` : "empty";
}

async function uploadFile() {
  const file = $("fileInput").files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  try {
    const res = await fetch("/api/upload-transcript", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Upload failed");
    $("transcript").value = data.text;
    $("transcriptFold").open = true;
    updateCounts();
    hint($("sourceState"), `${file.name} — ${data.chars.toLocaleString()} characters`, "ok");
  } catch (e) {
    hint($("sourceState"), e.message, "bad");
  }
  $("fileInput").value = "";
}

async function fetchCaptions(url) {
  hint($("sourceState"), "Fetching captions…");
  status("Fetching captions");
  try {
    const data = await api("/api/transcript", { method: "POST", body: JSON.stringify({ url }) });
    $("transcript").value = data.text;
    $("transcriptFold").open = false;
    updateCounts();
    const kind = data.is_auto ? "auto" : "published";
    hint($("sourceState"), `${kind} captions · ${data.lines} lines · ${hms(data.seconds)}`, "ok");
    status("Captions ready", `${data.lines} lines`);
    if (data.title) document.title = `${data.title} — Clip Studio`;
  } catch (e) {
    hint($("sourceState"), [e.message, e.hint].filter(Boolean).join(" "), "bad");
    status("Captions unavailable", e.message);
    $("transcriptFold").open = true;
  }
}

/* ── panes ───────────────────────────────────────────── */
const PANES = ["emptyPane", "progressPane", "errorPane", "resultsPane"];

function showPane(id) {
  PANES.forEach((p) => { $(p).hidden = p !== id; });
}

function renderEmpty() {
  let last = null;
  try { last = JSON.parse(localStorage.getItem("saa_last") || "null"); } catch { last = null; }

  $("emptyTitle").textContent = last ? "Last session" : "No session";
  $("emptyNote").textContent = last
    ? "Start a new extraction from the sidebar."
    : "Paste a YouTube URL to fetch captions and run an extraction.";

  const table = $("metaTable");
  table.textContent = "";
  if (!last) { table.hidden = true; return; }
  [
    ["Niche", last.niche],
    ["Kept", `${last.clips} of ${last.requested} requested`],
    ["Rejected", String(last.rejected)],
    ["Model", last.model],
    ["Source", last.source],
    ["When", last.at],
  ].forEach(([k, v]) => {
    if (!v) return;
    const tr = el("tr");
    tr.appendChild(el("td", null, k));
    tr.appendChild(el("td", null, v));
    table.appendChild(tr);
  });
  table.hidden = false;
}

function renderError(title, message, detail) {
  showPane("errorPane");
  const pane = $("errorPane");
  pane.textContent = "";

  const wrap = el("div", "err-wrap bad");
  const head = el("div", "err-head");
  head.appendChild(el("div", "ico", "!"));
  head.appendChild(el("h1", null, title));
  wrap.appendChild(head);
  wrap.appendChild(el("p", "err-msg", message));
  if (detail) wrap.appendChild(el("div", "err-hint", detail));

  const actions = el("div");
  actions.style.display = "flex";
  actions.style.gap = "7px";
  const back = el("button", "btn small", "Back");
  back.onclick = () => showPane("emptyPane");
  actions.appendChild(back);
  wrap.appendChild(actions);

  pane.appendChild(wrap);
  status("Failed", title);
}

function renderFatal(title, message, detail) {
  renderError(title, message, detail);
  $("runBtn").disabled = true;
}

/* ── extraction ──────────────────────────────────────── */
function readPayload() {
  const custom = $("windowSel").value === "E";
  return {
    youtube_url: $("ytUrl").value.trim(),
    transcript_text: $("transcript").value.trim(),
    niche: nicheValue(),
    audience: $("audienceSel").value,
    language: $("langSel").value,
    num_clips: parseInt($("numClips").value, 10) || 5,
    window: $("windowSel").value,
    custom_min_sec: custom ? (parseInt($("customMin").value, 10) || null) : null,
    custom_max_sec: custom ? (parseInt($("customMax").value, 10) || null) : null,
    model: $("modelSel").value,
    cascade: $("cascadeToggle").checked,
    already_extracted: $("alreadyExtracted").value.trim(),
    api_key: $("apiKey").value.trim(),
  };
}

async function run() {
  const payload = readPayload();
  if (!payload.youtube_url && !payload.transcript_text) {
    hint($("sourceState"), "Paste a URL or load a transcript first.", "bad");
    $("ytUrl").focus();
    return;
  }

  STATE.payload = payload;
  STATE.result = null;
  STATE.jobId = null;
  $("runBtn").disabled = true;
  showPane("progressPane");
  $("stageLog").textContent = "";
  $("barFill").style.width = "2%";
  $("pctText").textContent = "0%";
  $("stageText").textContent = "Queued";
  status("Running", payload.niche);

  try {
    const { job_id } = await api("/api/extract", { method: "POST", body: JSON.stringify(payload) });
    STATE.jobId = job_id;
    pollJob(job_id);
  } catch (e) {
    $("runBtn").disabled = false;
    renderError("Run could not start", e.message, e.hint);
  }
}

function pollJob(jobId) {
  clearInterval(STATE.timers.poll);
  let lastPct = -1;

  STATE.timers.poll = setInterval(async () => {
    let job;
    try {
      job = await api(`/api/jobs/${jobId}`);
    } catch (e) {
      clearInterval(STATE.timers.poll);
      $("runBtn").disabled = false;
      renderError("Lost contact with the server", e.message);
      return;
    }

    const pct = Math.round(job.progress || 0);
    $("barFill").style.width = pct + "%";
    $("pctText").textContent = pct + "%";
    $("stageText").textContent = job.stage || "Working";
    $("statusElapsed").textContent = job.elapsed_s ? `${job.elapsed_s}s` : "";

    if (pct !== lastPct) {
      lastPct = pct;
      $("stageLog").textContent += `${String(pct).padStart(3, " ")}%  ${job.stage}\n`;
      $("stageLog").scrollTop = $("stageLog").scrollHeight;
    }

    if (job.status === "done") {
      clearInterval(STATE.timers.poll);
      $("runBtn").disabled = false;
      try {
        const result = await api(`/api/jobs/${jobId}/results`);
        STATE.result = result;
        renderResults(result, STATE.payload, job);
        saveLast(result, STATE.payload);
      } catch (e) {
        renderError("Results unreadable", e.message, "The job finished but the payload failed to render.");
      }
    } else if (job.status === "error") {
      clearInterval(STATE.timers.poll);
      $("runBtn").disabled = false;
      renderError(titleFor(job.error), job.error || "Unknown error", job.error_hint);
    }
  }, 1000);
}

function titleFor(message) {
  const m = message || "";
  if (m.includes("NO TIMESTAMPS")) return "Transcript has no timestamps";
  if (m.includes("clip-report")) return "Answer was not valid JSON";
  if (m.includes("slow right now")) return "Model timed out";
  if (/api key/i.test(m)) return "API key rejected";
  if (/caption/i.test(m)) return "Captions unavailable";
  return "Run failed";
}

/* ── results ─────────────────────────────────────────── */
function renderResults(data, payload, job) {
  showPane("resultsPane");

  const clips = data.clips || [];
  const rejected = data.dropped || [];
  STATE.selected = 0;

  $("resTitle").textContent = data.video_title || "Transcript session";
  $("resMeta").textContent = [
    data.video_id ? `id ${data.video_id}` : "",
    data.channel || "",
    data.transcript_source ? `captions ${data.transcript_source}` : "",
    data.model_used ? `model ${data.model_used}` : "",
    data.ranges_planned ? `coverage ${data.ranges_planned}` : "",
    job && job.elapsed_s ? `${job.elapsed_s}s` : "",
  ].filter(Boolean).join("  ·  ");

  const candidates = (data.sweep && data.sweep.longlist) || (data.longlist || []).length;
  $("statCandidates").textContent = candidates;
  $("statKept").textContent = clips.length;
  $("statRejected").textContent = rejected.length;
  $("statRequested").textContent = payload.num_clips;
  $("tabClipsN").textContent = clips.length;
  $("tabRejectedN").textContent = rejected.length;

  /* clip table */
  const rows = $("clipRows");
  rows.textContent = "";
  clips.forEach((clip, index) => {
    const tr = el("tr");
    tr.setAttribute("aria-selected", index === 0 ? "true" : "false");
    tr.appendChild(el("td", "c-n", clip.n));
    tr.appendChild(el("td", "c-time", clip.start_stamp || hms(clip.start_sec)));
    tr.appendChild(el("td", "c-time", clip.end_stamp || hms(clip.end_sec)));
    tr.appendChild(el("td", "c-dur", clip.duration_str || ""));
    const avgCell = el("td", "c-avg");
    const avg = clip.scores && clip.scores.avg;
    avgCell.appendChild(el("span", "avg-pill" + (avg >= 8 ? " hi" : ""), avg == null ? "—" : avg));
    tr.appendChild(avgCell);
    tr.appendChild(el("td", "c-hook", clip.hook_summary || ""));
    tr.onclick = () => selectClip(index);
    rows.appendChild(tr);
  });
  $("clipsEmpty").hidden = clips.length > 0;

  /* rejected */
  const list = $("rejectedList");
  list.textContent = "";
  rejected.forEach((item) => {
    const li = el("li");
    li.appendChild(el("span", "idx", `#${item.clip}`));
    li.appendChild(el("span", null, item.reason));
    list.appendChild(li);
  });
  $("rejectedEmpty").hidden = rejected.length > 0;

  $("rawAnswer").textContent = data.oracle_report || "";

  setView("clips");
  selectClip(0);
  setupExport(data);
  status(`${clips.length} of ${payload.num_clips} kept`, `${rejected.length} rejected`);
}

function selectClip(index) {
  const clips = (STATE.result && STATE.result.clips) || [];
  const clip = clips[index];
  STATE.selected = index;

  Array.from($("clipRows").children).forEach((tr, i) => {
    tr.setAttribute("aria-selected", i === index ? "true" : "false");
  });

  $("inspTitle").textContent = clip ? `Clip ${clip.n}` : "No clip selected";
  $("inspTime").textContent = clip
    ? `${clip.start_stamp || hms(clip.start_sec)} → ${clip.end_stamp || hms(clip.end_sec)}`
    : "";

  const body = $("inspBody");
  body.textContent = "";
  if (!clip) {
    body.appendChild(el("p", "hint", "Select a clip to inspect it."));
    return;
  }

  const scores = el("div", "scores");
  Object.entries(clip.scores || {}).forEach(([k, v]) => {
    if (v == null) return;
    scores.appendChild(el("span", k === "avg" ? "hi" : "", `${k} ${v}`));
  });
  if (scores.children.length) body.appendChild(field("scores", scores, true));

  const t = clip.titles || {};
  const rows = [
    ["hook", clip.hook_summary, false, clip.hook_summary],
    ["opens", `[${clip.start_stamp}] ${clip.start_sentence}`, true, clip.start_sentence],
    ["ends", `[${clip.end_stamp}] ${clip.end_sentence}`, true, clip.end_sentence],
    ["length", `${clip.duration_str || ""}${clip.duration_line ? " · " + clip.duration_line : ""}`],
    ["clickbait", t.clickbait, false, t.clickbait],
    ["search", t.search, false, t.search],
    ["debate", t.debate, false, t.debate],
    ["verbal hook", clip.verbal_hook, false, clip.verbal_hook],
    ["ending", clip.ending],
    ["why", clip.why_it_works],
    ["share", clip.share_trigger],
    ["overlays", (clip.overlays || []).map((o) => `${o.offset}  ${o.text}`).join("\n"), true],
    ["sfx", clip.sfx],
    ["captions", clip.captions],
    ["upload text", clip.upload_caption, false, clip.upload_caption],
    ["hashtags", clip.hashtags, true, clip.hashtags],
    ["pinned", clip.pinned_comment, false, clip.pinned_comment],
    ["safety", clip.safety && String(clip.safety).toLowerCase() !== "none" ? clip.safety : ""],
  ];
  rows.forEach(([k, v, mono, copyText]) => {
    const node = field(k, v, mono, copyText);
    if (node) body.appendChild(node);
  });
}

function field(key, value, mono, copyText) {
  if (value === undefined || value === null || value === "") return null;
  const row = el("div", "irow");
  row.appendChild(el("div", "k", key));

  if (value instanceof Node) {
    const cell = el("div", "v");
    cell.appendChild(value);
    row.appendChild(cell);
    return row;
  }

  const cell = el("div", "v" + (mono ? " mono" : ""));
  cell.appendChild(document.createTextNode(String(value)));
  if (copyText) {
    const btn = el("button", "copy", "copy");
    btn.type = "button";
    btn.dataset.copy = copyText;
    cell.appendChild(btn);
  }
  row.appendChild(cell);
  return row;
}

function setView(view) {
  STATE.view = view;
  $("viewClips").hidden = view !== "clips";
  $("viewRejected").hidden = view !== "rejected";
  $("viewRaw").hidden = view !== "raw";
  Array.from($("segTabs").children).forEach((btn) => {
    btn.setAttribute("aria-selected", btn.dataset.view === view ? "true" : "false");
  });
}

/* ── export / cut ────────────────────────────────────── */
function setupExport(data) {
  const clips = data.clips || [];
  const canCut = STATE.tools.can_cut && data.video_id && clips.length;
  $("cutBtn").disabled = !canCut;
  $("fileList").textContent = "";
  $("cutFill").style.width = "0%";
  $("exportQuality").textContent = "";

  if (!STATE.tools.can_cut) {
    hint($("cutState"), "Needs ffmpeg and yt-dlp on PATH.", "warn");
    $("qualitySel").textContent = "";
    $("qualitySel").appendChild(new Option("unavailable", ""));
    return;
  }
  if (!data.video_id) {
    hint($("cutState"), "Pasted transcript — no source video to cut.", "warn");
    $("qualitySel").textContent = "";
    $("qualitySel").appendChild(new Option("n/a", ""));
    return;
  }

  const sel = $("qualitySel");
  sel.textContent = "";
  sel.appendChild(new Option("checking…", ""));
  sel.disabled = true;
  hint($("cutState"), "Reading available qualities…");

  api(`/api/video-quality/${encodeURIComponent(data.video_id)}`)
    .then((res) => {
      sel.textContent = "";
      const min = STATE.cfg.min_height || 1080;
      const heights = (res.qualities || []).filter((q) => q >= min);
      (heights.length ? heights : [min]).forEach((q) => {
        sel.appendChild(new Option(q >= 2160 ? `${q}p · 4K` : `${q}p`, String(q)));
      });
      sel.disabled = false;
      hint($("cutState"), "Ready.", "ok");
    })
    .catch((e) => {
      sel.textContent = "";
      sel.appendChild(new Option("unavailable", ""));
      sel.disabled = true;
      hint($("cutState"), e.message + (e.hint ? " — " + e.hint : ""), "warn");
    });
}

async function startCut() {
  if (!STATE.jobId || !STATE.result || !STATE.tools.can_cut) return;
  const sel = $("qualitySel");
  const height = sel && sel.value ? parseInt(sel.value, 10) : (STATE.cfg.min_height || 1080);

  $("cutBtn").disabled = true;
  $("fileList").textContent = "";
  $("cutFill").style.width = "0%";
  hint($("cutState"), "Downloading source…");
  status("Cutting", `${height}p`);

  try {
    const { cut_id } = await api(`/api/jobs/${STATE.jobId}/cut`, {
      method: "POST",
      body: JSON.stringify({ height }),
    });
    pollCut(cut_id);
  } catch (e) {
    $("cutBtn").disabled = false;
    hint($("cutState"), [e.message, e.hint].filter(Boolean).join(" — "), "bad");
    status("Cut failed", e.message);
  }
}

function pollCut(cutId) {
  clearInterval(STATE.timers.cut);
  STATE.timers.cut = setInterval(async () => {
    let cut;
    try {
      cut = await api(`/api/cuts/${cutId}`);
    } catch (e) {
      clearInterval(STATE.timers.cut);
      $("cutBtn").disabled = false;
      hint($("cutState"), e.message, "bad");
      return;
    }

    $("cutFill").style.width = `${cut.progress || 0}%`;
    hint($("cutState"), `${cut.progress || 0}% · ${cut.stage}`);
    $("exportQuality").textContent = cut.quality || "";

    if (cut.status === "done") {
      clearInterval(STATE.timers.cut);
      $("cutBtn").disabled = false;
      hint($("cutState"), `${cut.files.length} file(s) · ${cut.quality || ""}`, "ok");
      renderFiles(cut.files || []);
      status("Cut complete", `${cut.files.length} files`);
    } else if (cut.status === "error") {
      clearInterval(STATE.timers.cut);
      $("cutBtn").disabled = false;
      hint($("cutState"), cut.error || "Cut failed", "bad");
      status("Cut failed", cut.error || "");
    }
  }, 1200);
}

function renderFiles(files) {
  const list = $("fileList");
  list.textContent = "";
  files.forEach((file) => {
    const li = el("li");
    li.appendChild(el("span", "fname", file.name));
    li.appendChild(el("span", "fsize", `${file.size_mb} MB`));
    const a = el("a", null, "save");
    a.href = file.url;
    a.setAttribute("download", file.name);
    li.appendChild(a);
    list.appendChild(li);
  });
}

/* ── last session ────────────────────────────────────── */
function saveLast(result, payload) {
  try {
    localStorage.setItem("saa_last", JSON.stringify({
      at: new Date().toLocaleString(),
      niche: payload.niche,
      clips: (result.clips || []).length,
      requested: payload.num_clips,
      rejected: (result.dropped || []).length,
      model: result.model_used || payload.model,
      source: result.transcript_source || "pasted",
    }));
  } catch { /* storage blocked — not essential */ }
}
