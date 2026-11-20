/* UI smoke test: boots index.html + app.js in jsdom against a stubbed API.
   Fails on any uncaught error, any console.error, and any empty critical node.
   Usage: node tools/ui_smoke.js */
const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");

const ROOT = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(ROOT, "web/index.html"), "utf8")
  .replace('<script src="/static/app.js"></script>', "");

const CONFIG = {
  version: "v0.1.0",
  provider: "stub",
  requires_invite: false,
  min_height: 1080,
  tools: { ffmpeg: true, ffprobe: true, yt_dlp: true, can_cut: true, hints: {} },
  prompt: { master_loaded: true, location: "prompts/master.md" },
  niches: [{ id: "True Crime", icon: "x" }, { id: "Sports", icon: "x" }],
  subniches: { "True Crime": ["Scandal", "Cult"], Sports: [] },
  audiences: ["U.S. English"],
  languages: ["U.S. English", "Pure Urdu"],
  models: [{ id: "m1", label: "Model One" }, { id: "m2", label: "Model Two" }],
  default_model: "m1",
  windows: [{ id: "E", label: "45s–5m25s" }, { id: "A", label: "30–60s" }],
  default_window: "E",
};

const RESULTS = {
  video_id: "dQw4w9WgXcQ", video_title: "Test video", channel: "Channel",
  transcript_source: "youtube-captions", model_used: "offline-demo",
  ranges_planned: "00:00:00-00:01:00",
  sweep: { longlist: 6, cleared: 2, window: "E", ranges: "00:00:00-00:01:00" },
  longlist: [], dropped: [{ clip: 2, reason: "average score 6.0 is below the 8.0 quality gate" }],
  oracle_report: "{}",
  clips: [{
    n: 1, hook_summary: "door logged locked", start_sec: 8, end_sec: 63,
    start_stamp: "00:00:08", end_stamp: "00:01:03",
    start_sentence: "The detective arrived at midnight.", end_sentence: "The alibi collapsed.",
    duration_str: "00:00:55", duration_line: "0 min 55 sec",
    titles: { clickbait: "cb", search: "srch", debate: "db" },
    scores: { curiosity: 9, stakes: 8, specificity: 9, speed: 8, avg: 8.5 },
    verbal_hook: "vh", ending: "en", why_it_works: "why", share_trigger: "st",
    safety: "none", overlays: [{ offset: "00:02", text: "LBL" }],
    sfx: "sfx", captions: "cap", upload_caption: "uc", hashtags: "#a #b",
    pinned_comment: "pc", transcript_ts: "t", transcript: "t", n_clip: 1,
  }],
};

function makeFetch(log) {
  return async (url, opts = {}) => {
    const u = String(url);
    log.push(`${(opts.method || "GET")} ${u}`);
    const json = (obj, status = 200) => ({
      ok: status < 400, status,
      json: async () => obj,
      blob: async () => obj,
      headers: { get: () => "application/json" },
    });
    if (u.includes("/api/config")) return json(CONFIG);
    if (u.includes("/api/tools")) return json(CONFIG.tools);
    if (u.includes("/api/transcript")) return json({
      text: "00:00:08 - a line\n00:01:03 - another", lines: 2, seconds: 63,
      is_auto: true, title: "T", channel: "C", video_id: "dQw4w9WgXcQ", source: "youtube-captions",
    });
    if (u.includes("/api/extract")) return json({ job_id: "job1" });
    if (u.match(/\/api\/jobs\/[^/]+\/results/)) return json(RESULTS);
    if (u.match(/\/api\/jobs\/[^/]+$/)) return json({
      status: "done", progress: 100, stage: "Done", error: null, elapsed_s: 1.2, warnings: [],
    });
    if (u.includes("/api/video-quality")) return json({ qualities: [2160, 1440, 1080] });
    if (u.match(/\/api\/jobs\/[^/]+\/cut/)) return json({ cut_id: "cut1" });
    if (u.match(/\/api\/cuts\/[^/]+$/)) return json({
      status: "done", progress: 100, stage: "ready", quality: "1080p",
      files: [{ name: "clip-01_00-00-08_00-01-03.mp4", size_mb: 12.4, url: "/api/cuts/cut1/file/x.mp4" }],
    });
    return json({ detail: "unhandled " + u }, 404);
  };
}

(async () => {
  const errors = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push("jsdomError: " + (e.stack || e.message)));
  vc.on("error", (...a) => errors.push("console.error: " + a.join(" ")));

  const dom = new JSDOM(html, { runScripts: "outside-only", virtualConsole: vc, url: "http://localhost:8137/" });
  const { window } = dom;
  window.fetch = makeFetch([]);
  window.navigator.clipboard = { writeText: async () => {} };
  window.elementFromPoint = () => null;

  const app = fs.readFileSync(path.join(ROOT, "web/app.js"), "utf8");
  try {
    window.eval(app);
  } catch (e) {
    errors.push("eval: " + (e.stack || e.message));
  }
  window.document.dispatchEvent(new window.Event("DOMContentLoaded"));
  await new Promise((r) => setTimeout(r, 60));

  const $ = (id) => window.document.getElementById(id);
  const checks = {
    "niche options": $("nicheSel").options.length,
    "model options": $("modelSel").options.length,
    "window options": $("windowSel").options.length,
    "audience options": $("audienceSel").options.length,
    "provider chip": $("providerText").textContent.trim(),
    "prompt chip": $("promptText").textContent.trim(),
    "tools chip": $("toolsText").textContent.trim(),
    "empty title": $("emptyTitle").textContent.trim(),
  };

  // drive a full run: URL -> captions -> extract -> results -> cut
  $("ytUrl").value = "https://www.youtube.com/watch?v=dQw4w9WgXcQ";
  $("ytUrl").dispatchEvent(new window.Event("input"));
  await new Promise((r) => setTimeout(r, 800));

  $("transcript").value = "00:00:08 - a line\n00:01:03 - another";
  $("runBtn").click();
  await new Promise((r) => setTimeout(r, 1300));

  const rows = window.document.querySelectorAll("#clipRows tr").length;
  const detailRows = window.document.querySelectorAll("#inspBody .irow").length;
  checks["result rows"] = rows;
  checks["detail rows"] = detailRows;
  checks["results pane visible"] = !$("resultsPane").hidden;
  checks["cut enabled"] = !$("cutBtn").disabled;

  if (rows > 0) {
    $("cutBtn").click();
    await new Promise((r) => setTimeout(r, 1700));
    checks["file links"] = window.document.querySelectorAll("#fileList a").length;
    checks["cut state"] = $("cutState").textContent.trim();
  // tab switching must not throw
  const rejectedTab = window.document.querySelector('#segTabs button[data-view="rejected"]');
  rejectedTab.click();
  checks["rejected view"] = !$("viewRejected").hidden;
  window.document.querySelector('#segTabs button[data-view="clips"]').click();
  }

  console.log("── checks");
  Object.entries(checks).forEach(([k, v]) => console.log(`   ${k.padEnd(22)} ${v}`));

  const bad = Object.entries(checks).filter(([k, v]) =>
    (k.endsWith("options") || k === "result rows" || k === "detail rows") ? !v : false);

  if (errors.length) {
    console.log("\n── errors");
    errors.forEach((e) => console.log("   " + e.split("\n")[0]));
  }
  if (bad.length || errors.length) {
    console.log("\nFAIL");
    process.exit(1);
  }
  console.log("\nOK");
})();
