/* UI smoke test: boots the production UI (ui-d) in jsdom against a
   stubbed API and walks the real flow: link → details → plan → extract → results
   → cut → packaging → copy → ZIP → failure → retry → downloader → reset.
   Every direction must expose the same data-role contract (see REQUIRED).
   Fails on any uncaught error, console.error, or missing role.
   Usage: node tools/ui_smoke.js            (all directions)
          node tools/ui_smoke.js ui-d       (production UI) */
const fs = require("fs");
const path = require("path");
const { JSDOM, VirtualConsole } = require("jsdom");

const ROOT = path.resolve(__dirname, "..");
const { DIRECTIONS } = require("./ui_contract");

const { REQUIRED } = require("./ui_contract");

const CONFIG = {
  version: "v0.1.0", provider: "stub", min_height: 1080, min_clips: 5, max_clips: 15,
  default_window: "40-50", tools: { ffmpeg: true, ffprobe: true, yt_dlp: true, can_cut: true, hints: {} },
  prompt: { master_loaded: true, location: "prompts/master.md" },
  windows: [{ id: "40-50", label: "40–50 s" }],
};
const TRANSCRIPT = {
  text: "00:00:08 - a line\n00:01:03 - another", lines: 2, seconds: 63, is_auto: true,
  title: "The Third Floor", channel: "Cold Case Files", video_id: "dQw4w9WgXcQ",
  source: "youtube-captions", chars: 30,
};
const CLIP = {
  n: 1, hook_summary: "door logged locked", start_sec: 8, end_sec: 63,
  start_stamp: "00:00:08", end_stamp: "00:01:03", duration_str: "0 min 55 sec", ending: "Cliffhanger",
  titles: { clickbait: "HE PRESSED IT 💀", search: "Who used his badge?", debate: "Accident… or murder? 😳" },
  scores: { curiosity: 9, stakes: 8, specificity: 9, speed: 8, avg: 8.5 },
  verbal_hook: "vh", why_it_works: "why", share_trigger: "st", safety: "none",
  overlays: [{ offset: "00:02", text: "LBL" }], sfx: "sfx", captions: "cap",
  upload_caption: "uc", hashtags: "#a #b", pinned_comment: "pc", transcript_ts: "t", transcript: "t",
};
const RESULTS = {
  video_id: "dQw4w9WgXcQ", video_title: "The Third Floor", channel: "Cold Case Files",
  transcript_source: "youtube-captions", model_used: "offline-demo", ranges_planned: "00:00:00-00:01:00",
  sweep: { longlist: 6, cleared: 2, window: "40-50", ranges: "00:00:00-00:01:00" }, longlist: [],
  dropped: [{ clip: 2, reason: "average score 6.0 is below the 8.0 quality gate" }],
  oracle_report: "{}", clips: [CLIP],
};
const FILES = [{ name: "clip-01_00-00-08_00-01-03.mp4", size_mb: 12.4, url: "/api/cuts/cut1/file/clip-01.mp4" }];

function makeFetch(state) {
  return async (url, opts = {}) => {
    const u = String(url);
    state.calls.push(`${opts.method || "GET"} ${u}`);
    const json = (obj, status = 200) => ({
      ok: status < 400, status,
      json: async () => obj,
      headers: { get: () => "application/json" },
    });
    if (u.includes("/api/config")) return json(CONFIG);
    if (u.includes("/api/transcript")) {
      if (state.failTranscript) return json({ detail: "NO CAPTIONS", hint: "Paste a transcript instead." }, 422);
      return json(TRANSCRIPT);
    }
    if (u.includes("/api/extract")) return json({ job_id: state.failRun ? "jobfail" : "job1" });
    if (/\/api\/jobs\/[^/]+\/results/.test(u)) return json(state.noClips ? { ...RESULTS, clips: [] } : RESULTS);
    if (u.includes("/api/jobs/jobfail")) return json({
      status: "error", progress: 56, stage: "Failed", elapsed_s: 0.4, warnings: [],
      error: "TypeError: _HttpProvider.complete() got an unexpected keyword argument 'ctx'",
      raw_answer: '{"sweep": {"longlist": 3}, "clips": 3}',
      error_hint: "Sheikh Arsalan Automation hit an internal error — nothing you did.",
    });
    if (/\/api\/jobs\/[^/]+$/.test(u)) return json({ status: "done", progress: 100, stage: "Done", error: null, elapsed_s: 1.2, warnings: [] });
    if (/\/api\/jobs\/[^/]+\/cut/.test(u)) return json({ cut_id: "cut1" });
    if (/\/api\/cuts\/[^/]+$/.test(u)) return json({ status: "done", progress: 100, stage: "ready", quality: "1080p", files: FILES });
    if (u.includes("/api/upload-transcript")) return json({ text: "00:00:01 - uploaded", chars: 20 });
    return json({ detail: "unhandled " + u }, 404);
  };
}

async function runDirection(name) {
  const html = fs.readFileSync(path.join(ROOT, "web", name + ".html"), "utf8");
  const core = fs.readFileSync(path.join(ROOT, "web/core.js"), "utf8");
  const view = fs.readFileSync(path.join(ROOT, "web", name + ".js"), "utf8");
  const page = html.replace(/<script src="\/static\/[^"]+"><\/script>/g, "");

  const errors = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push("jsdomError: " + (e.stack || e.message)));
  vc.on("error", (...a) => errors.push("console.error: " + a.join(" ")));

  const dom = new JSDOM(page, { runScripts: "outside-only", virtualConsole: vc, url: "http://localhost:8137/" });
  const { window } = dom;
  const state = { calls: [], failTranscript: false, failRun: false, noClips: false };
  window.fetch = makeFetch(state);
  window.navigator.clipboard = { writeText: async () => {} };
  window.isSecureContext = false;                        // exactly what a plain-http LAN origin gives you
  window.document.execCommand = () => true;
  window.URL.createObjectURL = () => "blob:stub";
  window.URL.revokeObjectURL = () => {};
  window.HTMLAnchorElement.prototype.click = function () {};   // no navigation in jsdom
  window.eval(core);
  window.eval(view);
  window.document.dispatchEvent(new window.Event("DOMContentLoaded"));

  const doc = window.document;
  const role = (r, scope) => (scope || doc).querySelector(`[data-role="${r}"]`);
  const roles = (r, scope) => Array.from((scope || doc).querySelectorAll(`[data-role="${r}"]`));
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const fire = (node, type) => node.dispatchEvent(new window.Event(type, { bubbles: true }));
  const visible = (node) => Boolean(node) && !node.hidden && !node.closest("[hidden]");
  const checks = {};
  const check = (label, ok) => { checks[label] = Boolean(ok); };

  await wait(60);

  /* 0 · contract: every requirement has a home in this direction */
  const missing = REQUIRED.filter((r) => !role(r));
  check("contract complete", missing.length === 0);
  if (missing.length) checks["missing roles"] = missing.join(", ");

  /* 1 · landing, config bounds, length presets */
  check("landing visible", visible(role("pane-landing")));
  check("build tag shows config version", (role("build-tag").textContent || "").includes("v0.1.0"));
  check("clip bounds 5..15", role("clip-count").min === "5" && role("clip-count").max === "15");
  check("four length presets", roles("len-option").length === 4);
  check("default length 40-50", (roles("len-option").find((b) => b.getAttribute("aria-pressed") === "true") || {}).dataset?.len === "40-50");
  check("badge AUTO", role("clip-badge").textContent.trim() === "AUTO");

  role("clip-count").value = "7";
  fire(role("clip-count"), "input");
  check("badge 7 clips", role("clip-badge").textContent.trim() === "7 clips");
  roles("len-option").find((b) => b.dataset.len === "custom").click();
  check("custom range shown", role("custom-len").hidden === false);
  roles("len-option").find((b) => b.dataset.len === "40-50").click();
  check("custom range hidden", role("custom-len").hidden === true);

  role("clip-count").value = "3"; fire(role("clip-count"), "change");
  check("low count clamped", role("clip-count").value === "5");
  role("clip-count").value = "99"; fire(role("clip-count"), "change");
  check("high count clamped", role("clip-count").value === "15");
  role("clip-count").value = "7"; fire(role("clip-count"), "change");

  /* 2 · paste a link → details */
  role("link-input").value = "https://www.youtube.com/watch?v=dQw4w9WgXcQ";
  fire(role("link-input"), "input");
  await wait(900);
  check("details visible", visible(role("pane-details")) && !visible(role("pane-landing")));
  check("fact title", role("fact-title").textContent.trim() === "The Third Floor");
  check("detail badge ready", role("detail-badge").textContent.trim() === "ready");
  check("badge keeps video id as tooltip", (role("detail-badge").title || "").includes("dQw4w9WgXcQ"));

  /* 3 · own transcript drawer toggles */
  role("own-toggle").click();
  check("own transcript open", visible(role("own-box")));
  role("own-toggle").click();
  check("own transcript closed", !visible(role("own-box")));

  /* 4 · Details → plan (direction C keeps the plan on a second card) */
  if (role("plan-next") && visible(role("plan-next"))) role("plan-next").click();

  /* 5 · extract → working (credits move under the bar) → results */
  role("run").click();
  await wait(120);
  check("credits under the bar", role("credits-slot").contains(role("credits")));
  await wait(3300);
  check("results visible with five-stage progress structure", visible(role("pane-results")) && doc.querySelectorAll(".steps li").length === 5);
  check("one clip row", roles("clip-item").length === 1);
  check("asked for 7", role("stat-asked").textContent.trim() === "7");
  check("download link per clip", roles("clip-download").length === 1);
  check("cut finished", (role("cut-state").textContent || "").includes("1080p"));

  /* 6 · packaging: More/Inspect shows every field, copy works without navigator.clipboard */
  roles("clip-more")[0].click();
  await wait(30);
  const pack = roles("packaging")[0];
  check("packaging shown", Boolean(pack));
  check("packaging fields", roles("packaging")[0] ? pack.querySelectorAll("[data-field]").length >= 5 : false);
  check("thumbnail text shown", (doc.body.textContent || "").includes("HE PRESSED IT 💀"));
  const copyBtn = roles("copy-control")[0];
  check("copy control present", Boolean(copyBtn));
  if (copyBtn) {
    const before = errors.length;
    copyBtn.click();
    await wait(40);
    check("copy fallback no crash", errors.length === before);
    check("copy fallback toast", (role("toasts").textContent || "").includes("Copied"));
  }

  /* 7 · theme toggles twice with no error */
  {
    const before = errors.length;
    role("theme-toggle").click();
    role("theme-toggle").click();
    check("theme toggle no crash", errors.length === before);
  }

  /* 8 · ZIP toggle replaces per-clip downloads with one archive link */
  role("zip-toggle").checked = true;
  fire(role("zip-toggle"), "change");
  await wait(30);
  check("zip link visible", visible(role("zip-link")));
  check("zip href", role("zip-link").getAttribute("href") === "/api/cuts/cut1/zip");
  check("row downloads hidden in zip mode", roles("clip-download").length === 0);
  role("zip-toggle").checked = false;
  fire(role("zip-toggle"), "change");
  await wait(20);
  check("row downloads back", roles("clip-download").length === 1);

  /* 9 · mode tabs */
  roles("mode").find((b) => b.dataset.mode === "downloader").click();
  check("downloader pane", visible(role("pane-downloader")) && !visible(role("pane-cutter")));
  roles("mode").find((b) => b.dataset.mode === "cutter").click();
  check("back to cutter", visible(role("pane-cutter")) && !visible(role("pane-downloader")));

  /* 10 · reset returns to landing, credits go home */
  role("new-run").click();
  await wait(30);
  check("reset to landing", visible(role("pane-landing")) && !visible(role("pane-results")));
  check("credits back in footer", role("credits-home").contains(role("credits")) && !role("credits-slot").contains(role("credits")));

  /* 11 · a fetch that finds no captions still opens Details with the drawer ready */
  state.failTranscript = true;
  role("link-input").value = "https://www.youtube.com/watch?v=blocked0001";
  fire(role("link-input"), "input");
  await wait(900);
  check("failed fetch opens details", visible(role("pane-details")));
  check("failed fetch badge", role("detail-badge").textContent.trim() === "no captions");
  check("failed fetch drawer", visible(role("own-box")));
  state.failTranscript = false;
  role("new-run").click();
  await wait(30);

  /* 12 · a run that dies inside the server: readable title, raw answer, retry works */
  state.failRun = true;
  role("link-input").value = "https://www.youtube.com/watch?v=dQw4w9WgXcQ";
  fire(role("link-input"), "input");
  await wait(900);
  if (role("plan-next") && visible(role("plan-next"))) role("plan-next").click();
  role("run").click();
  await wait(1700);
  check("error pane", visible(role("pane-error")));
  check("error title", role("error-title").textContent.trim() === "Automation hit a bug");
  check("error hint shown", visible(role("error-hint")) && role("error-hint").textContent.includes("nothing you did"));
  check("raw answer shown", visible(role("error-raw")));
  check("raw answer text", (role("error-raw").textContent || "").includes('"clips": 3'));
  check("run re-armed", role("run").disabled === false);
  state.failRun = false;
  role("retry").click();
  await wait(3400);
  check("retry reaches results", visible(role("pane-results")));
  role("new-run").click();
  await wait(30);

  /* 13 · a run that finds no clip says why, using the server's own reasons */
  state.noClips = true;
  role("link-input").value = "https://www.youtube.com/watch?v=dQw4w9WgXcQ";
  fire(role("link-input"), "input");
  await wait(900);
  if (role("plan-next") && visible(role("plan-next"))) role("plan-next").click();
  role("run").click();
  await wait(3400);
  check("empty run shows results", visible(role("pane-results")));
  check("empty run explains itself", (role("clip-list").textContent || "").includes("No clip passed the checks") && (role("clip-list").textContent || "").includes("8.0 quality gate"));
  check("empty run has no clip rows", roles("clip-item").length === 0);
  state.noClips = false;
  role("new-run").click();
  await wait(30);

  /* 14 · the credits line: both names bold, never clipped */
  const credits = role("credits").textContent.replace(/\s+/g, " ").trim();
  check("credits text", ["Proudly Created by", "Sheikh Arsalan", "in Collaboration with", "Mubashir"].every((w) => credits.includes(w)));
  const bold = roles("credits")[0].querySelectorAll("b");
  check("credits bold names", bold.length === 2 && bold[0].textContent.trim() === "Sheikh Arsalan" && bold[1].textContent.trim() === "Mubashir");

  const failed = Object.entries(checks).filter(([, v]) => v === false).map(([k]) => k);
  const info = Object.entries(checks).filter(([, v]) => typeof v === "string").map(([k, v]) => `${k}: ${v}`);
  return { name, checks, failed, info, errors };
}

(async () => {
  const only = process.argv[2];
  const targets = only ? [only] : DIRECTIONS;
  let bad = 0;
  for (const name of targets) {
    const res = await runDirection(name);
    const total = Object.keys(res.checks).length;
    console.log(`── ${name}: ${total - res.failed.length}/${total} checks`);
    res.info.forEach((line) => console.log("   " + line));
    if (res.failed.length) {
      res.failed.forEach((k) => console.log("   FAILED  " + k));
      bad += res.failed.length;
    }
    if (res.errors.length) {
      res.errors.forEach((e) => console.log("   ERROR   " + e.split("\n")[0]));
      bad += res.errors.length;
    }
  }
  console.log(bad ? `\nFAIL (${bad})` : "\nOK — all directions pass the same contract");
  process.exitCode = bad ? 1 : 0;
})();
