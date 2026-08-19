// T57 companion (iter 68): phase_b.diagnostics three-state render in
// report.js renderReport — vm sandbox with a minimal fake DOM (the file only
// declares functions; host globals are injected per its header comment).
// Exits non-zero on failure (verify-script-exit-code pattern).
"use strict";
const fs = require("fs"), path = require("path"), vm = require("vm");

function makeEl(tag) {
  return { tagName: tag, children: [], textContent: "", _innerHTML: "",
    style: {}, dataset: {}, className: "",
    set innerHTML(v) { this._innerHTML = v; this.children = []; },
    get innerHTML() { return this._innerHTML; },
    appendChild: function (c) { this.children.push(c); return c; },
    addEventListener: function () {},
    setAttribute: function (k, v) { (this.attrs || (this.attrs = {}))[k] = v; },
    querySelectorAll: function () { return []; },
    classList: { add: function () {}, toggle: function () {}, remove: function () {} } };
}
const elements = {};
function $(id) { return elements[id] || (elements[id] = makeEl("div")); }
function textOf(node) {  // deep text incl. textContent set + appended children
  let t = node.textContent || "";
  (node.children || []).forEach(function (c) { t += textOf(c); });
  return t;
}
function boxText(id) { return elements[id] ? textOf(elements[id]) : ""; }

const ctx = {
  $: $,
  el: function (tag, cls, text) {
    const e = makeEl(tag); e.className = cls || "";
    if (text !== undefined && text !== null) e.textContent = String(text);
    return e;
  },
  num: function (v, d) { return v === null || v === undefined ? "—" : Number(v).toFixed(d); },
  numEnv: function (v, d) { return v === null || v === undefined ? "—" : Number(v).toFixed(d); },
  fmtUnit: function (v, d, u) { return v === null || v === undefined ? "—" : Number(v).toFixed(d) + " " + u; },
  LOAD_LABELS: {}, state: {}, setParamValue: function () {},
  syncEnvFromReport: function () {}, stlSetOrient: function () {},
  stlSelectOrient: function () {}, stlOrientToDir: function () {},
  stlView: { orient: null, orientSel: 0 },
  document: { createTextNode: function (t) { return { textContent: String(t) }; },
              querySelectorAll: function () { return []; } },
  Math: Math, Array: Array, Object: Object, String: String, Number: Number,
  JSON: JSON, isFinite: isFinite, isNaN: isNaN, parseFloat: parseFloat,
  console: console
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "report.js"), "utf8"), ctx);
// (iter 75) load the REAL num/numEnv/fmtUnit from index.html so the render
// test exercises the production helpers, not the stubs above
const html = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");
const hStart = html.indexOf("function num(v, d)");
const hEnd = html.indexOf("}", html.indexOf("function fmtUnit")) + 1;
if (hStart < 0 || hEnd <= hStart) {
  console.error("FATAL: num/fmtUnit helpers not found in index.html"); process.exit(1);
}
vm.runInContext(html.slice(hStart, hEnd), ctx);
if (typeof ctx.renderReport !== "function") {
  console.error("FATAL: renderReport not found"); process.exit(1);
}

const real = JSON.parse(fs.readFileSync(
  path.join(__dirname, "..", "test_data", "real3mf-results", "report.json"), "utf8"));

let fails = 0;
function expect(name, cond, detail) {
  console.log((cond ? "PASS" : "FAIL") + "  " + name + (cond ? "" : "  " + detail));
  if (!cond) fails++;
}
function rerender(d) {
  for (const k in elements) delete elements[k];
  ctx.renderReport(d, "");
}

// 1. real sample: cg converged hint + part_visibility warning surfaced
rerender(real);
expect("real: CG hint with iterations+residual",
       /CG 求解器收敛: 39 次迭代/.test(boxText("phase-b-detail"))
       && /8\.33e-5/.test(boxText("phase-b-detail")),
       boxText("phase-b-detail").slice(0, 80));
expect("real: part_visibility_warning surfaced with Phase B prefix",
       boxText("warning-list").indexOf("Phase B: 网格含 41 个几何部件") >= 0);

// 2. forged: solver did NOT converge → loud warning, no hint
const d2 = JSON.parse(JSON.stringify(real));
d2.phase_b.diagnostics.cg_converged = false;
rerender(d2);
expect("forged: 未收敛 warning rendered",
       boxText("warning-list").indexOf("线性求解器未收敛") >= 0
       && boxText("phase-b-detail").indexOf("CG 求解器收敛") < 0);

// 3. forged: diagnostics.warning string surfaced; empty string not
const d3 = JSON.parse(JSON.stringify(real));
d3.phase_b.diagnostics.warning = "extra solver caveat";
rerender(d3);
expect("forged: diagnostics.warning surfaced",
       boxText("warning-list").indexOf("Phase B: extra solver caveat") >= 0);

// 4. absent diagnostics (older engine) → no CG/diagnostics content (the
// grid-dims hint of iter 81 is diagnostics-independent and MAY be present)
const d4 = JSON.parse(JSON.stringify(real));
delete d4.phase_b.diagnostics;
rerender(d4);
expect("absent diagnostics: silent",
       boxText("phase-b-detail").indexOf("CG") < 0
       && boxText("warning-list").indexOf("Phase B:") < 0);

// 5. cg_converged non-boolean shape → falls through as not assessable
const d5 = JSON.parse(JSON.stringify(real));
d5.phase_b.diagnostics.cg_converged = "true";
rerender(d5);
expect("non-boolean cg_converged: no hint (strict === true)",
       boxText("phase-b-detail").indexOf("CG 求解器收敛") < 0);

// 6. (iter 69) recommendation priority badge + tradeoff_note surfaced
rerender(real);
expect("real: [P n] priority badge on item 0",
       boxText("rec-items").indexOf("[P2]") >= 0
       && boxText("rec-items").indexOf("[decrease] nozzle_diameter") >= 0,
       boxText("rec-items").slice(0, 120));
expect("real: tradeoff_note surfaced as 权衡",
       boxText("rec-items").indexOf("权衡: improves thin-wall manufacturability") >= 0);
// 7. support_volume_available === false → caveat row under candidates
const d7 = JSON.parse(JSON.stringify(real));
d7.support_volume_available = false;
rerender(d7);
expect("forged: support-unavailable caveat row",
       boxText("cand-body").indexOf("未计入支撑") >= 0);
rerender(real);
expect("real: no caveat when support available",
       boxText("cand-body").indexOf("未计入支撑") < 0);

// 8. (iter 70) estimate tooltip: mass / filament / solid on the volume cell
(function () {
  let title = null;
  (elements["cand-body"].children || []).forEach(function (tr) {
    (tr.children || []).forEach(function (td) {
      if (td.attrs && td.attrs.title) title = td.attrs.title;
    });
  });
  expect("real: volume cell tooltip has 材料/耗材/实体",
         title !== null && title.indexOf("材料 ") >= 0
         && title.indexOf("耗材 ") >= 0 && title.indexOf("实体 ") >= 0,
         String(title));
})();

// 9. (iter 71) SF cell provenance tooltip (raw engine sf_source)
(function () {
  let sfTitle = null;
  (elements["cand-body"].children || []).forEach(function (tr) {
    (tr.children || []).forEach(function (td) {
      if (td.attrs && td.attrs.title
          && td.attrs.title.indexOf("SF 来源") >= 0) sfTitle = td.attrs.title;
    });
  });
  expect("real: SF cell tooltip carries raw sf_source",
         sfTitle === "SF 来源: extrapolated", String(sfTitle));
})();
const d9 = JSON.parse(JSON.stringify(real));
d9.process_optimization.candidates.forEach(function (c) { c.sf_source = null; });
rerender(d9);
(function () {
  let hit = false;
  (elements["cand-body"].children || []).forEach(function (tr) {
    (tr.children || []).forEach(function (td) {
      if (td.attrs && td.attrs.title && td.attrs.title.indexOf("SF 来源") >= 0) hit = true;
    });
  });
  expect("null sf_source: no tooltip", !hit);
})();

// 10. (iter 72) yielded_elements: 0 rendered as "无屈服" info, >0 flagged
rerender(real);
expect("real: yielded_elements 0 rendered without 屈曲 flag",
       boxText("phase-c-detail").indexOf("屈服单元: 0") >= 0
       && boxText("phase-c-detail").indexOf("局部已屈服") < 0);
const d10 = JSON.parse(JSON.stringify(real));
d10.phase_c.yielded_elements = 7;
rerender(d10);
expect("forged: yielded 7 flagged 局部已屈服",
       boxText("phase-c-detail").indexOf("屈服单元: 7（局部已屈服）") >= 0);

// 11. (iter 75) real num/numEnv: non-numeric engine value renders "—",
// never "NaN" (res-sf comes from numEnv(safety_factor))
const d11 = JSON.parse(JSON.stringify(real));
d11.phase_b.safety_factor = "not-a-number";
rerender(d11);
expect("iter75: string safety_factor → —, not NaN",
       elements["res-sf"].textContent === "—",
       elements["res-sf"].textContent);
expect("iter75: real helpers still format numbers (res-overall)",
       /^\d+(\.\d+)?$/.test(elements["res-overall"].textContent),
       elements["res-overall"].textContent);

// 12. (iter 77) slenderness / target-life tooltips (probed shapes:
// buckling_slenderness 86.6 and fatigue_expected_cycles 1e5 under
// --load compression --fatigue-cycles 100000 on the beam fixture)
const d12 = JSON.parse(JSON.stringify(real));
d12.phase_d.run = true;
d12.phase_d.buckling_slenderness = 86.60254;
d12.phase_d.fatigue_expected_cycles = 100000;
rerender(d12);
expect("iter77: slenderness tooltip on res-buckling",
       elements["res-buckling"].attrs
       && elements["res-buckling"].attrs.title === "细长比 86.6",
       JSON.stringify(elements["res-buckling"].attrs));
expect("iter77: target-life tooltip on res-fatigue",
       elements["res-fatigue"].attrs
       && elements["res-fatigue"].attrs.title === "目标寿命 100000 次",
       JSON.stringify(elements["res-fatigue"].attrs));
rerender(real);
expect("iter77: no tooltips when fields null",
       !elements["res-buckling"].attrs && !elements["res-fatigue"].attrs);

// 13. (iter 81) actual grid dims rendered (real sample: 5×4×4, 150 nodes)
expect("iter81: grid dims + nodes hint",
       boxText("phase-b-detail").indexOf("网格: 5×4×4（150 节点）") >= 0,
       boxText("phase-b-detail"));

process.exit(fails ? 1 : 0);
