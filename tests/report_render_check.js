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
    // v0.9: solver split + apply CTA need DOM-ish surface below
    get childNodes() { return this.children; },
    get firstChild() { return this.children[0] || null; },
    appendChild: function (c) { this.children.push(c); return c; },
    insertBefore: function (c, ref) {
      const i = this.children.indexOf(ref);
      if (i >= 0) this.children.splice(i, 0, c); else this.children.unshift(c);
      return c;
    },
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
              querySelectorAll: function () { return []; },
              createElement: function (t) { return makeEl(t); } },
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
function rerender(d, applyable) {
  for (const k in elements) delete elements[k];
  ctx.renderReport(d, "", applyable);
}

// v0.9: solver internals moved out of phase-b-detail — shorthand targets
const B_MAIN = "phase-b-detail", B_INT = "phase-b-internals",
      C_MAIN = "phase-c-detail", C_INT = "phase-c-internals";

// 1. real sample: cg converged hint (v0.9: in the internals box) + warning
rerender(real);
expect("real: CG hint with iterations+residual",
       /CG 求解器收敛: 39 次迭代/.test(boxText(B_INT))
       && /8\.33e-5/.test(boxText(B_INT)),
       boxText(B_INT).slice(0, 80));
expect("real: part_visibility_warning surfaced with Phase B prefix",
       boxText("warning-list").indexOf("Phase B: 网格含 41 个几何部件") >= 0);
expect("real: solver internals box visible, main flow keeps Tsai-Wu only",
       elements["phase-b-solver"].style.display === ""
       && boxText(B_MAIN).indexOf("CG") < 0);

// 2. forged: solver did NOT converge → loud warning, no hint
const d2 = JSON.parse(JSON.stringify(real));
d2.phase_b.diagnostics.cg_converged = false;
rerender(d2);
expect("forged: 未收敛 warning rendered",
       boxText("warning-list").indexOf("线性求解器未收敛") >= 0
       && boxText(B_INT).indexOf("CG 求解器收敛") < 0);

// 3. forged: diagnostics.warning string surfaced; empty string not
const d3 = JSON.parse(JSON.stringify(real));
d3.phase_b.diagnostics.warning = "extra solver caveat";
rerender(d3);
expect("forged: diagnostics.warning surfaced",
       boxText("warning-list").indexOf("Phase B: extra solver caveat") >= 0);

// 4. absent diagnostics (older engine) → no CG/diagnostics content
const d4 = JSON.parse(JSON.stringify(real));
delete d4.phase_b.diagnostics;
rerender(d4);
expect("absent diagnostics: silent",
       boxText(B_INT).indexOf("CG") < 0
       && boxText("warning-list").indexOf("Phase B:") < 0);

// 5. cg_converged non-boolean shape → falls through as not assessable
const d5 = JSON.parse(JSON.stringify(real));
d5.phase_b.diagnostics.cg_converged = "true";
rerender(d5);
expect("non-boolean cg_converged: no hint (strict === true)",
       boxText(B_INT).indexOf("CG 求解器收敛") < 0);

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
       boxText(B_INT).indexOf("网格: 5×4×4（150 节点）") >= 0,
       boxText(B_INT));

// 14. (v0.8 iter 1) numEnv dual-shape contract — v2 {nominal,lo,hi} object vs
// v3 scalar + *_envelope twin. Production helpers are injected (slice above).
const ne = ctx.numEnv, fu = ctx.fmtUnit;
expect("numEnv v2 object → nominal (lo–hi)",
       ne({nominal: 6.5, lo: 5.2, hi: 7.9}, 1) === "6.5 (5.2–7.9)", ne({nominal: 6.5, lo: 5.2, hi: 7.9}, 1));
expect("numEnv v3 scalar+twin → same string",
       ne(6.5303, 1, {nominal: 6.5303, lo: 5.2, hi: 7.9}).indexOf("6.5 (5.2–7.9)") === 0,
       ne(6.5303, 1, {nominal: 6.5303, lo: 5.2, hi: 7.9}));
expect("numEnv v3 scalar without twin → bare scalar",
       ne(6.5303, 1) === "6.5", ne(6.5303, 1));
expect("numEnv null/undefined → —",
       ne(null, 1) === "—" && ne(undefined, 1, {}) === "—");
expect("numEnv unassessable envelope (null nominal) → —",
       ne({nominal: null, lo: null, hi: null}, 1) === "—");
expect("fmtUnit passes v3 twin through",
       fu(0.0122, 2, "MPa", {nominal: 0.0122, lo: 0.009, hi: 0.014}).indexOf("0.01 (0.01–0.01) MPa") === 0,
       fu(0.0122, 2, "MPa", {nominal: 0.0122, lo: 0.009, hi: 0.014}));

// 15. (v0.8 iter 1) the REAL v3 fixture renders end-to-end: scalar SF into
// res-sf (band via twin), no NaN anywhere, layer height from input echo
const real3 = JSON.parse(fs.readFileSync(
  path.join(__dirname, "..", "test_data", "real3mf-results", "report-v3.json"), "utf8"));
rerender(real3);
expect("v3 fixture: res-sf renders band from envelope twin",
       /\(\d/.test(elements["res-sf"].textContent),
       elements["res-sf"].textContent);
expect("v3 fixture: no NaN in any rendered value",
       ["res-sf", "res-stress", "res-overall", "cp-lh"].every(
         function (id) { return String(boxText(id)).indexOf("NaN") < 0; }),
       ["res-sf", "res-stress", "res-overall", "cp-lh"].map(
         function (id) { return String(boxText(id)); }).join(" | "));
expect("v3 fixture: cp-lh from input.layer_height_mm",
       elements["cp-lh"].textContent.indexOf("0.2 mm") >= 0,
       elements["cp-lh"].textContent);

// 16. (v0.8.1 render-gap batch) fields the engine already disclosed that the
// UI never consumed. Shapes below are REAL engine values probed 2026-08-29
// on 0.24.0 (beam_100x10x4.3mf, full-flag + --phase-c/d runs) — only the
// container report is synthetic.
const d16 = JSON.parse(JSON.stringify(real3));
d16.input.fast_mode = true;
d16.input.filament_slots = [
  {slot: 1, filament_type: "PLA", diameter_mm: 1.75},
  {slot: 2, filament_type: "PETG", diameter_mm: 1.75}];
d16.input.analysis_material_note =
  "analysis runs at the slot-1 material; per-part material assignment is not supported (A-3 v1 disclosure)";
d16.input_overrides = [
  {parameter: "material", requested: "NYLON", effective: "PLA",
   reason: "unrecognized"}];
d16.printability = {overhang_pct: 12.5, overhang_area_mm2: 360.0,
                    bridge_area_mm2: 40.0, surface_area_mm2: 2880.0,
                    bed_contact_area_mm2: 1000.0};
d16.phase_b.resolution_adequacy = {assessed: true, eta_rms_mpa: 0.01037,
                                   eta_max_mpa: 0.02527, rel_index: 0.2205};
d16.phase_b.tsai_wu_safety_factor = 17.59296;
d16.phase_b.mesh_quality = {element_shape: "uniform_cubic_voxel",
                            scaled_jacobian: 1.0, aspect_ratio: 1.0,
                            by_construction: true};
d16.phase_b.diagnostics.preconditioner = "ic0";
d16.phase_b.diagnostics.precond_fallback_count = 0;
d16.phase_c.thermal_speed = {assessable: true, t_sub_current_c: 125.596,
                             cap_c: 62.0, overheated: true,
                             suggested_speed_mms: 16.49,
                             suggested_layer_time_s: 21.83, tier: "Gap",
                             rationale: "PLA: T_sub(8s)=125.6°C > Tg 62°C"};
d16.phase_c.weld_infill_aware = {a_eff: 0.036042, bond_quality_eff: 0.036042,
                                 disclosure: "non-decision-grade"};
d16.phase_d.run = true;
d16.phase_d.skipped_reasons = [
  "Findley 1959 method classical; no published FDM PLA Findley calibration"];
d16.phase_d.fatigue_life_cycles = 1e9;
d16.phase_d.fatigue_damage_per_cycle = 1e-9;
d16.phase_d.weibull_ran = true;
d16.phase_d.weibull_R = 1.0;
d16.phase_d.weibull_Pf = 0.0;
d16.phase_d.weibull_size_factor = 1.0;
d16.phase_d.weibull_sigma_eff_mpa = 45.2958;
rerender(d16);
expect("v0.8.1: fast-mode tag visible on fast_mode:true",
       elements["fast-mode-tag"].style.display === "");
expect("v0.8.1: filament slots + engine note verbatim",
       boxText("cp-filament-note").indexOf("#1 PLA，#2 PETG") >= 0 &&
       boxText("cp-filament-note").indexOf("slot-1 material") >= 0,
       boxText("cp-filament-note"));
expect("v0.8.1: input_overrides rendered with requested/effective/reason",
       boxText("warning-list").indexOf("参数回退: material 请求 NYLON → 实际 PLA（unrecognized）") >= 0,
       boxText("warning-list"));
expect("v0.8.1: printability line values",
       boxText("printability-line").indexOf("悬垂") >= 0 &&
       boxText("printability-line").indexOf("12.5%") >= 0 &&
       boxText("printability-line").indexOf("底面接触") >= 0 &&
       boxText("printability-line").indexOf("1000 mm²") >= 0,
       boxText("printability-line"));
expect("v0.8.1: ZZ-SPR / mesh quality / precond hints (internals box); Tsai-Wu stays main",
       boxText(B_INT).indexOf("离散误差 (ZZ-SPR)") >= 0 &&
       boxText(B_INT).indexOf("22.1%") >= 0 &&
       boxText(B_INT).indexOf("uniform_cubic_voxel") >= 0 &&
       boxText(B_INT).indexOf("预条件子: ic0") >= 0 &&
       boxText(B_MAIN).indexOf("Tsai-Wu SF: 17.6") >= 0,
       boxText(B_INT) + " || " + boxText(B_MAIN));
expect("v0.8.1: thermal-speed loop overheated line + rationale verbatim",
       boxText("phase-c-detail").indexOf("热-速闭环: 基板温 125.6°C / 上限 62.0°C — 超温，建议速度 16.5 mm/s") >= 0 &&
       boxText("phase-c-detail").indexOf("PLA: T_sub(8s)=125.6°C > Tg 62°C") >= 0,
       boxText("phase-c-detail"));
expect("v0.8.1: weld_infill_aware with disclosure verbatim (internals box)",
       boxText(C_INT).indexOf("有效键合(含填充): a_eff 0.0360") >= 0 &&
       boxText(C_INT).indexOf("non-decision-grade") >= 0);
expect("v0.8.1: skipped reason / fatigue life / Weibull numbers",
       boxText("phase-d-detail").indexOf("跳过: Findley") >= 0 &&
       boxText("phase-d-detail").indexOf("疲劳寿命估算: 1.00e+9 次") >= 0 &&
       boxText("phase-d-detail").indexOf("Weibull: R 100.0% / Pf 0.0%") >= 0 &&
       boxText("phase-d-detail").indexOf("σ_eff 45.3 MPa") >= 0,
       boxText("phase-d-detail"));

// 17. absent-vs-present discipline. The v3 fixture is a REAL 0.24 report and
// DOES carry printability / resolution_adequacy / mesh_quality / precond /
// thermal_speed / weibull_ran — so first assert those render from real data
// alone, then that the truly-absent ones (fast_mode, filament_slots) stay
// hidden (absent-not-null).
rerender(real3);
expect("v0.8.1: real fixture itself renders printability/thermal/precond",
       boxText("printability-line").indexOf("2880 mm²") >= 0 &&
       boxText(B_INT).indexOf("预条件子: ic0") >= 0 &&
       boxText(B_INT).indexOf("ZZ-SPR") >= 0 &&
       boxText(C_MAIN).indexOf("热-速闭环: 基板温 125.6°C") >= 0,
       boxText("printability-line") + " || " + boxText(B_INT) +
       " || " + boxText(C_MAIN));
expect("v0.8.1: absent fast_mode/filament_slots stay hidden",
       elements["fast-mode-tag"].style.display === "none" &&
       elements["cp-filament-note"].style.display === "none");

// 18. rec confidence + est fields; candidate provenance tooltip
const d18 = JSON.parse(JSON.stringify(real3));
d18.recommendations.items = [{
  action: "decrease", parameter: "nozzle_diameter", priority: 2,
  reason: "fine nozzle reduces stress concentration",
  confidence: 0.65, est_safety_factor: 6.5, est_max_stress: 0.091 }];
d18.process_optimization.candidates = [{
  name: "safe", goal: "strength", feasible: true, note: "",
  calibrated: false, policy_applied: false,
  verification_dimensions: ["sf", "stress"],
  estimate: {assessable: true, calibrated: true}}];
rerender(d18);
expect("v0.8.1: rec confidence % + est SF/stress line",
       boxText("rec-items").indexOf("置信度 65%") >= 0 &&
       boxText("rec-items").indexOf("SF 6.5") >= 0 &&
       boxText("rec-items").indexOf("0.091 MPa") >= 0,
       boxText("rec-items"));
(function () {
  let title = null;
  (elements["cand-body"].children || []).forEach(function (tr) {
    (tr.children || []).forEach(function (td) {
      if (td.attrs && td.attrs.title && td.attrs.title.indexOf("已校准") >= 0)
        title = td.attrs.title;
    });
  });
  expect("v0.8.1: candidate provenance tooltip (calibrated/policy/verif)",
         title === "已校准估算（cal-time/mass） · 未应用策略 · 验证维: sf/stress",
         String(title));
})();

// 19. machine-limits: unknown layer band (0/0) hidden, not "0–0 mm"
const d19 = JSON.parse(JSON.stringify(real3));
d19.machine_limits = {identified: "X1C", source: "cli", max_speed_mm_s: 200,
                      min_layer_mm: 0, max_layer_mm: 0, clamps: []};
rerender(d19);
expect("v0.8.1: unknown layer band hidden (0/0), max speed kept",
       boxText("machine-limits-detail").indexOf("0–0 mm") < 0 &&
       boxText("machine-limits-detail").indexOf("200 mm/s") >= 0,
       boxText("machine-limits-detail"));

// 20. (v0.8.1) --appearance / --rheology blocks. Shapes are the REAL engine
// output probed 2026-08-29 on 0.24.0 (beam 3MF, bed-heat path).
const d20 = JSON.parse(JSON.stringify(real3));
d20.appearance = {
  crystallinity_pct: null,
  gloss_assessment: "N/A — 未运行退火结晶度评估(anneal_hours=0 或非 PLA)，光泽不可观测",
  shear_rate_1_s: 573, apparent_viscosity_Pas: 1898, sharkskin_risk: false,
  viscosity_calibrated: true, die_swell_calibrated: true,
  temperature_corrected: false,
  texture_assessment: "良好 — 低剪切，挤出纹理均匀",
  layer_diffusion_quality: 1,
  layer_line_assessment: "极淡 — 层间扩散近完全，层纹几乎不可见",
  stair_stepping_area_pct: 7.25,
  stair_step_assessment: "可见 — 中等台阶纹",
  max_residual_stress_mpa: 0.55932, residual_stress_assessable: true,
  surface_warp_assessment: "低 — 残余应力(0MPa) 不足以产生可见表面变形",
  suggestions: ["降低层高或使用 3D 拐角过渡以减少台阶纹"]};
d20.rheology = {
  shear_rate_1_s: 573, apparent_viscosity_Pas: 1898,
  pressure_drop_MPa: 8.699, is_stable: true, die_swell_ratio: 1.08,
  die_swell_calibrated: true, viscosity_calibrated: true,
  temperature_corrected: false, calibrated_at_c: 210,
  warning: "示例警示",
  weld_bond_assessment: "层间粘接优秀(100%)，t_weld=23.3s, t_rep=0.009s",
  weld_bond_quality: 1, weld_bsf_saturated: true,
  corner_assessment: "转角质量良好"};
rerender(d20);
expect("v0.8.1: appearance box renders engine assessments verbatim",
       boxText("appearance-detail").indexOf("低剪切，挤出纹理均匀") >= 0 &&
       boxText("appearance-detail").indexOf("台阶纹占比: 7.3%") >= 0 &&
       boxText("appearance-detail").indexOf("最大残余应力: 0.559 MPa") >= 0 &&
       boxText("appearance-detail").indexOf("鲨鱼皮") < 0,
       boxText("appearance-detail"));
expect("v0.8.1: appearance suggestions rendered",
       boxText("appearance-detail").indexOf("建议: 降低层高") >= 0);
expect("v0.8.1: rheology box renders kv + weld bond + warning",
       boxText("rheology-detail").indexOf("8.70 MPa") >= 0 &&
       boxText("rheology-detail").indexOf("层间粘接优秀") >= 0 &&
       boxText("rheology-detail").indexOf("BSF 已饱和") >= 0 &&
       boxText("rheology-detail").indexOf("流变: 示例警示") >= 0,
       boxText("rheology-detail"));
const d20b = JSON.parse(JSON.stringify(d20));
d20b.rheology.is_stable = false;
d20b.rheology.viscosity_calibrated = false;
rerender(d20b);
expect("v0.8.1: rheology unstable + uncalibrated surfaced",
       boxText("rheology-detail").indexOf("不稳定") >= 0 &&
       boxText("rheology-detail").indexOf("黏度未标定") >= 0);

// 21. absent appearance/rheology → boxes hidden (flag not passed)
rerender(real3);
expect("v0.8.1: appearance/rheology boxes hidden when blocks absent",
       elements["appearance-box"].style.display === "none" &&
       elements["rheology-box"].style.display === "none");

// 22. (v0.8.1) --est-error-profile table + --resolution-check hints. Shapes
// are the REAL engine output probed 2026-08-29 on 0.24.0 (beam fixture).
const d22 = JSON.parse(JSON.stringify(real3));
d22.est_error_profile = {
  ran: true,
  rows: [
    {dim: "walls", group: "elastic", est_ratio: 1.3, real_ratio: 1.098502,
     err: 1.18343},
    {dim: "speed x2", group: "process", est_ratio: 1.42, real_ratio: -1,
     err: 1.42}],
  process_dims_note: "speed/layer_height are rerun-blind (never enter the elastic solver)"};
d22.phase_b.resolution_check = {
  coarse_grid: 16, fine_grid: 32, capped: false, fine_converged: true,
  disp_delta_pct: 72.33, stress_delta_pct: 40.89,
  zz_rel_coarse: 0.2047, zz_rel_fine: 0.1976};
rerender(d22);
expect("v0.8.1: est-error table rows + group column + engine note",
       boxText("esterr-detail").indexOf("walls") >= 0 &&
       boxText("esterr-detail").indexOf("1.183") >= 0 &&
       boxText("esterr-detail").indexOf("elastic") >= 0 &&
       boxText("esterr-detail").indexOf("process") >= 0 &&
       boxText("esterr-detail").indexOf("rerun-blind") >= 0,
       boxText("esterr-detail"));
expect("v0.8.1: est-error process row keeps -1 sentinel honest as —",
       boxText("esterr-detail").indexOf("—") >= 0);
expect("v0.8.1: resolution-check hints verbatim deltas (internals box)",
       boxText(B_INT).indexOf("分辨率校验: 16→32 网格，位移 Δ72.3% / 应力 Δ40.9%（细网格收敛）") >= 0 &&
       boxText(B_INT).indexOf("粗 0.205 / 细 0.198") >= 0,
       boxText(B_INT));
const d22b = JSON.parse(JSON.stringify(d22));
d22b.phase_b.resolution_check.capped = true;
d22b.phase_b.resolution_check.fine_converged = false;
rerender(d22b);
expect("v0.8.1: resolution-check capped + not-converged surfaced",
       boxText(B_INT).indexOf("已封顶 128") >= 0 &&
       boxText(B_INT).indexOf("细网格未收敛") >= 0);
rerender(real3);
expect("v0.8.1: esterr box hidden when block absent",
       elements["esterr-box"].style.display === "none");

// 23. (v0.8.1) calibration block (--cal-time/--cal-mass). Values are the
// REAL engine output probed 2026-08-29 on 0.24.0 (beam 3MF + --compare-
// profiles --cal-time 1200 --cal-mass 15.5: applied=true, factors
// 0.505912/0.836601, predicted 2371.96 s / 18.53 g).
const d23 = JSON.parse(JSON.stringify(real3));
d23.calibration = {
  applied: true, time_factor: 0.505912, mass_factor: 0.836601,
  measured_time_s: 1200.0, measured_mass_g: 15.5,
  predicted_time_s: 2371.95579, predicted_mass_g: 18.527344,
  notes: ["absolute-only: scores/ranking/tier unchanged",
          "single-point baseline calibration"]};
rerender(d23);
expect("v0.8.1: calibration applied block renders factors + measured",
       boxText("calibration-detail").indexOf("已应用") >= 0 &&
       boxText("calibration-detail").indexOf("0.5059") >= 0 &&
       boxText("calibration-detail").indexOf("1200 s") >= 0 &&
       boxText("calibration-detail").indexOf("18.5 g") >= 0,
       boxText("calibration-detail"));
const d23b = JSON.parse(JSON.stringify(real3));
d23b.calibration = {applied: false, time_factor: 1, mass_factor: 1,
                    reason: "estimator did not run (--optimize/--compare-profiles/Phase C required)",
                    notes: []};
rerender(d23b);
expect("v0.8.1: calibration not-applied carries reason verbatim",
       boxText("calibration-detail").indexOf("未应用") >= 0 &&
       boxText("calibration-detail").indexOf("estimator did not run") >= 0);
rerender(real3);
expect("v0.8.1: calibration box hidden when block absent",
       elements["calibration-box"].style.display === "none");

// 24. (v0.9) verdict-first split visibility + engine assessment line +
// applyable checkboxes/CTA. The v1 identity whitelist lives server-side
// (smoke T-numbers pin it against the real engine); here we pin the RENDER
// contract only: applyable[i] pairs with items[i], applicable → checkbox,
// applicable:false → reason text, no applyable → plain text (old callers).
//
// 24a. real v3 fixture carries phase_b.assessment → verdict line verbatim;
// solver boxes visible (both fixtures carry internals data)
rerender(real3);
expect("v0.9: phase_b assessment verdict line verbatim",
       boxText("phase-b-assessment").indexOf("结论: ✅ 安全 — 结构强度充足") >= 0,
       boxText("phase-b-assessment"));
expect("v0.9: phase-b/c internals boxes visible on real data " +
       "(v3 fixture: grid/precond + yield-idx/weld are all present)",
       elements["phase-b-solver"].style.display === "" &&
       elements["phase-c-solver"].style.display === "" &&
       boxText(C_INT).indexOf("Hill48 屈服指数: 0.0000") >= 0,
       boxText(C_INT));
expect("v0.9: Hill48 yield index split out of the main SF line",
       boxText(C_MAIN).indexOf("Hill48 SF:") >= 0 &&
       boxText(C_MAIN).indexOf("屈服指数") < 0,
       boxText(C_MAIN).slice(0, 120));
// 24b. absent assessment + empty internals → hidden boxes (absent-not-null,
// per-frame reverse reset: a previous render's content must not leak)
const d24 = JSON.parse(JSON.stringify(real3));
delete d24.phase_b.assessment;
delete d24.phase_b.diagnostics;
delete d24.phase_b.grid;
delete d24.phase_b.resolution_adequacy;
delete d24.phase_b.mesh_quality;
d24.phase_c.max_hill48_yield_index = null;
d24.phase_c.abs_wlf_shift_factor = null;
d24.phase_c.crystallinity_modulus_factor = null;
d24.phase_c.weld_infill_aware = null;
rerender(d24);
expect("v0.9: assessment absent → hidden",
       elements["phase-b-assessment"].style.display === "none");
expect("v0.9: internals emptied → both solver boxes reset to hidden",
       elements["phase-b-solver"].style.display === "none" &&
       elements["phase-c-solver"].style.display === "none");
// 24c. applyable render contract: multi-item applicable list → CTA with
// count + checked checkboxes paired by index. The v3 fixture carries a
// single item, so forge a 3-item rec list shaped like the real v2 sample
// (identity keys — render contract only; server pairing is smoke's scope).
const d24c = JSON.parse(JSON.stringify(real3));
d24c.recommendations.items = [
  {action: "decrease", parameter: "nozzle_diameter", priority: 2,
   reason: "thin-wall risk; nozzle is too large",
   current_value: 0.4, recommended_value: 0.2,
   confidence: 0.7, est_safety_factor: null, est_max_stress: null},
  {action: "decrease", parameter: "print_speed", priority: 2,
   reason: "slow down for thin-wall extrusion accuracy",
   current_value: 60, recommended_value: 36,
   confidence: 0.7, est_safety_factor: null, est_max_stress: null},
  {action: "decrease", parameter: "cooling_fan", priority: 2,
   reason: "reduce fan to lower shrinkage gradients",
   current_value: 100, recommended_value: 60,
   confidence: 0.65, est_safety_factor: null, est_max_stress: null}];
const app24 = d24c.recommendations.items.map(function (it) {
  return {parameter: it.parameter, action: it.action,
          current_value: it.current_value,
          recommended_value: it.recommended_value,
          priority: it.priority, applicable: true, reason: "",
          ui_key: it.parameter};
});
rerender(d24c, app24);
expect("v0.9: CTA rendered with count",
       boxText("rec-items").indexOf("应用勾选建议 (3)") >= 0,
       boxText("rec-items").slice(0, 80));
(function () {
  // checkboxes live inside the per-item divs — walk recursively
  const found = [];
  (function walk(n) {
    (n.children || []).forEach(function (c) {
      if (c.tagName === "input") found.push(c); else walk(c);
    });
  })(elements["rec-items"]);
  expect("v0.9: 3 checked checkboxes paired by index",
         found.length === 3 &&
         found.every(function (c) { return c.checked === true; }) &&
         found.map(function (c) { return c.attrs["data-apply-idx"]; }).join(",")
           === "0,1,2",
         JSON.stringify(found.map(function (c) { return c.attrs; })));
})();
// 24d. applicable:false → inline reason, not a checkbox; CTA counts only
// applicable items
const app24b = JSON.parse(JSON.stringify(app24));
app24b[0].applicable = false;
app24b[0].reason = "参数不可一键应用（UI 无对应数值滑杆）";
app24b[1].applicable = false;
app24b[1].reason = "已等于当前值";
rerender(d24c, app24b);
expect("v0.9: non-applicable reason shown inline, no checkbox",
       boxText("rec-items").indexOf("不可一键应用: 参数不可一键应用") >= 0 &&
       boxText("rec-items").indexOf("不可一键应用: 已等于当前值") >= 0);
expect("v0.9: CTA counts only applicable items",
       boxText("rec-items").indexOf("应用勾选建议 (1)") >= 0);
// 24e. no applyable argument (old callers / fixture renders) → exactly the
// v0.8 text-only render, no CTA, no checkboxes
rerender(d24c);
expect("v0.9: no applyable → no CTA/checkbox (backward compatible)",
       boxText("rec-items").indexOf("应用勾选建议") < 0 &&
       boxText("rec-items").indexOf("不可一键应用") < 0 &&
       boxText("rec-items").indexOf("[decrease] nozzle_diameter") >= 0);
// 24f. forged WLF sample → phase-c internals box becomes visible
const d24f = JSON.parse(JSON.stringify(real3));
d24f.phase_c.abs_wlf_shift_factor = 1.2345;
rerender(d24f);
expect("v0.9: ABS WLF rendered in internals box, box visible",
       boxText(C_INT).indexOf("ABS WLF: 移位因子 1.2345") >= 0 &&
       elements["phase-c-solver"].style.display === "",
       boxText(C_INT));
// 24g. v0.9.1 engine alignment: cooling-fan suggestion + huge residual
// margin → inline hint surfaced; absent residual SF / other params → no hint
const d24g = JSON.parse(JSON.stringify(d24c));
d24g.phase_c.residual_safety_factor = 422.15918;  // real v2 sample value
rerender(d24g, app24);
expect("v0.9.1: cooling_fan hint shown when residual SF > 100",
       boxText("rec-items").indexOf("残余应力安全系数 422.2") >= 0 &&
       boxText("rec-items").indexOf("此项建议对强度的收益可能有限") >= 0,
       boxText("rec-items").slice(0, 200));
const d24g2 = JSON.parse(JSON.stringify(d24c));
rerender(d24g2, app24);  // phase_c present but residual_safety_factor null
expect("v0.9.1: no fan hint when residual SF absent",
       boxText("rec-items").indexOf("此项建议对强度的收益可能有限") < 0);
const d24g3 = JSON.parse(JSON.stringify(d24g));
d24g3.recommendations.items = [{parameter: "print_speed", action: "decrease",
                                current_value: 60, recommended_value: 36,
                                priority: 2}];
rerender(d24g3, [{parameter: "print_speed", action: "decrease",
                  current_value: 60, recommended_value: 36,
                  priority: 2, applicable: true, reason: "", ui_key: "print_speed"}]);
expect("v0.9.1: no fan hint for non-cooling_fan suggestion",
       boxText("rec-items").indexOf("此项建议对强度的收益可能有限") < 0);

// 25. (v0.10) productization render surface: verdict-first summary cards /
// SF display band / warnings card toggle / term glossary tooltips /
// candidate comparison bars / actionable error card / empty-guide lifecycle
function findTitle(node, sub) {
  if (!node) return null;
  if (node.title && String(node.title).indexOf(sub) >= 0) return node.title;
  let hit = null;
  (node.children || []).forEach(function (c) { if (!hit) hit = findTitle(c, sub); });
  return hit;
}
function findBtn(node, label) {
  let hit = null;
  (function walk(n) {
    (n.children || []).forEach(function (c) {
      if (hit) return;
      if (c.tagName === "button" && String(c.textContent).indexOf(label) >= 0) hit = c;
      else walk(c);
    });
  })(node);
  return hit;
}
function findFillWidths(node, out) {
  (function walk(n) {
    (n.children || []).forEach(function (c) {
      if (c.tagName === "i" && c.style && c.style.width) out.push(c.style.width);
      walk(c);
    });
  })(node);
  return out;
}
rerender(real3);
expect("v0.10: empty-guide hidden by a successful render",
       elements["empty-guide"] && elements["empty-guide"].style.display === "none");
expect("v0.10: three summary cards rendered (verdict/risk/advice)",
       elements["summary-cards"] &&
       elements["summary-cards"].children.length === 3,
       String(elements["summary-cards"] && elements["summary-carts"]));
expect("v0.10: verdict card carries the engine assessment verbatim",
       textOf(elements["summary-cards"].children[0]).indexOf("✅ 安全 — 结构强度充足") >= 0,
       textOf(elements["summary-cards"].children[0]));
expect("v0.10: SF KPI gets a display-band class (engine number present)",
       /^v sf-(low|mid|high)$/.test(elements["res-sf"].className),
       elements["res-sf"].className);
expect("v0.10: SF band fill rendered inside the verdict card",
       findFillWidths(elements["summary-cards"].children[0], []).some(
         function (w) { return parseInt(w, 10) > 0; }),
       String(findFillWidths(elements["summary-cards"].children[0], [])));
const d25a = JSON.parse(JSON.stringify(real3));
d25a.phase_b.safety_factor = null;
rerender(d25a);
expect("v0.10: no engine SF → no band class, no guess",
       elements["res-sf"].className === "v" &&
       findFillWidths(elements["summary-cards"].children[0], []).length === 0,
       elements["res-sf"].className);

// warnings card: badge count + user-owned open state survives re-renders
rerender(real);
expect("v0.10: warnings card shown with a numeric count",
       elements["warnings-card"].style.display === "" &&
       /^\d+$/.test(elements["warnings-count"].textContent) &&
       parseInt(elements["warnings-count"].textContent, 10) > 0,
       elements["warnings-count"].textContent);
expect("v0.10: warnings list collapsed until opened (progressive disclosure)",
       elements["warning-list"].style.display === "none");
elements["warnings-card"].dataset.open = "1";
// NOTE: no rerender() here — the vm harness recreates stub elements on
// rerender, which would drop the user-owned dataset flag. Direct call keeps
// the same stubs, matching the REAL DOM where #warnings-card persists.
ctx.renderReport(real, "");
expect("v0.10: open flag survives a re-render",
       elements["warning-list"].style.display === "");
elements["warnings-card"].dataset.open = "0";
rerender(real);
// v0.14: the summary risk card aggregates BOTH sources, severity-ranked —
// with 491 S5 geometric risks in this fixture they lead the card (warnings
// no longer crowd out harder evidence); overflow points at the two lists.
expect("v0.14: risk card aggregates risks first, severity-ranked",
       textOf(elements["summary-cards"].children[1]).indexOf("S5") >= 0 &&
       textOf(elements["summary-cards"].children[1]).indexOf("interlaminar_shear") >= 0 &&
       /还有 \d+ 条/.test(textOf(elements["summary-cards"].children[1])),
       textOf(elements["summary-cards"].children[1]).slice(0, 160));

// v0.14: the risk list collapses behind a count/max-severity toggle; the
// verdict gates the default until the user clicks (dataset.user takes over)
rerender(real3);  // 2 risks (S5/S3), assessment "✅ 安全" → collapsed
expect("v0.14: risk card toggle shows count and max severity",
       elements["risk-card"].style.display === "" &&
       elements["risk-count"].textContent === "2" &&
       elements["risk-max-sev"].textContent === "S5",
       elements["risk-count"].textContent + "/" + elements["risk-max-sev"].textContent);
expect("v0.14: ✅ verdict collapses the list by default",
       elements["risk-list"].style.display === "none" &&
       elements["risk-card"].dataset.open === "0",
       elements["risk-list"].style.display + "/" + elements["risk-card"].dataset.open);
// ⚠ verdict re-gates to expanded (same stubs — direct call, see NOTE above)
const d3warn = JSON.parse(JSON.stringify(real3));
d3warn.phase_b.assessment = "⚠️ 有风险 — 注意";
ctx.renderReport(d3warn, "");
expect("v0.14: ⚠ verdict expands the list (evidence up front)",
       elements["risk-card"].dataset.open === "1" &&
       elements["risk-list"].style.display === "",
       elements["risk-card"].dataset.open + "/" + elements["risk-list"].style.display);
// user click takes over: dataset.user freezes the choice across renders
elements["risk-card"].dataset.user = "1";
elements["risk-card"].dataset.open = "0";
ctx.renderReport(d3warn, "");
expect("v0.14: user-owned open flag survives re-render",
       elements["risk-card"].dataset.open === "0" &&
       elements["risk-list"].style.display === "none",
       elements["risk-card"].dataset.open);
// severity verbatim: engine S5 stays S5 in the list (old clamp showed S3)
rerender(real);
const firstBadge = elements["risk-list"].children[0].children[0];
expect("v0.14: severity 1..5 shown verbatim (S5 not clamped to S3)",
       firstBadge.textContent === "S5",
       firstBadge.textContent);
// risks empty → toggle card hidden; warnings still surface in the summary
// (warning-list collects phase_b.diagnostics fields: cg/part_visibility/
// warning — buckling lives in phase-d detail and is NOT a summary source)
const d3norisk = JSON.parse(JSON.stringify(real3));
d3norisk.phase_a.risks = [];
d3norisk.phase_b.diagnostics = d3norisk.phase_b.diagnostics || {};
d3norisk.phase_b.diagnostics.warning = "测试提示行: 网格分辨率不足";
rerender(d3norisk);
expect("v0.14: no risks → toggle card hidden",
       elements["risk-card"].style.display === "none",
       elements["risk-card"].style.display);
expect("v0.14: no risks → warnings still lead the summary card",
       textOf(elements["summary-cards"].children[1]).indexOf("测试提示行") >= 0,
       textOf(elements["summary-cards"].children[1]).slice(0, 120));
// both sources empty → explicit all-clear (previously "无警告。" ignored risks)
d3norisk.phase_b.diagnostics.warning = null;
rerender(d3norisk);
expect("v0.14: both sources empty → 无风险",
       textOf(elements["summary-cards"].children[1]).indexOf("无风险") >= 0,
       textOf(elements["summary-cards"].children[1]));

// advice card: applyable CTA front and center + appendix-C grid action
rerender(d24c, app24);
expect("v0.10: advice card CTA with count",
       textOf(elements["summary-cards"].children[2]).indexOf("应用可行建议 (3)") >= 0,
       textOf(elements["summary-cards"].children[2]).slice(0, 120));
const sumCta = findBtn(elements["summary-cards"], "应用可行建议");
expect("v0.10: summary CTA wired to applyCheckedSuggestions",
       !!sumCta && typeof sumCta.onclick === "function");
rerender(real);
const gridBtn = findBtn(elements["summary-cards"], "提高网格精度");
expect("v0.10: part_visibility_warning → grid-precision action button",
       textOf(elements["summary-cards"].children[2]).indexOf("网格分辨率不足") >= 0 &&
       !!gridBtn && typeof gridBtn.onclick === "function",
       textOf(elements["summary-cards"].children[2]).slice(0, 160));

// term glossary hover tooltips (≥6 core terms across static + dynamic rows)
rerender(real3);
expect("v0.10: Hill48 hint carries the anisotropy glossary",
       findTitle(elements["phase-c-detail"], "各向异性") !== null);
const d25t = JSON.parse(JSON.stringify(real3));
d25t.phase_c.run = true;
d25t.phase_c.max_delamination_risk = 0.000123;
d25t.phase_c.hill48_safety_factor = 2.5;
d25t.phase_d.weibull_ran = true;
rerender(d25t);
expect("v0.10: delamination hint carries the interlaminar glossary",
       findTitle(elements["phase-c-detail"], "层间强度") !== null);
expect("v0.10: phase-d Weibull row carries the reliability glossary",
       findTitle(elements["phase-d-detail"], "缺陷分布") !== null);

// candidate comparison bars: relative CSS widths, feasible rows only
const d25b = JSON.parse(JSON.stringify(real3));
d25b.process_optimization.candidates = [
  {name: "alpha", goal: "strength", feasible: true, scores: {},
   search_est_safety_factor: 8,
   estimate: {print_time_min: 100, material_volume_mm3: 10000}},
  {name: "beta", goal: "speed", feasible: true, scores: {},
   search_est_safety_factor: 4,
   estimate: {print_time_min: 50, material_volume_mm3: 6000}},
  {name: "nofeas", goal: "speed", feasible: false, scores: {}}];
rerender(d25b);
expect("v0.10: cand bars render feasible candidates only",
       boxText("cand-bars").indexOf("alpha") >= 0 &&
       boxText("cand-bars").indexOf("beta") >= 0 &&
       boxText("cand-bars").indexOf("nofeas") < 0,
       boxText("cand-bars").slice(0, 120));
const widths = findFillWidths(elements["cand-bars"], []).map(
  function (w) { return Math.round(parseFloat(w)); });
expect("v0.10: bar widths normalized against the in-set max (100/50)",
       widths.indexOf(100) >= 0 && widths.indexOf(50) >= 0,
       JSON.stringify(widths));
rerender(real);
expect("v0.10: cand bars skip sets without ≥2 FEASIBLE rows",
       elements["cand-bars"].children.length === 0 ||
       boxText("cand-bars").indexOf("nofeas") < 0);

// actionable error card (1.4): verbatim error + next-step buttons
ctx.renderAnalyzeError({status: "validation_refused",
                        error: "输入拓扑校验拒绝（--validate strict）：网格含 41 个几何部件"});
expect("v0.10: error card shows the verbatim engine error",
       elements["analyze-error"].style.display === "block" &&
       boxText("analyze-error").indexOf("输入拓扑校验拒绝") >= 0,
       boxText("analyze-error").slice(0, 120));
const tierBtn = findBtn(elements["analyze-error"], "校验档位");
const gridErrBtn = findBtn(elements["analyze-error"], "提高网格精度");
expect("v0.10: refusal error carries standard-tier rerun button",
       !!tierBtn && typeof tierBtn.onclick === "function");
expect("v0.10: grid/multi-part error carries grid-×2 rerun button",
       !!gridErrBtn && typeof gridErrBtn.onclick === "function");
rerender(real3);
expect("v0.10: a successful render clears the error card",
       elements["analyze-error"].style.display === "none" &&
       elements["analyze-error"].children.length === 0);
ctx.renderAnalyzeError(null);
expect("v0.10: null payload → card hidden, no throw",
       elements["analyze-error"].style.display === "none");

// v0.16 (engine 0.26) suggestion channel: motivation badges + suppressions.
// The real fixtures predate 0.26 (no motivation key, no suppressions key),
// so positive paths run on inline fixtures; the negative path doubles as
// the real-engine smoke contract (beam probe on 0.26.0: schema 3, both
// keys absent, renderer must stay silent).
const d26 = JSON.parse(JSON.stringify(real3));
d26.recommendations.items = [
  {action: "increase", parameter: "walls", priority: 1,
   motivation: "layer_bond", current_value: 2, recommended_value: 4,
   reason: "bond-critical"},
  {action: "decrease", parameter: "print_speed", priority: 2,
   motivation: "future_token_zzz", current_value: 60, recommended_value: 40,
   reason: "forward-compat probe"},
  {action: "decrease", parameter: "cooling_fan", priority: 2,
   motivation: null, current_value: 100, recommended_value: 60,
   reason: "unclassified"},
];
d26.recommendations.suppressions = [
  {parameter: "walls", reason_code: "solid_part_uniform_scaling",
   detail: "voxel 6.2mm ≥ min wall 4mm"},
  {parameter: "nozzle_diameter",
   reason_code: "machine_nozzle_variant_unavailable", detail: null},
  {parameter: "infill", reason_code: "brand_new_code_2100", detail: "x"},
];
rerender(d26);
function motBadges() {
  const out = [];
  (elements["rec-items"].children || []).forEach(function (li) {
    (li.children || []).forEach(function (c) {
      if (String(c.className).indexOf("mot-badge") >= 0) out.push(c);
    });
  });
  return out;
}
const badges = motBadges();
expect("v0.16: known motivation token renders its zh label badge",
       badges.length >= 1 && textOf(badges[0]) === "层间键合",
       badges.map(textOf).join("|"));
expect("v0.16: unknown motivation token renders RAW (forward compat)",
       badges.length >= 2 && textOf(badges[1]) === "future_token_zzz",
       badges.map(textOf).join("|"));
expect("v0.16: badge title carries the raw engine token",
       badges[0].attrs && badges[0].attrs.title === "建议动机: layer_bond",
       String(badges[0].attrs && badges[0].attrs.title));
expect("v0.16: null motivation → no badge on that item",
       badges.length === 2, "badge count " + badges.length);
const recTxt26 = boxText("rec-items");
expect("v0.16: solid_part suppression discloses the --grid ungate hint",
       recTxt26.indexOf("walls") >= 0 &&
       recTxt26.indexOf("建议被闸") >= 0 &&
       recTxt26.indexOf("提高网格精度（--grid）") >= 0,
       recTxt26.slice(0, 200));
expect("v0.16: nozzle-variant suppression renders its own reason",
       recTxt26.indexOf("nozzle_diameter") >= 0 &&
       recTxt26.indexOf("机型无该喷嘴变体") >= 0,
       recTxt26.slice(0, 200));
expect("v0.16: unknown reason_code renders raw (forward compat)",
       recTxt26.indexOf("brand_new_code_2100") >= 0,
       recTxt26.slice(0, 200));
expect("v0.16: engine detail string rendered verbatim",
       recTxt26.indexOf("voxel 6.2mm ≥ min wall 4mm") >= 0,
       recTxt26.slice(0, 200));
// negative: key absent / empty array → nothing rendered
rerender(real3);
expect("v0.16: suppressions key ABSENT → no suppression line",
       boxText("rec-items").indexOf("建议被闸") < 0);
expect("v0.16: pre-0.26 items (no motivation key) → zero badges",
       motBadges().length === 0);
const d26e = JSON.parse(JSON.stringify(d26));
d26e.recommendations.suppressions = [];
rerender(d26e);
expect("v0.16: EMPTY suppressions array → still nothing rendered",
       boxText("rec-items").indexOf("建议被闸") < 0);

// v0.16 HTML snapshot builder: pure string assembly extracted from
// index.html (same source-slicing pattern as num/fmtUnit above). The DOM
// clone/sanitize side runs for real in browser_render_check.js.
const snapStart = html.indexOf("function snapEsc(s)");
// end marker must be the WIRING (not the earlier $("btn-snapshot").disabled
// reset in the upload path, which sorts before the helper definitions)
const snapEnd = html.indexOf('$("btn-snapshot").addEventListener');
if (snapStart < 0 || snapEnd <= snapStart) {
  console.error("FATAL: snapshot helpers not found in index.html"); process.exit(1);
}
vm.runInContext(html.slice(snapStart, snapEnd), ctx);
const snap = ctx.buildSnapshotDoc('<div id="x">结果内容</div>', "body{color:red}",
  {title: "T <b> & q", heading: "报告快照", line: "beam · UI 0.16", footer: "foot note"});
expect("v0.16: snapshot doc is a standalone html5 document",
       snap.indexOf("<!DOCTYPE html>") === 0 && snap.indexOf('<meta charset="utf-8">') >= 0,
       snap.slice(0, 60));
expect("v0.16: snapshot inlines the stylesheet",
       snap.indexOf("<style>") >= 0
       && snap.indexOf("body{color:red}") > snap.indexOf("<style>"),
       "");
expect("v0.16: snapshot carries zero scripts / external refs",
       snap.indexOf("<script") < 0 && !/\s(src|href)=/.test(snap),
       "");
expect("v0.16: snapshot header/footer/meta rendered, title HTML-escaped",
       snap.indexOf("&lt;b&gt;") >= 0 && snap.indexOf("<b>") < 0
       && snap.indexOf("报告快照") >= 0 && snap.indexOf("beam · UI 0.16") >= 0
       && snap.indexOf("foot note") >= 0 && snap.indexOf("结果内容") >= 0,
       "");

// v0.17 P1 snapshot model view: meta.view {dataUrl, caption} embeds the
// preview at the top of the doc; dataUrl=null must degrade to the caption
// line with NO <img> (honest "not captured", never a placeholder image).
const FAKE_PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg==";
const snapV = ctx.buildSnapshotDoc('<div id="x">结果内容</div>', "body{color:red}",
  {title: "t", heading: "h", line: "l", footer: "f",
   view: {dataUrl: FAKE_PNG, caption: "beam · 导出时刻视角"}});
expect("v0.17: snapshot embeds the model view img at doc top",
       snapV.indexOf('<img src="data:image/png;base64,') >= 0
       && snapV.indexOf("beam · 导出时刻视角") >= 0
       && snapV.indexOf('<img src="data:image/png;base64,') < snapV.indexOf("结果内容"),
       snapV.slice(snapV.indexOf("<body"), snapV.indexOf("<body") + 200));
expect("v0.17: model view img rendered exactly once before content",
       (snapV.match(/<img /g) || []).length === 1
       && snapV.indexOf("<img ") < snapV.indexOf("结果内容"),
       "");
const snapX = ctx.buildSnapshotDoc("<div>x</div>", "",
  {title: "t", heading: "h", line: "l", footer: "f",
   view: {dataUrl: 'data:image/png;base64,x"><script>alert(1)</script>',
          caption: "c"}});
expect("v0.17: hostile dataUrl cannot break out of the src attribute",
       snapX.indexOf('"><script>') < 0 && snapX.indexOf("<script") < 0
       && snapX.indexOf("&quot;&gt;&lt;script&gt;") >= 0,
       snapX.slice(snapX.indexOf("<img"), snapX.indexOf("<img") + 120));
const snapN = ctx.buildSnapshotDoc('<div id="x">结果内容</div>', "",
  {title: "t", heading: "h", line: "l", footer: "f",
   view: {dataUrl: null, caption: "模型预览未捕获（导出时无可用预览）"}});
expect("v0.17: null dataUrl degrades to text line, no <img>",
       snapN.indexOf("<img") < 0
       && snapN.indexOf("模型预览未捕获（导出时无可用预览）") >= 0,
       snapN.slice(snapN.indexOf("<body"), snapN.indexOf("<body") + 200));
expect("v0.17: meta without view keeps the v0.16 shape (no view block)",
       snap.indexOf("导出时刻视角") < 0 && snap.indexOf("<img") < 0,
       "");

// v0.16 run-history helpers (pure, sliced from index.html): per-run param
// diff + inline-SVG sparkline. The DOM integration side (history rows,
// #history-spark) runs for real in browser_render_check.js.
const histStart = html.indexOf("function histParamDiff(prev, cur) {");
const histEnd = html.indexOf("function refreshHistory() {");
if (histStart < 0 || histEnd <= histStart) {
  console.error("FATAL: history helpers not found in index.html"); process.exit(1);
}
vm.runInContext(html.slice(histStart, histEnd), ctx);
const pd = ctx.histParamDiff(
  {params: {walls: 2, print_speed: 60}, env: {}},
  {params: {walls: 4, print_speed: 60}, env: {}});
expect("v0.16: param diff lists changed keys, omits equal ones",
       pd.length === 1 && pd[0] === "walls 2 → 4",
       JSON.stringify(pd));
expect("v0.16: identical consecutive inputs → empty diff",
       ctx.histParamDiff({params: {walls: 2}, env: {a: 1}},
                         {params: {walls: 2}, env: {a: 1}}).length === 0);
const pd2 = ctx.histParamDiff(
  {params: {walls: 2, layer_height: 0.2}, env: {}},
  {params: {walls: 4}, env: {}});
expect("v0.16: key present on one side only renders （未设）",
       pd2.length === 2 && pd2.indexOf("layer_height 0.2 → （未设）") >= 0,
       JSON.stringify(pd2));
const sp1 = ctx.sparkSvg([1, 2, 3], "red", 200, 34);
expect("v0.16: sparkline draws an inline svg polyline",
       sp1.indexOf("<svg") === 0 && sp1.indexOf("<polyline") >= 0
       && sp1.indexOf('points="') >= 0 && (sp1.match(/,/g) || []).length >= 2,
       sp1.slice(0, 80));
expect("v0.16: sparkline flat series does not divide by zero",
       ctx.sparkSvg([3, 3, 3], "red").indexOf("<polyline") >= 0);
expect("v0.16: sparkline with <2 finite points → empty (no fake trend)",
       ctx.sparkSvg([2], "red") === "" && ctx.sparkSvg([null, null], "red") === "");
const sp2 = ctx.sparkSvg([1, null, 3], "red");
expect("v0.16: isolated point between nulls renders as a dot, not dropped",
       sp2.indexOf("<circle") >= 0 && sp2.indexOf('fill="red"') >= 0,
       sp2.slice(0, 120));

process.exit(fails ? 1 : 0);
