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
expect("v0.8.1: ZZ-SPR / Tsai-Wu / mesh quality / precond hints",
       boxText("phase-b-detail").indexOf("离散误差 (ZZ-SPR)") >= 0 &&
       boxText("phase-b-detail").indexOf("22.1%") >= 0 &&
       boxText("phase-b-detail").indexOf("Tsai-Wu SF: 17.6") >= 0 &&
       boxText("phase-b-detail").indexOf("uniform_cubic_voxel") >= 0 &&
       boxText("phase-b-detail").indexOf("预条件子: ic0") >= 0,
       boxText("phase-b-detail"));
expect("v0.8.1: thermal-speed loop overheated line + rationale verbatim",
       boxText("phase-c-detail").indexOf("热-速闭环: 基板温 125.6°C / 上限 62.0°C — 超温，建议速度 16.5 mm/s") >= 0 &&
       boxText("phase-c-detail").indexOf("PLA: T_sub(8s)=125.6°C > Tg 62°C") >= 0,
       boxText("phase-c-detail"));
expect("v0.8.1: weld_infill_aware with disclosure verbatim",
       boxText("phase-c-detail").indexOf("有效键合(含填充): a_eff 0.0360") >= 0 &&
       boxText("phase-c-detail").indexOf("non-decision-grade") >= 0);
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
       boxText("phase-b-detail").indexOf("预条件子: ic0") >= 0 &&
       boxText("phase-b-detail").indexOf("ZZ-SPR") >= 0 &&
       boxText("phase-c-detail").indexOf("热-速闭环: 基板温 125.6°C") >= 0,
       boxText("printability-line") + " || " + boxText("phase-b-detail") +
       " || " + boxText("phase-c-detail"));
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
expect("v0.8.1: resolution-check hints verbatim deltas",
       boxText("phase-b-detail").indexOf("分辨率校验: 16→32 网格，位移 Δ72.3% / 应力 Δ40.9%（细网格收敛）") >= 0 &&
       boxText("phase-b-detail").indexOf("粗 0.205 / 细 0.198") >= 0,
       boxText("phase-b-detail"));
const d22b = JSON.parse(JSON.stringify(d22));
d22b.phase_b.resolution_check.capped = true;
d22b.phase_b.resolution_check.fine_converged = false;
rerender(d22b);
expect("v0.8.1: resolution-check capped + not-converged surfaced",
       boxText("phase-b-detail").indexOf("已封顶 128") >= 0 &&
       boxText("phase-b-detail").indexOf("细网格未收敛") >= 0);
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

process.exit(fails ? 1 : 0);
