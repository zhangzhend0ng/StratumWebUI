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
expect("v0.22: two summary cards rendered (verdict hero / advice)",
       elements["summary-cards"] &&
       elements["summary-cards"].children.length === 2,
       String(elements["summary-cards"] && elements["summary-cards"].children.length));
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

// v0.22 merged 「风险与提示」 card: engine warnings + geometric risks behind
// ONE toggle (was: separate warnings card + risk card, plus a summary
// risk-preview card that could contradict the lists below)
rerender(real);
const wLen = elements["warning-list"].children.length;
const rLen = elements["risk-list"].children.length;
expect("v0.22: merged alerts card shows the combined count",
       elements["alerts-card"].style.display === "" &&
       parseInt(elements["alerts-count"].textContent, 10) === wLen + rLen &&
       wLen > 0 && rLen > 0,
       elements["alerts-count"].textContent + " vs " + wLen + "+" + rLen);
expect("v0.22: headline carries risk count + max severity verbatim",
       elements["alerts-headline"].textContent.indexOf("条几何风险 · 最高 S5") >= 0,
       elements["alerts-headline"].textContent);
expect("v0.22: both streams get a sub-header inside one body",
       elements["alerts-warn-h"].textContent.indexOf("引擎提示") === 0 &&
       elements["alerts-risk-h"].textContent.indexOf("几何风险") === 0,
       elements["alerts-warn-h"].textContent + " / " +
       elements["alerts-risk-h"].textContent);
// user-owned open flag survives a re-render (same stubs — direct call: the
// vm harness recreates nothing here, matching the REAL DOM where the
// wrapper persists)
elements["alerts-card"].dataset.user = "1";
elements["alerts-card"].dataset.open = "1";
ctx.renderReport(real, "");
expect("v0.22: user-owned open flag survives a re-render",
       elements["alerts-body"].style.display === "",
       elements["alerts-body"].style.display);
elements["alerts-card"].dataset.user = "";
elements["alerts-card"].dataset.open = "";

// verdict gates the merged default until the user clicks (dataset.user)
rerender(real3);  // 2 risks (S5/S3), assessment "✅ 安全" → collapsed
expect("v0.22: ✅ verdict collapses the merged body by default",
       elements["alerts-card"].style.display === "" &&
       elements["alerts-card"].dataset.open === "0" &&
       elements["alerts-body"].style.display === "none",
       elements["alerts-card"].dataset.open + "/" +
       elements["alerts-body"].style.display);
// ⚠ verdict re-gates to expanded (risks are the evidence)
const d3warn = JSON.parse(JSON.stringify(real3));
d3warn.phase_b.assessment = "⚠️ 有风险 — 注意";
ctx.renderReport(d3warn, "");
expect("v0.22: ⚠ verdict expands the merged body (evidence up front)",
       elements["alerts-card"].dataset.open === "1" &&
       elements["alerts-body"].style.display === "",
       elements["alerts-card"].dataset.open + "/" +
       elements["alerts-body"].style.display);
// user click takes over: dataset.user freezes the choice across renders
elements["alerts-card"].dataset.user = "1";
elements["alerts-card"].dataset.open = "0";
ctx.renderReport(d3warn, "");
expect("v0.22: user-owned collapsed state survives re-render",
       elements["alerts-card"].dataset.open === "0" &&
       elements["alerts-body"].style.display === "none",
       elements["alerts-card"].dataset.open);
elements["alerts-card"].dataset.user = "";
elements["alerts-card"].dataset.open = "";
// severity verbatim: engine S5 stays S5 in the list (old clamp showed S3)
rerender(real);
const firstBadge = elements["risk-list"].children[0].children[0];
expect("v0.14: severity 1..5 shown verbatim (S5 not clamped to S3)",
       firstBadge.textContent === "S5",
       firstBadge.textContent);
// risks empty but warnings present → card STAYS with a notices-only
// headline and the risk sub-header hidden (both lists still one surface)
const d3norisk = JSON.parse(JSON.stringify(real3));
d3norisk.phase_a.risks = [];
d3norisk.phase_b.diagnostics = d3norisk.phase_b.diagnostics || {};
d3norisk.phase_b.diagnostics.warning = "测试提示行: 网格分辨率不足";
rerender(d3norisk);
expect("v0.22: warnings-only report keeps the merged card, notices headline",
       elements["alerts-card"].style.display === "" &&
       elements["alerts-headline"].textContent === "条提示" &&
       elements["alerts-risk-h"].style.display === "none",
       elements["alerts-headline"].textContent + "/" +
       elements["alerts-risk-h"].style.display);
// both streams empty → card hidden (the old summary card said 无风险;
// now the ABSENCE of the ⚠ card is the all-clear)
d3norisk.phase_b.diagnostics.warning = null;
rerender(d3norisk);
expect("v0.22: both streams empty → merged card hidden",
       elements["alerts-card"].style.display === "none",
       elements["alerts-card"].style.display);

// advice card: dual CTA (v0.22) + 将调整 summary line + appendix-C action
rerender(d24c, app24);
expect("v0.10: advice card CTA with count",
       textOf(elements["summary-cards"].children[1]).indexOf("应用可行建议 (3)") >= 0,
       textOf(elements["summary-cards"].children[1]).slice(0, 160));
expect("v0.22: simple-mode apply-ALL CTA rides the advice card",
       textOf(elements["summary-cards"].children[1])
         .indexOf("应用全部建议并重新分析 (3)") >= 0,
       textOf(elements["summary-cards"].children[1]).slice(0, 200));
expect("v0.22: 将调整 line lists current→recommended per applicable item",
       textOf(elements["summary-cards"].children[1]).indexOf("将调整：") >= 0 &&
       /\d→\d/.test(textOf(elements["summary-cards"].children[1])),
       textOf(elements["summary-cards"].children[1]).slice(0, 240));
const sumCta = findBtn(elements["summary-cards"], "应用可行建议");
expect("v0.10: summary CTA wired to applyCheckedSuggestions",
       !!sumCta && typeof sumCta.onclick === "function");
rerender(real);
const gridBtn = findBtn(elements["summary-cards"], "提高网格精度");
expect("v0.10: part_visibility_warning → grid-precision action button",
       textOf(elements["summary-cards"].children[1]).indexOf("网格分辨率不足") >= 0 &&
       !!gridBtn && typeof gridBtn.onclick === "function",
       textOf(elements["summary-cards"].children[1]).slice(0, 160));

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

// 25. (v0.18) structured-warning mirror (#pd-warn-promoted): simple mode
// folds the engine detail wall, so the engine's own structured channels
// (phase_d.buckling_warning / fracture_risk_detected) must echo above it.
// Same-render echo of the exact wall text — no UI rephrasing.
const d25v18 = JSON.parse(JSON.stringify(real));
d25v18.phase_d.run = true;
d25v18.phase_d.buckling_warning =
  "细长件屈曲风险: λ=86 > λ_trans=17, 屈曲安全系数=0 (Euler P_cr=88N)";
d25v18.phase_d.fracture_risk_detected = true;
d25v18.phase_d.fracture_assessment = "检出 K_Iz 超限";
rerender(d25v18);
expect("v0.18: buckling warning mirrored above the fold (v0.28 human note + engine text verbatim)",
       boxText("pd-warn-promoted").indexOf("⚠ 屈曲警示: 零件可能被压弯/压塌（屈曲）——引擎原文：细长件屈曲风险") >= 0,
       boxText("pd-warn-promoted"));
expect("v0.18: fracture detected+assessment mirrored (v0.28 human note + verbatim)",
       boxText("pd-warn-promoted").indexOf("⚠ 断裂判定: 零件可能出现裂纹并扩展（断裂风险）——引擎原文：检出 K_Iz 超限") >= 0,
       boxText("pd-warn-promoted"));
expect("v0.18: wall lines carry pd-warn class on both engine channels",
       (function () {
         const kids = elements["phase-d-detail"].children || [];
         const warned = kids.filter(function (c) {
           return (c.className || "").indexOf("pd-warn") >= 0; });
         return warned.length === 2;
       })(),
       JSON.stringify((elements["phase-d-detail"].children || [])
         .map(function (c) { return c.className; })));
expect("v0.18: fatigue assessment never mirrored (no structured discriminator)",
       boxText("pd-warn-promoted").indexOf("疲劳判定") < 0,
       boxText("pd-warn-promoted"));
// REFUTE P2 shape: risk flag true but assessment null must not render "null"
const d25v18b = JSON.parse(JSON.stringify(real));
d25b.phase_d.run = true;
d25b.phase_d.fracture_risk_detected = true;
d25b.phase_d.fracture_assessment = null;
rerender(d25v18b);
expect("v0.18: fracture detected + null assessment → no mirror line, no 'null'",
       boxText("pd-warn-promoted").indexOf("null") < 0
       && boxText("pd-warn-promoted").indexOf("断裂判定") < 0,
       boxText("pd-warn-promoted"));
// REFUTE major#4: a warning-free report after a warned one drops the alarm
const d25v18c = JSON.parse(JSON.stringify(real));
d25v18c.phase_d.run = true;
rerender(d25v18c);
expect("v0.18: warning-free report clears a previous mirror (no stale alarm)",
       boxText("pd-warn-promoted").indexOf("屈曲警示") < 0
       && boxText("pd-warn-promoted").indexOf("断裂判定") < 0,
       boxText("pd-warn-promoted"));
// 26. (v0.19 round B) raw-table fold (#cand-raw-fold) + significant-figure
// denoise. Teeth: pre-0.19 code renders raw floats ("70.712937") and never
// references the fold element — the positive fold assertions read
// undefined.open and fail cleanly.
const d19a = JSON.parse(JSON.stringify(real3));
d19a.process_optimization.candidates = [
  {name: "noisy", goal: "balanced", feasible: true,
   profile: {infill_pct: 15.000001, print_speed: 120},
   scores: {overall: 70.712937, strength: 56.34, time: 100,
            material: 71.814511, reliability: 90, quality: 15.000001}},
  {name: "twin", goal: "strength", feasible: true,
   scores: {overall: 71.812937}}];
rerender(d19a);
expect("v0.19: 6 significant digits — noise dropped, ROADMAP twin pair stays distinct",
       boxText("cand-body").indexOf("70.712937") < 0 &&
       boxText("cand-body").indexOf("71.8129") >= 0 &&
       boxText("cand-body").indexOf("71.8145") >= 0,
       boxText("cand-body").slice(0, 200));
expect("v0.19: infill denoised (15.000001% → 15%), speed cell untouched",
       boxText("cand-body").indexOf("15.000001%") < 0 &&
       boxText("cand-body").indexOf("15%") >= 0 &&
       boxText("cand-body").indexOf("120mm/s") >= 0,
       boxText("cand-body").slice(0, 200));
expect("v0.19: fold stays closed with ≥2 feasible (bars are the outlet)",
       (elements["cand-raw-fold"] || {}).open !== true);
const d19f = JSON.parse(JSON.stringify(real3));
d19f.process_optimization.candidates = [
  {name: "only", goal: "balanced", feasible: true, scores: {}},
  {name: "dead", goal: "speed", feasible: false, scores: {}}];
rerender(d19f);
expect("v0.19: fold auto-opens when <2 feasible (bars hidden — fold is the only outlet)",
       (elements["cand-raw-fold"] || {}).open === true &&
       boxText("cand-body").indexOf("dead") >= 0);
const d19e = JSON.parse(JSON.stringify(real3));
delete d19e.process_optimization;
rerender(d19e);
expect("v0.19: fold auto-opens when the report has no candidates at all",
       (elements["cand-raw-fold"] || {}).open === true &&
       boxText("cand-body").indexOf("无候选") >= 0);
const d19s = JSON.parse(JSON.stringify(real3));
d19s.process_optimization.candidates = [
  {name: "guards", goal: "balanced", feasible: true,
   profile: {infill_pct: null},
   scores: {overall: null, strength: "85"}}];
rerender(d19s);
expect("v0.19: fmtSig guards — null → placeholder, string passes through (no throw)",
       boxText("cand-body").indexOf("85") >= 0 &&
       boxText("cand-body").indexOf("null") < 0,
       boxText("cand-body").slice(0, 160));
rerender(real);

// ---------- v0.23 gcode-diff render functions ----------
if (typeof ctx.renderGcodeDiff !== "function"
    || typeof ctx.renderGcodeScore !== "function") {
  console.error("FATAL: gcode render functions not found"); process.exit(1);
}
function gtxt() { return textOf($("gcode-result")); }
const gdiffFixture = {
  schema_version: "gcode-diff-report/v1",
  file_a: "C:/tmp/x-a.gcode", file_b: "C:/tmp/x-b.gcode",
  layers_added: 0, layers_removed: 1, layers_modified: 3,
  overall_verdict: "CLEAN",
  overall_detail: "CLEAN: all surface-critical type paths OK",
  slicer_format: "PrusaSlicer 2.7.4",
  geometry_diff: {available: true, chamfer_distance: 0.012,
                  hausdorff_distance: 0.05, frechet_distance: 0.2,
                  overlap_ratio: 0.98},
  physics_delta: {assessable: true, material: "PLA",
                  newly_overheated_layers: 2, weld_regressed_layers: 1,
                  over_machine_limit_layers: 0, over_melt_ceiling_layers: 0,
                  worst_weld_delta_pct: null},
  fem_delta: null,
  global_diffs: [
    {metric: "total_extrusion_mm3", a: 100, b: 125, delta: 25,
     delta_pct: 25.0, significant: true},
    {metric: "avg_speed", a: 90, b: 90, delta: 0, delta_pct: 0,
     significant: false}],
  category_diffs: {},
  slicer_issues: [
    {category: "flow", severity: "WARNING_MAJOR", summary: "over-extrusion",
     recommendation: "lower flow", confidence: "medium"}],
};
ctx.renderGcodeDiff(gdiffFixture, "[gcode-diff] verdict=Clean",
                    {names: ["before.gcode", "after.gcode"], token: "tok123"});
expect("gcode diff: verdict hero + UI names (argv paths NOT shown)",
       gtxt().indexOf("CLEAN") >= 0 && gtxt().indexOf("before.gcode") >= 0
       && gtxt().indexOf("C:/tmp/x-a.gcode") < 0,
       gtxt().slice(0, 200));
expect("gcode diff: global table rows + significance mark",
       gtxt().indexOf("total_extrusion_mm3") >= 0
       && gtxt().indexOf("25.0%") >= 0 && gtxt().indexOf("✓") >= 0,
       gtxt().slice(0, 400));
expect("gcode diff: physics scalars shown; null weld delta hides its line",
       gtxt().indexOf("新过热层 2") >= 0
       && gtxt().indexOf("最差焊合强度变化") < 0,
       gtxt().slice(0, 400));
expect("gcode diff: severity tone class on issue row",
       (function () {
         const card = $("gcode-result");
         function findCls(n) {
           return (n.children || []).some(function (c) {
             return String(c.className).indexOf("rec-row warn") >= 0 || findCls(c); });
         }
         return findCls(card);
       })(), "no rec-row warn found");
expect("gcode diff: footer deep link carries the token",
       (function () {
         let found = "";
         (function walk(n) {
           (n.children || []).forEach(function (c) {
             // the footer sets a.href by plain assignment (not setAttribute)
             // — read both shapes, same as a real DOM element exposes
             if (c.href) found = String(c.href);
             if (c.attrs && c.attrs.href) found = c.attrs.href;
             walk(c); });
         })($("gcode-result"));
         return found.indexOf("/api/gcode-report?token=tok123") === 0;
       })(), "no report link");
// absent-not-null: geometry unavailable hides the WHOLE card
const gdiffNoGeom = JSON.parse(JSON.stringify(gdiffFixture));
gdiffNoGeom.geometry_diff = {available: false};
ctx.renderGcodeDiff(gdiffNoGeom, "", {names: ["a", "b"], token: "t"});
expect("gcode diff: geometry available=false hides the card entirely",
       gtxt().indexOf("几何差异") < 0 && gtxt().indexOf("Chamfer") < 0,
       gtxt().slice(0, 200));
// unknown verdict label → neutral (no crash, still rendered)
const gdiffUnknown = JSON.parse(JSON.stringify(gdiffFixture));
gdiffUnknown.overall_verdict = "SOMETHING_NEW";
ctx.renderGcodeDiff(gdiffUnknown, "", {names: ["a", "b"], token: "t"});
expect("gcode diff: unknown verdict token renders neutral, verbatim",
       gtxt().indexOf("SOMETHING_NEW") >= 0);
// score: null dimension score is 不可评估 dash, never 0.0
ctx.renderGcodeScore({
  overall_score: 57.5, summary: "Fair", slicer: "PrusaSlicer",
  material: "PLA", has_critical: true, dimensions_scored: 13,
  dimensions: [
    {name: "Cooling", assessable: true, score: 20.0,
     severity: "WARNING_MAJOR", verdict: "fan too low"},
    {name: "Multi-Extruder", assessable: false, score: null,
     severity: "BENIGN", verdict: "Not assessable: single tool"}],
  suggestions: [
    {parameter: "fan_speed", suggested_value: "255", reason: "layers 2-3",
     expected_effect: "better bridging"}],
}, "[gcode-diff] score=57.5", {names: ["x.gcode"], token: "tok9"});
expect("gcode score: hero + critical flag + dimension rows",
       gtxt().indexOf("57.5 / 100") >= 0 && gtxt().indexOf("CRITICAL") >= 0
       && gtxt().indexOf("Cooling") >= 0 && gtxt().indexOf("fan too low") >= 0,
       gtxt().slice(0, 300));
expect("gcode score: null score renders dash, never 0.0 (two-state sentinel)",
       (function () {
         // find the Multi-Extruder row and read its SCORE cell exactly —
         // a substring "0.0" scan would false-positive on "20.0"
         let cell = "";
         (function walk(n) {
           (n.children || []).forEach(function (c) {
             if (textOf(c).indexOf("Multi-Extruder") >= 0
                 && (c.tagName === "tr")) {
               const tds = (c.children || []).filter(function (t) {
                 return t.tagName === "td"; });
               if (tds.length >= 2) cell = tds[1].textContent;
             }
             walk(c); });
         })($("gcode-result"));
         return cell === "—";
       })(), "score cell not exactly the dash");
expect("gcode score: suggestion row verbatim",
       gtxt().indexOf("fan_speed → 255") >= 0
       && gtxt().indexOf("better bridging") >= 0);
// score: the fail-closed rc=2 state is its own card, not a 0-score render
ctx.renderGcodeScore({
  overall_score: 0.0, summary: "Not assessable", dimensions_scored: 0,
  dimensions: [{name: "Cooling", assessable: false, score: null,
                severity: "BENIGN", verdict: "Not assessable"}],
  suggestions: [],
}, "", {names: ["void.gcode"], token: "tok0"});
expect("gcode score: dimensions_scored=0 → 整体不可评估 card, no 0/100 hero",
       gtxt().indexOf("整体不可评估") >= 0 && gtxt().indexOf("/ 100") < 0,
       gtxt().slice(0, 300));

// ---- §28 v0.25 slice-gcode stress-tune audit card (renderGcodeTune) ----
// fixture: a REAL engine sidecar (beam STL + a.gcode probe, 2026-10-03) —
// coverage 0 / candidates 0 is the mismatched-slice legal state
const tuneFx = JSON.parse(fs.readFileSync(
  path.join(__dirname, "..", "test_data", "gcode-tune-audit.json"), "utf8"));
ctx.renderGcodeTune(tuneFx, "tok99");
expect("tune: audit card visible with engine stats verbatim",
       elements["gcode-tune-box"].style.display === ""
       && boxText("gcode-tune-body").indexOf("应力覆盖率") >= 0
       && boxText("gcode-tune-body").indexOf("段总数") >= 0
       && boxText("gcode-tune-body").indexOf("0") >= 0,
       boxText("gcode-tune-body").slice(0, 200));
// patch_coverage_ratio -1 is the engine's "not applicable" sentinel — never
// a bare -1 number on screen (two-state sentinel)
expect("tune: patch_coverage_ratio -1 renders the dash, never -1",
       boxText("gcode-tune-body").indexOf("热区覆盖率") >= 0
       && boxText("gcode-tune-body").indexOf("-1") < 0,
       boxText("gcode-tune-body").slice(0, 200));
expect("tune: engine prose (alignment/blind spots) carried verbatim",
       boxText("gcode-tune-body").indexOf("bbox-center") >= 0,
       boxText("gcode-tune-body").slice(0, 300));
// download button only with a live token
let tuneBtn = null;
(function walkT(n) {
  (n.children || []).forEach(function (c) {
    if (c.tagName === "button") tuneBtn = c;
    walkT(c);
  });
})(elements["gcode-tune-body"]);
expect("tune: download button rendered with a token",
       !!tuneBtn && textOf(tuneBtn).indexOf("下载调优后 G-code") >= 0);
// absent channel (no attachment / old engine stripped the flags): the box
// hides and leaves nothing behind — no half-rendered stale card
ctx.renderGcodeTune(null, "tok99");
expect("tune: absent channel hides the box and clears the body",
       elements["gcode-tune-box"].style.display === "none"
       && boxText("gcode-tune-body") === "",
       JSON.stringify(elements["gcode-tune-body"].style));
// no token → stats render but no download button
ctx.renderGcodeTune(tuneFx, null);
let btn2 = null;
(function walkT2(n) {
  (n.children || []).forEach(function (c) {
    if (c.tagName === "button") btn2 = c;
    walkT2(c);
  });
})(elements["gcode-tune-body"]);
expect("tune: no token → card renders without the download button",
       elements["gcode-tune-box"].style.display === "" && !btn2);
// live shape: geometry-matched slice (engine probe 2026-10-03, Cura
// WALL-OUTER/INNER markers) — tuned=80, drift +2.4278% renders WITH the
// explicit plus sign (add-only law made visible)
const tuneLive = JSON.parse(fs.readFileSync(
  path.join(__dirname, "..", "test_data", "gcode-tune-live.json"), "utf8"));
ctx.renderGcodeTune(tuneLive, "tok100");
expect("tune: live shape renders tuned=80 and a signed + drift",
       boxText("gcode-tune-body").indexOf("80") >= 0
       && /\+2\.43/.test(boxText("gcode-tune-body"))
       && boxText("gcode-tune-body").indexOf("-1") < 0,
       boxText("gcode-tune-body").slice(0, 260));

// ---- §29 v0.27 verdictRank / auto-tune decision / advice-card CTA ----
// The rank mapping is the v0.22 hero edge color, extracted top-level so the
// loop driver reuses ONE mapping — these pins keep it identical to the
// documented precedence (emoji < structured phase_d < SF<1, worst-of).
expect("29 verdictRank: ✅ assessment → 1",
       ctx.verdictRank({assessment: "✅ 安全 — 结构强度充足"}, {}) === 1);
expect("29 verdictRank: ⚠ assessment → 2 (no phase_d)",
       ctx.verdictRank({assessment: "⚠ 注意 — 有风险"}, {}) === 2);
expect("29 verdictRank: ❌ assessment → 3",
       ctx.verdictRank({assessment: "❌ 危险"}, {}) === 3);
expect("29 verdictRank: structured buckling warning lifts a ✅ phrase to 2",
       ctx.verdictRank({assessment: "✅ 安全"}, {buckling_warning: "λ=86"}) === 2);
expect("29 verdictRank: fracture detected + assessment → 2",
       ctx.verdictRank({assessment: "✅ 安全"},
                       {fracture_risk_detected: true,
                        fracture_assessment: "层间裂纹风险"}) === 2);
expect("29 verdictRank: fracture without assessment prose does NOT lift",
       ctx.verdictRank({assessment: "✅ 安全"},
                       {fracture_risk_detected: true}) === 1);
expect("29 verdictRank: SF<1 (scalar) → 3 regardless of ✅",
       ctx.verdictRank({assessment: "✅", safety_factor: 0.88}, {}) === 3);
expect("29 verdictRank: SF<1 (v2 object nominal) → 3",
       ctx.verdictRank({assessment: "✅",
                        safety_factor: {nominal: 0.9, lo: 0.7, hi: 1.1}}, {}) === 3);
expect("29 verdictRank: 🟡 phrase alone has no rank-bearing emoji → 0",
       ctx.verdictRank({assessment: "🟡 可接受 — 建议关注高应力区"}, {}) === 0);
expect("29 verdictRank: null pb / no signals → 0",
       ctx.verdictRank(null, null) === 0
       && ctx.verdictRank({}, {}) === 0);
expect("29 safetyFactorScalar: object→nominal, scalar passthrough, null",
       ctx.safetyFactorScalar({safety_factor: {nominal: 2.5}}) === 2.5
       && ctx.safetyFactorScalar({safety_factor: 1.5}) === 1.5
       && ctx.safetyFactorScalar({safety_factor: null}) === null
       && ctx.safetyFactorScalar(null) === null);

// autoTuneStepDecision — pure per-round policy (driver in index.html E2E):
// every stop shape reachable synthetically here, since the real engine's
// suggestion surface today yields single-round chains (probe 2026-10-04).
const _mkApp = (k, v, ok) => ({ui_key: k, recommended_value: v, applicable: ok !== false});
expect("29 decision: rank1 → stop safe (even with suggestions pending)",
       ctx.autoTuneStepDecision({rank: 1, round: 0, maxRounds: 3,
         lastSig: null, applyable: [_mkApp("walls", 3)]}).code === "safe");
expect("29 decision: round cap → stop cap",
       ctx.autoTuneStepDecision({rank: 2, round: 3, maxRounds: 3,
         lastSig: null, applyable: [_mkApp("walls", 3)]}).code === "cap");
expect("29 decision: no applicable entries → stop exhausted",
       ctx.autoTuneStepDecision({rank: 2, round: 0, maxRounds: 3,
         lastSig: null, applyable: [_mkApp("walls", 3, false)]}).code === "exhausted");
expect("29 decision: empty/absent applyable → stop exhausted (null-safe)",
       ctx.autoTuneStepDecision({rank: 2, round: 0, maxRounds: 3,
         lastSig: null, applyable: null}).code === "exhausted");
const _sig = ctx.autoTuneStepDecision({rank: 2, round: 0, maxRounds: 3,
  lastSig: null, applyable: [_mkApp("walls", 3), _mkApp("infill", 35)]});
expect("29 decision: apply carries a sorted key:value signature",
       _sig.action === "apply" && _sig.sig === "infill:35|walls:3"
       && _sig.picked.length === 2, JSON.stringify(_sig));
expect("29 decision: same signature next round → stop unchanged (oscillation)",
       ctx.autoTuneStepDecision({rank: 2, round: 1, maxRounds: 3,
         lastSig: "infill:35|walls:3",
         applyable: [_mkApp("walls", 3), _mkApp("infill", 35)]}).code === "unchanged");
expect("29 decision: precedence — safe outranks cap at equal round",
       ctx.autoTuneStepDecision({rank: 1, round: 3, maxRounds: 3,
         lastSig: null, applyable: [_mkApp("walls", 3)]}).code === "safe");

// advice-card third CTA: rank≥2 + applicable>0 renders the loop entry;
// rank1 (safe) and no-applicable shapes keep it hidden — the one-shot
// apply-all CTA remains the honest entry there
const d29 = JSON.parse(JSON.stringify(real3));
d29.phase_d = d29.phase_d || {};
d29.phase_d.buckling_warning = "细长件屈曲风险: λ=173 > λ_trans=17";  // rank2 lift
rerender(d29, [{parameter: "walls", action: "increase", current_value: 2,
                recommended_value: 3, priority: 1, applicable: true,
                reason: "", ui_key: "walls"}]);
let nsTune1 = null;
(function walkT(n) {
  (n.children || []).forEach(function (c) {
    if (c.id === "btn-auto-tune") nsTune1 = c;
    walkT(c);
  });
})(elements["summary-cards"]);
expect("29 CTA: rank2 + applicable → auto-tune button rendered (simple-only class)",
       !!nsTune1 && nsTune1.className.indexOf("simple-only") >= 0
       && nsTune1.textContent.indexOf("自动调参") >= 0,
       nsTune1 && nsTune1.textContent);
expect("29 CTA: rank2 renders the hero warn edge (worst-of intact)",
       elements["summary-cards"].children[0].className.indexOf("warn") >= 0,
       elements["summary-cards"].children[0].className);
// rank1 shape: real3 itself carries the λ=86 buckling warning (rank 2 —
// v0.18's motivating fixture), so strip the structured warning for a TRUE
// rank1 (✅ phrase, SF 6.53 > 1, no phase_d warning)
const d29b = JSON.parse(JSON.stringify(real3));
d29b.phase_d = d29b.phase_d || {};
d29b.phase_d.buckling_warning = null;
d29b.phase_d.fracture_risk_detected = false;
rerender(d29b, [{parameter: "walls", action: "increase", current_value: 2,
                 recommended_value: 3, priority: 1, applicable: true,
                 reason: "", ui_key: "walls"}]);
let nsTune2 = null;
(function walkT2b(n) {
  (n.children || []).forEach(function (c) {
    if (c.id === "btn-auto-tune") nsTune2 = c;
    walkT2b(c);
  });
})(elements["summary-cards"]);
expect("29 CTA: rank1 (✅, SF>1, no phase_d warning) → no auto-tune button",
       !nsTune2, nsTune2 && nsTune2.textContent);
rerender(d29, []);  // rank2 but nothing applicable
let nsTune3 = null;
(function walkT3(n) {
  (n.children || []).forEach(function (c) {
    if (c.id === "btn-auto-tune") nsTune3 = c;
    walkT3(c);
  });
})(elements["summary-cards"]);
expect("29 CTA: rank2 + zero applicable → no auto-tune button",
       !nsTune3, nsTune3 && nsTune3.textContent);

// 30. (v0.28) language layer: banner human-note prefix (banner-only), term
// "?" buttons, error-card action extension, cand-bars novice summary.
// Teeth: pre-v0.28 code renders the bare label (no note), no .term-q
// children, no memory/queue branches, and no summary line — every positive
// below reads absent/empty and fails cleanly.
// a) A1 wall discipline: the engine detail wall keeps the BARE label+prose
// (the human sentence targets the novice banner only — never the wall)
rerender(d25v18);
expect("30 A1: wall stays verbatim (no human note, no 引擎原文 marker)",
       boxText("phase-d-detail").indexOf("屈曲警示: 细长件屈曲风险") >= 0
       && boxText("phase-d-detail").indexOf("零件可能被压弯") < 0
       && boxText("phase-d-detail").indexOf("引擎原文") < 0,
       boxText("phase-d-detail").slice(0, 160));
// PD6: empty-string buckling warning is falsy → no line anywhere
const d30e = JSON.parse(JSON.stringify(real));
d30e.phase_d.run = true;
d30e.phase_d.buckling_warning = "";
rerender(d30e);
expect("30 A1: empty-string buckling_warning → no banner line",
       boxText("pd-warn-promoted").indexOf("屈曲") < 0,
       boxText("pd-warn-promoted"));
// b) A3 term buttons: real3 fires the phase_c glossary rows (delamination
// site asserted since v0.10); every .term-q must carry the title (popup
// source) and an onclick
function findAll(root, cls, out) {
  (root.children || []).forEach(function (c) {
    if ((c.className || "").indexOf(cls) >= 0) out.push(c);
    findAll(c, cls, out);
  });
  return out;
}
rerender(real3);
const tqs = findAll(elements["phase-c-detail"], "term-q", [])
  .concat(findAll(elements["phase-d-detail"], "term-q", []));
expect("30 A3: term rows carry ?-buttons with title + onclick",
       tqs.length >= 1 && tqs.every(function (b) {
         return typeof b.title === "string" && b.title.length > 4
                && typeof b.onclick === "function"; }),
       "n=" + tqs.length);
// S6: the vm stub has no document.body — openTermPop must no-op, not throw
let popNoThrow = true;
try { ctx.openTermPop({ title: "x" }); ctx.closeTermPop(); }
catch (e) { popNoThrow = false; }
expect("30 A3: popup no-ops without document.body (vm-stub guard)",
       popNoThrow && ctx._termPop === null);
// c) A4 error-card extensions
ctx.analyzeCalls = 0;
ctx.analyze = function () { ctx.analyzeCalls++; };
ctx.renderAnalyzeError({ error: "stratum.exe 失败 (rc=3): std::bad_alloc" });
let fastBtn = findBtn(elements["analyze-error"], "开快速预览并重跑");
expect("30 A4: memory-class error → quick-preview rerun button",
       !!fastBtn, boxText("analyze-error").slice(0, 120));
if (fastBtn) fastBtn.onclick();
expect("30 A4: clicking it checks opt-fast and re-runs",
       elements["opt-fast"].checked === true && ctx.analyzeCalls === 1,
       "checked=" + elements["opt-fast"].checked +
       " calls=" + ctx.analyzeCalls);
// timeout class: contains 分辨率 (would match the legacy grid regex) but
// the grid×2 button must be SUPPRESSED — doubling the grid worsens timeouts
ctx.renderAnalyzeError({ error:
  "分析超时（180s）——模型过大/面数过高（52.3 MB）。可尝试：① 用环境变量 STRATUM_UI_GRID 调低体素分辨率后重启；② 换用更小/更简化的模型" });
expect("30 A4: timeout text (contains 分辨率) suppresses the harmful grid-×2 button",
       !findBtn(elements["analyze-error"], "提高网格精度")
       && !findBtn(elements["analyze-error"], "开快速预览")
       && boxText("analyze-error").indexOf("分析超时") >= 0,
       boxText("analyze-error").slice(0, 120));
// queue full: hint line only, no invented retry CTA
ctx.renderAnalyzeError({ error: "引擎忙（排队已满）——稍后重试或取消其他任务" });
expect("30 A4: queue-full → one guidance line, no extra button",
       boxText("analyze-error").indexOf("本次请求未开始") >= 0
       && !findBtn(elements["analyze-error"], "开快速预览")
       && !findBtn(elements["analyze-error"], "提高网格精度"),
       boxText("analyze-error").slice(0, 160));
// E3 overlap: grid + memory in one message → both buttons coexist
ctx.renderAnalyzeError({ error: "网格部件解析失败: out of memory" });
expect("30 A4: grid+memory overlap → both buttons",
       !!findBtn(elements["analyze-error"], "提高网格精度")
       && !!findBtn(elements["analyze-error"], "开快速预览"),
       boxText("analyze-error").slice(0, 120));
// d) A5 cand novice summary (v0.29: lives in #cand-novice-line OUTSIDE the
// detail-walled bars — enumeration fact; candidates carry no rank field,
// so the wording must NOT claim one)
const d30c = JSON.parse(JSON.stringify(real3));
d30c.process_optimization.candidates = [
  {name: "safe", feasible: true, search_est_safety_factor: 2.6},
  {name: "fast", feasible: true, search_est_safety_factor: 1.2}];
rerender(d30c);
expect("30 A5: first feasible row stated (Math.round SF, table convention)",
       boxText("cand-novice-line").indexOf("第一个可行档位（引擎枚举序）：safe —— 安全系数 3") >= 0,
       boxText("cand-novice-line"));
// C2: SF null on the first row → name only, no "null" fragment
d30c.process_optimization.candidates = [
  {name: "safe", feasible: true},
  {name: "fast", feasible: true, search_est_safety_factor: 1.2}];
rerender(d30c);
const cb2 = boxText("cand-novice-line");
expect("30 A5: first row without SF → name only (never renders null)",
       cb2.indexOf("第一个可行档位（引擎枚举序）：safe") >= 0
       && cb2.indexOf("安全系数 null") < 0 && cb2.indexOf("undefined") < 0,
       cb2);
// C4: missing name → "??", not "undefined"
d30c.process_optimization.candidates = [
  {feasible: true, search_est_safety_factor: 2},
  {name: "fast", feasible: true, search_est_safety_factor: 1}];
rerender(d30c);
expect("30 A5: missing name → ?? placeholder",
       boxText("cand-novice-line").indexOf("第一个可行档位（引擎枚举序）：?? —— 安全系数 2") >= 0,
       boxText("cand-novice-line"));
// C3: <2 feasible rows → the line is dropped (cleared every render)
d30c.process_optimization.candidates = [
  {name: "safe", feasible: true, search_est_safety_factor: 2.6}];
rerender(d30c);
expect("30 A5: <2 feasible → summary line cleared (gate unchanged)",
       boxText("cand-novice-line").indexOf("第一个可行档位") < 0,
       boxText("cand-novice-line"));

process.exit(fails ? 1 : 0);
