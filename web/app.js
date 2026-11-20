/* NexCut — client.
   Flow: paste link → details → config → extract (model) → cut (ffmpeg) → downloads.
   Plain DOM. Model output is written with textContent only; every render path is
   guarded so a bad payload shows a readable failure card instead of a blank page. */
"use strict";

const $ = (id) => document.getElementById(id);

const S = {
  cfg: null,
  details: null,      // /api/transcript payload
  link: "",
  jobId: null,
  result: null,
  payload: null,
  cutId: null,
  files: [],
  zip: false,
  len: "40-50",
  open: new Set(),
  mode: "cutter",
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

const mmss = (sec) => {
  const s = Math.max(0, Math.round(Number(sec) || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
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
  navigator.clipboard.writeText(text).then(() => toast("Copied"), () => toast("Copy blocked"));
}

const PANES = ["landPane", "setupPane", "workPane", "errorPane", "resultsPane"];
const SIDE = { landPane: "Link intake", setupPane: "Details", workPane: "Working", errorPane: "Stopped", resultsPane: "Clips" };

function showPane(id) {
  PANES.forEach((p) => {
    if ($(p)) $(p).hidden = p !== id;
  });
  if ($("sideLabel")) $("sideLabel").textContent = SIDE[id] || "";
  setCreditsInline(id === "workPane");
}

/* the credits line moves under the loading bar while a run is working */
function setCreditsInline(inline) {
  const credits = $("credits");
  if (!credits) return;
  const slot = $("creditsSlot");
  if (inline && slot && credits.parentElement !== slot) {
    slot.appendChild(credits);
    credits.classList.add("inline");
    document.body.classList.add("working");
  } else if (!inline && credits.parentElement !== document.body) {
    document.body.appendChild(credits);
    credits.classList.remove("inline");
    document.body.classList.remove("working");
  }
}

/* ── boot ────────────────────────────────────────────── */
document.addEventListener("DOMContentLoaded", boot);

let booted = false;

async function boot() {
  if (booted) return;          // DOMContentLoaded can fire twice under test harnesses
  booted = true;
  if (localStorage.getItem("saa_theme") === "light") document.body.classList.add("light");
  setThemeIcon();

  try {
    S.cfg = await api("/api/config");
  } catch (e) {
    renderError("Server unreachable", e.message, "Start it with: python3 -m nexcut.server");
    return;
  }

  $("buildTag").textContent = S.cfg.version ? String(S.cfg.version) : "";
  $("numClips").min = S.cfg.min_clips || 5;
  $("numClips").max = S.cfg.max_clips || 15;
  wire();
  updateClipBadge();
  showPane("landPane");
}

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

  /* one input, nothing else: pasting a link starts the fetch */
  $("ytUrl").addEventListener("input", () => {
    clearTimeout(S.timers.fetch);
    const url = $("ytUrl").value.trim();
    S.link = url;
    if (!url) {
      note($("sourceState"), "No source");
      return;
    }
    note($("sourceState"), "Reading the link…");
    S.timers.fetch = setTimeout(() => loadLink(url), 800);
  });
  $("ytUrl").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      clearTimeout(S.timers.fetch);
      loadLink($("ytUrl").value.trim(), true);
    }
  });
  $("fetchBtn").onclick = () => {
    clearTimeout(S.timers.fetch);
    loadLink($("ytUrl").value.trim(), true);
  };

  $("viewTranscript").onclick = () => {
    const text = transcriptText();
    if (!text) return toast("No transcript yet");
    const blob = new Blob([text], { type: "text/plain" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `transcript-${(S.details && S.details.video_id) || "session"}.txt`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 3000);
  };

  $("ownTranscript").onclick = () => {
    const box = $("ownTranscriptBox");
    box.hidden = !box.hidden;
    $("ownTranscript").setAttribute("aria-expanded", box.hidden ? "false" : "true");
    if (!box.hidden) $("transcript").focus();
  };
  $("uploadBtn").onclick = () => $("fileInput").click();
  $("fileInput").onchange = uploadFile;
  $("transcript").addEventListener("input", () => {
    const text = $("transcript").value.trim();
    note($("ownNote"), text ? `${text.split(/\r?\n/).filter((l) => l.trim()).length} lines` : "One timestamp per line.");
  });

  $("numClips").addEventListener("input", updateClipBadge);

  $("lenSeg").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-len]");
    if (btn) setLength(btn.dataset.len);
  });

  $("runBtn").onclick = run;
  $("newRunBtn").onclick = reset;
  $("copyJsonBtn").onclick = () => { if (S.result) copy(S.result.oracle_report || ""); };
  $("zipToggle").addEventListener("change", () => {
    S.zip = $("zipToggle").checked;
    renderClips();
  });

  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-copy]");
    if (btn) copy(btn.dataset.copy);
    const more = e.target.closest("[data-more]");
    if (more) {
      const n = Number(more.dataset.more);
      if (S.open.has(n)) S.open.delete(n); else S.open.add(n);
      renderClips();
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("resultsPane").hidden) reset();
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

function setLength(value) {
  S.len = value;
  Array.from($("lenSeg").children).forEach((b) => {
    b.setAttribute("aria-selected", b.dataset.len === value ? "true" : "false");
  });
  $("customLen").hidden = value !== "custom";
}

function updateClipBadge() {
  const raw = $("numClips").value.trim();
  const n = parseInt(raw, 10);
  const auto = !raw || !n;
  $("clipCountBadge").textContent = auto ? "AUTO" : `${n} clips`;
  $("clipCountBadge").style.opacity = auto ? "1" : "1";
}

const transcriptText = () => {
  const own = $("transcript").value.trim();
  if (own) return own;
  return (S.details && S.details.text) || "";
};

/* ── step 1: the link ────────────────────────────────── */
async function loadLink(url, force) {
  if (!url) {
    if (force) note($("sourceState"), "Paste a YouTube link first.", "bad");
    return;
  }
  note($("sourceState"), "Fetching captions…");
  try {
    const data = await api("/api/transcript", { method: "POST", body: JSON.stringify({ url }) });
    S.details = data;
    S.link = url;
    fillDetails(data);
    note($("sourceState"), `Captions ready — ${data.lines} lines`, "ok");
    showPane("setupPane");
  } catch (e) {
    S.details = null;
    note($("sourceState"), [e.message, e.hint].filter(Boolean).join(" "), "bad");
  }
}

function fillDetails(data) {
  $("factTitle").textContent = data.title || "—";
  $("factChannel").textContent = data.channel || "—";
  $("factLength").textContent = data.seconds ? hms(data.seconds) : "—";
  $("factCaptions").textContent = data.is_auto ? "auto-generated" : "published";
  $("factTranscript").textContent = data.lines
    ? `${data.lines} lines · ${(data.text || "").length.toLocaleString()} characters`
    : "—";
  $("factNiche").textContent = "detected by the model on extract";
  $("detailBadge").textContent = data.video_id ? data.video_id : "ready";
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
    $("ownTranscriptBox").hidden = false;
    $("transcript").value = data.text;
    note($("ownNote"), `${file.name} — ${data.chars.toLocaleString()} characters`, "ok");
    if (!S.details) toast("Transcript loaded — paste a link to add video details");
  } catch (e) {
    note($("ownNote"), e.message, "bad");
  }
}

/* ── step 2: extract ─────────────────────────────────── */
function readPayload() {
  const raw = $("numClips").value.trim();
  const n = parseInt(raw, 10);
  const custom = S.len === "custom";
  return {
    youtube_url: S.link || $("ytUrl").value.trim(),
    transcript_text: transcriptText(),
    niche: "auto",
    audience: "U.S. English",
    language: "U.S. English",
    num_clips: raw && n ? n : 0,
    window: custom ? "custom" : S.len,
    custom_min_sec: custom ? (parseInt($("customMin").value, 10) || null) : null,
    custom_max_sec: custom ? (parseInt($("customMax").value, 10) || null) : null,
    model: "",
    cascade: true,
    already_extracted: "",
    api_key: "",
  };
}

async function run() {
  const payload = readPayload();
  if (!payload.youtube_url && !payload.transcript_text) {
    note($("sourceState"), "Paste a link first.", "bad");
    showPane("landPane");
    $("ytUrl").focus();
    return;
  }
  if (payload.youtube_url && !payload.transcript_text) {
    note($("sourceState"), "Captions are still loading — one moment.", "bad");
    return;
  }

  S.payload = payload;
  S.result = null;
  S.files = [];
  S.cutId = null;
  S.open.clear();

  $("runBtn").disabled = true;
  showPane("workPane");
  $("stageLog").textContent = "";
  $("barFill").style.width = "2%";
  $("pctText").textContent = "0%";
  $("stageText").textContent = "Queued";
  note($("workHint"), "model pass");

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

    const pct = Math.round((job.progress || 0) * 0.7);   // extraction owns 0–70 %
    $("barFill").style.width = pct + "%";
    $("pctText").textContent = pct + "%";
    $("stageText").textContent = job.stage || "Working";

    if (job.progress !== last) {
      last = job.progress;
      $("stageLog").textContent += `${String(Math.round(job.progress || 0)).padStart(3, " ")}%  ${job.stage}\n`;
      $("stageLog").scrollTop = $("stageLog").scrollHeight;
    }

    if (job.status === "done") {
      clearInterval(S.timers.poll);
      try {
        const result = await api(`/api/jobs/${jobId}/results`);
        S.result = result;
        renderResults(result, S.payload);
        startCut();                                  // 1080p MP4s, automatically
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
function renderResults(data, payload) {
  const clips = data.clips || [];
  const rejected = data.dropped || [];

  $("resTitle").textContent = data.video_title || "Transcript session";
  $("resMeta").textContent = [
    data.channel || "",
    data.transcript_source ? `captions ${data.transcript_source}` : "",
    data.model_used ? `model ${data.model_used}` : "",
    data.ranges_planned ? `coverage ${data.ranges_planned}` : "",
  ].filter(Boolean).join("   ·   ");

  $("statCandidates").textContent = (data.sweep && data.sweep.longlist) || (data.longlist || []).length;
  $("statKept").textContent = clips.length;
  $("statRejected").textContent = rejected.length;
  $("statRequested").textContent = payload.num_clips || "AUTO";

  $("zipToggle").checked = S.zip;
  $("zipBtn").hidden = true;
  note($("cutState"), "Cutting 1080p…");
  $("cutTrack").hidden = true;

  renderClips();
  showPane("resultsPane");
}

function renderClips() {
  const list = $("clipList");
  const clips = (S.result && S.result.clips) || [];
  list.textContent = "";

  clips.forEach((clip, i) => {
    const li = el("li", "clip" + (S.open.has(i) ? " open" : ""));
    const row = el("div", "clip-row");

    row.appendChild(el("span", "clip-n", `Clip ${clip.n}`));
    row.appendChild(el("span", "clip-title", clip.hook_summary || clip.verbal_hook || "—"));

    const avg = clip.scores && clip.scores.avg;
    row.appendChild(el("span", "score" + (avg >= 8 ? " hi" : ""), avg == null ? "—" : avg));

    const file = S.files[i];
    if (file && !S.zip) {
      const a = el("a", "btn small primary", "Download");
      a.href = file.url;
      a.setAttribute("download", file.name);
      row.appendChild(a);
    } else if (!S.zip) {
      const b = el("button", "btn small", "Cutting…");
      b.type = "button";
      b.disabled = true;
      row.appendChild(b);
    } else {
      row.appendChild(el("span", "note", file ? `${file.size_mb} MB` : ""));
    }

    const more = el("button", "chip-btn", S.open.has(i) ? "Less" : "More");
    more.type = "button";
    more.dataset.more = String(i);
    more.setAttribute("aria-expanded", S.open.has(i) ? "true" : "false");
    row.appendChild(more);

    li.appendChild(row);
    if (S.open.has(i)) li.appendChild(morePanel(clip));
    list.appendChild(li);
  });

  $("zipBtn").hidden = !(S.zip && S.cutId && S.files.length);
}

function morePanel(clip) {
  const wrap = el("div", "clip-more");
  const titles = clip.titles || {};
  const scores = clip.scores || {};

  const time = el("div", "dgrid");
  [
    ["In", clip.start_stamp || hms(clip.start_sec)],
    ["Out", clip.end_stamp || hms(clip.end_sec)],
    ["Length", clip.duration_str || "—"],
  ].forEach(([k, v]) => {
    const cell = el("div", "dcell");
    cell.appendChild(el("div", "k", k));
    cell.appendChild(el("div", "v", v));
    time.appendChild(cell);
  });
  wrap.appendChild(time);

  const bars = el("div");
  Object.entries(scores).filter(([k, v]) => k !== "avg" && typeof v === "number").forEach(([k, v]) => {
    const row = el("div", "srow");
    row.appendChild(el("div", "k", k));
    const track = el("div", "track");
    const fill = el("i");
    fill.style.width = `${Math.max(0, Math.min(100, v * 10))}%`;
    track.appendChild(fill);
    row.appendChild(track);
    row.appendChild(el("div", "v", v));
    bars.appendChild(row);
  });
  wrap.appendChild(bars);

  [
    block("thumbnail text", titles.clickbait, { copy: true, strong: true }),
    block("search title", titles.search, { copy: true }),
    block("on-screen question", titles.debate, { copy: true }),
    block("upload caption", clip.upload_caption, { copy: true }),
    block("hashtags", clip.hashtags, { copy: true }),
    block("pinned comment", clip.pinned_comment, { copy: true }),
    block("verbal hook", clip.verbal_hook),
    block("ending", clip.ending),
    block("why it works", clip.why_it_works),
  ].forEach((node) => { if (node) wrap.appendChild(node); });
  return wrap;
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
  wrap.appendChild(el("div", "v" + (opts.strong ? " strong" : ""), text));
  return wrap;
}

/* ── cutting: 1080p, automatic ───────────────────────── */
async function startCut() {
  if (!S.jobId || !S.result) return;
  const clips = S.result.clips || [];
  if (!S.result.video_id || !clips.length) {
    note($("cutState"), S.result.video_id ? "No clips to cut." : "Pasted transcript — nothing to cut.", "warn");
    return;
  }

  $("cutTrack").hidden = false;
  $("cutFill").style.width = "2%";
  note($("cutState"), "Fetching the 1080p source…");

  try {
    const { cut_id } = await api(`/api/jobs/${S.jobId}/cut`, {
      method: "POST",
      body: JSON.stringify({ height: 1080 }),
    });
    S.cutId = cut_id;
    pollCut(cut_id);
  } catch (e) {
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
      note($("cutState"), e.message, "bad");
      return;
    }

    const pct = 70 + Math.round((cut.progress || 0) * 0.3);
    $("barFill").style.width = pct + "%";
    $("pctText").textContent = pct + "%";
    $("stageText").textContent = cut.stage || "Cutting";
    $("cutFill").style.width = `${cut.progress || 0}%`;
    note($("cutState"), `${cut.stage || "Cutting"} · ${cut.progress || 0}%`);

    if (cut.status === "done") {
      clearInterval(S.timers.cut);
      $("barFill").style.width = "100%";
      $("pctText").textContent = "100%";
      $("stageText").textContent = "Done";
      S.files = cut.files || [];
      note($("cutState"), `${S.files.length} clip(s) · ${cut.quality || "1080p"}`, "ok");
      $("zipBtn").href = `/api/cuts/${cutId}/zip`;
      showPane("resultsPane");
      renderClips();
      $("runBtn").disabled = false;
    } else if (cut.status === "error") {
      clearInterval(S.timers.cut);
      note($("cutState"), cut.error || "Cut failed", "bad");
      $("runBtn").disabled = false;
    }
  }, 1200);
}

/* ── reset / failure ─────────────────────────────────── */
function reset() {
  clearInterval(S.timers.poll);
  clearInterval(S.timers.cut);
  S.result = null;
  S.files = [];
  S.cutId = null;
  S.jobId = null;
  S.open.clear();
  $("runBtn").disabled = false;
  $("ytUrl").value = "";
  $("transcript").value = "";
  $("ownTranscriptBox").hidden = true;
  $("clipList").textContent = "";
  note($("sourceState"), "No source");
  showPane("landPane");
  $("ytUrl").focus();
}

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
  back.onclick = reset;
  const row = el("div");
  row.style.display = "flex";
  row.appendChild(back);
  box.appendChild(row);
  pane.appendChild(box);
  $("runBtn").disabled = false;
}
