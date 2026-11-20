/* UI smoke test: boots index.html + app.js in jsdom against a stubbed API.
   Walks the real flow: paste link → details → config → extract → results → cut.
   Fails on any uncaught error, any console.error, and any empty critical node.
   Usage: node tools/ui_smoke.js */
const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");

const ROOT = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(ROOT, "web/index.html"), "utf8")
  .replace(/<script src="\/static\/app\.js[^"]*"><\/script>/, "");

const CONFIG = {
  version: "v0.1.0",
  provider: "stub",
  min_height: 1080,
  min_clips: 5,
  max_clips: 15,
  default_window: "40-50",
  tools: { ffmpeg: true, ffprobe: true, yt_dlp: true, can_cut: true, hints: {} },
  prompt: { master_loaded: true, location: "prompts/master.md" },
  windows: [
    { id: "40-50", label: "40–50 s" },
    { id: "60-90", label: "60–90 s" },
    { id: "90-180", label: "90–180 s" },
    { id: "custom", label: "Custom range" },
  ],
};

const TRANSCRIPT = {
  text: "00:00:08 - a line\n00:01:03 - another", lines: 2, seconds: 63,
  is_auto: true, title: "The Third Floor", channel: "Cold Case Files",
  video_id: "dQw4w9WgXcQ", source: "youtube-captions",
};

const RESULTS = {
  video_id: "dQw4w9WgXcQ", video_title: "The Third Floor", channel: "Cold Case Files",
  transcript_source: "youtube-captions", model_used: "offline-demo",
  ranges_planned: "00:00:00-00:01:00",
  sweep: { longlist: 6, cleared: 2, window: "40-50", ranges: "00:00:00-00:01:00" },
  longlist: [], dropped: [{ clip: 2, reason: "average score 6.0 is below the 8.0 quality gate" }],
  oracle_report: "{}",
  clips: [{
    n: 1, hook_summary: "door logged locked", start_sec: 8, end_sec: 63,
    start_stamp: "00:00:08", end_stamp: "00:01:03",
    start_sentence: "The detective arrived at midnight.", end_sentence: "The alibi collapsed.",
    duration_str: "00:00:55", duration_line: "0 min 55 sec", ending: "Cliffhanger",
    titles: { clickbait: "HE PRESSED IT 💀", search: "Who used his badge?", debate: "Accident… or murder? 😳" },
    scores: { curiosity: 9, stakes: 8, specificity: 9, speed: 8, avg: 8.5 },
    verbal_hook: "vh", why_it_works: "why", share_trigger: "st",
    safety: "none", overlays: [{ offset: "00:02", text: "LBL" }],
    sfx: "sfx", captions: "cap", upload_caption: "uc", hashtags: "#a #b",
    pinned_comment: "pc", transcript_ts: "t", transcript: "t",
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
    if (u.includes("/api/transcript")) return json(TRANSCRIPT);
    if (u.includes("/api/extract")) return json({ job_id: "job1" });
    if (u.match(/\/api\/jobs\/[^/]+\/results/)) return json(RESULTS);
    if (u.match(/\/api\/jobs\/[^/]+$/)) return json({
      status: "done", progress: 100, stage: "Done", error: null, elapsed_s: 1.2, warnings: [],
    });
    if (u.includes("/api/video-quality")) return json({ qualities: [2160, 1440, 1080] });
    if (u.match(/\/api\/jobs\/[^/]+\/cut/)) return json({ cut_id: "cut1" });
    if (u.match(/\/api\/cuts\/[^/]+$/)) return json({
      status: "done", progress: 100, stage: "ready", quality: "1080p",
      files: [
        { name: "clip-01_00-00-08_00-01-03.mp4", size_mb: 12.4, url: "/api/cuts/cut1/file/clip-01.mp4" },
      ],
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
  const calls = [];
  window.fetch = makeFetch(calls);
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
  const sel = (q) => window.document.querySelector(q);
  const all = (q) => window.document.querySelectorAll(q);
  const checks = {};

  checks["landing visible"] = !$("landPane").hidden;
  checks["build tag"] = $("buildTag").textContent.trim();
  checks["clips min"] = $("numClips").min;
  checks["clips max"] = $("numClips").max;
  checks["length presets"] = all("#lenSeg button").length;
  checks["default length"] = sel('#lenSeg button[aria-selected="true"]').dataset.len;
  checks["clip badge auto"] = $("clipCountBadge").textContent.trim();
  checks["side label"] = $("sideLabel").textContent.trim();

  // config: 7 clips + custom range
  $("numClips").value = "7";
  $("numClips").dispatchEvent(new window.Event("input"));
  checks["clip badge manual"] = $("clipCountBadge").textContent.trim();
  sel('#lenSeg button[data-len="custom"]').click();
  checks["custom length shown"] = !$("customLen").hidden;
  sel('#lenSeg button[data-len="40-50"]').click();
  checks["custom length hidden"] = $("customLen").hidden;

  // paste a link → details
  $("ytUrl").value = "https://www.youtube.com/watch?v=dQw4w9WgXcQ";
  $("ytUrl").dispatchEvent(new window.Event("input"));
  await new Promise((r) => setTimeout(r, 900));
  checks["details pane"] = !$("setupPane").hidden && $("landPane").hidden;
  checks["fact title"] = $("factTitle").textContent.trim();
  checks["fact length"] = $("factLength").textContent.trim();
  checks["side label details"] = $("sideLabel").textContent.trim();

  // own transcript drawer
  $("ownTranscript").click();
  checks["own transcript open"] = !$("ownTranscriptBox").hidden;
  $("ownTranscript").click();
  checks["own transcript closed"] = $("ownTranscriptBox").hidden;

  // extract → results → cut
  $("runBtn").click();
  await new Promise((r) => setTimeout(r, 120));
  checks["credits under the bar"] = $("credits").parentElement === $("creditsSlot");
  await new Promise((r) => setTimeout(r, 3100));
  checks["clip rows"] = all("#clipList li").length;
  checks["results visible"] = !$("resultsPane").hidden;
  checks["asked"] = $("statRequested").textContent.trim();
  checks["download links"] = all("#clipList a.btn").length;
  checks["cut state"] = $("cutState").textContent.trim();

  // More expands the packaging
  sel("#clipList [data-more]").click();
  await new Promise((r) => setTimeout(r, 30));
  checks["more panel"] = all("#clipList .clip-more").length;
  checks["packaging fields"] = all("#clipList .clip-more .dblock").length;
  checks["thumbnail text"] = $("clipList").textContent.includes("HE PRESSED IT 💀");

  // ZIP toggle turns the row buttons into one archive button
  $("zipToggle").checked = true;
  $("zipToggle").dispatchEvent(new window.Event("change"));
  await new Promise((r) => setTimeout(r, 30));
  checks["zip button visible"] = !$("zipBtn").hidden;
  checks["zip href"] = $("zipBtn").getAttribute("href");
  checks["row downloads hidden"] = all("#clipList a.btn").length === 0;
  $("zipToggle").checked = false;
  $("zipToggle").dispatchEvent(new window.Event("change"));

  // downloader tab
  sel('#modeTabs button[data-mode="downloader"]').click();
  checks["downloader pane"] = !$("downloaderPane").hidden && $("cutterPane").hidden;
  sel('#modeTabs button[data-mode="cutter"]').click();
  checks["back to cutter"] = !$("cutterPane").hidden && $("downloaderPane").hidden;

  // credits return to the footer, new link resets
  $("newRunBtn").click();
  await new Promise((r) => setTimeout(r, 30));
  checks["credits in footer"] = $("credits").parentElement === window.document.body;
  checks["back to landing"] = !$("landPane").hidden;

  console.log("── checks");
  Object.entries(checks).forEach(([k, v]) => console.log(`   ${k.padEnd(22)} ${v}`));

  const mustBeTrue = [
    "landing visible", "details pane", "custom length shown", "custom length hidden",
    "own transcript open", "own transcript closed", "results visible", "more panel",
    "thumbnail text", "zip button visible", "row downloads hidden", "downloader pane",
    "back to cutter", "credits in footer", "back to landing", "credits under the bar",
  ];
  const mustBeNonZero = ["length presets", "clip rows", "download links", "packaging fields"];
  const expected = { "clips min": "5", "clips max": "15", "default length": "40-50",
    "clip badge auto": "AUTO", "clip badge manual": "7 clips", "asked": "7",
    "zip href": "/api/cuts/cut1/zip" };

  const fail = [];
  mustBeTrue.forEach((k) => { if (!checks[k]) fail.push(`${k} = ${checks[k]}`); });
  mustBeNonZero.forEach((k) => { if (!checks[k]) fail.push(`${k} = ${checks[k]}`); });
  Object.entries(expected).forEach(([k, v]) => { if (String(checks[k]) !== v) fail.push(`${k} = ${checks[k]} (want ${v})`); });

  if (errors.length) {
    console.log("\n── errors");
    errors.forEach((e) => console.log("   " + e.split("\n")[0]));
  }
  if (fail.length) {
    console.log("\n── failed");
    fail.forEach((f) => console.log("   " + f));
    console.log("\nFAIL");
    process.exit(1);
  }
  if (errors.length) { console.log("\nFAIL"); process.exit(1); }
  console.log("\nOK");
})();
