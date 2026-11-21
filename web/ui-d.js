/* NexCut — direction D, "Field".
   Layout and interaction only. Flow, state and the API live in core.js. */
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
    R("pane-cutter").hidden = mode !== "cutter";
    R("pane-downloader").hidden = mode !== "downloader";
    RS("mode").forEach(function (b) {
      b.setAttribute("aria-selected", b.getAttribute("data-mode") === mode ? "true" : "false");
    });
    var side = document.querySelector(".rail-side");
    if (side) side.textContent = mode === "downloader" ? "Side B" : "Side A";
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

    if (pack.scores.length) {
      var scores = N.el("dl", "pack-scores");
      pack.scores.forEach(function (s) {
        var cell = N.el("div");
        cell.appendChild(N.el("dt", null, s.label));
        cell.appendChild(N.el("dd", null, s.value));
        scores.appendChild(cell);
      });
      wrap.appendChild(scores);
    }

    pack.fields.forEach(function (f) {
      var block = N.el("div", "field-block" + (f.strong ? " strong" : ""));
      block.setAttribute("data-field", f.key);
      var key = N.el("div", "fk");
      key.appendChild(N.el("span", null, f.label));
      if (f.copy) {
        var btn = N.el("button", "copy", "Copy");
        btn.type = "button";
        btn.setAttribute("data-role", "copy-control");
        btn.setAttribute("data-action", "copy");
        btn.setAttribute("data-copy", f.value);
        btn.setAttribute("aria-label", "Copy " + f.label.toLowerCase());
        key.appendChild(btn);
      }
      block.appendChild(key);
      block.appendChild(N.el("div", "fv", f.value));
      wrap.appendChild(block);
    });

    if (pack.overlays.length) {
      var ov = N.el("div", "field-block");
      ov.setAttribute("data-field", "overlays");
      ov.appendChild(N.el("div", "fk", "On-screen overlays"));
      var list = N.el("ul", "overlays");
      pack.overlays.forEach(function (o) {
        var li = N.el("li");
        li.appendChild(N.el("span", "ov-time", o.offset));
        li.appendChild(N.el("span", null, o.text));
        list.appendChild(li);
      });
      ov.appendChild(list);
      wrap.appendChild(ov);
    }
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

      var row = N.el("div", "clip-row");
      row.appendChild(N.el("span", "clip-n", pad2(i + 1)));
      row.appendChild(N.el("span", "t", clip.pack.title));
      row.appendChild(N.el("span", "score" + (clip.pack.avg !== null && clip.pack.avg >= 8 ? " hi" : ""), clip.pack.avgText));
      row.appendChild(actionFor(i));

      var more = N.el("button", "ghost more", isOpen ? "Less" : "More");
      more.type = "button";
      more.setAttribute("data-role", "clip-more");
      more.setAttribute("data-action", "more");
      more.setAttribute("data-index", String(i));
      more.setAttribute("aria-expanded", isOpen ? "true" : "false");
      row.appendChild(more);
      li.appendChild(row);

      if (isOpen) li.appendChild(packagingNode(clip.pack));
      list.appendChild(li);
    });
  }

  function syncZipLink() {
    var link = R("zip-link");
    link.hidden = !(lastModel && lastModel.zip && lastZip);
    link.setAttribute("href", lastZip || "#");
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
      N.put("stage-label", RAIL[name] || "");
      moveCredits(name === "working");
    },

    renderDetails: function (details, err) {
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
      N.put("res-title", model.ready ? model.title : "—");
      N.put("res-meta", model.meta.join("   ·   "));
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
      lastFiles = c.files || [];
      lastZip = c.zipUrl || "";
      renderList();
      syncZipLink();

      if (c.clips && c.clips.length) {
        try {
          var hist = JSON.parse(localStorage.getItem("saa_history_d") || "[]");
          var chEl = R("detail-meta");
          var channel = chEl ? (chEl.textContent || "").trim() : "";
          var now = new Date();
          var cutAt = now.toLocaleDateString() + " " + now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
          var entry = { title: c.title || "Untitled", channel: channel || "YouTube", cutAt: cutAt, clips: c.clips };
          if (!hist.length || hist[0].title !== entry.title || hist[0].clips.length !== entry.clips.length) {
            hist.unshift(entry);
            localStorage.setItem("saa_history_d", JSON.stringify(hist.slice(0, 20)));
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
    "history": function () {
      var hp = R("history-panel");
      var cutter = R("pane-cutter");
      var list = R("history-list");
      var open = hp.hidden;
      hp.hidden = !open;
      cutter.hidden = open;
      if (open && list) {
        var items = [];
        try { items = JSON.parse(localStorage.getItem("saa_history_d") || "[]"); } catch (_) {}
        list.innerHTML = "";
        if (!items.length) {
          list.appendChild(N.el("p", "sub", "No cut history yet. Extract a video to see it here."));
          return;
        }
        items.forEach(function (it) {
          var btn = N.el("button", "history-item");
          btn.type = "button";
          btn.appendChild(N.el("div", "history-title", it.title || "Untitled video"));
          btn.appendChild(N.el("div", "history-meta", (it.channel || "Unknown channel") + " · Cut " + (it.cutAt || "") + " · " + (it.clips ? it.clips.length : 0) + " clips"));
          btn.addEventListener("click", function () {
            hp.hidden = true;
            cutter.hidden = false;
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
    N.bindDrop(function (file) { app.uploadFile(file); });

    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") return;
      if (!R("own-box").hidden) view.openOwnTranscript(false);
      if (Object.keys(open).some(function (k) { return open[k]; })) { open = {}; renderList(); }
    });
  }

  function init() {
    if (inited) return;
    inited = true;
    N.hydrateIcons(document);
    N.bindActions(actions);
    syncTheme();
    wireInputs();
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
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
