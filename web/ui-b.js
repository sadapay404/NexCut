/* NexCut — direction B, console / tool.
   Layout and interaction only. Flow, state and the API live in core.js.
   Clip packaging is shown in the inspector for the selected row, not inline. */
(function () {
  "use strict";
  var N = window.NexCut;
  var R = function (name) { return N.role(name); };
  var RS = function (name) { return N.roles(name); };

  var STAGES = ["landing", "details", "working", "error", "results"];
  var app = null;
  var selected = -1;        // index of the clip shown in the inspector
  var runSeen = -1;
  var lastModel = null;
  var lastFiles = [];
  var lastZip = "";
  var lastErrorText = "";
  var minClips = 5;
  var maxClips = 15;
  var inited = false;

  function pad(n) { return String(n).padStart(2, "0"); }
  function clipLen(clip) { return clip.pack.seconds ? clip.pack.seconds + " s" : clip.pack.timing[2][1]; }

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

  /* packaging, rendered for the inspector */
  function packagingNode(pack) {
    var wrap = N.el("div");
    wrap.setAttribute("data-role", "packaging");

    var grid = N.el("dl", "pk-grid");
    pack.timing.forEach(function (pair) {
      var cell = N.el("div");
      cell.appendChild(N.el("dt", null, pair[0]));
      cell.appendChild(N.el("dd", "mono", pair[1]));
      grid.appendChild(cell);
    });
    pack.scores.forEach(function (s) {
      var cell = N.el("div", "score-cell");
      cell.appendChild(N.el("dt", null, s.label));
      cell.appendChild(N.el("dd", "mono", s.value));
      var track = N.el("div", "meter");
      var fill = N.el("i");
      fill.style.width = Math.max(0, Math.min(100, s.value * 10)) + "%";
      track.appendChild(fill);
      cell.appendChild(track);
      grid.appendChild(cell);
    });
    wrap.appendChild(grid);

    pack.fields.forEach(function (f) {
      var block = N.el("div", "pk-field" + (f.strong ? " strong" : ""));
      block.setAttribute("data-field", f.key);
      var head = N.el("div", "pk-k");
      head.appendChild(N.el("span", null, f.label));
      if (f.copy) {
        var btn = N.el("button", "copy", "copy");
        btn.type = "button";
        btn.setAttribute("data-role", "copy-control");
        btn.setAttribute("data-action", "copy");
        btn.setAttribute("data-copy", f.value);
        btn.setAttribute("aria-label", "Copy " + f.label.toLowerCase());
        head.appendChild(btn);
      }
      block.appendChild(head);
      block.appendChild(N.el("div", "pk-v", f.value));
      wrap.appendChild(block);
    });

    if (pack.overlays.length) {
      var ov = N.el("div", "pk-field");
      ov.setAttribute("data-field", "overlays");
      ov.appendChild(N.el("div", "pk-k", "overlays"));
      pack.overlays.forEach(function (o) {
        ov.appendChild(N.el("div", "pk-v mono", o.offset + "  " + o.text));
      });
      wrap.appendChild(ov);
    }
    return wrap;
  }

  function renderInspector() {
    var body = R("inspector");
    body.textContent = "";
    var clips = (lastModel && lastModel.clips) || [];
    var clip = clips[selected];
    N.put("insp-clip", clip ? "clip " + pad(clip.n) : "—");
    if (!clip) {
      var empty = N.el("p", "empty-note");
      empty.appendChild(document.createTextNode("Select a clip with "));
      empty.appendChild(N.el("b", null, "inspect"));
      empty.appendChild(document.createTextNode(" to see its packaging here."));
      body.appendChild(empty);
      return;
    }
    var head = N.el("p", "insp-title", clip.pack.title);
    body.appendChild(head);
    body.appendChild(packagingNode(clip.pack));
  }

  function actionCell(index) {
    var cell = N.el("td", "c-act");
    cell.setAttribute("data-label", "");
    var file = lastFiles[index];
    if (lastModel && lastModel.zip) {
      cell.appendChild(N.el("span", "note", file ? file.size_mb + " MB" : "in ZIP"));
    } else if (file) {
      var a = N.el("a", "btn small primary", "download");
      a.href = file.url;
      a.setAttribute("download", file.name);
      a.setAttribute("data-role", "clip-download");
      cell.appendChild(a);
    } else {
      var pending = N.el("span", "note", "cutting…");
      pending.setAttribute("data-role", "clip-pending");
      cell.appendChild(pending);
    }
    return cell;
  }

  function renderList() {
    var body = R("clip-list");
    body.textContent = "";
    var clips = (lastModel && lastModel.clips) || [];
    if (lastModel && lastModel.ready && !clips.length) {
      var row = N.el("tr", "empty-row");
      var cell = N.el("td", "list-empty", N.emptyMessage(lastModel));
      cell.colSpan = 6;
      cell.setAttribute("data-role", "clip-empty");
      row.appendChild(cell);
      body.appendChild(row);
    }
    clips.forEach(function (clip, i) {
      var isSel = i === selected;
      var tr = N.el("tr", isSel ? "is-sel" : "");
      tr.setAttribute("data-role", "clip-item");

      tr.appendChild(N.el("td", "c-n", pad(clip.n)));
      var title = N.el("td", "c-title", clip.pack.title);
      title.setAttribute("data-label", "clip");
      tr.appendChild(title);
      var score = N.el("td", "c-score" + (clip.pack.avg !== null && clip.pack.avg >= 8 ? " hi" : ""), clip.pack.avgText);
      score.setAttribute("data-label", "score");
      tr.appendChild(score);
      var range = N.el("td", "c-range", clip.pack.timing[0][1] + " → " + clip.pack.timing[1][1]);
      range.setAttribute("data-label", "range");
      tr.appendChild(range);
      var len = N.el("td", "c-len", clipLen(clip));
      len.setAttribute("data-label", "len");
      tr.appendChild(len);

      var act = actionCell(i);
      var inspect = N.el("button", "tbtn", isSel ? "inspecting" : "inspect");
      inspect.type = "button";
      inspect.setAttribute("data-role", "clip-more");
      inspect.setAttribute("data-action", "more");
      inspect.setAttribute("data-index", String(i));
      inspect.setAttribute("aria-pressed", isSel ? "true" : "false");
      act.insertBefore(inspect, act.firstChild);
      tr.appendChild(act);
      body.appendChild(tr);
    });
    renderInspector();
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
        var pane = R(s === "landing" ? "pane-landing" : "pane-" + s);
        if (pane) pane.hidden = s !== name;
      });
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

    renderProgress: function (p) {
      var pct = Math.max(0, Math.min(100, Math.round(p.pct) || 0));
      R("progress-fill").style.width = pct + "%";
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
      if (model.runId !== runSeen) { runSeen = model.runId; selected = -1; }
      if (selected >= (model.clips || []).length) selected = -1;
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
      selected = selected === i ? -1 : i;
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
      if (selected !== -1) { selected = -1; renderList(); }
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
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
