/* Shared client engine for Sheikh Arsalan Automation.
 *
 * The production UI renders the shared flow. This file owns
 * everything that is not layout: API calls, the stage machine, polling, the 1080p
 * cut, packaging fields, theme, icons and a copy fallback that works on plain
 * http://<lan-ip>:8137. A direction supplies a "view" that renders state and
 * forwards user actions back to the app. Model output is written only with
 * textContent, never innerHTML. */
(function () {
  "use strict";

  var SVG_NS = "http://www.w3.org/2000/svg";
  var THEME_KEY = "saa_theme";
  var DEFAULT_NOTE = "One timestamp per line.";

  var ICONS = {
    scissors: '<circle cx="6" cy="6" r="2.4"/><circle cx="6" cy="18" r="2.4"/><path d="M8 7.6L20 17M8 16.4L20 7"/>',
    download: '<path d="M12 4v10M8 11l4 4 4-4M4 19h16"/>',
    link: '<path d="M10 13a4 4 0 0 0 6 0l2-2a4 4 0 0 0-6-6l-1 1"/><path d="M14 11a4 4 0 0 0-6 0l-2 2a4 4 0 0 0 6 6l1-1"/>',
    copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M15 5H6a1 1 0 0 0-1 1v9"/>',
    alert: '<path d="M12 4l9 16H3l9-16z"/><path d="M12 10v4M12 17v.5"/>',
    upload: '<path d="M12 20V9M8 12l4-4 4 4M4 5h16"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6L17 7M7 17l-1.4 1.4"/>',
    moon: '<path d="M20 14a8 8 0 1 1-9-11 6.5 6.5 0 0 0 9 11z"/>',
    captions: '<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M8 12h3M14 12h2"/>',
    check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
    back: '<path d="M19 12H5M11 6l-6 6 6 6"/>',
    minus: '<path d="M5 12h14"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    github: '<path d="M9 19c-4 .9-4-2.2-5.5-2.7M15 21v-3.2c0-.9.1-1.3-.5-1.9 2.4-.3 4.5-1.2 4.5-5.2a4 4 0 0 0-1.1-2.8 3.7 3.7 0 0 0-.1-2.8s-.9-.3-3 1.1a10.4 10.4 0 0 0-5.4 0C7.3 3.8 6.4 4.1 6.4 4.1a3.7 3.7 0 0 0-.1 2.8A4 4 0 0 0 5.2 9.7c0 4 2.1 4.9 4.5 5.2-.6.6-.6 1.2-.5 1.9V21"/>',
    video: '<rect x="3" y="6" width="12" height="12" rx="2.5"/><path d="M15 11l6-3.5v9L15 13z"/>',
    audio: '<path d="M9 18V6l10-2v12"/><circle cx="7" cy="18" r="2.2"/><circle cx="17" cy="16" r="2.2"/>'
  };

  /* ── DOM helpers ───────────────────────────────────────────────────── */
  function role(name, scope) {
    return (scope || document).querySelector('[data-role="' + name + '"]');
  }
  function roles(name, scope) {
    return Array.prototype.slice.call((scope || document).querySelectorAll('[data-role="' + name + '"]'));
  }
  function put(name, text, scope) {
    var node = role(name, scope);
    if (node) node.textContent = text === null || text === undefined ? "" : String(text);
    return node;
  }
  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }
  function icon(name, cls) {
    var svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("class", "ic" + (cls ? " " + cls : ""));
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    svg.innerHTML = ICONS[name] || "";
    return svg;
  }
  function hydrateIcons(scope) {
    Array.prototype.forEach.call((scope || document).querySelectorAll("[data-icon]"), function (node) {
      if (!node.querySelector("svg")) node.appendChild(icon(node.getAttribute("data-icon")));
    });
  }
  function bindActions(map) {
    document.addEventListener("click", function (e) {
      var target = e.target && e.target.closest ? e.target.closest("[data-action]") : null;
      if (!target) return;
      var fn = map[target.getAttribute("data-action")];
      if (typeof fn === "function") fn(target, e);
    });
  }
  function bindDrop(onFile) {
    document.addEventListener("dragover", function (e) { e.preventDefault(); });
    document.addEventListener("drop", function (e) {
      e.preventDefault();
      var file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      if (file) onFile(file);
    });
  }
  function focusIfDesktop(node) {
    if (!node || !window.matchMedia) return;
    if (window.matchMedia("(hover: hover) and (pointer: fine)").matches) node.focus();
  }

  /* ── theme ─────────────────────────────────────────────────────────── */
  var theme = {
    isLight: function () { return document.documentElement.getAttribute("data-theme") === "light"; },
    set: function (light) {
      document.documentElement.setAttribute("data-theme", light ? "light" : "dark");
      try { localStorage.setItem(THEME_KEY, light ? "light" : "dark"); } catch (_) { /* private mode */ }
    },
    toggle: function () { var light = !theme.isLight(); theme.set(light); return light; }
  };

  /* ── formatting and model shaping ──────────────────────────────────── */
  function hms(sec) {
    var s = Math.max(0, Math.round(Number(sec) || 0));
    return [Math.floor(s / 3600), Math.floor((s % 3600) / 60), s % 60]
      .map(function (n) { return String(n).padStart(2, "0"); }).join(":");
  }
  function clampClips(raw, min, max) {
    var text = String(raw === null || raw === undefined ? "" : raw).trim();
    var n = parseInt(text, 10);
    if (!text || !n) return 0;                       // 0 = AUTO
    return Math.max(min, Math.min(max, n));
  }
  function scoreText(avg) {
    if (avg === null || avg === undefined || avg === "") return "—";
    var n = Number(avg);
    return isFinite(n) ? n.toFixed(1) : "—";
  }
  function txt(value) {
    return value === null || value === undefined ? "" : String(value).trim();
  }
  function field(key, label, value, extra) {
    if (value === null || value === undefined) return null;
    var text = typeof value === "object" ? JSON.stringify(value) : String(value);
    if (!text.trim()) return null;
    return Object.assign({ key: key, label: label, value: text, copy: false, strong: false }, extra || {});
  }

  /* The full packaging for one clip. Every direction renders these same fields,
     so the owner sees identical content whichever layout he picks. */
  function packaging(clip) {
    var c = clip && typeof clip === "object" ? clip : {};
    var t = c.titles && typeof c.titles === "object" ? c.titles : {};
    var s = c.scores && typeof c.scores === "object" ? c.scores : {};
    var avg = s.avg === null || s.avg === undefined || s.avg === "" ? null : Number(s.avg);
    if (avg !== null && !isFinite(avg)) avg = null;
    var scores = Object.keys(s).filter(function (k) {
      return k !== "avg" && typeof s[k] === "number";
    }).map(function (k) { return { label: k, value: s[k] }; });
    var fields = [
      field("thumb", "Thumbnail text", t.clickbait, { copy: true, strong: true }),
      field("search", "Search title", t.search, { copy: true }),
      field("question", "Video Title", t.debate, { copy: true }),
      field("caption", "Upload caption", c.upload_caption, { copy: true }),
      field("hashtags", "Hashtags", c.hashtags, { copy: true }),
      field("pinned", "Pinned comment", c.pinned_comment, { copy: true }),
      field("hook", "Verbal hook", c.verbal_hook),
      field("share", "Share trigger", c.share_trigger),
      field("ending", "Ending", c.ending),
      field("why", "Why it works", c.why_it_works),
      field("sfx", "Sound effects", c.sfx),
      field("safety", "Safety", c.safety)
    ].filter(Boolean);
    var thumb = fields.filter(function (f) { return f.key === "thumb"; })[0];
    var span = Number(c.end_sec) - Number(c.start_sec);
    return {
      title: txt(c.hook_summary) || txt(c.verbal_hook) || "—",
      seconds: isFinite(span) && span > 0 ? Math.round(span) : null,
      avg: avg,
      avgText: scoreText(avg),
      timing: [
        ["In", txt(c.start_stamp) || (c.start_sec === undefined ? "—" : hms(c.start_sec))],
        ["Out", txt(c.end_stamp) || (c.end_sec === undefined ? "—" : hms(c.end_sec))],
        ["Length", txt(c.duration_str) || "—"]
      ],
      scores: scores,
      fields: fields,
      thumb: thumb ? thumb.value : "",
      start: txt(c.start_stamp) || hms(c.start_sec),
      end: txt(c.end_stamp) || hms(c.end_sec),
      duration: txt(c.duration_str) || (isFinite(span) && span > 0 ? hms(span) : "—")
    };
  }

  /* Facts for the Details block. Shared so the wording never drifts. */
  function factsOf(d) {
    return {
      title: txt(d.title) || "—",
      channel: txt(d.channel) || "—",
      length: d.seconds ? hms(d.seconds) : "—",
      captions: d.is_auto ? "auto-generated" : "published",
      transcript: d.lines ? d.lines + " lines · " + String(d.text || "").length.toLocaleString() + " characters" : "—",
      niche: "detected by the model on extract",
      badge: "ready",
      badgeTone: "ok",
      badgeTitle: d.video_id ? "video id " + d.video_id : ""
    };
  }
  function factsFailed(err) {
    return {
      title: "not fetched", channel: "—", length: "—", captions: "unavailable",
      transcript: "paste your own below", niche: "detected by the model on extract",
      badge: "no captions", badgeTone: "bad", badgeTitle: (err && err.message) || ""
    };
  }
  function factsEmpty() {
    return { title: "—", channel: "—", length: "—", captions: "—", transcript: "—",
      niche: "detected by the model on extract", badge: "", badgeTone: "", badgeTitle: "" };
  }

  /* what to say when a run ends with no clip: the server's own rejection reasons */
  function emptyMessage(model) {
    var why = (model.dropped || []).slice(0, 3);
    return why.length
      ? "No clip passed the checks. Rejected: " + why.join(" · ")
      : "No clip passed the checks, and the model returned no usable ranges.";
  }

  function titleFor(message) {
    var m = message || "";
    if (m.indexOf("NO TIMESTAMPS") !== -1) return "Transcript has no timestamps";
    if (m.indexOf("clip-report") !== -1) return "Answer was not valid JSON";
    if (m.indexOf("slow right now") !== -1) return "Model timed out";
    if (/api key/i.test(m)) return "API key rejected";
    if (/cut off|output tokens|output room/i.test(m)) return "The answer was cut off";
    if (/caption/i.test(m)) return "Captions unavailable";
    if (/^(TypeError|KeyError|AttributeError|NameError|IndexError|ValueError|OSError):/.test(m)) return "Automation hit a bug";
    return "Run failed";
  }

  /* ── clipboard: works on https, localhost AND plain http on a LAN address ── */
  function copyText(text) {
    var value = String(text === null || text === undefined ? "" : text);
    if (!value.trim()) return Promise.resolve("empty");
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(value).then(function () { return "ok"; }, function () {
        return legacyCopy(value);
      });
    }
    return Promise.resolve(legacyCopy(value));
  }
  function legacyCopy(value) {
    var box = document.createElement("textarea");
    box.value = value;
    box.setAttribute("readonly", "");
    box.setAttribute("aria-hidden", "true");
    box.style.cssText = "position:fixed;top:0;left:-9999px;width:1px;height:1px;opacity:0";
    document.body.appendChild(box);
    var ok = false;
    try {
      box.select();
      box.setSelectionRange(0, value.length);
      ok = document.execCommand("copy");
    } catch (_) {
      ok = false;
    }
    box.remove();
    return ok ? "ok" : "blocked";
  }

  /* ── API ───────────────────────────────────────────────────────────── */
  function api(path, opts) {
    var options = opts || {};
    var init = Object.assign({}, options, {
      headers: Object.assign({ "Content-Type": "application/json" }, options.headers || {})
    });
    return fetch(path, init).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (!res.ok) {
          var err = new Error((data && data.detail) || "HTTP " + res.status);
          err.hint = (data && data.hint) || "";
          throw err;
        }
        return data;
      });
    });
  }

  /* ── the app: flow + state. Views only render and forward actions. ── */
  function createApp(view) {
    var S = {
      cfg: null, booted: false, busy: false, details: null, link: "", payload: null,
      jobId: null, result: null, cutId: null, files: [], zip: false,
      runId: 0, fetchSeq: 0,
      timers: { fetch: null, poll: null, cut: null }
    };

    function setSource(tone, text) { view.setSource({ tone: tone || "", text: text || "" }); }

    function clearTimers(names) {
      names.forEach(function (n) { clearTimeout(S.timers[n]); clearInterval(S.timers[n]); S.timers[n] = null; });
    }

    function finishRun() { S.busy = false; view.setBusy(false); }

    function renderError(title, message, hint, raw) {
      view.renderError({
        title: title, message: message || "", hint: hint || "", raw: raw || "",
        canRetry: Boolean(S.payload)
      });
      view.showStage("error");
    }

    function transcriptText() {
      var own = String(view.readTranscript() || "").trim();
      return own || (S.details && S.details.text) || "";
    }

    function buildModel() {
      var data = S.result || {};
      var clips = Array.isArray(data.clips) ? data.clips : [];
      var dropped = Array.isArray(data.dropped) ? data.dropped : [];
      var sweep = data.sweep && typeof data.sweep === "object" ? data.sweep : {};
      var longlist = Array.isArray(data.longlist) ? data.longlist.length : 0;
      var payload = S.payload || {};
      return {
        ready: Boolean(S.result),
        runId: S.runId,
        title: data.video_title || (S.result ? "Transcript session" : ""),
        meta: [
          txt(data.channel),
          data.transcript_source ? "captions " + data.transcript_source : "",
          data.model_used ? "model " + data.model_used : "",
          data.ranges_planned ? "coverage " + data.ranges_planned : ""
        ].filter(Boolean),
        stats: {
          found: sweep.longlist || longlist,
          kept: clips.length,
          rejected: dropped.length,
          asked: payload.num_clips ? payload.num_clips : "AUTO"
        },
        clips: clips.map(function (c, i) {
          return { index: i, n: Number(c && c.n) || i + 1, pack: packaging(c) };
        }),
        dropped: dropped.map(function (d) {
          return typeof d === "string" ? d : txt(d && d.reason) || "rejected";
        }).filter(Boolean),
        zip: S.zip,
        files: S.files,
        zipUrl: S.cutId && S.files.length ? "/api/cuts/" + S.cutId + "/zip" : ""
      };
    }

    function readPayload() {
      var o = view.readOptions();
      var custom = o.len === "custom";
      var num = function (v) { return parseInt(v, 10) || null; };
      return {
        youtube_url: S.link || view.readLink(),
        transcript_text: transcriptText(),
        niche: "auto",
        audience: "U.S. English",
        language: "U.S. English",
        num_clips: clampClips(o.clips, S.cfg.min_clips || 5, S.cfg.max_clips || 15),
        window: custom ? "custom" : o.len,
        custom_min_sec: custom ? num(o.customMin) : null,
        custom_max_sec: custom ? num(o.customMax) : null,
        model: "",
        cascade: true,
        already_extracted: ""
      };
    }

    /* step 0: boot */
    function boot() {
      if (S.booted) return Promise.resolve();
      S.booted = true;
      return api("/api/config").then(function (cfg) {
        S.cfg = cfg;
        view.setConfig(cfg);
        view.renderResults(buildModel());
        view.showStage("landing");
      }, function (e) {
        renderError("Server unreachable", e.message, "Start it with: python -m nexcut.server", "");
      });
    }

    /* step 1: the link */
    function onLinkInput(raw) {
      clearTimeout(S.timers.fetch);
      var url = txt(raw);
      S.link = url;
      if (!url) { setSource("", "No source"); return; }
      setSource("", "Reading the link…");
      S.timers.fetch = setTimeout(function () { fetchLink(url, false); }, 800);
    }

    function fetchLink(raw, force) {
      clearTimeout(S.timers.fetch);
      var url = txt(raw);
      if (!url) { if (force) setSource("bad", "Paste a YouTube link first."); return; }
      if (S.busy) { setSource("bad", "A run is in progress. Wait for it, or press New link."); return; }
      var seq = ++S.fetchSeq;
      S.link = url;
      setSource("", "Fetching captions…");
      api("/api/transcript", { method: "POST", body: JSON.stringify({ url: url }) }).then(function (data) {
        if (seq !== S.fetchSeq) return;
        S.details = data;
        view.renderDetails(data, null);
        setSource("ok", "Captions ready — " + data.lines + " lines");
        view.showStage("details");
      }, function (e) {
        if (seq !== S.fetchSeq) return;
        var msg = [e.message, e.hint].filter(Boolean).join(" ");
        S.details = null;
        // captions are optional: land on Details anyway so the run can continue with a pasted transcript
        view.renderDetails(null, { message: e.message, hint: e.hint || "" });
        view.setOwnNote(msg, "bad");
        view.openOwnTranscript(true);
        // the status line stays short; the full reason is in the transcript note
        setSource("bad", msg.length > 110 ? msg.slice(0, 107).trimEnd() + "…" : msg);
        view.showStage("details");
      });
    }

    function uploadFile(file) {
      if (!file) return;
      var form = new FormData();
      form.append("file", file);
      fetch("/api/upload-transcript", { method: "POST", body: form }).then(function (res) {
        return res.json().catch(function () { return {}; }).then(function (data) {
          if (!res.ok) throw new Error((data && data.detail) || "Upload failed");
          view.setTranscript(data.text);
          view.openOwnTranscript(true);
          view.setOwnNote(file.name + " — " + Number(data.chars || 0).toLocaleString() + " characters", "ok");
          if (!S.details) view.toast("Transcript loaded — paste a link to add video details");
        });
      }).catch(function (e) {
        view.openOwnTranscript(true);
        view.setOwnNote(e.message, "bad");
      });
    }

    function viewTranscript() {
      var text = transcriptText();
      if (!text) { view.toast("No transcript yet"); return; }
      var blob = new Blob([text], { type: "text/plain" });
      var a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "transcript-" + ((S.details && S.details.video_id) || "session") + ".txt";
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(function () { URL.revokeObjectURL(a.href); }, 3000);
    }

    /* step 2: extract */
    function run() {
      if (!S.cfg || S.busy) return;
      var payload = readPayload();
      if (!payload.youtube_url && !payload.transcript_text) {
        setSource("bad", "Paste a link first.");
        view.showStage("landing");
        view.focusLink();
        return;
      }
      if (!payload.transcript_text) {
        view.setOwnNote("Paste a transcript first, or retry the link.", "bad");
        view.openOwnTranscript(true);
        view.focusTranscript();
        return;
      }
      submit(payload);
    }

    function submit(payload) {
      S.payload = payload;
      S.result = null;
      S.files = [];
      S.cutId = null;
      S.jobId = null;
      S.runId += 1;
      S.busy = true;
      clearTimers(["poll", "cut"]);
      view.setBusy(true);
      view.showStage("working");
      view.renderProgress({ pct: 2, stage: "Queued", reset: true });
      api("/api/extract", { method: "POST", body: JSON.stringify(payload) }).then(function (res) {
        S.jobId = res.job_id;
        pollJob(res.job_id);
      }, function (e) {
        finishRun();
        renderError("Run could not start", e.message, e.hint, "");
      });
    }

    function pollJob(jobId) {
      clearInterval(S.timers.poll);
      var last = -1;
      S.timers.poll = setInterval(function () {
        api("/api/jobs/" + jobId).then(function (job) {
          if (S.jobId !== jobId) return;               // reset() or a newer run superseded this one
          var progress = Number(job.progress) || 0;
          var stage = job.stage || "Working";
          var line = null;
          if (progress !== last) {
            last = progress;
            line = String(Math.round(progress)).padStart(3, " ") + "%  " + stage;
          }
          view.renderProgress({ pct: Math.round(progress * 0.7), stage: stage, logLine: line });

          if (job.status === "done") {
            clearInterval(S.timers.poll);
            return api("/api/jobs/" + jobId + "/results").then(function (result) {
              if (S.jobId !== jobId) return;
              S.result = result;
              finishRun();
              renderResults();
              startCut();
            }, function (e) {
              clearInterval(S.timers.poll);
              finishRun();
              renderError("Results unreadable", e.message, "The job finished but its results could not be loaded.", "");
            });
          }
          if (job.status === "error") {
            clearInterval(S.timers.poll);
            finishRun();
            renderError(titleFor(job.error), job.error || "Unknown error", job.error_hint || "", job.raw_answer || "");
          }
        }, function (e) {
          if (S.jobId !== jobId) return;
          clearInterval(S.timers.poll);
          finishRun();
          renderError("Lost contact with the server", e.message, "", "");
        });
      }, 1000);
    }

    function renderResults() {
      view.renderResults(buildModel());
      view.showStage("results");
      view.renderCut({ cut: { status: "idle", pct: 0, text: "" }, files: [], zipUrl: "" });
    }

    /* step 3: cut at 1080p, automatically */
    function startCut() {
      if (!S.jobId || !S.result) return;
      var clips = Array.isArray(S.result.clips) ? S.result.clips : [];
      if (!S.result.video_id || !clips.length) {
        view.renderCut({
          cut: { status: "warn", pct: 0, text: S.result.video_id ? "No clips to cut." : "Pasted transcript — nothing to cut." },
          files: [], zipUrl: ""
        });
        return;
      }
      view.renderCut({ cut: { status: "progress", pct: 2, text: "Fetching the 1080p source…" }, files: [], zipUrl: "" });
      api("/api/jobs/" + S.jobId + "/cut", { method: "POST", body: JSON.stringify({ height: 1080 }) }).then(function (res) {
        S.cutId = res.cut_id;
        pollCut(res.cut_id);
      }, function (e) {
        view.renderCut({ cut: { status: "error", pct: 0, text: [e.message, e.hint].filter(Boolean).join(" — ") }, files: [], zipUrl: "" });
      });
    }

    function pollCut(cutId) {
      clearInterval(S.timers.cut);
      S.timers.cut = setInterval(function () {
        api("/api/cuts/" + cutId).then(function (cut) {
          if (S.cutId !== cutId) return;
          var pct = Number(cut.progress) || 0;
          if (cut.status === "done") {
            clearInterval(S.timers.cut);
            S.files = Array.isArray(cut.files) ? cut.files : [];
            view.renderCut({
              cut: { status: "done", pct: 100, text: S.files.length + " clip(s) · " + (cut.quality || "1080p") },
              files: S.files, zipUrl: "/api/cuts/" + cutId + "/zip",
              history: { title: S.result.video_title || "Untitled video", channel: S.result.channel || "", clips: buildModel().clips, runId: S.runId }
            });
          } else if (cut.status === "error") {
            clearInterval(S.timers.cut);
            view.renderCut({ cut: { status: "error", pct: pct, text: cut.error || "Cut failed" }, files: S.files, zipUrl: "" });
          } else {
            view.renderCut({ cut: { status: "progress", pct: pct, text: (cut.stage || "Cutting") + " · " + pct + "%" }, files: S.files, zipUrl: "" });
          }
        }, function (e) {
          if (S.cutId !== cutId) return;
          clearInterval(S.timers.cut);
          view.renderCut({ cut: { status: "error", pct: 0, text: e.message }, files: S.files, zipUrl: "" });
        });
      }, 1200);
    }

    /* actions the views call */
    function retry() { if (S.payload && !S.busy) submit(S.payload); }

    function reset() {
      clearTimers(["fetch", "poll", "cut"]);
      S.fetchSeq += 1;
      S.busy = false;
      S.jobId = null;
      S.cutId = null;
      S.result = null;
      S.files = [];
      S.payload = null;
      S.details = null;
      S.link = "";
      view.setBusy(false);
      view.setLink("");
      view.setTranscript("");
      view.openOwnTranscript(false);
      view.setOwnNote(DEFAULT_NOTE, "");
      view.renderDetails(null, null);
      view.renderResults(buildModel());
      view.renderCut({ cut: { status: "idle", pct: 0, text: "" }, files: [], zipUrl: "" });
      setSource("", "No source");
      view.showStage("landing");
      view.focusLink();
    }

    function setZip(on) {
      S.zip = Boolean(on);
      view.renderResults(buildModel());
    }

    function copy(text) {
      var value = text === null || text === undefined ? "" : String(text);
      if (!value.trim()) { view.toast("Nothing to copy"); return Promise.resolve(); }
      return copyText(value).then(function (outcome) {
        view.toast(outcome === "ok" ? "Copied" : "Copy blocked — select the text instead");
      });
    }

    function copyAnswer() {
      copy(S.result && S.result.oracle_report ? String(S.result.oracle_report) : "");
    }

    return {
      boot: boot,
      onLinkInput: onLinkInput,
      fetchLink: fetchLink,
      uploadFile: uploadFile,
      viewTranscript: viewTranscript,
      run: run,
      retry: retry,
      reset: reset,
      setZip: setZip,
      copy: copy,
      copyAnswer: copyAnswer,
      isBusy: function () { return S.busy; }
    };
  }

  window.NexCut = {
    createApp: createApp,
    role: role, roles: roles, put: put, el: el, icon: icon,
    hydrateIcons: hydrateIcons, bindActions: bindActions, bindDrop: bindDrop,
    focusIfDesktop: focusIfDesktop,
    theme: theme,
    hms: hms, clampClips: clampClips, scoreText: scoreText,
    packaging: packaging, factsOf: factsOf, factsFailed: factsFailed, factsEmpty: factsEmpty,
    copyText: copyText,
    emptyMessage: emptyMessage
  };

  // theme follows the saved choice even before any view boots
  try {
    document.documentElement.setAttribute("data-theme", localStorage.getItem(THEME_KEY) === "light" ? "light" : "dark");
  } catch (_) {
    document.documentElement.setAttribute("data-theme", "dark");
  }
})();
