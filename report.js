"use strict";
// Extracted from index.html (zero-build split, see ROADMAP):
// loaded as a classic <script src> before the main inline script.
// All helpers ($, el, num, numEnv, state, ...) are globals resolved
// at CALL time — this file only declares functions, runs nothing.

// ---------- render ----------
function renderReport(d, consoleText) {
  // engine console verbatim (collapsible): the CLI prints skip rationales
  // (e.g. "Findley: skipped (no published FDM PLA k/f calibration)") that the
  // JSON does not carry — this is the only place the reason is visible
  var con = $("engine-console");
  if (consoleText) {
    con.style.display = "";
    $("engine-console-pre").textContent = consoleText;
  } else {
    con.style.display = "none";
  }
  $("btn-report").disabled = false;  // last_report now exists server-side
  var inp = d.input || {};
  var po = d.process_optimization || {};
  var base = po.baseline || {};
  // current params (values the engine actually used)
  $("cp-material").textContent = inp.material || "—";
  $("cp-nozzle").textContent = fmtUnit(inp.nozzle_mm, 2, "mm");
  $("cp-walls").textContent = inp.walls !== undefined && inp.walls !== null ? inp.walls : "—";
  $("cp-infill").textContent = inp.infill_density != null
    ? (inp.infill_density * 100).toFixed(0) + "%" : "—";
  $("cp-pattern").textContent = inp.infill_pattern || "—";
  // layer_height appears in the JSON ONLY inside candidate diffs (input and
  // process_optimization.baseline never carry it — probed on 0.21.0), so
  // scraping the first candidate's "before" is the only possible source.
  var lh = null;
  (po.candidates || []).some(function (c) {
    if (!c.diff || !c.diff.length) return false;
    c.diff.forEach(function (chg) {
      if (chg.key === "layer_height") lh = chg.before;
    });
    return lh !== null;
  });
  $("cp-lh").textContent = lh != null ? lh + " mm" : "—";
  $("cp-nozzle-temp").textContent = inp.nozzle_temperature_c !== null && inp.nozzle_temperature_c !== undefined
    ? inp.nozzle_temperature_c + " °C" : "—";
  $("cp-bed-temp").textContent = fmtUnit(inp.bed_temperature_c, 0, "°C");
  $("cp-speed").textContent = inp.print_speed_mms !== null && inp.print_speed_mms !== undefined
    ? inp.print_speed_mms + " mm/s" : "—";
  $("cp-fan").textContent = inp.cooling_fan_pct != null
    ? inp.cooling_fan_pct + "%" : "—";
  $("cp-load").textContent = inp.load_type || "—";
  $("cp-force").textContent = fmtUnit(inp.force_N, 0, "N");
  var locks = inp.locked_parameters || [];
  $("cp-locked").textContent = locks.length ? "锁定参数: " + locks.join(", ") : "";

  // structural summary
  var pb = d.phase_b || {};
  $("res-sf").textContent = numEnv(pb.safety_factor, 1);
  $("res-stress").textContent = fmtUnit(pb.max_stress_mpa, 2, "MPa");
  $("res-load").textContent = pb.load_adequacy
    ? (LOAD_LABELS[pb.load_adequacy] || pb.load_adequacy) : "—";
  // color keyed on the engine enum only (LOAD_ADEQUACY_CLASS) — no UI-side
  // thresholds; unknown enum values stay neutral
  $("res-load").className = "v " + (LOAD_ADEQUACY_CLASS[pb.load_adequacy] || "");
  var rec = d.recommendations || {};
  $("res-overall").textContent = rec.overall_score !== null && rec.overall_score !== undefined
    ? rec.overall_score : "—";

  // warnings (engine-global list; item shape not pinned by schema — render
  // defensively. Empty list keeps the block hidden.)
  var warnBox = $("warning-list");
  warnBox.innerHTML = "";
  (d.warnings || []).forEach(function (w) {
    var item = el("div", "risk-item");
    item.appendChild(el("span", "sev sev-2", "⚠"));
    item.appendChild(document.createTextNode(
      typeof w === "string" ? w : String(w.message || w.text || JSON.stringify(w))));
    warnBox.appendChild(item);
  });

  // Phase B solver diagnostics (iter 68; was fully unconsumed — real sample
  // carries a non-empty part_visibility_warning "网格含 41 个几何部件…
  // 物理结论不覆盖全部部件" that the UI silently dropped = false-optimistic).
  // Three-state on cg_converged (schema does not pin it to boolean, so strict
  // === matches; any other shape falls through as "not assessable", same
  // convention as thermal_is_upper_bound): true → evidence hint (no warning
  // text duplicated here); false → loud warning; null → nothing (older
  // engine without the field). Diagnostics-sourced warnings get a "Phase B: "
  // prefix so users can tell them from the engine-global list above.
  var pbd = (d.phase_b || {}).diagnostics || {};
  var pbdBox = $("phase-b-detail");
  if (pbdBox) {
    pbdBox.innerHTML = "";
    if (pbd.cg_converged === true) {
      pbdBox.appendChild(el("div", "hint",
        "CG 求解器收敛" +
        (typeof pbd.cg_iterations === "number" ? ": " + pbd.cg_iterations + " 次迭代" : "") +
        (typeof pbd.cg_relative_residual === "number"
          ? ", 相对残差 " + pbd.cg_relative_residual.toExponential(2) : "")));
    }
    // (iter 81) actual grid dims — the engine adapts them (real sample:
    // --grid 16 → 5×4×4/150 nodes), so this is not a re-echo of the UI knob
    var pg = pb.grid || {};
    if (typeof pg.nx === "number" && typeof pg.ny === "number"
        && typeof pg.nz === "number") {
      pbdBox.appendChild(el("div", "hint",
        "网格: " + pg.nx + "×" + pg.ny + "×" + pg.nz +
        (typeof pg.nodes === "number" ? "（" + pg.nodes + " 节点）" : "")));
    }
  }
  if (pbd.cg_converged === false) {
    var w1 = el("div", "risk-item");
    w1.appendChild(el("span", "sev sev-2", "⚠"));
    w1.appendChild(document.createTextNode(
      "Phase B: 线性求解器未收敛 — 数值结果不可靠"));
    warnBox.appendChild(w1);
  }
  if (typeof pbd.part_visibility_warning === "string" && pbd.part_visibility_warning) {
    var w2 = el("div", "risk-item");
    w2.appendChild(el("span", "sev sev-2", "⚠"));
    w2.appendChild(document.createTextNode("Phase B: " + pbd.part_visibility_warning));
    warnBox.appendChild(w2);
  }
  if (typeof pbd.warning === "string" && pbd.warning) {
    var w3 = el("div", "risk-item");
    w3.appendChild(el("span", "sev sev-2", "⚠"));
    w3.appendChild(document.createTextNode("Phase B: " + pbd.warning));
    warnBox.appendChild(w3);
  }

  // Phase C (plasticity / thermal / layer residual / delamination / fracture
  // / aging). Every row is null-gated on the engine's own value — a null IS
  // information ("not evaluated for this input"), never rendered as 0.
  // Forward-looking note: the aging / ABS-WLF / crystallinity groups only
  // become non-null when the engine is given --service-time/--humidity/
  // --anneal-hours, which this UI's server whitelist does not pass yet; the
  // branches stay because they are pure data-driven renders of engine shapes
  // (probed: ABS+service-time, PLA+anneal-hours).
  var pc = d.phase_c || {};
  var pcd = $("phase-c-detail");
  pcd.innerHTML = "";
  if (pc.run) {
    if (pc.hill48_safety_factor != null) {
      pcd.appendChild(el("div", "hint",
        "Hill48 SF: " + numEnv(pc.hill48_safety_factor, 1) +
        (pc.max_hill48_yield_index != null
          ? "（屈服指数 " + numEnv(pc.max_hill48_yield_index, 4) + "）" : "")));
    }
    if (pc.plastic_safety_factor != null) {
      pcd.appendChild(el("div", "hint",
        "塑性 SF: " + numEnv(pc.plastic_safety_factor, 1) +
        (pc.max_plastic_strain != null
          ? "（最大塑性应变 " + numEnv(pc.max_plastic_strain, 4) + "）" : "")));
    }
    if (pc.max_thermal_stress_mpa != null) {
      pcd.appendChild(el("div", "hint",
        "热应力: " + numEnv(pc.max_thermal_stress_mpa, 3) + " MPa" +
        (pc.thermal_is_upper_bound === true ? "（上界）" : "")));
    }
    if (pc.max_layer_residual_stress_mpa != null) {
      pcd.appendChild(el("div", "hint",
        "层间残余: max " + numEnv(pc.max_layer_residual_stress_mpa, 3) +
        " / mean " + numEnv(pc.mean_layer_residual_stress_mpa, 3) + " MPa" +
        (pc.residual_safety_factor != null
          ? "（SF " + numEnv(pc.residual_safety_factor, 1) + "）" : "")));
    }
    if (pc.max_delamination_risk != null) {
      pcd.appendChild(el("div", "hint",
        "分层风险: " + numEnv(pc.max_delamination_risk, 6) +
        (pc.delamination_risk_layers != null
          ? "（" + pc.delamination_risk_layers + " 层）" : "")));
    }
    if (pc.max_fracture_peel_risk != null || pc.max_fracture_shear_risk != null) {
      pcd.appendChild(el("div", "hint",
        "剥离/剪切断裂风险: " + numEnv(pc.max_fracture_peel_risk, 6) + " / " +
        numEnv(pc.max_fracture_shear_risk, 6)));
    }
    // Weibull numbers live in phase_c too; the A+ grade shows in the summary
    // via phase_d — these rows keep the numeric Pf/R from being lost.
    if (pc.weibull_failure_probability != null) {
      pcd.appendChild(el("div", "hint",
        "Weibull: Pf " + numEnv(pc.weibull_failure_probability, 6) +
        " / R " + numEnv(pc.weibull_reliability_factor, 4)));
    }
    // (iter 72) yielded_elements: 0 is meaningful information ("no element
    // yielded"), not a sentinel — render the raw count when the engine
    // produced one; null = field absent, skip.
    if (pc.yielded_elements != null) {
      pcd.appendChild(el("div", "hint",
        "屈服单元: " + pc.yielded_elements +
        (pc.yielded_elements > 0 ? "（局部已屈服）" : "")));
    }
    var aging = [pc.moisture_uptake_pct, pc.modulus_retention,
                 pc.strength_retention, pc.is_degraded, pc.aging_safety_factor];
    if (aging.every(function (v) { return v == null; })) {
      pcd.appendChild(el("div", "hint", "服役老化: 未评估"));
    } else {
      var parts = [];
      if (pc.moisture_uptake_pct != null) parts.push("吸湿 " + numEnv(pc.moisture_uptake_pct, 4) + "%");
      if (pc.modulus_retention != null) parts.push("模量保持 " + numEnv(pc.modulus_retention, 4));
      if (pc.strength_retention != null) parts.push("强度保持 " + numEnv(pc.strength_retention, 4));
      if (pc.aging_safety_factor != null) parts.push("老化 SF " + numEnv(pc.aging_safety_factor, 3));
      if (pc.is_degraded === true) parts.push("已降级");
      else if (pc.is_degraded === false) parts.push("未降级");
      pcd.appendChild(el("div", "hint", "服役老化: " + parts.join("，")));
    }
    if (pc.abs_wlf_shift_factor != null) {
      pcd.appendChild(el("div", "hint",
        "ABS WLF: 移位因子 " + numEnv(pc.abs_wlf_shift_factor, 4) +
        "，折算时间 " + numEnv(pc.abs_wlf_reduced_time_s, 1) + " s" +
        (pc.abs_viscoelastic_creep_risk != null
          ? "，蠕变风险 " + numEnv(pc.abs_viscoelastic_creep_risk, 4) : "")));
    }
    if (pc.crystallinity_modulus_factor != null) {
      pcd.appendChild(el("div", "hint",
        "退火结晶模量因子: " + numEnv(pc.crystallinity_modulus_factor, 4)));
    }
  }

  // Phase D (buckling / fatigue / fracture / Weibull). All display strings
  // come from the engine's own assessment fields — no JS-side rules.
  var pd = d.phase_d || {};
  var bkEl = $("res-buckling");
  bkEl.textContent = pd.run && pd.buckling_safety_factor != null
    ? numEnv(pd.buckling_safety_factor, 1) : "—";
  // (iter 77) slenderness on hover — probed non-null only under compression
  // (86.6 on the beam fixture); null/absent → no tooltip
  if (typeof pd.buckling_slenderness === "number")
    bkEl.setAttribute("title", "细长比 " + pd.buckling_slenderness.toFixed(1));
  // fatigue_infinite_life is the engine's own discriminator for the 1e10
  // "infinite life" sentinel — only then is ∞ honest; the assessment text
  // carries the engine's caveat (e.g. "Z-direction life is uncalibrated").
  var ftEl = $("res-fatigue");
  ftEl.textContent = !pd.run || pd.fatigue_safety_factor == null ? "—"
    : (pd.fatigue_infinite_life === true ? "∞" : numEnv(pd.fatigue_safety_factor, 1));
  // (iter 77) target-life cycles on hover (echo of --fatigue-cycles; probed
  // non-null 1e5 when fatigue ran under an explicit target)
  if (typeof pd.fatigue_expected_cycles === "number")
    ftEl.setAttribute("title", "目标寿命 " + pd.fatigue_expected_cycles + " 次");
  $("res-fracture").textContent = pd.run && pd.fracture_risk_detected != null
    ? (pd.fracture_risk_detected ? "检出" : "无") : "—";
  $("res-weibull").textContent = pd.weibull_ran && pd.weibull_grade != null
    ? pd.weibull_grade : "—";
  var pdd = $("phase-d-detail");
  pdd.innerHTML = "";
  if (pd.run) {
    [["疲劳判定", pd.fatigue_assessment], ["断裂判定", pd.fracture_assessment],
     ["屈曲警示", pd.buckling_warning]].forEach(function (pair) {
      if (pair[1]) pdd.appendChild(el("div", "hint", pair[0] + ": " + pair[1]));
    });
    if (pd.findley_ran && pd.findley_sf != null) {
      pdd.appendChild(el("div", "hint", "Findley SF: " + num(pd.findley_sf, 1)));
    }
  }

  // orientation candidates (--optimize-orient, engine's own ranking; the
  // table is rendered only when the engine says assessable AND has rows)
  var ori = d.orientation;
  var orBox = $("orient-detail");
  orBox.innerHTML = "";
  // overlay the candidate arrows on the STL preview (no-op for 3MF — the
  // preview degrades to a text note there; stlSetOrient guards shapes)
  stlSetOrient(ori && ori.assessable ? (ori.candidates || null) : null);
  if (ori && ori.assessable && (ori.candidates || []).length) {
    var ot = el("table");
    var oh = el("tr");
    ["Rank", "方向 (x,y,z)", "总代价", "悬空 mm²", "Z 高 mm", "底面 mm²", "表质量 mm²"].forEach(
      function (h) { oh.appendChild(el("th", null, h)); });
    ot.appendChild(oh);
    ori.candidates.slice().sort(function (a, b) { return (a.rank || 0) - (b.rank || 0); })
      .forEach(function (c) {
        var r = el("tr");
        r.appendChild(el("td", null, c.rank != null ? String(c.rank) : "—"));
        r.appendChild(el("td", "num", Array.isArray(c.direction)
          ? c.direction.map(function (v) {
              return v == null ? "—" : Number(v).toFixed(3); }).join(", ")
          : "—"));
        [c.total_cost, c.overhang_cost_mm2, c.z_height_mm,
         c.base_area_mm2, c.surface_quality_mm2].forEach(function (v) {
          r.appendChild(el("td", "num", v == null ? "—" : Number(v).toFixed(2)));
        });
        // row click: highlight that candidate's arrow (red) AND rotate the
        // view so its build direction points screen-up; clicking the
        // selected row again clears the highlight (rotation stays — the
        // user can drag back)
        r.style.cursor = "pointer";
        r.addEventListener("click", function () {
          var on = stlView.orientSel === c.rank;
          stlSelectOrient(on ? 0 : c.rank);
          if (!on && Array.isArray(c.direction)) stlOrientToDir(c.direction);
        });
        ot.appendChild(r);
      });
    orBox.appendChild(el("h2", null, "打印方向候选 <span class=\"tag\">--optimize-orient · 引擎排序</span>"));
    orBox.appendChild(ot);
    orBox.appendChild(el("p", "hint",
      "点击行可在左侧 3D 预览中高亮该候选的打印方向箭头并将视图旋转到该方向朝上（rank 1 金色，其余灰蓝，选中红色；需 STL 预览可用）。"));
  }

  // risks
  var riskBox = $("risk-list");
  riskBox.innerHTML = "";
  var risks = ((d.phase_a || {}).risks) || [];
  if (!risks.length) { riskBox.appendChild(el("p", "muted", "未检测到几何风险。")); }
  risks.forEach(function (r) {
    var item = el("div", "risk-item");
    var sev = Math.max(1, Math.min(3, Math.round(r.severity || 1)));
    item.appendChild(el("span", "sev sev-" + sev, "S" + sev));
    item.appendChild(el("strong", null, r.type + " · "));
    item.appendChild(document.createTextNode(r.description || ""));
    if (r.suggestion) {
      item.appendChild(el("div", "hint", "建议: " + r.suggestion));
    }
    riskBox.appendChild(item);
  });

  // recommendations
  var recBox = $("rec-items");
  recBox.innerHTML = "";
  var items = rec.items || [];
  if (!items.length) { recBox.appendChild(el("p", "muted", "无参数建议。")); }
  items.forEach(function (it) {
    var li = el("div", "risk-item");
    // priority badge (iter 69; unconsumed engine field): displayed, order
    // stays engine-authoritative — the UI never re-sorts recommendations.
    li.appendChild(el("strong", null,
      (typeof it.priority === "number" ? "[P" + it.priority + "] " : "")
      + "[" + it.action + "] " + it.parameter));
    li.appendChild(document.createTextNode(" — " + (it.reason || "")));
    if (it.recommended_value !== null && it.recommended_value !== undefined) {
      li.appendChild(el("div", "hint",
        "当前 " + it.current_value + " → 建议 " + it.recommended_value +
        (it.effect_note ? "；" + it.effect_note : "") +
        (typeof it.tradeoff_note === "string" && it.tradeoff_note
          ? "；权衡: " + it.tradeoff_note : "")));
    }
    recBox.appendChild(li);
  });

  // engine recommendation line (verbatim from CLI stdout — no JS logic)
  var er = $("engine-recommendation");
  var m = /Recommended:.*/.exec(consoleText || "");
  if (m) { er.style.display = ""; er.textContent = m[0]; }
  else { er.style.display = "none"; }

  // candidates table
  var body = $("cand-body");
  body.innerHTML = "";
  var cands = po.candidates || [];
  if (!cands.length) {
    body.appendChild(el("tr", null, "").appendChild(
      el("td", "muted", "无候选（报告缺少 process_optimization 数据）").parentNode));
  }
  cands.forEach(function (c) {
    var tr = el("tr", c.feasible ? "" : "infeasible");
    var goal = c.goal || "balanced";
    var goalTag = el("span", "goal-tag goal-" + goal, goal);
    var est = c.estimate || {};
    var s = c.scores || {};
    function td(v) { var x = el("td", "num", v === null || v === undefined ? "—" : v); tr.appendChild(x); return x; }
    tr.appendChild(el("td", null, c.name));
    var gtd = el("td", null, ""); gtd.appendChild(goalTag); tr.appendChild(gtd);
    tr.appendChild(el("td", null, c.feasible ? "OK" : "No"));
    var p = c.profile || {};
    td(p.infill_pct !== undefined && p.infill_pct !== null ? p.infill_pct + "%" : "—");
    td(p.wall_count !== undefined && p.wall_count !== null ? p.wall_count : "—");
    td(p.print_speed !== undefined && p.print_speed !== null ? p.print_speed + "mm/s" : "—");
    td(s.overall); td(s.strength); td(s.time); td(s.material); td(s.reliability);
    var sfTd = td(c.search_est_safety_factor !== null && c.search_est_safety_factor !== undefined
       ? Math.round(c.search_est_safety_factor) : "—");
    // (iter 71) SF provenance on hover — engine's own raw sf_source string
    // (observed: "extrapolated" on all real candidates). Raw verbatim, no UI
    // interpretation of what "extrapolated" means for trust (null-two-state:
    // absent/null → no tooltip).
    if (typeof c.sf_source === "string" && c.sf_source)
      sfTd.setAttribute("title", "SF 来源: " + c.sf_source);
    td(est.print_time_min != null ? est.print_time_min.toFixed(1) + "min" : "—");
    var volTd = td(est.material_volume_mm3 != null
       ? (est.material_volume_mm3 / 1000).toFixed(1) + "cm3" : "—");
    // (iter 70) richer estimate provenance on hover: mass / filament length /
    // solid volume — unconsumed engine fields with real cost relevance.
    // Tooltip only: values are supplementary, not column-worthy.
    var tips = [];
    // (iter 76 CLEAN) typeof guards: a string here would throw inside toFixed
    // and abort the whole render — skip the segment instead (num() convention)
    if (typeof est.material_mass_g === "number")
      tips.push("材料 " + est.material_mass_g.toFixed(1) + "g");
    if (typeof est.filament_length_mm === "number")
      tips.push("耗材 " + (est.filament_length_mm / 1000).toFixed(1) + "m");
    if (typeof est.solid_volume_mm3 === "number")
      tips.push("实体 " + (est.solid_volume_mm3 / 1000).toFixed(1) + "cm3");
    if (tips.length) volTd.setAttribute("title", tips.join(" · "));
    td(s.quality);
    body.appendChild(tr);
    if (!c.feasible && c.note) {
      var note = el("tr", "infeasible");
      var nd = el("td", "muted", c.note); nd.colSpan = 15;
      note.appendChild(nd);
      body.appendChild(note);
    }
  });
  // support_volume_available === false (iter 69): the engine could not
  // estimate support volume, so material/time columns understate the real
  // print — say so instead of silently showing an optimistic estimate.
  if (d.support_volume_available === false) {
    var sv = el("tr", null);
    var svd = el("td", "muted", "支撑体积不可用 — 材料/时间估算未计入支撑"); svd.colSpan = 15;
    sv.appendChild(svd);
    body.appendChild(sv);
  }

  // init tuning sliders from the values the engine used (except layer_height)
  setParamValue("walls", inp.walls);
  setParamValue("infill", inp.infill_density != null ? (inp.infill_density * 100) : 15);
  setParamValue("pattern", inp.infill_pattern);
  setParamValue("material", inp.material);
  setParamValue("nozzle_diameter", inp.nozzle_mm);
  setParamValue("nozzle_temperature", inp.nozzle_temperature_c);
  setParamValue("bed_temperature", inp.bed_temperature_c);
  setParamValue("print_speed", inp.print_speed_mms);
  setParamValue("cooling_fan", inp.cooling_fan_pct);
  // clear stale locks visually (engine's locked set is authoritative)
  Array.prototype.forEach.call(document.querySelectorAll("input[data-lock]"),
    function (cb) { cb.checked = locks.indexOf(cb.dataset.lock) >= 0; });

  // env sliders re-display what the engine actually used (sent keys only)
  syncEnvFromReport(inp);

    // Orca process suggestions (--orca-suggest). Pure data-driven render:
    // tier/confidence/kb_module come from the engine's own fields. current/
    // recommended can both be null for "set"-style advice (probed 0.21.0) —
    // then only the effect_note carries meaning.
    var orca = d.orca_suggestions || {};
    var oBox = $("orca-list");
    oBox.innerHTML = "";
    var oItems = orca.items || [];
    if (!oItems.length) { oBox.appendChild(el("p", "muted", "报告未含 Orca 建议。")); }
    oItems.forEach(function (it) {
      var row = el("div", "risk-item");
      var tierCls = it.tier === "decision" ? "goal-tag goal-strength" : "goal-tag";
      row.appendChild(el("span", tierCls, it.tier || "—"));
      row.appendChild(document.createTextNode(" "));
      row.appendChild(el("strong", null,
        it.parameter + (it.parameter_cn ? "（" + it.parameter_cn + "）" : "")));
      var bits = [];
      if (it.action) bits.push("[" + it.action + "]");
      if (it.current_value != null && it.recommended_value != null) {
        bits.push("当前 " + it.current_value + " → 建议 " + it.recommended_value);
      }
      if (it.confidence != null) bits.push("置信度 " + Math.round(it.confidence * 100) + "%");
      row.appendChild(document.createTextNode(" " + bits.join("，")));
      if (it.reason) row.appendChild(el("div", "hint", it.reason));
      if (it.effect_note) row.appendChild(el("div", "hint", it.effect_note));
      if (it.kb_module) row.appendChild(el("div", "hint", "grounding: " + it.kb_module));
      oBox.appendChild(row);
    });

    // trust badges — level styling keyed on the engine's own levels; the
  // citation string rides along in the title (hover)
  var trust = d.trust || {};
  $("trust-material").textContent = trust.material || "";
  var tBox = $("trust-list");
  tBox.innerHTML = "";
  var levels = Object.keys(trust.modules || {});
  if (!levels.length) { tBox.appendChild(el("p", "muted", "报告未含可信层数据。")); }
  levels.forEach(function (k) {
    var m = trust.modules[k] || {};
    var cls = m.level === "verified" ? "badge ok"
      : m.level === "partial" ? "badge" : "badge err";
    var row = el("div", "risk-item");
    var b = el("span", cls, m.label || m.level || k);
    b.title = (m.source || "") + (m.decision_safe === false ? " [决策不安全]" : "");
    row.appendChild(b);
    row.appendChild(document.createTextNode(" " + k));
    tBox.appendChild(row);
  });
}
