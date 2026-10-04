// v0.21 UI visual-consistency guard — STATIC audit of the index.html
// <style> block (no browser, no engine). Locks the type scale and radius
// system that the v0.21 normalization established:
//   C1  every font-size is var(--fs-*) OR an allow-listed icon glyph size
//       (the ◇/⬆/● decorations at 9/21/24/30px) — no raw px text sizes,
//       no .5px steps
//   C2  every border-radius is var(--r-*), 999px (pill/bar), 50% (circle)
//       or the snapshot-template's var token — no one-off px corners
//   C3  the tokens themselves exist and the scale has no .5px values
//   C4  control-height contract: base button/input/select rules carry
//       height: var(--ctl-h); the documented opt-outs keep height:auto
// Why static: the E2E suites pin behavior, not styling — a hard-coded
// 13.5px would sail through them. This file is the tripwire.
// Usage: node tests/ui_consistency_check.js   (exit 1 on any FAIL)
"use strict";
const fs = require("fs"), path = require("path");

const ROOT = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
const style = (html.match(/<style>([\s\S]*?)<\/style>/) || [])[1];
if (!style) { console.error("FAIL  no <style> block found"); process.exit(1); }

// strip comments so commented-out legacy values don't trip the audit
const css = style.replace(/\/\*[\s\S]*?\*\//g, "");
const lineNo = (offset) => css.slice(0, offset).split("\n").length + 9; // +9: <style> starts at index.html line 9... (approximate is fine — we print the css line)

let fails = 0;
const expect = (name, cond, detail) => {
  console.log((cond ? "PASS" : "FAIL") + "  " + name + (cond ? "" : "  " + detail));
  if (!cond) fails++;
};

// ---- C1: type scale -------------------------------------------------------
const FS_ICON_PX = new Set(["9px", "21px", "24px", "30px"]);  // glyph metrics only
const fsDecls = [];
for (const m of css.matchAll(/font-size:\s*([^;}\n]+)/g)) {
  fsDecls.push({ value: m[1].trim(), at: m.index });
}
const fsBad = fsDecls.filter(d => {
  if (/^var\(--fs-(xs|sm|md|lg|xl|2xl|kpi)\)$/.test(d.value)) return false;
  if (FS_ICON_PX.has(d.value)) return false;
  return true;
});
expect("C1 font-size: every declaration is var(--fs-*) or an icon glyph",
       fsBad.length === 0,
       fsBad.map(d => `「${d.value}」@css:${lineNo(d.at)}`).join(", "));
expect("C1 font-size: found declarations to audit (guard against selector rot)",
       fsDecls.length >= 30, String(fsDecls.length));

// ---- C2: radii ------------------------------------------------------------
const rDecls = [];
for (const m of css.matchAll(/border-radius:\s*([^;}\n]+)/g)) {
  rDecls.push({ value: m[1].trim(), at: m.index });
}
const rOk = v =>
  // every space-separated component (shorthand corners like
  // "0 0 var(--r-lg) var(--r-lg)") must be 0, a token, or the pill
  v.split(/\s+/).every(c =>
    c === "0" || /^var\(--r-(xs|sm|md|lg)\)$/.test(c)
    || c === "999px" || c === "50%");
const rBad = rDecls.filter(d => !rOk(d.value));
expect("C2 border-radius: every declaration is var(--r-*), 999px or 50%",
       rBad.length === 0,
       rBad.map(d => `「${d.value}」@css:${lineNo(d.at)}`).join(", "));

// ---- C3: tokens exist, scale is clean --------------------------------------
for (const t of ["--fs-xs: 11px", "--fs-sm: 12px", "--fs-md: 13px",
                 "--fs-lg: 14px", "--fs-xl: 15px", "--fs-2xl: 18px",
                 "--fs-kpi: 24px", "--ctl-h: 32px", "--ctl-h-hero: 40px",
                 "--ctl-h-chip: 28px", "--r-xs: 6px"]) {
  expect("C3 token defined: " + t, css.indexOf(t) >= 0);
}
const halfStep = fsDecls.filter(d => /\.5px/.test(d.value));
expect("C3 type scale: no .5px steps anywhere", halfStep.length === 0,
       halfStep.map(d => d.value).join(", "));

// ---- C4: control heights ----------------------------------------------------
expect("C4 button base rides --ctl-h",
       /button\s*\{[^}]*height:\s*var\(--ctl-h\)/.test(css));
expect("C4 text/number inputs ride --ctl-h",
       /input\[type=number\],\s*input\[type=text\]\s*\{[^}]*height:\s*var\(--ctl-h\)/.test(css));
expect("C4 select rides --ctl-h",
       /select\s*\{\s*height:\s*var\(--ctl-h\)/.test(css));
expect("C4 hero presets ride --ctl-h-hero",
       /\.preset-btn\s*\{[^}]*height:\s*var\(--ctl-h-hero\)/.test(css));
expect("C4 bare icon buttons opt out with height:auto",
       /\.p-reset\s*\{[^}]*height:\s*auto/.test(css)
       && /\.toast-x[^{]*\{[^}]*height:\s*auto/.test(css.replace(/\n\s*/g, " ")));

// HTML side: the transparent file-input overlay must NOT inherit control
// heights (it is absolutely positioned inset:0 — a 32px height would shrink
// the dropzone hit area). It keys on input[type=file], which none of the
// height rules select; assert that stays true structurally.
expect("C4 file-input overlay not height-locked",
       !/height:\s*var\(--ctl-h\)[^}]*/.test(
         (css.match(/\.ui-drop input\[type=file\]\s*\{[^}]*\}/) || [""])[0]));

console.log(fails === 0 ? "ui consistency check all green"
                        : fails + " FAILURES");
process.exit(fails === 0 ? 0 : 1);
