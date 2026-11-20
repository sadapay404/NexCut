/* SAA Clip Studio — client.
   Plain DOM. Model output is written with textContent only.
   Every render path is wrapped so a bad payload shows a readable error card. */
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

const S = {
  cfg: null,
  tools: null,
  jobId: null,
  result: null,
  payload: null,
  selected: 0,
  view: "clips",
  caption: { state: "idle", detail: "No link" },
  timers: { fetch: null, poll: null, cut: null },
};

/* ── helpers ─────────────────────────────────────────── */
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

const hms = (sec) => {
  const s = Math.max(0, Math.round(Number(sec) || 0));
  return [Math.floor(s / 3600), Math.floor((s % 3600) / 60), s % 60]
    .map((n) => String(n).padStart(2, "0")).join(":");
};

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = String(text);
  return n;
}

function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "ic");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#i-${name}`);
  svg.appendChild(use);
  return svg;
}

function note(node, text, kind) {
  node.textContent = text;
  node.className = "note" + (kind ? " " + kind : "");
}

function pill(wrap, textNode, text, kind) {
  textNode.textContent = text;
  wrap.className = "pill" + (kind ? " " + kind : "");
}

function status(main, detail) {
  $("statusText").textContent = main;
  $("statusHint").textContent = detail || "";
}

function toast(message) {
  const node = el("div", "toast", message);
  $("toasts").appendChild(node);
  setTimeout(() => node.remove(), 1800);
}

function copy(text) {
  navigator.clipboard.writeText(text).then(
    () => toast("Copied"),
    () => toast("Copy blocked")
  );
}

/* ── boot ────────────────────────────────────────────── */
document.addEventListener("DOMContentLoaded", boot);

async function boot() {
  if (localStorage.getItem("saa_theme") === "light") document.body.classList.add("light");
  setThemeIcon();

  try {
    S.cfg = await api("/api/config");
  } catch (e) {
    renderError("Server unreachable", e.message, "Start the studio: python3 -m nexcut.server");
    return;
  }
  S.tools = S.cfg.tools || { can_cut: false, hints: {} };

  const stub = S.cfg.provider === "stub";
  pill($("providerBadge"), $("providerText"), stub ? "demo" : S.cfg.provider, stub ? "warn" : "ok");
  const master = !!(S.cfg.prompt && S.cfg.prompt.master_loaded);
  pill($("promptBadge"), $("promptText"), master ? "master.md" : "built-in", master ? "ok" : "warn");
  pill($("toolsBadge"), $("toolsText"), S.tools.can_cut ? "ready" : "unavailable",
    S.tools.can_cut ? "ok" : "bad");

  $("statusProvider").textContent = S.cfg.provider || "";
  $("statusVersion").textContent = S.cfg.version || "";
  note($("providerNote"), stub
    ? "Offline demo — no key required."
    : "Key is used for this run only.");

  buildControls();
  wire();
  restoreKey();
  updateCounts();
  renderDashboard();
  status("Ready", master ? "prompt: master.md" : "prompt: built-in");
}

function buildControls() {
  const niche = $("nicheSel");
  (S.cfg.niches || []).forEach((n) => niche.appendChild(new Option(n.id, n.id)));
  if (niche.options.length) { niche.value = niche.options[0].value; fillSubs(niche.value); }

  (S.cfg.audiences || []).forEach((x) => $("audienceSel").appendChild(new Option(x, x)));
  (S.cfg.languages || []).forEach((x) => $("langSel").appendChild(new Option(x, x)));
  (S.cfg.models || []).forEach((x) => $("modelSel").appendChild(new Option(x.label || x.id, x.id)));

  // shorten "Option E: 45s–5m25s (Oracle Wide Range - default)" -> "45s–5m25s"
  (S.cfg.windows || []).forEach((w) => {
    const full = String(w.label || w.id);
    const label = full
      .replace(/^Option\s*[A-Z]\s*:\s*/i, "")
      .replace(/\s*\(.*?\)\s*$/, "")
      .trim();
    const opt = new Option(label, w.id);
    opt.title = full;
    $("windowSel").appendChild(opt);
  });

  if (S.cfg.default_window) $("windowSel").value = S.cfg.default_window;
  if (S.cfg.default_model) $("modelSel").value = S.cfg.default_model;
}

function fillSubs(base) {
  const sel = $("subSel");
  const subs = (S.cfg.subniches || {})[base] || [];
  sel.textContent = "";
  sel.appendChild(new Option("—", ""));
  subs.forEach((s) => sel.appendChild(new Option(s, s)));
  $("subWrap").hidden = subs.length === 0;
  sel.value = "";
}

const nicheValue = () => {
  const base = $("nicheSel").value;
  const sub = $("subSel").value;
  return sub ? `${base} — ${sub}` : base;
};

/* ── wiring ──────────────────────────────────────────── */
function wire() {
  $("themeBtn").onclick = () => {
    const light = document.body.classList.toggle("light");
    localStorage.setItem("saa_theme", light ? "light" : "dark");
    setThemeIcon();
  };

  $("nicheSel").onchange = () => { fillSubs($("nicheSel").value); renderDashboard(); };
  ["subSel", "audienceSel", "langSel", "numClips", "windowSel", "modelSel"].forEach((id) => {
    $(id).addEventListener("change", renderDashboard);
  });

  $("ytUrl").addEventListener("input", () => {
    clearTimeout(S.timers.fetch);
    const url = $("ytUrl").value.trim();
    if (!url) {
      S.caption = { state: "idle", detail: "No link" };
      note($("sourceState"), "No source");
      renderDashboard();
      return;
    }
    S.caption = { state: "fetching", detail: "Fetching captions…" };
    note($("sourceState"), "Fetching captions…");
    renderDashboard();
    S.timers.fetch = setTimeout(() => fetchCaptions(url), 700);
  });

  $("transcript").addEventListener("input", () => { updateCounts(); renderDashboard(); });

  $("sampleBtn").onclick = () => {
    $("transcript").value = SAMPLE;
    $("transcriptFold").open = true;
    updateCounts();
    S.caption = { state: "ready", detail: "Sample transcript" };
    note($("sourceState"), "Sample transcript loaded", "ok");
    renderDashboard();
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
    renderDashboard();
  });
  $("rememberKey").onchange = () => {
    if ($("rememberKey").checked) localStorage.setItem("saa_key", $("apiKey").value);
    else localStorage.removeItem("saa_key");
  };

  $("windowSel").addEventListener("change", () => {
    const custom = $("windowSel").value === "E";
    $("customMinWrap").hidden = !custom;
    $("customMaxWrap").hidden = !custom;
  });

  $("runBtn").onclick = run;
  $("cutBtn").onclick = startCut;
  $("newRunBtn").onclick = () => { showPane("emptyPane"); renderDashboard(); };
  $("copyJsonBtn").onclick = () => { if (S.result) copy(S.result.oracle_report || ""); };
  $("downloadBtn").onclick = downloadReport;
  $("clearRecent").onclick = () => { localStorage.removeItem("saa_recent"); renderDashboard(); };

  $("segTabs").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-view]");
    if (btn) setView(btn.dataset.view);
  });

  $("toolsBadge").onclick = () => {
    const hints = S.tools.hints || {};
    const msg = S.tools.can_cut
      ? "ffmpeg and yt-dlp detected."
      : [hints.ffmpeg, hints.yt_dlp].filter(Boolean).join(" ");
    toast(msg || "Cutting unavailable");
  };

  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-copy]");
    if (btn) copy(btn.dataset.copy);
  });

  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      if (!$("runBtn").disabled) run();
    }
    if (e.key === "Escape" && !$("resultsPane").hidden) {
      showPane("emptyPane");
      renderDashboard();
    }
  });

  /* drop a transcript anywhere */
  ["dragover", "drop"].forEach((type) => {
    document.addEventListener(type, (e) => {
      e.preventDefault();
      if (type !== "drop") return;
      const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (file) loadFile(file);
    });
  });
}

function setThemeIcon() {
  const light = document.body.classList.contains("light");
  $("themeBtn").innerHTML = "";
  const svg = icon(light ? "sun" : "moon");
  $("themeBtn").appendChild(svg);
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
  if (file) await loadFile(file);
  $("fileInput").value = "";
}

async function loadFile(file) {
  const form = new FormData();
  form.append("file", file);
  try {
    const res = await fetch("/api/upload-transcript", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Upload failed");
    $("transcript").value = data.text;
    $("transcriptFold").open = true;
    updateCounts();
    S.caption = { state: "ready", detail: file.name };
    note($("sourceState"), `${file.name} — ${data.chars.toLocaleString()} characters`, "ok");
    renderDashboard();
  } catch (e) {
    note($("sourceState"), e.message, "bad");
  }
}

async function fetchCaptions(url) {
  try {
    const data = await api("/api/transcript", { method: "POST", body: JSON.stringify({ url }) });
    $("transcript").value = data.text;
    $("transcriptFold").open = false;
    updateCounts();
    S.caption = {
      state: "ready",
      detail: `${data.is_auto ? "auto" : "published"} · ${data.lines} lines · ${hms(data.seconds)}`,
    };
    note($("sourceState"), S.caption.detail, "ok");
    if (data.title) document.title = `${data.title} — Clip Studio`;
    status("Captions ready", `${data.lines} lines`);
  } catch (e) {
    S.caption = { state: "failed", detail: e.message };
    note($("sourceState"), [e.message, e.hint].filter(Boolean).join(" "), "bad");
    $("transcriptFold").open = true;
    status("Captions unavailable", e.message);
  }
  renderDashboard();
}

/* ── dashboard ───────────────────────────────────────── */
function renderDashboard() {
  const niche = nicheValue();
  const model = $("modelSel").value;
  const length = $("windowSel").selectedOptions[0];
  const stamps = ($("transcript").value.match(/^\s*\[?\d{1,2}:\d{2}/gm) || []).length;

  /* config chips */
  const box = $("dashConfig");
  box.textContent = "";
  [
    ["Niche", niche],
    ["Audience", $("audienceSel").value],
    ["Clips", $("numClips").value],
    ["Length", length ? length.textContent : ""],
    ["Model", model],
  ].forEach(([k, v]) => {
    if (!v) return;
    const chip = el("span", "chip");
    chip.appendChild(el("b", null, k));
    chip.appendChild(document.createTextNode(v));
    box.appendChild(chip);
  });

  /* pipeline */
  const steps = [
    {
      icon: "captions", name: "Captions",
      state: S.caption.detail,
      tone: S.caption.state === "ready" ? "done" : S.caption.state === "failed" ? "" : "ready",
    },
    {
      icon: "scan", name: "Transcript check",
      state: stamps ? `${stamps} timestamps` : "no timestamps yet",
      tone: stamps ? "done" : "",
    },
    {
      icon: "chip", name: "Model",
      state: model || "none",
      tone: model ? "done" : "",
    },
    {
      icon: "shield", name: "Rule gate",
      state: "6 rules · 8.0 threshold",
      tone: "done",
    },
    {
      icon: "scissors", name: "Export",
      state: S.tools.can_cut ? "ffmpeg ready" : "ffmpeg missing",
      tone: S.tools.can_cut ? "done" : "",
    },
  ];
  const list = $("pipeline");
  list.textContent = "";
  steps.forEach((step) => {
    const li = el("li", step.tone);
    const dot = el("div", "step-dot");
    dot.appendChild(icon(step.icon));
    li.appendChild(dot);
    const body = el("div", "step-body");
    body.appendChild(el("div", "step-name", step.name));
    body.appendChild(el("div", "step-state", step.state));
    li.appendChild(body);
    list.appendChild(li);
  });

  /* recent runs */
  const recent = readRecent();
  const body = $("recentBody");
  body.textContent = "";
  $("clearRecent").hidden = recent.length === 0;

  if (!recent.length) {
    const empty = el("div", "recent-empty");
    empty.appendChild(el("strong", null, "No runs yet"));
    empty.appendChild(el("span", null, "Each extraction is logged here, on this device."));
    body.appendChild(empty);
    return;
  }
  const table = el("table", "recent-tbl");
  recent.slice(0, 6).forEach((run) => {
    const tr = el("tr");
    tr.appendChild(el("td", "c-niche", run.niche || "—"));
    tr.appendChild(el("td", "c-count", `${run.kept}/${run.requested}`));
    tr.appendChild(el("td", "c-count", run.model || ""));
    tr.appendChild(el("td", "c-when", run.at || ""));
    table.appendChild(tr);
  });
  body.appendChild(table);
}

function readRecent() {
  try {
    const list = JSON.parse(localStorage.getItem("saa_recent") || "[]");
    return Array.isArray(list) ? list : [];
  } catch { return []; }
}

/* ── panes ───────────────────────────────────────────── */
const PANES = ["emptyPane", "progressPane", "errorPane", "resultsPane"];
const showPane = (id) => PANES.forEach((p) => { $(p).hidden = p !== id; });

function renderError(title, message, detail) {
  showPane("errorPane");
  const pane = $("errorPane");
  pane.textContent = "";

  const wrap = el("div", "err bad");
  const head = el("div", "err-head");
  const ico = el("div", "ico");
  ico.appendChild(icon("alert"));
  head.appendChild(ico);
  head.appendChild(el("h1", null, title));
  wrap.appendChild(head);
  wrap.appendChild(el("p", "err-msg", message));
  if (detail) wrap.appendChild(el("div", "err-hint", detail));

  const back = el("button", "btn tiny", "Back");
  back.onclick = () => { showPane("emptyPane"); renderDashboard(); };
  const row = el("div");
  row.style.display = "flex";
  row.appendChild(back);
  wrap.appendChild(row);

  pane.appendChild(wrap);
  status("Failed", title);
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
    already_extracted: "",
    api_key: $("apiKey").value.trim(),
  };
}

async function run() {
  const payload = readPayload();
  if (!payload.youtube_url && !payload.transcript_text) {
    note($("sourceState"), "Paste a URL or load a transcript first.", "bad");
    $("ytUrl").focus();
    return;
  }

  S.payload = payload;
  S.result = null;
  S.jobId = null;
  $("runBtn").disabled = true;
  showPane("progressPane");
  $("stageLog").textContent = "";
  $("barFill").style.width = "2%";
  $("pctText").textContent = "0%";
  $("stageText").textContent = "Queued";
  status("Running", payload.niche);

  try {
    const { job_id } = await api("/api/extract", { method: "POST", body: JSON.stringify(payload) });
    S.jobId = job_id;
    pollJob(job_id);
  } catch (e) {
    $("runBtn").disabled = false;
    renderError("Run could not start", e.message, e.hint);
  }
}

function pollJob(jobId) {
  clearInterval(S.timers.poll);
  let last = -1;

  S.timers.poll = setInterval(async () => {
    let job;
    try {
      job = await api(`/api/jobs/${jobId}`);
    } catch (e) {
      clearInterval(S.timers.poll);
      $("runBtn").disabled = false;
      renderError("Lost contact with the server", e.message);
      return;
    }

    const pct = Math.round(job.progress || 0);
    $("barFill").style.width = pct + "%";
    $("pctText").textContent = pct + "%";
    $("stageText").textContent = job.stage || "Working";
    $("statusElapsed").textContent = job.elapsed_s ? `${job.elapsed_s}s` : "";

    if (pct !== last) {
      last = pct;
      $("stageLog").textContent += `${String(pct).padStart(3, " ")}%  ${job.stage}\n`;
      $("stageLog").scrollTop = $("stageLog").scrollHeight;
    }

    if (job.status === "done") {
      clearInterval(S.timers.poll);
      $("runBtn").disabled = false;
      try {
        const result = await api(`/api/jobs/${jobId}/results`);
        S.result = result;
        renderResults(result, S.payload, job);
        saveRun(result, S.payload);
      } catch (e) {
        renderError("Results unreadable", e.message, "The job finished but the payload failed to render.");
      }
    } else if (job.status === "error") {
      clearInterval(S.timers.poll);
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
  S.selected = 0;

  $("resTitle").textContent = data.video_title || "Transcript session";
  $("resMeta").textContent = [
    data.video_id ? `id ${data.video_id}` : "",
    data.channel || "",
    data.transcript_source ? `captions ${data.transcript_source}` : "",
    data.model_used ? `model ${data.model_used}` : "",
    data.ranges_planned ? `coverage ${data.ranges_planned}` : "",
    job && job.elapsed_s ? `${job.elapsed_s}s` : "",
  ].filter(Boolean).join("  ·  ");

  $("statCandidates").textContent = (data.sweep && data.sweep.longlist) || (data.longlist || []).length;
  $("statKept").textContent = clips.length;
  $("statRejected").textContent = rejected.length;
  $("statRequested").textContent = payload.num_clips;
  $("tabClipsN").textContent = clips.length;
  $("tabRejectedN").textContent = rejected.length;

  const rows = $("clipRows");
  rows.textContent = "";
  clips.forEach((clip, index) => {
    const tr = el("tr");
    tr.setAttribute("aria-selected", index === 0 ? "true" : "false");
    tr.appendChild(el("td", "c-n", clip.n));
    tr.appendChild(el("td", "c-t", clip.start_stamp || hms(clip.start_sec)));
    tr.appendChild(el("td", "c-t", clip.end_stamp || hms(clip.end_sec)));
    tr.appendChild(el("td", "c-d", clip.duration_str || ""));
    const scoreCell = el("td", "c-s");
    const avg = clip.scores && clip.scores.avg;
    scoreCell.appendChild(el("span", "score" + (avg >= 8 ? " hi" : ""), avg == null ? "—" : avg));
    tr.appendChild(scoreCell);
    tr.appendChild(el("td", "hook", clip.hook_summary || ""));
    tr.onclick = () => selectClip(index);
    rows.appendChild(tr);
  });
  $("clipsEmpty").hidden = clips.length > 0;

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
  const clips = (S.result && S.result.clips) || [];
  const clip = clips[index];
  S.selected = index;

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
    body.appendChild(el("p", "note pad", "Select a clip."));
    return;
  }

  const scores = el("div", "scores");
  Object.entries(clip.scores || {}).forEach(([k, v]) => {
    if (v == null) return;
    scores.appendChild(el("span", k === "avg" ? "hi" : "", `${k} ${v}`));
  });
  if (scores.children.length) body.appendChild(row("scores", scores, true));

  const t = clip.titles || {};
  [
    ["opens", `[${clip.start_stamp}] ${clip.start_sentence}`, true, clip.start_sentence],
    ["ends", `[${clip.end_stamp}] ${clip.end_sentence}`, true, clip.end_sentence],
    ["length", `${clip.duration_str || ""}${clip.duration_line ? " · " + clip.duration_line : ""}`],
    ["clickbait", t.clickbait, false, t.clickbait],
    ["search", t.search, false, t.search],
    ["debate", t.debate, false, t.debate],
    ["verbal hook", clip.verbal_hook, false, clip.verbal_hook],
    ["why", clip.why_it_works],
    ["share", clip.share_trigger],
    ["overlays", (clip.overlays || []).map((o) => `${o.offset}  ${o.text}`).join("\n"), true],
    ["sfx", clip.sfx],
    ["captions", clip.captions],
    ["upload text", clip.upload_caption, false, clip.upload_caption],
    ["hashtags", clip.hashtags, true, clip.hashtags],
    ["pinned", clip.pinned_comment, false, clip.pinned_comment],
    ["safety", clip.safety && String(clip.safety).toLowerCase() !== "none" ? clip.safety : ""],
  ].forEach(([k, v, mono, copyText]) => {
    const node = row(k, v, mono, copyText);
    if (node) body.appendChild(node);
  });
}

function row(key, value, mono, copyText) {
  if (value === undefined || value === null || value === "") return null;
  const line = el("div", "irow");
  line.appendChild(el("div", "k", key));

  if (value instanceof Node) {
    const cell = el("div", "v");
    cell.appendChild(value);
    line.appendChild(cell);
    return line;
  }

  const cell = el("div", "v" + (mono ? " mono" : ""));
  cell.appendChild(document.createTextNode(String(value)));
  if (copyText) {
    const btn = el("button", "copy", "copy");
    btn.type = "button";
    btn.dataset.copy = copyText;
    cell.appendChild(btn);
  }
  line.appendChild(cell);
  return line;
}

function setView(view) {
  S.view = view;
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
  const canCut = S.tools.can_cut && data.video_id && clips.length;
  $("cutBtn").disabled = !canCut;
  $("fileList").textContent = "";
  $("cutFill").style.width = "0%";
  $("exportQuality").textContent = "";
  const sel = $("qualitySel");

  if (!S.tools.can_cut) {
    note($("cutState"), "ffmpeg / yt-dlp not found.", "warn");
    sel.textContent = "";
    sel.appendChild(new Option("unavailable", ""));
    return;
  }
  if (!data.video_id) {
    note($("cutState"), "Pasted transcript — no video to cut.", "warn");
    sel.textContent = "";
    sel.appendChild(new Option("n/a", ""));
    return;
  }

  sel.textContent = "";
  sel.appendChild(new Option("checking…", ""));
  sel.disabled = true;
  note($("cutState"), "Reading qualities…");

  api(`/api/video-quality/${encodeURIComponent(data.video_id)}`)
    .then((res) => {
      sel.textContent = "";
      const min = S.cfg.min_height || 1080;
      const heights = (res.qualities || []).filter((q) => q >= min);
      (heights.length ? heights : [min]).forEach((q) => {
        sel.appendChild(new Option(q >= 2160 ? `${q}p 4K` : `${q}p`, String(q)));
      });
      sel.disabled = false;
      note($("cutState"), "Ready.", "ok");
    })
    .catch((e) => {
      sel.textContent = "";
      sel.appendChild(new Option("unavailable", ""));
      sel.disabled = true;
      note($("cutState"), e.message + (e.hint ? " — " + e.hint : ""), "warn");
    });
}

async function startCut() {
  if (!S.jobId || !S.result || !S.tools.can_cut) return;
  const sel = $("qualitySel");
  const height = sel && sel.value ? parseInt(sel.value, 10) : (S.cfg.min_height || 1080);

  $("cutBtn").disabled = true;
  $("fileList").textContent = "";
  $("cutFill").style.width = "0%";
  note($("cutState"), "Downloading source…");
  status("Cutting", `${height}p`);

  try {
    const { cut_id } = await api(`/api/jobs/${S.jobId}/cut`, {
      method: "POST",
      body: JSON.stringify({ height }),
    });
    pollCut(cut_id);
  } catch (e) {
    $("cutBtn").disabled = false;
    note($("cutState"), [e.message, e.hint].filter(Boolean).join(" — "), "bad");
    status("Cut failed", e.message);
  }
}

function pollCut(cutId) {
  clearInterval(S.timers.cut);
  S.timers.cut = setInterval(async () => {
    let cut;
    try {
      cut = await api(`/api/cuts/${cutId}`);
    } catch (e) {
      clearInterval(S.timers.cut);
      $("cutBtn").disabled = false;
      note($("cutState"), e.message, "bad");
      return;
    }

    $("cutFill").style.width = `${cut.progress || 0}%`;
    note($("cutState"), `${cut.progress || 0}% · ${cut.stage}`);
    $("exportQuality").textContent = cut.quality || "";

    if (cut.status === "done") {
      clearInterval(S.timers.cut);
      $("cutBtn").disabled = false;
      note($("cutState"), `${cut.files.length} file(s) · ${cut.quality || ""}`, "ok");
      renderFiles(cut.files || []);
      status("Cut complete", `${cut.files.length} files`);
    } else if (cut.status === "error") {
      clearInterval(S.timers.cut);
      $("cutBtn").disabled = false;
      note($("cutState"), cut.error || "Cut failed", "bad");
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

function downloadReport() {
  if (!S.result) return;
  const blob = new Blob([S.result.oracle_report || ""], { type: "text/plain" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `clips-${S.result.video_id || "session"}.txt`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 3000);
  toast("Report downloaded");
}

/* ── history ─────────────────────────────────────────── */
function saveRun(result, payload) {
  try {
    const list = readRecent();
    list.unshift({
      at: new Date().toLocaleString(),
      niche: payload.niche,
      kept: (result.clips || []).length,
      requested: payload.num_clips,
      rejected: (result.dropped || []).length,
      model: result.model_used || payload.model,
      source: result.transcript_source || "pasted",
    });
    localStorage.setItem("saa_recent", JSON.stringify(list.slice(0, 12)));
  } catch { /* storage blocked — not essential */ }
}
