/* NexCut — direction C, cards / consumer.
   One thing at a time: a five-step stepper, one card per stage, a two-step plan
   (details, then clip plan), results as clip cards. Layout and interaction only;
   flow, state and the API live in core.js. */
(function () {
  "use strict";
  var N = window.NexCut;
  var R = function (name) { return N.role(name); };
  var RS = function (name) { return N.roles(name); };

  var app = null;
  var planStep = false;     // inside the details stage: false = details card, true = plan card
  var stage = "landing";
  var open = {};
  var runSeen = -1;
  var lastModel = null;
  var lastFiles = [];
  var lastZip = "";
  var lastErrorText = "";
  var minClips = 5;
  var maxClips = 15;
  var inited = false;
  var logCount = 0;

  function pad(n) { return String(n).padStart(2, "0"); }

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

  function stepCount(delta) {
    var input = R("clip-count");
    var n = N.clampClips(input.value, minClips, maxClips);
    if (delta > 0) n = n ? Math.min(maxClips, n + 1) : minClips;
    else if (n) n = Math.max(minClips, n - 1);
    input.value = n ? String(n) : "";
    updateBadge();
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
  }

  /* stepper: 1 Link · 2 Details · 3 Plan · 4 Extract · 5 Clips */
  function paintSteps() {
    var current = { landing: 1, details: planStep ? 3 : 2, working: 4, error: 4, results: 5 }[stage] || 1;
    Array.prototype.forEach.call(document.querySelectorAll(".steps li"), function (li) {
      var n = Number(li.getAttribute("data-step"));
      li.classList.toggle("is-done", n < current);
      li.classList.toggle("is-current", n === current);
      li.classList.toggle("is-error", stage === "error" && n === current);
      var dot = li.querySelector(".dot");
      dot.textContent = "";
      if (n < current) dot.appendChild(N.icon("check"));
      else dot.textContent = String(n);
      if (n === current) li.setAttribute("aria-current", "step");
      else li.removeAttribute("aria-current");
    });
  }

  function packagingNode(pack) {
    var wrap = N.el("div", "pk");
    wrap.setAttribute("data-role", "packaging");

    var chips = N.el("div", "chips");
    pack.timing.forEach(function (pair) {
      chips.appendChild(N.el("span", "chip", pair[0] + " " + pair[1]));
    });
    wrap.appendChild(chips);

    if (pack.scores.length) {
      var scores = N.el("div", "score-row");
      pack.scores.forEach(function (s) {
        var cell = N.el("div", "score-cell");
        cell.appendChild(N.el("span", "score-k", s.label));
        cell.appendChild(N.el("span", "score-v", s.value));
        scores.appendChild(cell);
      });
      wrap.appendChild(scores);
    }

    pack.fields.forEach(function (f) {
      var card = N.el("div", "pk-card" + (f.strong ? " strong" : ""));
      card.setAttribute("data-field", f.key);
      var head = N.el("div", "pk-head");
      head.appendChild(N.el("span", "pk-k", f.label));
      if (f.copy) {
        var btn = N.el("button", "btn ghost small", "Copy");
        btn.type = "button";
        btn.setAttribute("data-role", "copy-control");
        btn.setAttribute("data-action", "copy");
        btn.setAttribute("data-copy", f.value);
        btn.setAttribute("aria-label", "Copy " + f.label.toLowerCase());
        head.appendChild(btn);
      }
      card.appendChild(head);
      card.appendChild(N.el("p", "pk-v", f.value));
      wrap.appendChild(card);
    });

    if (pack.overlays.length) {
      var ov = N.el("div", "pk-card");
      ov.setAttribute("data-field", "overlays");
      ov.appendChild(N.el("span", "pk-k", "On-screen overlays"));
      pack.overlays.forEach(function (o) {
        ov.appendChild(N.el("p", "pk-v", o.offset + "  ·  " + o.text));
      });
      wrap.appendChild(ov);
    }
    return wrap;
  }

  function actionFor(index) {
    var file = lastFiles[index];
    if (lastModel && lastModel.zip) return N.el("span", "muted small", file ? file.size_mb + " MB" : "in ZIP");
    if (file) {
      var a = N.el("a", "btn primary", "Download");
      a.href = file.url;
      a.setAttribute("download", file.name);
      a.setAttribute("data-role", "clip-download");
      return a;
    }
    var b = N.el("button", "btn ghost", "Cutting…");
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

      var thumb = N.el("div", "thumb");
      thumb.setAttribute("aria-hidden", "true");
      thumb.appendChild(N.el("span", "thumb-text", clip.pack.thumb || "Clip " + pad(clip.n)));
      if (clip.pack.seconds) thumb.appendChild(N.el("span", "thumb-len", clip.pack.seconds + " s"));
      li.appendChild(thumb);

      var body = N.el("div", "clip-body");
      var top = N.el("div", "clip-top");
      top.appendChild(N.el("span", "chip", "Clip " + pad(clip.n)));
      top.appendChild(N.el("span", "score" + (clip.pack.avg !== null && clip.pack.avg >= 8 ? " hi" : ""), clip.pack.avgText));
      body.appendChild(top);
      body.appendChild(N.el("h3", "clip-title", clip.pack.title));
      body.appendChild(N.el("p", "muted small", clip.pack.timing[0][1] + " → " + clip.pack.timing[1][1]));

      var actions = N.el("div", "row-btns");
      actions.appendChild(actionFor(i));
      var more = N.el("button", "btn ghost", isOpen ? "Hide details" : "Details");
      more.type = "button";
      more.setAttribute("data-role", "clip-more");
      more.setAttribute("data-action", "more");
      more.setAttribute("data-index", String(i));
      more.setAttribute("aria-expanded", isOpen ? "true" : "false");
      actions.appendChild(more);
      body.appendChild(actions);
      li.appendChild(body);

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

  function showPlan(on) {
    planStep = Boolean(on);
    R("card-details").hidden = planStep;
    R("pane-plan").hidden = !planStep;
    paintSteps();
    if (planStep) N.focusIfDesktop(R("clip-count"));
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
      stage = name;
      if (name === "details") planStep = false;
      ["landing", "details", "working", "error", "results"].forEach(function (s) {
        var pane = R(s === "landing" ? "pane-landing" : "pane-" + s);
        if (pane) pane.hidden = s !== name;
      });
      R("card-details").hidden = planStep;
      R("pane-plan").hidden = !planStep;
      paintSteps();
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
      N.put("avatar", f.channel && f.channel !== "—" ? f.channel.charAt(0).toUpperCase() : "N");
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

    renderProgress: function (p) {
      var pct = Math.max(0, Math.min(100, Math.round(p.pct) || 0));
      R("ring").style.setProperty("--p", String(pct));
      R("progress-fill").style.width = pct + "%";
      N.put("pct-text", pct + "%");
      N.put("stage-text", p.stage || "Working");
      var log = R("stage-log");
      if (p.reset) { log.textContent = ""; logCount = 0; }
      if (p.logLine) {
        var item = N.el("li", "log-item");
        item.appendChild(N.el("span", "log-tick")).appendChild(N.icon("check"));
        item.appendChild(N.el("span", "log-text", p.logLine.replace(/^\s*\d+%\s+/, "")));
        log.appendChild(item);
        logCount += 1;
        while (log.children.length > 6) log.removeChild(log.firstChild);
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
      N.put("res-meta", model.meta.join("  ·  "));
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
      R("cut-fill").style.width = Math.max(0, Math.min(100, Number(cut.pct) || 0)) + "%";
      lastFiles = c.files || [];
      lastZip = c.zipUrl || "";
      renderList();
      syncZipLink();
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
    "plan-next": function () { showPlan(true); },
    "plan-back": function () { showPlan(false); },
    "len": function (el) { setLen(el.getAttribute("data-len")); },
    "step": function (el) { stepCount(Number(el.getAttribute("data-step"))); },
    "run": function () { app.run(); },
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
    paintSteps();
    app = N.createApp(view);
    app.boot();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
