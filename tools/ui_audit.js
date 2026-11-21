#!/usr/bin/env node
/**
 * Static audit of the production UI and shared engine.
 *
 *   node tools/ui_audit.js
 *
 * Checks what breaks on someone else's machine and cannot be seen by a unit test:
 * the data-role contract is present in every direction, every control has a
 * handler, the JavaScript references only elements that exist, nothing loads from
 * a CDN, the clipboard has a plain-http fallback, hidden panes really hide, the
 * layout has breakpoints and a short-viewport story, and the browser never serves
 * stale assets. Exit code 1 when anything FAILs, so it can gate a commit.
 */
const fs = require("fs");
const path = require("path");
const { REQUIRED, DIRECTIONS } = require("./ui_contract");

const ROOT = path.resolve(__dirname, "..");
const read = (p) => fs.readFileSync(path.join(ROOT, p), "utf8");
const exists = (p) => fs.existsSync(path.join(ROOT, p));

const findings = [];
const add = (level, area, message, hint) => findings.push({ level, area, message, hint });

const core = read("web/core.js");

/* ── 0. the old single-page client is gone; nothing points at it ─────── */
for (const old of ["web/app.js", "web/style.css"]) {
  if (exists(old)) add("FAIL", "cleanup", `${old} still exists`, "the old UI was replaced by the production UI");
}

let controlCount = 0;

for (const dir of DIRECTIONS) {
  const html = read(`web/${dir}.html`);
  const js = read(`web/${dir}.js`);
  const css = read(`web/${dir}.css`);
  const tag = dir.toUpperCase();
  const htmlRoles = new Set([...html.matchAll(/data-role="([^"]+)"/g)].map((m) => m[1]));

  /* 1 · the owner's contract is present */
  const missing = REQUIRED.filter((r) => !htmlRoles.has(r));
  if (missing.length) add("FAIL", "contract", `${tag} is missing: ${missing.join(", ")}`, "every direction must carry every requirement");

  /* 2 · the script only reaches for elements that exist */
  const referenced = new Set([
    ...[...js.matchAll(/\bR\("([a-z-]+)"\)/g)].map((m) => m[1]),
    ...[...js.matchAll(/\bRS\("([a-z-]+)"\)/g)].map((m) => m[1]),
    ...[...js.matchAll(/N\.put\("([a-z-]+)"/g)].map((m) => m[1]),
  ]);
  for (const r of referenced) {
    if (!htmlRoles.has(r)) add("FAIL", "markup", `${tag} script uses data-role "${r}", markup has no such element`, "rename one side or add the element");
  }

  /* 3 · every control has a handler */
  const actionKeys = new Set();
  const actionsBlock = (js.match(/var actions = \{([\s\S]*?)\n  \};/) || [])[1] || "";
  for (const m of actionsBlock.matchAll(/"([a-z-]+)":\s*function/g)) actionKeys.add(m[1]);
  const actionUses = new Set([...html.matchAll(/data-action="([^"]+)"/g)].map((m) => m[1]));
  for (const dynamic of js.matchAll(/setAttribute\("data-action",\s*"([^"]+)"\)/g)) actionUses.add(dynamic[1]);
  for (const a of actionUses) {
    if (!actionKeys.has(a)) add("FAIL", "controls", `${tag}: data-action="${a}" has no handler`, "add it to the actions map or remove the control");
  }
  for (const a of actionKeys) {
    if (!actionUses.has(a)) add("WARN", "controls", `${tag}: handler "${a}" is never used`, "dead handler");
  }
  for (const m of html.matchAll(/<(button|input|select|textarea)\b([^>]*)>/g)) {
    const attrs = m[2];
    if (/type="(hidden|file)"/.test(attrs) || /\bhidden\b/.test(attrs)) continue;
    controlCount += 1;
    const role = (attrs.match(/data-role="([^"]+)"/) || [])[1];
    const action = (attrs.match(/data-action="([^"]+)"/) || [])[1];
    if (action) continue;
    if (role && (referenced.has(role) || js.includes(`"${role}"`))) continue;
    if (/data-copy|class="copy"/.test(attrs)) continue;   // generated copy buttons are wired by delegation
    add("FAIL", "controls", `${tag}: <${m[1]}${role ? ` data-role="${role}"` : ""}> has no handler`, "wire it or remove it");
  }

  /* 4 · no external assets: the app runs offline and on a LAN */
  for (const m of html.matchAll(/(?:src|href)="(https?:\/\/[^"]+)"/g)) {
    if (!/github\.com\/sadapay404\/NexCut/.test(m[1])) add("FAIL", "offline", `${tag} loads ${m[1]}`, "no CDNs: bundle it or drop it");
  }
  if (/@import|url\(\s*["']?https?:/.test(css)) add("FAIL", "offline", `${tag} CSS loads an external resource`, "no CDNs");

  /* 5 · hidden panes really hide, whatever the layout rules say */
  if (!/\[hidden\]\s*\{[^}]*display:\s*none\s*!important/.test(css)) {
    add("FAIL", "layout", `${tag} has no [hidden] override`, "a pane with display:flex/grid would stay on screen");
  }

  /* 6 · responsive coverage */
  const widths = [...css.matchAll(/@media[^{]*max-width:\s*(\d+)px/g)].map((m) => Number(m[1]));
  for (const needed of [1024, 768]) {
    if (!widths.some((w) => w <= needed && w > needed - 280)) {
      add("FAIL", "responsive", `${tag}: no breakpoint near ${needed}px`, "tablets and small laptops need their own layout");
    }
  }
  if (!widths.some((w) => w <= 480)) add("FAIL", "responsive", `${tag}: no phone breakpoint (≤480px)`, "phones beyond the design width rely on it");
  if (!/(min-height:\s*100dvh|min-height:\s*100vh)/.test(css)) add("FAIL", "responsive", `${tag}: body has no min-height`, "the frame must fill the viewport");
  if (!/safe-area-inset/.test(css)) add("WARN", "responsive", `${tag}: no safe-area padding`, "notched phones can clip the footer");
  if (!/pointer:\s*coarse/.test(css)) add("FAIL", "responsive", `${tag}: no touch-pointer rule`, "tap targets stay small on phones and tablets");
  if (!/body\s*\{[^}]*overflow:\s*hidden/.test(css) === false && /body\s*\{[^}]*overflow:\s*hidden/.test(css)) {
    add("FAIL", "layout", `${tag}: body is overflow:hidden`, "on a 1366×600 laptop the bottom becomes unreachable");
  }

  /* 7 · accessibility */
  if (!/:focus-visible/.test(css)) add("FAIL", "a11y", `${tag}: no :focus-visible ring`, "keyboard users cannot see where they are");
  if (!/prefers-reduced-motion/.test(css)) add("FAIL", "a11y", `${tag}: ignores prefers-reduced-motion`, "motion-sensitive users need it off");
  if (!/aria-live/.test(html)) add("WARN", "a11y", `${tag}: no aria-live region`, "screen readers miss progress");
  if (!/<h1[\s>]/.test(html)) add("FAIL", "a11y", `${tag}: no <h1>`, "every direction needs a real page heading");
  const urlInput = (html.match(/<input[^>]*data-role="link-input"[^>]*>/) || [])[0] || "";
  for (const [attr, why] of [
    ['inputmode="url"', "phones open a full keyboard for a URL field"],
    ['autocomplete="off"', "keyboard suggestions fight the URL field"],
    ['autocapitalize="off"', "a pasted link gets mangled"],
    ['spellcheck="false"', "squiggles under every link"],
  ]) {
    if (!urlInput.includes(attr)) add("FAIL", "forms", `${tag}: link input lacks ${attr}`, why);
  }

  /* 8 · the credits line is mandatory and must never be clipped */
  if (!/\.credits\s*\{/.test(css)) add("FAIL", "layout", `${tag}: credits line has no styles`, "it is mandatory");
  if (!/\.credits b\s*\{/.test(css)) add("FAIL", "layout", `${tag}: credit names are not styled bold`, "both names must be bold");
  if (!/<b>Sheikh Arsalan<\/b>/.test(html) || !/<b>Mubashir<\/b>/.test(html)) add("FAIL", "layout", `${tag}: credit names not bold in markup`, "both names are bold");

  /* 9 · stale-asset guard: CSS, JS and the engine share one cache-buster */
  const busters = [...html.matchAll(/\?v=(\d+)/g)].map((m) => m[1]);
  if (new Set(busters).size !== 1) add("FAIL", "cache", `${tag}: cache-busters disagree (${busters.join(", ")})`, "CSS, JS and core.js must be versioned together");

  /* 10 · classes that no rule styles render with browser defaults */
  const css_ = new Set([...css.matchAll(/\.([A-Za-z][\w-]*)/g)].map((m) => m[1]));
  const used = new Set();
  for (const m of html.matchAll(/class="([^"]+)"/g)) m[1].split(/\s+/).forEach((c) => c && used.add(c));
  for (const m of js.matchAll(/(?:el|N\.el)\(\s*"[a-z0-9]+",\s*"([^"]+)"/g)) m[1].split(/\s+/).forEach((c) => c && used.add(c));
  for (const c of [...used].sort()) {
    if (!css_.has(c) && !["ic", "sr", "is-open", "is-sel", "is-done", "is-current", "is-error", "strong", "wide", "act", "more", "size", "log-item", "log-tick", "log-text", "score-k", "score-v"].includes(c)) {
      add("WARN", "css", `${tag}: class .${c} is used but never styled`, "it renders with browser defaults");
    }
  }
}

/* 11 · the shared engine: clipboard fallback, and no innerHTML for model output */
if (/navigator\.clipboard/.test(core) && !/execCommand\(\s*"copy"/.test(core)) {
  add("FAIL", "behaviour", "core copy() has no execCommand fallback", "on http://<lan-ip>:8137 navigator.clipboard is undefined");
}
if (!/isSecureContext/.test(core)) add("WARN", "behaviour", "core copy() does not check isSecureContext", "fallback should be explicit");
const modelInnerHtml = (core.match(/\.innerHTML\s*=\s*[^;]*\b(clip|job|job\.|data|res|raw|error|msg|message|text|value)\b/g) || []);
if (modelInnerHtml.length) add("FAIL", "security", "core writes model output with innerHTML", "use textContent: model output is untrusted");

/* ── report ─────────────────────────────────────────────────────────── */
const order = { FAIL: 0, WARN: 1 };
findings.sort((a, b) => order[a.level] - order[b.level] || a.area.localeCompare(b.area));
const fails = findings.filter((f) => f.level === "FAIL");
const warns = findings.filter((f) => f.level === "WARN");

console.log(`\nNexCut UI audit — ${DIRECTIONS.length} directions, ${controlCount} controls checked\n`);
if (!findings.length) console.log("  nothing to report");
for (const f of [...fails, ...warns]) {
  console.log(`  ${f.level}  ${f.area.padEnd(11)} ${f.message}`);
  if (f.hint) console.log(`        ${" ".repeat(11)} → ${f.hint}`);
}
console.log(`\n${fails.length} fail, ${warns.length} warn\n`);
process.exitCode = fails.length ? 1 : 0;
