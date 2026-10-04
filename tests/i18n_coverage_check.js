// i18n coverage check: finds Chinese strings that would survive EN-mode
// translation. Mirrors the trText() pipeline in index.html (exact LANG_EN
// match, then longest-first LANG_WORDS word-level replacement) and applies it
// to every Chinese-bearing string literal / static text node / title+placeholder
// attribute. Leftovers are reported with file:line for dictionary backfill.
//
// Known limits (by construction):
// - runtime-concatenated strings are checked per-literal; novel concatenation
//   patterns are caught by the CDP browser sweep (tests/browser_en_check.js)
// - data-i18n-skip nodes (engine-authored, Chinese by design) and the
//   INTENTIONAL list below are excluded from the pass/fail count
"use strict";
var fs = require("fs");
var path = require("path");
var ROOT = path.join(__dirname, "..");

var indexHtml = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
var reportJs = fs.readFileSync(path.join(ROOT, "report.js"), "utf8");
var stlPreviewJs = fs.readFileSync(path.join(ROOT, "stl-preview.js"), "utf8");

// ---- extract dictionaries by slicing index.html and evaluating ----
function sliceBetween(src, startMarker, endMarker) {
  var a = src.indexOf(startMarker);
  if (a < 0) throw new Error("marker not found: " + startMarker);
  a += startMarker.length;
  var b = src.indexOf(endMarker, a);
  if (b < 0) throw new Error("end marker not found: " + endMarker);
  return src.slice(a, b);
}
var LANG_EN_RAW = sliceBetween(indexHtml, "var LANG_EN = {", "\n};");
var LANG_EN = eval("({" + LANG_EN_RAW + "})");
var LANG_WORDS = (function () {
  var body = sliceBetween(indexHtml, "var pairs = [", "\n  ];");
  var pairs = eval("[" + body + "]");
  return pairs.sort(function (a, b) { return b[0].length - a[0].length; });
})();

function trText(s) {
  if (Object.prototype.hasOwnProperty.call(LANG_EN, s)) return LANG_EN[s];
  var out = s;
  for (var i = 0; i < LANG_WORDS.length; i++)
    out = out.split(LANG_WORDS[i][0]).join(LANG_WORDS[i][1]);
  return out;
}
function hasZh(s) { return /[\u4e00-\u9fff]/.test(s); }

// ---- strings that stay Chinese in EN mode BY DESIGN (not failures) ----
// Each needs a reason; anything added here must be justifiable in review.
var INTENTIONAL = [
  // lang-toggle self-labels: the button always shows the language it can
  // switch TO ("中" while in EN mode) — translating it would defeat it
  "中",
  "切换到中文（界面文案；引擎输出保持中文）",
  // applyAuto writes the prefix; the assembled node ("实时分析：开/关") is
  // covered by full-string word entries — the bare prefix never renders alone
  "实时分析：",
  // rendered inside data-i18n-skip nodes (engine-authored override/rheology
  // disclosure — UI label prefixes on skip-flagged items stay zh by design)
  "参数回退: ", " 请求 ", " → 实际 ",
  "层间键合: ", "转角: ", "流变: ", "（质量 "
];

// ---- collect candidates: {file, line, text, kind} ----
var candidates = [];
function push(file, line, text, kind) {
  if (hasZh(text)) candidates.push({ file: file, line: line, text: text, kind: kind });
}

// JS string literals (double/single/backtick), line-tracked. Comments are
// stripped first (quote-parity guard: a "//" inside a string literal has an
// odd number of unescaped quotes before it on that line — e.g. URLs).
function stripJsComments(src) {
  src = src.replace(/\/\*[\s\S]*?\*\//g, function (m) {
    var q = (m.match(/"/g) || []).length;
    return q % 2 ? m : m.replace(/[^\n]/g, " ");
  });
  return src.split("\n").map(function (ln) {
    var inStr = false;
    for (var i = 0; i < ln.length - 1; i++) {
      if (ln[i] === "\\") { i++; continue; }
      if (ln[i] === '"') inStr = !inStr;
      if (ln[i] === "/" && ln[i + 1] === "/" && !inStr) return ln.slice(0, i);
    }
    return ln;
  }).join("\n");
}
function scanJs(src, file, baseLine) {
  var re = /"((?:[^"\\\n]|\\.)*)"|'((?:[^'\\\n]|\\.)*)'|`((?:[^`\\]|\\.)*)`/g;
  var m, line = baseLine || 1, lastIdx = 0;
  while ((m = re.exec(src))) {
    for (var i = lastIdx; i < m.index; i++) if (src[i] === "\n") line++;
    lastIdx = m.index;
    var raw = m[1] !== undefined ? m[1] : m[2] !== undefined ? m[2] : m[3];
    var text;
    try { text = JSON.parse('"' + raw.replace(/\n/g, "\\n") + '"'); }
    catch (e) { text = raw; }
    push(file, line, text, "js-literal");
  }
}

// Static HTML: strip <script>/<style> blocks and comments, then text nodes +
// title/placeholder attributes. JS bodies are scanned separately.
function scanStaticHtml(src, file) {
  var stripped = src
    .replace(/<script[\s\S]*?<\/script>/g, function (m) {
      return m.replace(/[\s\S]/g, " ");
    })
    .replace(/<style[\s\S]*?<\/style>/g, function (m) {
      return m.replace(/[\s\S]/g, " ");
    })
    .replace(/<!--[\s\S]*?-->/g, function (m) {
      return m.replace(/[\s\S]/g, " ");
    });
  var tagRe = /([^<>]*)(<\/?[^>]*>)/g, m, line = 1;
  var upTo = 0;
  while ((m = tagRe.exec(stripped))) {
    for (var i = upTo; i < m.index; i++) if (stripped[i] === "\n") line++;
    upTo = m.index;
    var text = m[1].replace(/&[a-z]+;/g, " ");
    push(file, line, text.trim(), "html-text");
    var attrRe = /(title|placeholder|aria-label)="([^"]*[\u4e00-\u9fff][^"]*)"/g;
    var am;
    while ((am = attrRe.exec(m[2]))) push(file, line, am[2], "attr:" + am[1]);
  }
}

// <script> bodies of index.html, dictionary definitions excluded (they are
// the ground truth being checked against, not UI text).
function scanIndexScripts(src, file) {
  var re = /<script[^>]*>([\s\S]*?)<\/script>/g, m;
  while ((m = re.exec(src))) {
    var body = stripJsComments(m[1]
      .replace(sliceBetween(src, "var LANG_EN = {", "\n};"), '""')
      .replace(sliceBetween(src, "var pairs = [", "\n  ];"), ""));
    // line numbers: offset of the script body within the file
    var pre = src.slice(0, m.index + m[0].indexOf(m[1]));
    var baseLine = (pre.match(/\n/g) || []).length + 1;
    scanJs(body, file, baseLine);
  }
}

scanStaticHtml(indexHtml, "index.html");
scanIndexScripts(indexHtml, "index.html");
scanJs(stripJsComments(reportJs), "report.js");
scanJs(stripJsComments(stlPreviewJs), "stl-preview.js");

// ---- report leftovers ----
var misses = [];
candidates.forEach(function (c) {
  var tr = trText(c.text);
  if (hasZh(tr)) misses.push(c);
});

// dedupe identical (file, text) pairs, keep first line
var seen = Object.create(null);
var uniq = [];
misses.forEach(function (c) {
  var k = c.file + "\u0000" + c.text;
  if (seen[k]) return;
  seen[k] = 1;
  uniq.push(c);
});

// split intentional (documented design) from real failures
var failures = [], allowed = [];
uniq.forEach(function (c) {
  (INTENTIONAL.indexOf(c.text) >= 0 ? allowed : failures).push(c);
});

failures.sort(function (a, b) { return a.file.localeCompare(b.file) || a.line - b.line; });
failures.forEach(function (c) {
  console.log("[" + c.kind + "] " + c.file + ":" + c.line);
  console.log("    " + JSON.stringify(c.text));
});
console.log("\nFAIL " + failures.length +
            " (intentional-by-design " + allowed.length + ": " +
            allowed.map(function (c) { return JSON.stringify(c.text); }).join(", ") + ")");
process.exitCode = failures.length ? 1 : 0;
