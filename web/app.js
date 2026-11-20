/* NexCut — client.
   Plain DOM, no framework, no build step. Model output is written with
   textContent only; every render path is guarded so a bad payload shows a
   readable failure card instead of a blank screen. */
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
  mode: "cutter",
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
  node.classList.remove("ok", "bad", "warn");
  if (kind) node.classList.add(kind);
}

function toast(message) {
  const node = el("div", "toast", message);
  $("toasts").appendChild(node);
  setTimeout(() => node.remove(), 1900);
}

function copy(text) {
  navigator.clipboard.writeText(text).then(
    () => toast("Copied"),
    () => toast("Copy blocked")
  );
}

const PANES = ["landingPane", "progressPane", "errorPane", "resultsPane"];
const SIDE = { landingPane: "Link intake", progressPane: "Working", errorPane: "Stopped", resultsPane: "Clips" };
const showPane = (id) => PANES.forEach((p) => {
  if ($(p)) $(p).hidden = p !== id;
  if (p === id && $("sideLabel")) $("sideLabel").textContent = SIDE[id] || "";
});

function drawer(id, open) {
  const node = $(id);
  if (!node) return;
  const next = open === undefined ? node.hidden : open;
  node.hidden = !next;
  const btn = { optionsPanel: "optionsToggle", transcriptPanel: "transcriptToggle", historyPanel: "historyToggle" }[id];
  if (btn && $(btn)) $(btn).setAttribute("aria-expanded", next ? "true" : "false");
}

function closeDrawers() {
  drawer("optionsPanel", false);
  drawer("transcriptPanel", false);
  drawer("historyPanel", false);
}

/* ── boot ────────────────────────────────────────────── */
document.addEventListener("DOMContentLoaded", boot);

async function boot() {
  if (localStorage.getItem("saa_theme") === "light") document.body.classList.add("light");
  setThemeIcon();

  try {
    S.cfg = await api("/api/config");
  } catch (e) {
    renderError("Server unreachable", e.message, "Start it with: python3 -m nexcut.server");
    return;
  }
  S.tools = S.cfg.tools || { can_cut: false, hints: {} };

  $("buildTag").textContent = S.cfg.version ? String(S.cfg.version) : "";

  buildControls();
  wire();
  updateCounts();
  renderSummary();
  renderHistory();
  showPane("landingPane");
}

function buildControls() {
  const niche = $("nicheSel");
  (S.cfg.niches || []).forEach((n) => niche.appendChild(new Option(n.id, n.id)));
  if (niche.options.length) { niche.value = niche.options[0].value; fillSubs(niche.value); }

  (S.cfg.audiences || []).forEach((x) => $("audienceSel").appendChild(new Option(x, x)));
  (S.cfg.languages || []).forEach((x) => $("langSel").appendChild(new Option(x, x)));
  (S.cfg.models || []).forEach((x) => $("modelSel").appendChild(new Option(x.label || x.id, x.id)));

  // "Option E: 45s–5m25s (wide range — default)" -> "45s–5m25s"
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

  $("modeTabs").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-mode]");
    if (btn) setMode(btn.dataset.mode);
  });

  $("optionsToggle").onclick = () => drawer("optionsPanel");
  $("transcriptToggle").onclick = () => drawer("transcriptPanel");
  $("historyToggle").onclick = () => { renderHistory(); drawer("historyPanel"); };

  $("nicheSel").onchange = () => { fillSubs($("nicheSel").value); renderSummary(); };
  ["subSel", "audienceSel", "langSel", "numClips", "windowSel", "modelSel"].forEach((id) => {
    $(id).addEventListener("change", renderSummary);
  });

  $("ytUrl").addEventListener("input", () => {
    clearTimeout(S.timers.fetch);
    const url = $("ytUrl").value.trim();
    if (!url) {
      S.caption = { state: "idle", detail: "No link" };
      note($("sourceState"), "No source — paste a link, or open Transcript.");
      renderSummary();
      return;
    }
    S.caption = { state: "fetching", detail: "Fetching captions…" };
    note($("sourceState"), "Fetching captions…");
    renderSummary();
    S.timers.fetch = setTimeout(() => fetchCaptions(url), 700);
  });
  $("ytUrl").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); run(); }
  });

  $("transcript").addEventListener("input", () => { updateCounts(); renderSummary(); });

  $("sampleBtn").onclick = () => {
    $("transcript").value = SAMPLE;
    drawer("transcriptPanel", true);
    updateCounts();
    S.caption = { state: "ready", detail: "Sample transcript" };
    note($("sourceState"), "Sample transcript loaded — 10 lines", "ok");
    renderSummary();
  };

  $("uploadBtn").onclick = () => $("fileInput").click();
  $("fileInput").onchange = uploadFile;

  $("windowSel").addEventListener("change", () => {
    const custom = $("windowSel").value === "E";
    $("customMinWrap").hidden = !custom;
    $("customMaxWrap").hidden = !custom;
  });

  $("runBtn").onclick = run;
  $("cutBtn").onclick = startCut;
  $("newRunBtn").onclick = () => {
    showPane("landingPane");
    renderSummary();
    $("ytUrl").focus();
  };
  $("copyJsonBtn").onclick = () => { if (S.result) copy(S.result.oracle_report || ""); };
  $("downloadBtn").onclick = downloadReport;
  $("clearRecent").onclick = () => { localStorage.removeItem("saa_recent"); renderHistory(); renderSummary(); };

  $("segTabs").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-view]");
    if (btn) setView(btn.dataset.view);
  });

  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-copy]");
    if (btn) copy(btn.dataset.copy);
  });

  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      if (!$("runBtn").disabled && S.mode === "cutter") run();
    }
    if (e.key === "Escape") {
      if ($("landingPane").hidden) {
        showPane("landingPane");
        renderSummary();
      }
    }
  });

  ["dragover", "drop"].forEach((type) => {
    document.addEventListener(type, (e) => {
      e.preventDefault();
      if (type !== "drop") return;
      const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (file) loadFile(file);
    });
  });
}

function setMode(mode) {
  S.mode = mode;
  $("cutterPane").hidden = mode !== "cutter";
  $("downloaderPane").hidden = mode !== "downloader";
  Array.from($("modeTabs").children).forEach((btn) => {
    btn.setAttribute("aria-selected", btn.dataset.mode === mode ? "true" : "false");
  });
}

function setThemeIcon() {
  const light = document.body.classList.contains("light");
  $("themeBtn").innerHTML = "";
  $("themeBtn").appendChild(icon(light ? "sun" : "moon"));
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
    drawer("transcriptPanel", true);
    updateCounts();
    S.caption = { state: "ready", detail: file.name };
    note($("sourceState"), `${file.name} — ${data.chars.toLocaleString()} characters`, "ok");
    renderSummary();
  } catch (e) {
    note($("sourceState"), e.message, "bad");
  }
}

async function fetchCaptions(url) {
  try {
    const data = await api("/api/transcript", { method: "POST", body: JSON.stringify({ url }) });
    $("transcript").value = data.text;
    drawer("transcriptPanel", false);
    updateCounts();
    S.caption = {
      state: "ready",
      detail: `${data.is_auto ? "auto" : "published"} · ${data.lines} lines · ${hms(data.seconds)}`,
    };
    note($("sourceState"), `Captions ready — ${S.caption.detail}`, "ok");
    if (data.title) document.title = `${data.title} — NexCut`;
  } catch (e) {
    S.caption = { state: "failed", detail: e.message };
    note($("sourceState"), [e.message, e.hint].filter(Boolean).join(" "), "bad");
    drawer("transcriptPanel", true);
  }
  renderSummary();
}

/* ── summary chips + history ─────────────────────────── */
function renderSummary() {
  if (!S.cfg) return;
  const length = $("windowSel").selectedOptions[0];
  const box = $("dashConfig");
  box.textContent = "";
  [
    ["niche", nicheValue()],
    ["clips", $("numClips").value],
    ["length", length ? length.textContent : ""],
    ["model", $("modelSel").value],
  ].forEach(([k, v]) => {
    if (!v) return;
    const chip = el("span", "chip");
    chip.appendChild(el("b", null, k));
    chip.appendChild(document.createTextNode(String(v)));
    box.appendChild(chip);
  });
}

function readRecent() {
  try {
    const list = JSON.parse(localStorage.getItem("saa_recent") || "[]");
    return Array.isArray(list) ? list : [];
  } catch { return []; }
}

function renderHistory() {
  const body = $("recentBody");
  if (!body) return;
  const recent = readRecent();
  body.textContent = "";
  if (!recent.length) {
    body.appendChild(el("p", "recent-empty", "Nothing yet. Finished runs are listed here."));
    return;
  }
  const table = el("table", "recent-tbl");
  recent.slice(0, 10).forEach((run) => {
    const tr = el("tr");
    tr.appendChild(el("td", null, run.niche || "—"));
    tr.appendChild(el("td", "c-count", `${run.kept}/${run.requested}`));
    tr.appendChild(el("td", "c-count", run.model || ""));
    tr.appendChild(el("td", "c-when", run.at || ""));
    table.appendChild(tr);
  });
  body.appendChild(table);
}

/* ── failure card ────────────────────────────────────── */
function renderError(title, message, detail) {
  showPane("errorPane");
  const pane = $("errorPane");
  pane.textContent = "";

  const box = el("div", "fail-box");
  const head = el("div", "fail-head");
  const ico = el("div", "ico");
  ico.appendChild(icon("alert"));
  head.appendChild(ico);
  head.appendChild(el("h2", null, title));
  box.appendChild(head);
  box.appendChild(el("p", "fail-msg", message));
  if (detail) box.appendChild(el("div", "fail-hint", detail));

  const back = el("button", "btn small", "Back");
  back.onclick = () => { showPane("landingPane"); renderSummary(); };
  const row = el("div");
  row.style.display = "flex";
  row.appendChild(back);
  box.appendChild(row);
  pane.appendChild(box);
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
    api_key: "",
  };
}

async function run() {
  const payload = readPayload();
  if (!payload.youtube_url && !payload.transcript_text) {
    note($("sourceState"), "Paste a link or load a transcript first.", "bad");
    $("ytUrl").focus();
    return;
  }

  S.payload = payload;
  S.result = null;
  S.jobId = null;
  closeDrawers();
  $("runBtn").disabled = true;
  showPane("progressPane");
  $("stageLog").textContent = "";
  $("barFill").style.width = "2%";
  $("pctText").textContent = "0%";
  $("stageText").textContent = "Queued";

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
        renderHistory();
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
  ].filter(Boolean).join("   ·   ");

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

    const num = el("td", "c-n");
    num.appendChild(el("b", null, clip.n));
    tr.appendChild(num);

    const cell = el("td");
    const inner = el("div", "clip-cell");
    inner.appendChild(el("div", "clip-time",
      `${clip.start_stamp || hms(clip.start_sec)} → ${clip.end_stamp || hms(clip.end_sec)}`));
    inner.appendChild(el("div", "clip-hook", clip.hook_summary || clip.verbal_hook || "—"));
    cell.appendChild(inner);
    tr.appendChild(cell);

    tr.appendChild(el("td", "c-d cell-mono", clip.duration_str || ""));
    const scoreCell = el("td", "c-s");
    const avg = clip.scores && clip.scores.avg;
    scoreCell.appendChild(el("span", "score" + (avg >= 8 ? " hi" : ""), avg == null ? "—" : avg));
    tr.appendChild(scoreCell);

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
}

function block(label, text, opts = {}) {
  if (text === undefined || text === null || String(text).trim() === "") return null;
  const wrap = el("div", "dblock");
  const key = el("div", "k");
  key.appendChild(document.createTextNode(label));
  if (opts.copy) {
    const btn = el("button", "copy", "copy");
    btn.type = "button";
    btn.dataset.copy = String(text);
    key.appendChild(btn);
  }
  wrap.appendChild(key);
  const value = el("div", "v" + (opts.strong ? " strong" : "") + (opts.quote ? " quote" : ""), text);
  wrap.appendChild(value);
  return wrap;
}

function section(title, children) {
  const parts = children.filter(Boolean);
  if (!parts.length) return null;
  const sec = el("section", "dsec");
  sec.appendChild(el("h4", null, title));
  parts.forEach((n) => sec.appendChild(n));
  return sec;
}

function selectClip(index) {
  const clips = (S.result && S.result.clips) || [];
  const clip = clips[index];
  S.selected = index;

  Array.from($("clipRows").children).forEach((tr, i) => {
    tr.setAttribute("aria-selected", i === index ? "true" : "false");
  });

  const body = $("inspBody");
  body.textContent = "";

  const avg = clip && clip.scores ? clip.scores.avg : null;
  $("inspTitle").textContent = clip ? `Clip ${clip.n}` : "No clip selected";
  $("inspTime").textContent = clip
    ? `${clip.start_stamp || hms(clip.start_sec)} → ${clip.end_stamp || hms(clip.end_sec)}`
    : "";
  $("inspScore").textContent = avg == null ? "" : avg;
  $("inspScore").className = "score-lg" + (avg >= 8 ? " hi" : "");

  const link = $("clipLink");
  if (clip && S.result && S.result.video_id) {
    const t = Math.max(0, Math.round(clip.start_sec || 0));
    link.href = `https://youtu.be/${S.result.video_id}?t=${t}`;
    link.hidden = false;
  } else {
    link.hidden = true;
  }

  if (!clip) {
    body.appendChild(el("p", "note pad", "Select a clip."));
    return;
  }

  /* timing */
  const grid = el("div", "dgrid");
  [
    ["In", clip.start_stamp || hms(clip.start_sec)],
    ["Out", clip.end_stamp || hms(clip.end_sec)],
    ["Length", clip.duration_str || "—"],
  ].forEach(([k, v]) => {
    const cell = el("div", "dcell");
    cell.appendChild(el("div", "k", k));
    cell.appendChild(el("div", "v", v));
    grid.appendChild(cell);
  });

  /* scores */
  const scoreRows = Object.entries(clip.scores || {})
    .filter(([k, v]) => k !== "avg" && typeof v === "number")
    .map(([k, v]) => {
      const row = el("div", "srow");
      row.appendChild(el("div", "k", k));
      const track = el("div", "track");
      const fill = el("i");
      fill.style.width = `${Math.max(0, Math.min(100, v * 10))}%`;
      track.appendChild(fill);
      row.appendChild(track);
      row.appendChild(el("div", "v", v));
      return row;
    });

  const titles = clip.titles || {};
  const post = [
    block("upload text", clip.upload_caption, { copy: true }),
    block("hashtags", clip.hashtags, { copy: true }),
    block("pinned comment", clip.pinned_comment, { copy: true }),
    clip.safety && String(clip.safety).toLowerCase() !== "none"
      ? block("safety", clip.safety, { strong: true }) : null,
  ];

  [
    section("Timing", [grid]),
    section("Scores", scoreRows),
    section("Titles", [
      block("clickbait", titles.clickbait, { copy: true, strong: true }),
      block("search", titles.search, { copy: true }),
      block("debate", titles.debate, { copy: true }),
    ]),
    section("Dialogue", [
      block("opens", clip.start_sentence, { quote: true }),
      block("ends", clip.end_sentence, { quote: true }),
    ]),
    section("Why it works", [
      block("reason", clip.why_it_works, { strong: true }),
      block("share trigger", clip.share_trigger),
      block("verbal hook", clip.verbal_hook),
    ]),
    section("On screen", [
      block("overlays", (clip.overlays || []).map((o) => `${o.offset}   ${o.text}`).join("\n")),
      block("sfx", clip.sfx),
      block("captions", clip.captions),
    ]),
    section("Post", post),
  ].forEach((node) => { if (node) body.appendChild(node); });

  if (!body.children.length) body.appendChild(el("p", "note pad", "Nothing else for this clip."));
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
  $("cutTrack").hidden = true;
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
  $("cutTrack").hidden = false;
  note($("cutState"), "Downloading source…");

  try {
    const { cut_id } = await api(`/api/jobs/${S.jobId}/cut`, {
      method: "POST",
      body: JSON.stringify({ height }),
    });
    pollCut(cut_id);
  } catch (e) {
    $("cutBtn").disabled = false;
    note($("cutState"), [e.message, e.hint].filter(Boolean).join(" — "), "bad");
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
      toast(`${cut.files.length} file(s) cut`);
    } else if (cut.status === "error") {
      clearInterval(S.timers.cut);
      $("cutBtn").disabled = false;
      note($("cutState"), cut.error || "Cut failed", "bad");
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
  toast("Report saved");
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
