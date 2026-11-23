/* NexCut — direction D, "Field".
   Cutter flow lives in core.js; the Downloader pane has its own state. */
(function () {
  "use strict";
  var N = window.NexCut;
  var R = function (name) { return N.role(name); };
  var RS = function (name) { return N.roles(name); };

  var STAGES = ["landing", "details", "working", "error", "results"];
  var RAIL = { landing: "New cut", details: "Source & plan", working: "Working", error: "Stopped", results: "Clips" };

  var app = null;
  var open = {};            // clip index → packaging open
  var runSeen = -1;
  var lastModel = null;
  var lastFiles = [];
  var lastZip = "";
  var lastErrorText = "";
  var minClips = 5;
  var maxClips = 15;
  var inited = false;
  var workspace = "cutter";
  var cutterStage = "landing";
  var cutterHistoryOpen = false;
  var downloader = null;

  function pad2(n) {
    return String(n).padStart(2, "0");
  }

  function selectedLen() {
    var on = RS("len-option").filter(function (b) { return b.getAttribute("aria-pressed") === "true"; })[0];
    return on ? on.getAttribute("data-len") : "40-50";
  }

  function setLen(value) {
    RS("len-option").forEach(function (b) {
      b.setAttribute("aria-pressed", b.getAttribute("data-len") === value ? "true" : "false");
    });
    R("custom-len").hidden = value !== "custom";
  }

  function updateBadge() {
    var n = N.clampClips(R("clip-count").value, minClips, maxClips);
    R("clip-badge").textContent = n ? n + " clips" : "AUTO";
  }

  function syncTheme() {
    var b = R("theme-toggle");
    b.textContent = "";
    b.appendChild(N.icon(N.theme.isLight() ? "sun" : "moon"));
  }

  function setMode(mode) {
    if (mode === workspace || !["cutter", "downloader"].includes(mode)) return;
    var isDownloader = mode === "downloader";
    var history = R("history-panel");
    if (isDownloader) cutterHistoryOpen = !history.hidden;
    workspace = mode;
    document.querySelector(".work").dataset.workspace = mode;
    history.hidden = isDownloader || !cutterHistoryOpen;
    R("pane-cutter").hidden = isDownloader || cutterHistoryOpen;
    R("pane-downloader").hidden = !isDownloader;
    RS("mode").forEach(function (b) {
      b.setAttribute("aria-selected", b.getAttribute("data-mode") === mode ? "true" : "false");
    });
    var side = document.querySelector(".rail-side");
    if (side) side.textContent = isDownloader ? "Side B" : "Side A";
    N.put("stage-label", isDownloader ? "Downloader" : RAIL[cutterStage]);
    moveCredits(!isDownloader && cutterStage === "working");
  }

  /* the packaging block, same shape as the other directions */
  function packagingNode(pack) {
    var wrap = N.el("div", "pack");
    wrap.setAttribute("data-role", "packaging");

    var timing = N.el("dl", "pack-time");
    pack.timing.forEach(function (pair) {
      var cell = N.el("div");
      cell.appendChild(N.el("dt", null, pair[0]));
      cell.appendChild(N.el("dd", null, pair[1]));
      timing.appendChild(cell);
    });
    wrap.appendChild(timing);

    /* remove scores from details */

    pack.fields.forEach(function (f) {
      if (f.key === "safety" || f.key === "sfx") return;
      var block = N.el("div", "field-block" + (f.strong ? " strong" : ""));
      block.setAttribute("data-field", f.key);
      var key = N.el("div", "fk");
      var label = f.label === "On-screen question" ? "Video Title" : f.label;
      key.appendChild(N.el("span", null, label));
      if (f.copy) {
        var btn = N.el("button", "copy", "Copy");
        btn.type = "button";
        btn.setAttribute("data-role", "copy-control");
        btn.setAttribute("data-action", "copy");
        btn.setAttribute("data-copy", f.value);
        btn.setAttribute("aria-label", "Copy " + label.toLowerCase());
        key.appendChild(btn);
      }
      block.appendChild(key);
      block.appendChild(N.el("div", "fv", f.value));
      wrap.appendChild(block);
    });

    return wrap;
  }

  function actionFor(index) {
    var file = lastFiles[index];
    if (lastModel && lastModel.zip) {
      return N.el("span", "size act", file ? file.size_mb + " MB" : "in ZIP");
    }
    if (file) {
      var a = N.el("a", "btn small primary act", "Download");
      a.href = file.url;
      a.setAttribute("download", file.name);
      a.setAttribute("data-role", "clip-download");
      return a;
    }
    var b = N.el("button", "btn small act", "Cutting…");
    b.type = "button";
    b.disabled = true;
    b.setAttribute("data-role", "clip-pending");
    return b;
  }

  function renderList() {
    var list = R("clip-list");
    list.textContent = "";
    var clips = (lastModel && lastModel.clips) || [];
    if (lastModel && lastModel.ready && !clips.length) {
      var none = N.el("li", "list-empty", N.emptyMessage(lastModel));
      none.setAttribute("data-role", "clip-empty");
      list.appendChild(none);
    }
    clips.forEach(function (clip, i) {
      var isOpen = Boolean(open[i]);
      var li = N.el("li", "clip" + (isOpen ? " is-open" : ""));
      li.setAttribute("data-role", "clip-item");

      var img = N.el("img", "clip-art");
      var num = pad2(Math.min(i + 1, 15));
      img.src = "/static/clips/clip-" + num + ".svg";
      img.alt = "Clip " + pad2(i + 1);
      li.appendChild(img);

      li.appendChild(N.el("div", "clip-hook", clip.pack.title));

      var bar = N.el("div", "clip-bar");
      var more = N.el("button", "ghost more", isOpen ? "Hide Details" : "Details");
      more.type = "button";
      more.setAttribute("data-role", "clip-more");
      more.setAttribute("data-action", "more");
      more.setAttribute("data-index", String(i));
      more.setAttribute("aria-expanded", isOpen ? "true" : "false");
      bar.appendChild(more);
      bar.appendChild(actionFor(i));
      li.appendChild(bar);

      if (isOpen) li.appendChild(packagingNode(clip.pack));
      list.appendChild(li);
    });
  }

  function syncZipLink() {
    var link = R("zip-link");
    link.hidden = false;
    if (lastZip) {
      link.setAttribute("href", lastZip);
      link.className = "btn small primary";
      link.removeAttribute("aria-disabled");
      link.style.pointerEvents = "";
      link.style.opacity = "";
    } else {
      link.setAttribute("href", "#");
      link.className = "btn small";
      link.setAttribute("aria-disabled", "true");
      link.style.pointerEvents = "none";
      link.style.opacity = "0.5";
    }
  }

  function moveCredits(inSlot) {
    var credits = R("credits");
    var target = inSlot ? R("credits-slot") : R("credits-home");
    if (credits && target) target.appendChild(credits);
  }

  var view = {
    setConfig: function (cfg) {
      minClips = cfg.min_clips || 5;
      maxClips = cfg.max_clips || 15;
      var n = R("clip-count");
      n.min = String(minClips);
      n.max = String(maxClips);
      N.put("build-tag", cfg.version || "");
      downloader.setConfig(cfg);
      updateBadge();
    },

    setSource: function (s) {
      var node = R("source-state");
      node.textContent = s.text;
      node.setAttribute("data-tone", s.tone || "");
    },

    showStage: function (name) {
      STAGES.forEach(function (s) {
        var pane = R("pane-" + s);
        if (pane) pane.hidden = s !== name;
      });
      cutterStage = name;
      if (workspace === "cutter") {
        N.put("stage-label", RAIL[name] || "");
        moveCredits(name === "working");
      }
    },

    renderDetails: function (details, err) {
      var hb = document.getElementById("d-home-btn");
      if (hb && (details || err)) hb.hidden = false;
      var f = details ? N.factsOf(details) : err ? N.factsFailed(err) : N.factsEmpty();
      N.put("fact-title", f.title);
      N.put("fact-channel", f.channel);
      N.put("fact-length", f.length);
      N.put("fact-captions", f.captions);
      N.put("fact-transcript", f.transcript);
      N.put("fact-niche", f.niche);
      var badge = N.put("detail-badge", f.badge);
      badge.setAttribute("data-tone", f.badgeTone);
      badge.title = f.badgeTitle || "";
    },

    setOwnNote: function (text, tone) {
      var node = R("own-note");
      node.textContent = text;
      node.setAttribute("data-tone", tone || "");
    },

    openOwnTranscript: function (on) {
      R("own-box").hidden = !on;
      R("own-toggle").setAttribute("aria-expanded", on ? "true" : "false");
    },

    readLink: function () { return R("link-input").value.trim(); },
    setLink: function (text) { R("link-input").value = text || ""; },
    readTranscript: function () { return R("transcript-input").value; },
    setTranscript: function (text) { R("transcript-input").value = text || ""; },

    readOptions: function () {
      return {
        clips: R("clip-count").value,
        len: selectedLen(),
        customMin: R("custom-min").value,
        customMax: R("custom-max").value
      };
    },

    setBusy: function (busy) { R("run").disabled = Boolean(busy); },

    /* the bar is a transform, so the row never reflows while it moves */
    renderProgress: function (p) {
      var pct = Math.max(0, Math.min(100, Math.round(p.pct) || 0));
      R("progress-fill").style.transform = "scaleX(" + (pct / 100) + ")";
      N.put("pct-text", pct + "%");
      N.put("stage-text", p.stage || "Working");
      var log = R("stage-log");
      if (p.reset) log.textContent = "";
      if (p.logLine) {
        log.textContent += p.logLine + "\n";
        log.scrollTop = log.scrollHeight;
      }
    },

    renderError: function (e) {
      N.put("error-title", e.title);
      N.put("error-message", e.message);
      var hint = R("error-hint");
      hint.textContent = e.hint || "";
      hint.hidden = !e.hint;
      var raw = R("error-raw");
      var text = String(e.raw || "");
      raw.hidden = !text.trim();
      raw.querySelector("pre").textContent = text.length > 4000 ? text.slice(0, 4000) + "…" : text;
      R("retry").hidden = !e.canRetry;
      lastErrorText = [e.title, e.message, e.hint, e.raw].filter(Boolean).join("\n\n");
    },

    renderResults: function (model) {
      if (model.runId !== runSeen) { runSeen = model.runId; open = {}; }
      lastModel = model;
      var count = (model.clips || []).length;
      N.put("res-title", model.ready ? (count + " CLIPS FOUND") : "—");
      N.put("res-meta", model.ready ? "Using Claude. By NexCut" : "");
      N.put("stat-found", model.stats.found);
      N.put("stat-kept", model.stats.kept);
      N.put("stat-rejected", model.stats.rejected);
      N.put("stat-asked", model.stats.asked);
      R("zip-toggle").checked = Boolean(model.zip);
      renderList();
      syncZipLink();
    },

    renderCut: function (c) {
      var cut = c.cut || {};
      var state = N.put("cut-state", cut.text || "");
      state.setAttribute("data-tone", cut.status === "error" ? "bad" : cut.status === "done" ? "ok" : cut.status === "warn" ? "warn" : "");
      R("cut-track").hidden = cut.status !== "progress";
      R("cut-fill").style.transform = "scaleX(" + (Math.max(0, Math.min(100, Number(cut.pct) || 0)) / 100) + ")";
      var prevFilesLen = lastFiles.length;
      var prevZip = lastZip;
      lastFiles = c.files || [];
      lastZip = c.zipUrl || "";
      if (lastFiles.length !== prevFilesLen || lastZip !== prevZip) {
        renderList();
      }
      syncZipLink();

      if (c.clips && c.clips.length) {
        try {
          var hist = JSON.parse(localStorage.getItem("saa_history_d_v2") || "[]");
          var tEl = R("fact-title");
          var chEl = R("fact-channel");
          var vTitle = (tEl && tEl.textContent && tEl.textContent.trim() !== "—") ? tEl.textContent.trim() : ((lastModel && lastModel.title) || c.title || "Untitled video");
          var channel = (chEl && chEl.textContent && chEl.textContent.trim() !== "—") ? chEl.textContent.trim() : ((lastModel && lastModel.channel) || "YouTube");
          var now = new Date();
          var dd = String(now.getDate()).padStart(2, "0");
          var mm = String(now.getMonth() + 1).padStart(2, "0");
          var yyyy = now.getFullYear();
          var dateStr = dd + "-" + mm + "-" + yyyy;
          var timeStr = now.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", hour12: true });
          var entry = { title: vTitle, channel: channel, dateStr: dateStr, timeStr: timeStr, clips: c.clips };
          if (!hist.length || hist[0].title !== entry.title || hist[0].clips.length !== entry.clips.length) {
            hist.unshift(entry);
            localStorage.setItem("saa_history_d_v2", JSON.stringify(hist.slice(0, 20)));
          }
        } catch (_) {}
      }
    },

    focusLink: function () { N.focusIfDesktop(R("link-input")); },
    focusTranscript: function () { R("transcript-input").focus(); },

    toast: function (message) {
      var node = N.el("div", "toast", message);
      R("toasts").appendChild(node);
      setTimeout(function () { node.remove(); }, 1900);
    }
  };

  var actions = {
    "fetch": function () { app.fetchLink(R("link-input").value, true); },
    "view-transcript": function () { app.viewTranscript(); },
    "own-toggle": function () { view.openOwnTranscript(R("own-box").hidden); },
    "upload": function () { R("file-input").click(); },
    "len": function (el) { setLen(el.getAttribute("data-len")); },
    "run": function () { app.run(); },
    "manual-submit": function () {
      var manualBtn = R("manual-submit");
      var manualTxt = R("manual-json");
      var val = (manualTxt.value || "").trim();
      if (!val) { view.toast("Paste Claude's JSON first."); return; }
      manualBtn.disabled = true;
      fetch("/api/manual-answer", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: val })
      }).then(function (r) {
        if (!r.ok) throw new Error("Failed");
        manualTxt.value = "";
        view.toast("Submitted — processing clips…");
      }).catch(function () {
        view.toast("Failed to submit JSON.");
      }).finally(function () {
        manualBtn.disabled = false;
      });
    },
    "home": function () {
      var hb = document.getElementById("d-home-btn");
      if (hb) hb.hidden = true;
      var nr = R("new-run");
      if (nr) nr.click();
      else view.showPane("landing");
    },

    "credits-open": function () {
      var m = document.getElementById("d-credits-modal");
      if (m) m.hidden = false;
    },

    "credits-close": function () {
      var m = document.getElementById("d-credits-modal");
      if (m) m.hidden = true;
    },

    "dl-qual": function (el) { downloader.selectQuality(el.dataset.quality); },
    "dl-more-open": function () { downloader.openMore(); },
    "dl-more-close": function () { downloader.closeMore(); },
    "dl-qual-more": function (el) {
      downloader.selectQuality(el.dataset.quality);
      downloader.closeMore();
    },
    "dl-cancel": function () { downloader.cancel(); },
    "dl-add-clip": function () { downloader.addClip(); },

    "history": function () {
      var hp = R("history-panel");
      var cutter = R("pane-cutter");
      var list = R("history-list");
      var open = hp.hidden;
      hp.hidden = !open;
      cutter.hidden = open;
      if (open && list) {
        var items = [];
        try { items = JSON.parse(localStorage.getItem("saa_history_d_v2") || "[]"); } catch (_) {}
        list.innerHTML = "";
        if (!items.length) {
          list.appendChild(N.el("p", "sub", "No cut history yet. Extract a video to see it here."));
          return;
        }
        items.forEach(function (it) {
          var btn = N.el("button", "history-item");
          btn.type = "button";
          btn.appendChild(N.el("div", "history-title", it.title || "Untitled video"));
          btn.appendChild(N.el("div", "history-meta", it.channel || "YouTube"));
          btn.appendChild(N.el("div", "history-meta", "Date: " + (it.dateStr || "—")));
          btn.appendChild(N.el("div", "history-meta", "Time: " + (it.timeStr || "—")));
          btn.appendChild(N.el("div", "history-meta", "Clips Cut: " + (it.clips ? it.clips.length : 0) + " Clips"));
          btn.addEventListener("click", function () {
            hp.hidden = true;
            cutter.hidden = false;
            var hb = document.getElementById("d-home-btn");
            if (hb) hb.hidden = false;
            view.showPane("results");
            view.setResults({
              title: it.title || "History session",
              meta: (it.channel || "") + " · Cut " + (it.cutAt || ""),
              found: it.clips ? it.clips.length : 0,
              kept: it.clips ? it.clips.length : 0,
              rejected: 0,
              asked: "AUTO",
              clips: it.clips || [],
              files: [],
              zipUrl: ""
            });
          });
          list.appendChild(btn);
        });
      }
    },
    "history-close": function () {
      R("history-panel").hidden = true;
      R("pane-cutter").hidden = false;
    },
    "retry": function () { app.retry(); },
    "new-link": function () { app.reset(); },
    "copy-details": function () { app.copy(lastErrorText); },
    "copy-answer": function () { app.copyAnswer(); },
    "copy": function (el) { app.copy(el.getAttribute("data-copy")); },
    "more": function (el) {
      var i = Number(el.getAttribute("data-index"));
      open[i] = !open[i];
      renderList();
    },
    "mode": function (el) { setMode(el.getAttribute("data-mode")); },
    "theme": function () { N.theme.toggle(); syncTheme(); }
  };

  function wireInputs() {
    var link = R("link-input");
    link.addEventListener("input", function () { app.onLinkInput(link.value); });
    link.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { e.preventDefault(); app.fetchLink(link.value, true); }
    });

    var count = R("clip-count");
    count.addEventListener("input", updateBadge);
    count.addEventListener("change", function () {
      var n = N.clampClips(count.value, minClips, maxClips);
      if (n) count.value = String(n);
      updateBadge();
    });

    R("transcript-input").addEventListener("input", function () {
      var lines = R("transcript-input").value.split(/\r?\n/).filter(function (l) { return l.trim(); }).length;
      view.setOwnNote(lines ? lines + " lines" : "One timestamp per line.", "");
    });

    R("file-input").addEventListener("change", function (e) {
      var file = e.target.files && e.target.files[0];
      if (file) app.uploadFile(file);
      e.target.value = "";
    });

    R("zip-toggle").addEventListener("change", function (e) { app.setZip(e.target.checked); });
    N.bindDrop(function (file) { if (workspace === "cutter") app.uploadFile(file); });

    document.addEventListener("keydown", function (e) {
      if (workspace !== "cutter" || e.key !== "Escape") return;
      if (!R("own-box").hidden) view.openOwnTranscript(false);
      if (Object.keys(open).some(function (k) { return open[k]; })) { open = {}; renderList(); }
    });
  }

  /* Downloader state is independent of the Cutter's shared app. */
  function wireDownloader() {
    var pane = R("pane-downloader");
    var dl = function (key) { return N.role(key, pane); };
    var put = function (key, text) { N.put(key, text, pane); };
    var link = dl("dl-link"), format = dl("dl-format"), quality = dl("dl-quality");
    var invite = dl("dl-invite"), cover = dl("dl-thumbnail"), save = dl("dl-file");
    var cancelBtn = document.getElementById("d-dl-cancel");
    var moreBtn = document.getElementById("d-dl-more-btn");
    var more = document.getElementById("d-dl-more-modal");
    var qualityButtons = Array.from(document.querySelectorAll(".dl-qbtn[data-quality]"));
    var trimList = document.getElementById("d-dl-trim-list");
    var addBtn = document.getElementById("d-dl-add-clip");
    var trimToast = document.getElementById("d-dl-toast");
    var maxRanges = 10;
    var info = null, active = null, busy = false, toastTimer;

    function notice(text, tone, hint) {
      put("dl-source", text);
      dl("dl-source").dataset.tone = tone || "";
      put("dl-hint", hint || "");
      dl("dl-hint").hidden = !hint;
    }

    function selectedChoice(label) {
      // The hidden input contains the button's label (e.g. 720p), not an
      // extractor selector or the ID that the server expects (mp4-720).
      var match = /^(480|720|1080|1440|2160)p$/.exec(label || quality.value);
      return match && info && info.formats.find(function (item) {
        return item.format === format.value && item.quality === Number(match[1]);
      });
    }

    function sync() {
      var locked = busy || !!active;
      link.disabled = dl("dl-inspect").disabled = locked;
      invite.disabled = busy;
      dl("dl-start").disabled = locked || !selectedChoice();
      cancelBtn.hidden = !active;
      cancelBtn.disabled = !!active && (active.cancelPending || active.cancelling);
      moreBtn.disabled = locked || !(selectedChoice("1440p") || selectedChoice("2160p"));
      moreBtn.classList.toggle("is-active", ["1440p", "2160p"].includes(quality.value) && !!selectedChoice());
      qualityButtons.forEach(function (button) {
        var label = button.dataset.quality;
        var available = !!selectedChoice(label);
        var pressed = available && quality.value === label;
        button.disabled = locked || !available;
        button.classList.toggle("is-active", pressed);
        button.setAttribute("aria-pressed", String(pressed));
      });
      trimList.querySelectorAll("input, button").forEach(function (control) { control.disabled = locked; });
      addBtn.disabled = locked || trimList.children.length >= maxRanges;
      pane.classList.toggle("is-engaged", !dl("dl-details").hidden || !dl("dl-transfer").hidden);
    }

    function clearFile() {
      dl("dl-ready").hidden = true;
      save.removeAttribute("href");
      dl("dl-check").hidden = true;
    }

    function reset() {
      info = null;
      quality.value = "1080p";
      dl("dl-details").hidden = dl("dl-transfer").hidden = true;
      clearFile();
      cover.hidden = true;
      cover.removeAttribute("src");
      sync();
    }

    function checkInvite() {
      if (dl("dl-invite-field").hidden || invite.value.trim()) return true;
      notice("Enter the studio invite code to continue.", "warn");
      invite.focus();
      return false;
    }

    async function request(path, body) {
      var headers = { Accept: "application/json" };
      if (!dl("dl-invite-field").hidden && invite.value.trim()) headers["X-Invite-Code"] = invite.value.trim();
      var ctl = new AbortController();
      var options = { headers: headers, cache: "no-store", signal: ctl.signal };
      if (body !== undefined) {
        headers["Content-Type"] = "application/json";
        options.method = "POST";
        options.body = JSON.stringify(body);
      }
      var timer = setTimeout(function () { ctl.abort(); }, path === "/api/dl/info" ? 85000 : 12000);
      try {
        var response = await fetch(path, options);
        var data = await response.json().catch(function () { return {}; });
        if (!response.ok) {
          var error = new Error(data.detail || "The downloader returned HTTP " + response.status + ".");
          error.hint = data.hint;
          error.status = response.status;
          if (response.status === 403) dl("dl-invite-field").hidden = false;
          throw error;
        }
        return data;
      } catch (error) {
        if (error.status) throw error;
        throw new Error(error.name === "AbortError" ? "The downloader request timed out." : "Could not reach the NexCut downloader.");
      } finally {
        clearTimeout(timer);
      }
    }

    function size(n) {
      if (n >= 1024 * 1024 * 1024) return (n / (1024 * 1024 * 1024)).toFixed(2) + " GiB";
      if (n >= 1024 * 1024) return (n / (1024 * 1024)).toFixed(1) + " MiB";
      if (n >= 1024) return (n / 1024).toFixed(1) + " KiB";
      return Math.round(n) + " B";
    }

    function qualityHint() {
      var choice = selectedChoice();
      put("dl-choice", !choice ? "None of the listed MP4 qualities is available for this video."
        : choice.separate_tracks ? "Video and audio arrive separately and are joined into one file."
          : "Saves the original resolution with audio.");
      put("dl-est-size", choice ? "Selected: " + quality.value + " (MP4)" : "");
      sync();
    }

    function qualities() {
      if (!selectedChoice()) {
        quality.value = ["1080p", "2160p", "1440p", "720p", "480p"].find(function (label) {
          return !!selectedChoice(label);
        }) || "";
      }
      qualityHint();
    }

    function selectQuality(label) {
      if (busy || active || !label || !selectedChoice(label)) return;
      quality.value = label;
      qualityHint();
    }

    function parseTime(value) {
      var parts = value.split(":");
      var count = parts.length;
      var seconds = parts.pop();
      if (parts.length > 2 || !/^\d{1,7}(\.\d{1,3})?$/.test(seconds) || parts.some(function (part) {
        return !/^\d{1,7}$/.test(part);
      })) return NaN;
      var sec = Number(seconds), minutes = Number(parts.pop() || 0), hours = Number(parts.pop() || 0);
      if ((count > 1 && sec >= 60) || (count === 3 && minutes >= 60)) return NaN;
      return hours * 3600 + minutes * 60 + sec;
    }

    function readRanges() {
      var rows = trimList.querySelectorAll(".dl-trim-row");
      var ranges = [];
      if (rows.length > maxRanges) throw new Error("Use at most " + maxRanges + " clips.");
      rows.forEach(function (row, i) {
        var startText = N.role("dl-trim-start", row).value.trim();
        var endText = N.role("dl-trim-end", row).value.trim();
        var prefix = "Clip " + (i + 1) + ": ";
        if (!startText && !endText) return;
        if (!startText || !endText) throw new Error(prefix + "Enter both Start and End times.");
        var start = parseTime(startText), end = parseTime(endText);
        if (!Number.isFinite(start) || !Number.isFinite(end)) throw new Error(prefix + "Use H:M:S, M:S, or seconds.");
        if (start >= end) throw new Error(prefix + "Start time must be before End time.");
        if (info && Number.isFinite(info.duration) && end > info.duration) {
          throw new Error(prefix + "End time cannot exceed the video duration.");
        }
        ranges.push({ start: start, end: end });
      });
      return ranges;
    }

    function trimError(error) {
      notice(error.message, "bad");
      trimToast.textContent = error.message;
      trimToast.classList.add("is-open");
      clearTimeout(toastTimer);
      toastTimer = setTimeout(function () { trimToast.classList.remove("is-open"); }, 3000);
    }

    function addClip() {
      if (busy || active || trimList.children.length >= maxRanges) return;
      try {
        if (readRanges().length !== trimList.children.length) {
          throw new Error("Fill in the current clip's Start and End times before adding another.");
        }
      } catch (error) {
        trimError(error);
        return;
      }
      var row = trimList.firstElementChild.cloneNode(true);
      var start = N.role("dl-trim-start", row);
      start.value = N.role("dl-trim-end", row).value = "";
      var remove = N.el("button", "btn small", "×");
      remove.type = "button";
      remove.setAttribute("aria-label", "Remove clip");
      remove.addEventListener("click", function () { row.remove(); sync(); });
      row.appendChild(remove);
      trimList.appendChild(row);
      sync();
      start.focus();
    }

    function stage(text) {
      if (dl("dl-stage").textContent !== text) put("dl-stage", text);
    }

    function renderTransfer(job, choice) {
      var pct = Number.isFinite(job.progress) ? Math.max(0, Math.min(100, job.progress)) : null;
      var bar = dl("dl-progress");
      var stats = [];
      dl("dl-transfer").hidden = false;
      dl("dl-pulse").hidden = ["ready", "error", "cancelled"].includes(job.status);
      bar.querySelector("i").style.transform = "scaleX(" + (pct === null ? 0 : pct / 100) + ")";
      if (pct === null) bar.removeAttribute("aria-valuenow");
      else bar.setAttribute("aria-valuenow", String(pct));
      put("dl-percent", pct === null ? "—" : pct + "%");
      var headline = { queued: "Queued…", downloading: "Downloading media…", processing: "Preparing your file…",
        trimming: "Trimming video…", cancelling: "Cancelling…", cancelled: "Download cancelled",
        ready: "Download ready", error: "Download failed" };
      stage(headline[job.status]);
      if (job.status === "downloading") {
        if (choice && choice.separate_tracks && pct !== null) stats.push("Current track");
        if (Number.isFinite(job.speed) && job.speed > 0) stats.push(size(job.speed) + "/s");
        if (Number.isFinite(job.eta)) stats.push("ETA " + N.hms(job.eta));
      }
      put("dl-stats", stats.join(" · "));
      dl("dl-stats").hidden = !stats.length;
      sync();
    }

    function stop(run) {
      clearTimeout(run.timer);
      active = null;
      dl("dl-check").hidden = dl("dl-pulse").hidden = true;
      sync();
    }

    function schedule(run, delay) {
      clearTimeout(run.timer);
      run.timer = setTimeout(function () { poll(run); }, delay);
    }

    function showStatus(run, job) {
      if (!["queued", "downloading", "processing", "trimming", "cancelling", "cancelled", "ready", "error"].includes(job.status)) {
        throw new Error("NexCut did not return a download status.");
      }
      run.failures = 0;
      run.cancelling = job.status === "cancelling";
      renderTransfer(job, run.choice);
      if (job.status === "ready") {
        var file = job.file;
        // Only attach an API download link to this job, never a remote URL.
        var filePath = new RegExp("^/api/dl/file/" + run.id + "\\?token=[0-9a-f]{32}$");
        if (!file || typeof file.url !== "string" || !filePath.test(file.url)) {
          stage("File link unavailable");
          notice("The server did not return a valid download link.", "bad");
          stop(run);
          return;
        }
        save.href = file.url;
        save.download = file.name;
        put("dl-filename", file.name);
        put("dl-size", size(file.size));
        put("dl-file-label", "Save " + (file.format === "zip" ? "ZIP" : run.choice.format.toUpperCase()));
        dl("dl-ready").hidden = false;
        try {
          var dlTitle = (dl("dl-title") && dl("dl-title").textContent) || "Downloaded video";
          var dlUrl = (dl("dl-link") && dl("dl-link").value) || "";
          var dlQual = (document.getElementById("d-dl-quality") && document.getElementById("d-dl-quality").value) || "1080p";
          var dHist = JSON.parse(localStorage.getItem("saa_dl_history_d") || "[]");
          var nowD = new Date();
          var dStr = String(nowD.getDate()).padStart(2, "0") + "-" + String(nowD.getMonth() + 1).padStart(2, "0") + "-" + nowD.getFullYear();
          var tStr = nowD.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", hour12: true });
          dHist.unshift({ title: dlTitle, url: dlUrl, quality: dlQual, date: dStr, time: tStr });
          localStorage.setItem("saa_dl_history_d", JSON.stringify(dHist.slice(0, 20)));
          if (typeof window._renderDlHistory === "function") window._renderDlHistory();
        } catch (_) {}
        notice(run.noAutoSave ? "The download already finished. Use Save if you want the file."
          : "The file is ready. If your download doesn’t start, use Save.", "ok");
        stop(run);
        if (!run.noAutoSave) save.click();
      } else if (job.status === "cancelled") {
        clearFile();
        notice("Download cancelled.", "warn");
        stop(run);
      } else if (job.status === "error") {
        notice(job.detail || "The download could not be completed.", "bad", job.hint);
        stop(run);
      } else {
        schedule(run, 800);
      }
    }

    async function poll(run) {
      if (active !== run || run.cancelPending) return;
      var revision = ++run.revision;
      try {
        var job = await request("/api/dl/status/" + run.id);
        if (active === run && revision === run.revision) showStatus(run, job);
      } catch (error) {
        if (active !== run || revision !== run.revision) return;
        if (error.status === 404) {
          stage("Download no longer available");
          notice(error.message, "bad", error.hint);
          stop(run);
        } else if (error.status !== 403 && ++run.failures < 3) {
          stage("Reconnecting…");
          schedule(run, 1200);
        } else {
          stage("Status unavailable");
          dl("dl-pulse").hidden = true;
          dl("dl-check").hidden = false;
          notice(error.message, "warn", "The job may still be running. Check its status again.");
        }
      }
    }

    async function cancel() {
      var run = active;
      if (!run || run.cancelPending || run.cancelling || !checkInvite()) return;
      // Invalidate any in-flight status read before asking the server to stop.
      ++run.revision;
      clearTimeout(run.timer);
      run.cancelPending = run.noAutoSave = true;
      stage("Cancelling…");
      notice("Cancelling download…");
      dl("dl-check").hidden = true;
      sync();
      try {
        var job = await request("/api/dl/cancel/" + run.id, {});
        run.cancelPending = false;
        if (active === run) showStatus(run, job);
      } catch (error) {
        if (active !== run) return;
        run.cancelPending = false;
        notice("Could not confirm cancellation. " + error.message, "warn", error.hint);
        sync();
        poll(run);
      }
    }

    link.addEventListener("input", function () {
      reset();
      notice("Watch, share and Shorts links · One video at a time");
    });
    cover.addEventListener("error", function () { cover.hidden = true; });

    dl("dl-inspect-form").addEventListener("submit", async function (event) {
      event.preventDefault();
      if (busy || active || !checkInvite()) return;
      reset();
      busy = true;
      sync();
      notice("Reading available formats…");
      try {
        var data = await request("/api/dl/info", { url: link.value.trim() });
        if (!data.inspection_id || !Array.isArray(data.formats) || !data.formats.length) {
          throw new Error("The source has no compatible formats.");
        }
        info = data;
        put("dl-title", data.title);
        put("dl-meta", [data.channel, Number.isFinite(data.duration) ? N.hms(data.duration) : ""].filter(Boolean).join(" · "));
        if (data.thumbnail) { cover.src = data.thumbnail; cover.hidden = false; }
        dl("dl-details").hidden = false;
        qualities();
        if (selectedChoice()) notice("Choose a quality, then click Download.", "ok");
        else notice("This video does not offer any of the listed MP4 qualities.", "warn");
      } catch (error) {
        notice(error.message, "bad", error.hint);
      } finally {
        busy = false;
        sync();
      }
    });

    dl("dl-start-form").addEventListener("submit", async function (event) {
      event.preventDefault();
      if (busy || active || !checkInvite()) return;
      var choice = selectedChoice();
      if (!choice) { notice("Select an available MP4 quality.", "warn"); return; }
      var ranges;
      try { ranges = readRanges(); } catch (error) { trimError(error); return; }
      busy = true;
      clearFile();
      notice("Starting download…");
      renderTransfer({ status: "queued", progress: null });
      try {
        var job = await request("/api/dl/start", { inspection_id: info.inspection_id, format_id: choice.id, ranges: ranges });
        if (!/^[0-9a-f]{32}$/.test(job.job_id)) throw new Error("NexCut did not return a download job.");
        active = { id: job.job_id, choice: choice, failures: 0, revision: 0 };
        notice("NexCut is preparing your file.");
        poll(active);
      } catch (error) {
        dl("dl-transfer").hidden = true;
        if (error.status === 410) reset();
        notice(error.message, "bad", error.hint);
      } finally {
        busy = false;
        sync();
      }
    });

    dl("dl-check").addEventListener("click", function () {
      if (!active || active.cancelPending || !checkInvite()) return;
      this.hidden = true;
      active.failures = 0;
      notice("Checking the download…");
      poll(active);
    });
    sync();
    return {
      setConfig: function (cfg) { dl("dl-invite-field").hidden = !cfg.requires_invite; },
      selectQuality: selectQuality,
      openMore: function () { if (!moreBtn.disabled) more.hidden = false; },
      closeMore: function () { more.hidden = true; },
      cancel: cancel,
      addClip: addClip
    };
  }

  function init() {
    if (inited) return;
    inited = true;
    N.hydrateIcons(document);
    N.bindActions(actions);
    syncTheme();
    wireInputs();
    downloader = wireDownloader();
    app = N.createApp(view);
    app.boot();

    var badge = document.querySelector(".badge");
    if (badge) {
      badge.addEventListener("mousemove", function (e) {
        var r = badge.getBoundingClientRect();
        var x = (e.clientX - r.left) / r.width - 0.5;
        var y = (e.clientY - r.top) / r.height - 0.5;
        badge.style.transform = "perspective(400px) rotateX(" + (-y * 22).toFixed(1) + "deg) rotateY(" + (x * 22).toFixed(1) + "deg) scale(1.04)";
      });
      badge.addEventListener("mouseleave", function () {
        badge.style.transform = "";
      });
    }

    var foot = document.querySelector(".foot");
    var mark = document.querySelector(".panel-mark");
    if (foot && mark) {
      var rafId = 0;
      var syncMark = function () {
        rafId = 0;
        var rect = foot.getBoundingClientRect();
        var overlap = Math.max(0, Math.min(rect.height, window.innerHeight - rect.top));
        var atRest = overlap >= Math.max(1, rect.height - 2);
        mark.classList.toggle("is-floating", atRest);
        mark.style.transform = overlap > 0 ? ("translateY(-" + overlap.toFixed(1) + "px)") : "";
      };
      var onScroll = function () {
        if (!rafId) rafId = requestAnimationFrame(syncMark);
      };
      window.addEventListener("scroll", onScroll, { passive: true });
      window.addEventListener("resize", onScroll, { passive: true });
      syncMark();
    }

    var bgBtns = document.querySelectorAll("[data-bg-opt]");
    var applyBg = function (bg) {
      var val = /^bg-[1-5]$/.test(bg || "") ? bg : "bg-1";
      document.documentElement.setAttribute("data-bg", val);
      try { localStorage.setItem("nexcut_bg", val); } catch (e) {}
      bgBtns.forEach(function (b) { b.classList.toggle("is-active", b.getAttribute("data-bg-opt") === val); });
    };
    try { applyBg(localStorage.getItem("nexcut_bg") || "bg-1"); } catch (e) { applyBg("bg-1"); }
    bgBtns.forEach(function (b) {
      b.addEventListener("click", function () { applyBg(b.getAttribute("data-bg-opt")); });
    });

    var dlCard = document.querySelector(".dl-card");
    if (dlCard) {
      dlCard.addEventListener("mousemove", function (e) {
        var r = dlCard.getBoundingClientRect();
        var x = (e.clientX - r.left) / r.width - 0.5;
        var y = (e.clientY - r.top) / r.height - 0.5;
        dlCard.style.transform = "perspective(900px) rotateX(" + (-y * 6).toFixed(2) + "deg) rotateY(" + (x * 6).toFixed(2) + "deg)";
      });
      dlCard.addEventListener("mouseleave", function () {
        dlCard.style.transform = "";
      });
    }

    window._renderDlHistory = function () {
      var hList = document.getElementById("d-dl-hist-list");
      if (!hList) return;
      var items = [];
      try { items = JSON.parse(localStorage.getItem("saa_dl_history_d") || "[]"); } catch (_) {}
      hList.innerHTML = "";
      if (!items.length) {
        hList.appendChild(N.el("p", "meta", "No downloads yet."));
        return;
      }
      items.forEach(function (it) {
        var row = document.createElement("button");
        row.type = "button";
        row.className = "dl-hist-item";
        row.style.width = "100%";
        row.style.textAlign = "left";
        row.style.cursor = it.url ? "pointer" : "default";
        var left = document.createElement("div");
        left.textContent = it.title || "Downloaded video";
        var right = document.createElement("div");
        right.className = "meta";
        right.textContent = (it.quality || "1080p") + " · " + (it.date || "") + " · " + (it.time || "");
        row.appendChild(left);
        row.appendChild(right);
        if (it.url) {
          row.addEventListener("click", function () {
            var inp = document.querySelector('[data-role="dl-link"]');
            var form = document.querySelector('[data-role="dl-inspect-form"]');
            if (inp) inp.value = it.url;
            if (form) form.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
          });
        }
        hList.appendChild(row);
      });
    };
    window._renderDlHistory();

    var trimList = document.getElementById("d-dl-trim-list");
    if (trimList) {
      var getMaxSec = function () {
        var meta = document.querySelector('[data-role="dl-meta"]');
        var m = meta && meta.textContent ? meta.textContent.match(/(\d+):(\d{2}):(\d{2})/) : null;
        if (m) return Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3]);
        var m2 = meta && meta.textContent ? meta.textContent.match(/(\d+):(\d{2})/) : null;
        return m2 ? Number(m2[1]) * 60 + Number(m2[2]) : 0;
      };
      trimList.addEventListener("input", function (e) {
        var inp = e.target;
        if (!inp || !inp.classList.contains("dl-trim-in")) return;
        var maxSec = getMaxSec();
        var isHour = maxSec >= 3600;
        var maxDigits = isHour ? 5 : 4;
        var digits = inp.value.replace(/\D/g, "").slice(0, maxDigits);
        var formatted = digits;
        if (isHour) {
          if (digits.length > 3) formatted = digits.slice(0, 1) + ":" + digits.slice(1, 3) + ":" + digits.slice(3);
          else if (digits.length > 1) formatted = digits.slice(0, 1) + ":" + digits.slice(1);
        } else {
          if (digits.length > 2) formatted = digits.slice(0, 2) + ":" + digits.slice(2);
        }
        inp.value = formatted;
      });
    }

    var manualBox = document.getElementById("d-manual-box");
    var manualBtn = document.getElementById("d-manual-submit");
    var manualTxt = document.getElementById("d-manual-json");
    if (manualBox && manualBtn && manualTxt) {
      fetch("/api/config").then(function (r) { return r.json(); }).then(function (cfg) {
        if (cfg && cfg.provider === "manual") {
          manualBox.hidden = false;
        }
      }).catch(function () {});
      manualBtn.addEventListener("click", function () {
        var val = (manualTxt.value || "").trim();
        if (!val) { view.toast("Paste Claude's JSON first."); return; }
        manualBtn.disabled = true;
        fetch("/api/manual-answer", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: val })
        }).then(function (r) {
          if (!r.ok) throw new Error("Failed");
          manualTxt.value = "";
          view.toast("Submitted — processing clips…");
        }).catch(function () {
          view.toast("Failed to submit JSON.");
        }).finally(function () {
          manualBtn.disabled = false;
        });
      });
    }

    var creditsBtn = document.getElementById("d-credits-btn");
    var creditsModal = document.getElementById("d-credits-modal");
    var creditsClose = document.getElementById("d-credits-close");
    if (creditsBtn && creditsModal) {
      creditsBtn.addEventListener("click", function () { creditsModal.hidden = false; });
      if (creditsClose) creditsClose.addEventListener("click", function () { creditsModal.hidden = true; });
      creditsModal.addEventListener("click", function (e) {
        if (e.target === creditsModal) creditsModal.hidden = true;
      });
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
