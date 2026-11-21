/* The contract every UI direction must satisfy: the owner's functional
 * requirements, expressed as data-role names. ui_smoke.js walks them and
 * ui_audit.js checks the markup carries them. */
"use strict";
/* the contract every direction must satisfy: the owner's functional requirements */
const REQUIRED = [
  "mode", "theme-toggle", "build-tag", "brand",
  "pane-cutter", "pane-downloader", "pane-landing", "pane-details", "pane-working", "pane-error", "pane-results",
  "link-input", "fetch-btn", "source-state",
  "detail-badge", "fact-title", "fact-channel", "fact-length", "fact-captions", "fact-transcript", "fact-niche",
  "view-transcript", "own-toggle", "own-box", "transcript-input", "upload-btn", "file-input", "own-note",
  "clip-count", "clip-badge", "len-option", "custom-len", "custom-min", "custom-max", "run", "config-hint",
  "stage-text", "pct-text", "progress-fill", "stage-log", "credits-slot",
  "error-title", "error-message", "error-hint", "error-raw", "retry", "new-link", "copy-details",
  "res-title", "res-meta", "stat-found", "stat-kept", "stat-rejected", "stat-asked",
  "zip-toggle", "copy-answer", "new-run", "clip-list", "cut-state", "cut-fill", "cut-track", "zip-link",
  "credits", "credits-home", "toasts",
];

module.exports = { REQUIRED, DIRECTIONS: ["ui-d"] };
