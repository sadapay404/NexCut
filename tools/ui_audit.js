#!/usr/bin/env node
/**
 * Static + behavioural audit of the studio UI.
 *
 *   node tools/ui_audit.js
 *
 * Checks the things that break on someone else's machine and cannot be seen in a
 * screenshot: controls with no handler, ids the client expects but the markup
 * lacks, clipboard use without a fallback (fails on any non-https origin),
 * missing breakpoints, missing focus styles, and page-level clipping.
 *
 * Exit code 1 when anything FAILs, so it can gate a commit.
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const read = (p) => fs.readFileSync(path.join(ROOT, p), "utf8");

const html = read("web/index.html");
const js = read("web/app.js");
const css = read("web/style.css");

const findings = [];
const add = (level, area, message, hint) => findings.push({ level, area, message, hint });

/* ── 1. every id the client reaches for exists ────────────────────────── */
const htmlIds = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]));
const jsIds = new Set([...js.matchAll(/\$\("([A-Za-z0-9_-]+)"\)/g)].map((m) => m[1]));
for (const id of jsIds) {
  if (!htmlIds.has(id)) add("FAIL", "markup", `client uses #${id}, markup has no such element`);
}

/* ── 2. every control has a handler ───────────────────────────────────── */
const controlRe = /<(button|a|input|select)\b([^>]*)>([\s\S]*?)<\/\1>/g;
const idsWiredInJs = jsIds;
const delegated = ["modes", "lenSeg", "clipList", "detailPane", "resultsPane"];

let controlCount = 0;
for (const match of html.matchAll(controlRe)) {
  const [, tag, attrs, body] = match;
  if (/\btype="(hidden|file)"/.test(attrs)) continue;
  if (tag === "a" && /href=/.test(attrs)) continue;          // plain links
  if (/disabled/.test(attrs)) continue;
  controlCount += 1;

  const id = (attrs.match(/\bid="([^"]+)"/) || [])[1];
  const classes = ((attrs.match(/\bclass="([^"]+)"/) || [])[1] || "").split(/\s+/).filter(Boolean);
  const dataAttrs = [...attrs.matchAll(/\bdata-([a-z-]+)=/g)].map((m) => m[1]);
  const label = id ? `#${id}` : `<${tag} class="${classes.join(" ") || "?"}">`;

  let wired = false;
  if (id && idsWiredInJs.has(id)) wired = true;
  for (const attr of dataAttrs) {
    const camel = attr.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
    if (new RegExp(`dataset\\.${camel}|data-${attr}`).test(js)) wired = true;
  }
  if (classes.some((c) => new RegExp(`(^|[^\\w-])\\.[\\w-]*${c}\\b`).test(js))) wired = true;
  if (classes.includes("copy")) wired = wired || /\.copy\b/.test(js);
  for (const parent of delegated) {
    if (new RegExp(`\\$\\("${parent}"\\)\\.addEventListener`).test(js)) {
      // a button inside a delegated container is wired through it
      if (new RegExp(`id="${parent}"`).test(html) && html.indexOf(`id="${parent}"`) < html.indexOf(match[0])) {
        wired = true;
      }
    }
  }
  if (!wired) {
    add("FAIL", "controls", `${label} has no handler in app.js`,
        "give it an id or a data- hook and wire it, or remove it");
  }
}

/* ── 3. clipboard needs a fallback outside https/localhost ────────────── */
if (/navigator\.clipboard/.test(js) && !/execCommand|textContent\s*=\s*text|textarea/i.test(js)) {
  add("FAIL", "behaviour", "copy() only uses navigator.clipboard",
      "on http://<lan-ip>:8137 that object is undefined, so every copy button silently fails");
}

/* ── 4. responsive coverage ───────────────────────────────────────────── */
const widths = [...css.matchAll(/@media[^{]*max-width:\s*(\d+)px/g)].map((m) => Number(m[1]));
for (const needed of [1024, 768]) {
  if (!widths.some((w) => w <= needed && w > needed - 160)) {
    add("FAIL", "responsive", `no breakpoint near ${needed}px`,
        `add @media (max-width: ${needed}px) for tablets and small laptops`);
  }
}
if (!/@media[^{]*max-height/.test(css)) {
  add("FAIL", "responsive", "no short-viewport rule", "laptops lose the bottom of the card");
}
if (!/pointer:\s*(coarse|fine)|hover:\s*none/.test(css)) {
  add("FAIL", "responsive", "no touch-pointer rule",
      "tap targets stay 34px and feel broken on phones/tablets");
}
if (!/:focus-visible/.test(css)) {
  add("FAIL", "a11y", "no :focus-visible styles", "keyboard users cannot see where they are");
}
if (/:root[^{]*\{[^}]*--[\w-]*:/.test(css) && !/clamp\(|min\(|max\(|vw|dvh/.test(css)) {
  add("FAIL", "responsive", "no fluid sizing", "layout will break outside the design width");
}

/* ── 5. page-level clipping ───────────────────────────────────────────── */
const shortBlock = css.slice(css.indexOf("@media (max-height"));
if (/body\s*\{[^}]*overflow:\s*hidden/.test(css) && !/overflow(-y)?:\s*auto/.test(shortBlock)) {
  add("FAIL", "layout", "body{overflow:hidden} with no short-viewport escape",
      "on a 1366x600 laptop the bottom of the card is unreachable");
}

/* ── 6. form hygiene ──────────────────────────────────────────────────── */
const urlInput = (html.match(/<input[^>]*id="ytUrl"[^>]*>/) || [])[0] || "";
for (const [attr, why] of [
  ["autocomplete", "iOS/keyboard suggestions fight the URL bar"],
  ["spellcheck", "squiggles under every link"],
  ["inputmode", "mobile keyboard should be a URL keyboard"],
]) {
  if (!urlInput.includes(attr)) add("WARN", "forms", `#ytUrl has no ${attr}`, why);
}
if (!/aria-live/.test(html)) add("WARN", "a11y", "no aria-live region", "screen readers miss progress");

/* ── 7. markup classes that no rule styles ───────────────────────────── */
const usedClasses = new Set();
for (const m of html.matchAll(/class="([^"]+)"/g)) {
  m[1].split(/\s+/).filter(Boolean).forEach((c) => usedClasses.add(c));
}
for (const m of js.matchAll(/el\(\s*"[a-z0-9]+",\s*"([^"]+)"/g)) {
  m[1].split(/\s+/).filter(Boolean).forEach((c) => usedClasses.add(c));
}
const cssClasses = new Set([...css.matchAll(/\.([A-Za-z][\w-]*)/g)].map((m) => m[1]));
for (const c of [...usedClasses].sort()) {
  if (!cssClasses.has(c)) {
    add("WARN", "css", `.${c} is used but never styled`, "it renders with browser defaults");
  }
}

/* ── 8. the fixes themselves must stay ────────────────────────────────── */
const breakpoints = [...css.matchAll(/max-width:\s*(\d+)px/g)].map((m) => Number(m[1]));
for (const needed of [720, 520, 380]) {
  if (!breakpoints.includes(needed)) {
    add("FAIL", "responsive", `missing the ${needed}px breakpoint`,
        "phones beyond the design width rely on it");
  }
}
if (!/min-height:\s*100dvh|min-height:\s*100vh/.test(css)) {
  add("FAIL", "responsive", "no dvh/vh height on body", "mobile browser chrome clips the frame");
}
if (!/safe-area-inset/.test(css)) {
  add("WARN", "responsive", "no safe-area padding", "notched phones clip the top bar");
}
if (!/prefers-reduced-motion/.test(css)) {
  add("FAIL", "a11y", "ignores prefers-reduced-motion", "animation-sensitive users need it off");
}
const visibleTransitions = (css.match(/transition:/g) || []).length;
if (visibleTransitions > 20) {
  add("WARN", "perf", `${visibleTransitions} transitions declared`, "check the slow ones on low-end phones");
}

/* ── 9. the specific things that broke on a real laptop ───────────────── */
if (!/inputmode="url"/.test(urlInput)) {
  add("FAIL", "mobile", "#ytUrl has no inputmode=url", "phones open a full keyboard for a URL field");
}
if (!/autocomplete="off"/.test(urlInput) || !/autocapitalize="off"/.test(urlInput)) {
  add("FAIL", "mobile", "#ytUrl lets the OS autocorrect/capitalise", "a pasted link gets mangled");
}
if (!/touch-action:\s*manipulation/.test(css)) {
  add("WARN", "touch", "no touch-action: manipulation", "300ms tap delay on iOS");
}
if (!/\.credits\s*\{/.test(css)) {
  add("FAIL", "layout", "the credits footer has no styles", "it is mandatory in the frame");
}
if (/@media \(max-height: 560px\)/.test(css) && !/grid-template-rows/.test(shortBlock)) {
  add("FAIL", "layout", "the short-viewport escape keeps the fixed row grid",
      "the footer stays pinned over the scrollable card");
}
for (const [name, re] of [
  ["focus-visible ring", /:focus-visible/],
  ["reduced motion", /prefers-reduced-motion/],
  ["safe areas", /safe-area-inset/],
]) {
  if (!re.test(css)) add("WARN", "robustness", `${name} missing`, "breaks on some devices");
}

/* ── report ───────────────────────────────────────────────────────────── */
const order = { FAIL: 0, WARN: 1 };
findings.sort((a, b) => order[a.level] - order[b.level] || a.area.localeCompare(b.area));
const fails = findings.filter((f) => f.level === "FAIL");
const warns = findings.filter((f) => f.level === "WARN");

console.log(`\nNexCut UI audit — ${controlCount} controls checked\n`);
if (!findings.length) console.log("  nothing to report");
for (const f of [...fails, ...warns]) {
  console.log(`  ${f.level}  ${f.area.padEnd(11)} ${f.message}`);
  if (f.hint) console.log(`        ${" ".repeat(11)} → ${f.hint}`);
}
console.log(`\n${fails.length} fail, ${warns.length} warn\n`);
process.exit(fails.length ? 1 : 0);
