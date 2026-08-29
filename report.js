"use strict";
// Extracted from index.html (zero-build split, see ROADMAP):
// loaded as a classic <script src> before the main inline script.
// All helpers ($, el, num, numEnv, state, ...) are globals resolved
// at CALL time — this file only declares functions, runs nothing.

// ---------- render ----------
function renderReport(d, consoleText) {
  // a successful render supersedes any --validate refusal listing (④)
  var vr = $("validate-refused");
  if (vr) { vr.style.display = "none"; vr.innerHTML = ""; }
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
  // v0.8.1 artifact downloads share the session gate (a real report implies
  // a live session that can run the artifact analyses)
  var sup = $("btn-supports"), sm = $("btn-stress-modifier");
  if (sup) sup.disabled = false;
  if (sm) sm.disabled = false;
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
  // layer_height: 0.22+ echoes input.layer_height_mm directly; older engines
  // only carried it inside candidate diffs — keep the scrape as the fallback.
  var lh = (inp.layer_height_mm !== null && inp.layer_height_mm !== undefined)
    ? inp.layer_height_mm : null;
  if (lh === null) {
    (po.candidates || []).some(function (c) {
      if (!c.diff || !c.diff.length) return false;
      c.diff.forEach(function (chg) {
        if (chg.key === "layer_height") lh = chg.before;
      });
      return lh !== null;
    });
  }
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

  // v0.8.1 render-gap batch: fields the engine already discloses that the UI
  // never consumed. Every row is null-gated on the engine's own value.
  // fast_mode: the --fast disclosure must be VISIBLE in ④, not just live in
  // the checkbox tooltip — report input.fast_mode is the authoritative echo.
  $("fast-mode-tag").style.display = inp.fast_mode === true ? "" : "none";
  // multi-extruder 3MF: engine analyzes at the slot-1 material only (A-3 v1
  // disclosure; filament_slots present only for >=2-slot files, the note also
  // alone when per-slot files are unreadable but the mirror declares heterogeneity)
  var fnote = $("cp-filament-note");
  fnote.style.display = "none";
  fnote.textContent = "";
  if (Array.isArray(inp.filament_slots) && inp.filament_slots.length >= 2) {
    var slotBits = inp.filament_slots.map(function (s) {
      return "#" + s.slot + " " + (s && s.filament_type || "?");
    }).join("，");
    fnote.textContent = "多喷嘴文件（" + slotBits + "）。" +
      (typeof inp.analysis_material_note === "string"
        ? inp.analysis_material_note : "");
    fnote.style.display = "";
  } else if (typeof inp.analysis_material_note === "string"
             && inp.analysis_material_note) {
    fnote.textContent = inp.analysis_material_note;
    fnote.style.display = "";
  }

  // structural summary (v3: plain field = scalar nominal, band = *_envelope twin)
  var pb = d.phase_b || {};
  $("res-sf").textContent = numEnv(pb.safety_factor, 1, pb.safety_factor_envelope);
  $("res-stress").textContent = fmtUnit(pb.max_stress_mpa, 2, "MPa",
                                        pb.max_stress_mpa_envelope);
  $("res-load").textContent = pb.load_adequacy
    ? (LOAD_LABELS[pb.load_adequacy] || pb.load_adequacy) : "—";
  // color keyed on the engine enum only (LOAD_ADEQUACY_CLASS) — no UI-side
  // thresholds; unknown enum values stay neutral
  $("res-load").className = "v " + (LOAD_ADEQUACY_CLASS[pb.load_adequacy] || "");
  var rec = d.recommendations || {};
  $("res-overall").textContent = rec.overall_score !== null && rec.overall_score !== undefined
    ? rec.overall_score : "—";

  // printability block: quantitative Phase A surface numbers (the risks list
  // below carries only the qualitative regions). Hidden entirely when the
  // block is absent (pre-0.24 engines) or malformed.
  var pr = d.printability;
  var prLine = $("printability-line");
  prLine.innerHTML = "";
  if (pr && typeof pr === "object" && typeof pr.surface_area_mm2 === "number") {
    prLine.style.display = "";
    [["悬垂", pr.overhang_pct != null ? num(pr.overhang_pct, 1) + "%" : null,
      pr.overhang_area_mm2 != null ? "（" + num(pr.overhang_area_mm2, 0) + " mm²）" : ""],
     ["桥接面", pr.bridge_area_mm2 != null ? num(pr.bridge_area_mm2, 0) + " mm²" : null, ""],
     ["表面", pr.surface_area_mm2 != null ? num(pr.surface_area_mm2, 0) + " mm²" : null, ""],
     ["底面接触", pr.bed_contact_area_mm2 != null
       ? num(pr.bed_contact_area_mm2, 0) + " mm²" : null, ""]
    ].forEach(function (p) {
      if (p[1] === null) return;
      prLine.appendChild(el("span", "k", p[0]));
      prLine.appendChild(el("span", "v", p[1] + p[2]));
    });
  } else {
    prLine.style.display = "none";
  }

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
  // input_overrides: the engine REPLACED a requested value (unrecognized enum
  // fallback) — requested vs effective, engine-authored reason verbatim. The
  // UI whitelists enums server-side so this normally stays empty; render it
  // when the engine says otherwise (the engine is the authority on its own
  // replacements, not the UI's whitelist).
  (d.input_overrides || []).forEach(function (o) {
    if (!o || typeof o !== "object") return;
    var item = el("div", "risk-item");
    item.appendChild(el("span", "sev sev-2", "⚠"));
    item.appendChild(document.createTextNode(
      "参数回退: " + (o.parameter || "?") + " 请求 " + o.requested +
      " → 实际 " + o.effective + (o.reason ? "（" + o.reason + "）" : "")));
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
    // v0.8.1 render gaps (all engine-echoed, null-gated):
    // ZZ-SPR discretization error — how adequate the voxel grid actually is
    var ra = pb.resolution_adequacy;
    if (ra && ra.assessed === true && typeof ra.rel_index === "number") {
      pbdBox.appendChild(el("div", "hint",
        "离散误差 (ZZ-SPR): η_rms " + num(ra.eta_rms_mpa, 4) + " / η_max " +
        num(ra.eta_max_mpa, 4) + " MPa（相对指标 " +
        (ra.rel_index * 100).toFixed(1) + "%）"));
    }
    // Tsai-Wu criterion SF alongside the headline Tsai-Hill number
    if (typeof pb.tsai_wu_safety_factor === "number") {
      pbdBox.appendChild(el("div", "hint",
        "Tsai-Wu SF: " + num(pb.tsai_wu_safety_factor, 1)));
    }
    // voxel mesh quality (uniform-cubic voxels are by-construction; the
    // shape string is still rendered verbatim for future element types)
    var mq = pb.mesh_quality;
    if (mq && typeof mq === "object" && typeof mq.element_shape === "string"
        && mq.element_shape) {
      pbdBox.appendChild(el("div", "hint",
        "网格质量: " + mq.element_shape +
        (typeof mq.scaled_jacobian === "number"
          ? " · SJ " + num(mq.scaled_jacobian, 3) : "") +
        (typeof mq.aspect_ratio === "number"
          ? " · AR " + num(mq.aspect_ratio, 3) : "") +
        (mq.by_construction === true ? "（结构保证）" : "")));
    }
    // preconditioner identity + non-positive-pivot fallback count (ic0→Jacobi)
    if (typeof pbd.preconditioner === "string" && pbd.preconditioner) {
      pbdBox.appendChild(el("div", "hint",
        "预条件子: " + pbd.preconditioner +
        (typeof pbd.precond_fallback_count === "number"
         && pbd.precond_fallback_count > 0
          ? "（非正主元回退 ×" + pbd.precond_fallback_count + "）" : "")));
    }
    // --resolution-check (v0.8.1): the engine's own 2x-grid discretization
    // deltas, verbatim numbers — no UI-side judgement of what a delta "means"
    var rc = pb.resolution_check;
    if (rc && typeof rc === "object") {
      pbdBox.appendChild(el("div", "hint",
        "分辨率校验: " + num(rc.coarse_grid, 0) + "→" + num(rc.fine_grid, 0) +
        " 网格，位移 Δ" + num(rc.disp_delta_pct, 1) + "% / 应力 Δ" +
        num(rc.stress_delta_pct, 1) + "%" +
        (rc.fine_converged === true ? "（细网格收敛）"
          : rc.fine_converged === false ? "（细网格未收敛）" : "") +
        (rc.capped === true ? "［已封顶 128］" : "")));
      if (typeof rc.zz_rel_coarse === "number"
          && typeof rc.zz_rel_fine === "number") {
        pbdBox.appendChild(el("div", "hint",
          "分辨率校验 ZZ 相对指标: 粗 " + num(rc.zz_rel_coarse, 3) + " / 细 " +
          num(rc.zz_rel_fine, 3)));
      }
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
        "热应力: " + numEnv(pc.max_thermal_stress_mpa, 3,
                           pc.max_thermal_stress_mpa_envelope) + " MPa" +
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
    // thermal-speed closed loop (v0.8.1 render gap): bed/substrate heat-up
    // vs the material's cap; overheated → the engine's own suggested speed +
    // layer time, rationale verbatim. Fields all engine-authored.
    var ts = pc.thermal_speed;
    if (ts && typeof ts === "object" && ts.assessable === true) {
      pcd.appendChild(el("div", "hint",
        "热-速闭环: 基板温 " + num(ts.t_sub_current_c, 1) + "°C / 上限 " +
        num(ts.cap_c, 1) + "°C" +
        (ts.overheated === true
          ? " — 超温，建议速度 " + num(ts.suggested_speed_mms, 1) +
            " mm/s（层时间 " + num(ts.suggested_layer_time_s, 1) + " s）"
          : " — 未超温") +
        (typeof ts.tier === "string" && ts.tier ? "［" + ts.tier + "］" : "") +
        (typeof ts.rationale === "string" && ts.rationale
          ? "；" + ts.rationale : "")));
    }
    // infill-aware weld bond quality (v0.8.1 render gap): effective bond
    // accounting for the infill structure; disclosure tag verbatim
    var wi = pc.weld_infill_aware;
    if (wi && typeof wi === "object") {
      pcd.appendChild(el("div", "hint",
        "有效键合(含填充): a_eff " + num(wi.a_eff, 4) +
        "，键合质量 " + num(wi.bond_quality_eff, 4) +
        (typeof wi.disclosure === "string" && wi.disclosure
          ? "（" + wi.disclosure + "）" : "")));
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
    // skipped sub-modules with the engine's own reasons (v0.8.1 render gap —
    // previously only visible if the user opened the raw console)
    (pd.skipped_reasons || []).forEach(function (r) {
      if (typeof r === "string" && r)
        pdd.appendChild(el("div", "hint", "跳过: " + r));
    });
    // fatigue life numbers (v0.8.1): the estimated life in cycles + per-cycle
    // damage. fatigue_infinite_life already turns the headline cell into ∞;
    // these rows carry the raw estimate either way.
    if (typeof pd.fatigue_life_cycles === "number") {
      pdd.appendChild(el("div", "hint",
        "疲劳寿命估算: " + pd.fatigue_life_cycles.toExponential(2) + " 次" +
        (typeof pd.fatigue_damage_per_cycle === "number"
          ? "（损伤/次 " + pd.fatigue_damage_per_cycle.toExponential(2) + "）" : "")));
    }
    // Weibull numbers (v0.8.1): R/Pf are fractions in the JSON (console
    // prints %) — ×100 is display formatting, same convention as infill.
    if (pd.weibull_ran) {
      var wb = "Weibull: R " +
        num(pd.weibull_R != null ? pd.weibull_R * 100 : null, 1) + "% / Pf " +
        num(pd.weibull_Pf != null ? pd.weibull_Pf * 100 : null, 1) + "%";
      if (typeof pd.weibull_size_factor === "number")
        wb += "，尺寸因子 " + num(pd.weibull_size_factor, 3);
      if (typeof pd.weibull_sigma_eff_mpa === "number")
        wb += "，σ_eff " + num(pd.weibull_sigma_eff_mpa, 1) + " MPa";
      pdd.appendChild(el("div", "hint", wb));
    }
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

  // mesh topology audit (engine 0.22+, iter 666/672/699 contract: always
  // disclosed; the tier decides ENFORCEMENT only). Advanced-only details —
  // diagnostic, not a tuning result.
  var topoBox = $("mesh-topology-box");
  if (topoBox) {
    var topo = d.mesh_topology;
    if (!topo || typeof topo !== "object" || topo.analyzed !== true) {
      topoBox.style.display = "none";  // pre-0.22 engine: block absent
    } else {
      topoBox.style.display = "";
      $("mesh-topo-tier").textContent = topo.validation_tier || "standard";
      var mtd = $("mesh-topology-detail");
      mtd.innerHTML = "";
      (topo.validation_findings || []).forEach(function (f) {
        var item = el("div", "risk-item");
        item.appendChild(el("span", "sev " + (f.fatal ? "sev-1" : "sev-2"),
                            f.fatal ? "致命" : "提示"));
        item.appendChild(document.createTextNode(
          (f.code || "?") + (typeof f.count === "number" ? " ×" + f.count : "")));
        mtd.appendChild(item);
      });
      var mtKv = el("div", "kv");
      [["边界边", topo.boundary_edges], ["非流形边", topo.nonmanifold_edges],
       ["非流形顶点", topo.nonmanifold_vertices], ["退化边", topo.degenerate_edges],
       ["朝向不一致面", topo.inconsistent_faces],
       ["焊合顶点/边", topo.welded_vertices != null && topo.welded_undirected_edges != null
         ? topo.welded_vertices + "/" + topo.welded_undirected_edges : null],
       ["焊合部件", topo.welded_components],
       ["欧拉示性数 χ", topo.euler_characteristic],
       ["修复面数", topo.repaired_faces],
       ["不可定向部件", topo.non_orientable_components]].forEach(function (p) {
        mtKv.appendChild(el("span", "k", p[0]));
        mtKv.appendChild(el("span", "v",
          p[1] === null || p[1] === undefined ? "—" : String(p[1])));
      });
      mtd.appendChild(mtKv);
      mtd.appendChild(el("p", "hint",
        "signed volume " + num(topo.signed_volume, 1) + " mm³" +
        (topo.manifold === true ? " · 流形" : topo.manifold === false ? " · 非流形" : "") +
        (topo.consistently_oriented === true ? " · 朝向一致"
          : topo.consistently_oriented === false ? " · 朝向不一致（可用③b「修复网格朝向」）" : "") +
        "。standard 档仅披露不拒绝。"));
    }
  }

  // machine limits (engine 0.22+ iter 663/699): identified machine, source,
  // firmware ceilings and any candidate clamps applied to the suggestions
  var mlBox = $("machine-limits-box");
  if (mlBox) {
    var ml = d.machine_limits;
    if (!ml || typeof ml !== "object") {
      mlBox.style.display = "none";  // pre-0.22 engine / no machine attempted
    } else {
      mlBox.style.display = "";
      $("machine-limits-src").textContent =
        (ml.identified ? String(ml.identified) : "未识别") +
        (ml.source ? " · " + ml.source : "");
      var mld = $("machine-limits-detail");
      mld.innerHTML = "";
      if (!ml.identified) {
        mld.appendChild(el("div", "hint",
          "无机器约束（③b 可手动选型号，或让 3MF 的 printer_model 自动识别）。"));
      } else {
        var mlKv = el("div", "kv");
        // layer band only when the engine actually knows it (0/0 = unknown
        // for this machine row — "0–0 mm" would be a lie, not a disclosure)
        [["最高速度", ml.max_speed_mm_s != null && ml.max_speed_mm_s > 0
           ? ml.max_speed_mm_s + " mm/s" : null],
         ["层高带", (ml.min_layer_mm != null && ml.max_layer_mm != null
           && ml.max_layer_mm > 0)
           ? ml.min_layer_mm + "–" + ml.max_layer_mm + " mm" : null]].forEach(function (p) {
          mlKv.appendChild(el("span", "k", p[0]));
          mlKv.appendChild(el("span", "v", p[1] || "—"));
        });
        mld.appendChild(mlKv);
      }
      (ml.clamps || []).forEach(function (c) {
        var item = el("div", "risk-item");
        item.appendChild(el("span", "sev sev-2", "钳制"));
        item.appendChild(document.createTextNode(
          (c.parameter || "?") + ": " + c.from + " → " + c.to +
          "（候选/建议被固件上限收敛）"));
        mld.appendChild(item);
      });
    }
  }

  // appearance block (v0.8.1, --appearance; absent-not-null: the whole box
  // stays hidden when the flag was not passed or the engine predates it).
  // All assessment strings are the engine's own — rendered verbatim.
  var apBox = $("appearance-box");
  if (apBox) {
    var ap = d.appearance;
    if (!ap || typeof ap !== "object") {
      apBox.style.display = "none";
    } else {
      apBox.style.display = "";
      var apd = $("appearance-detail");
      apd.innerHTML = "";
      var apKv = el("div", "kv");
      [["光泽", ap.gloss_assessment], ["纹理", ap.texture_assessment],
       ["层纹", ap.layer_line_assessment], ["台阶纹", ap.stair_step_assessment],
       ["表面翘曲", ap.surface_warp_assessment]].forEach(function (p) {
        if (typeof p[1] === "string" && p[1]) {
          apKv.appendChild(el("span", "k", p[0]));
          apKv.appendChild(el("span", "v", p[1]));
        }
      });
      apd.appendChild(apKv);
      if (ap.stair_stepping_area_pct != null) {
        apd.appendChild(el("div", "hint",
          "台阶纹占比: " + num(ap.stair_stepping_area_pct, 1) + "%"));
      }
      if (ap.layer_diffusion_quality != null) {
        apd.appendChild(el("div", "hint",
          "层间扩散质量: " + num(ap.layer_diffusion_quality, 2)));
      }
      if (ap.crystallinity_pct != null) {
        apd.appendChild(el("div", "hint",
          "结晶度: " + num(ap.crystallinity_pct, 1) + "%"));
      }
      if (ap.residual_stress_assessable === true
          && ap.max_residual_stress_mpa != null) {
        apd.appendChild(el("div", "hint",
          "最大残余应力: " + num(ap.max_residual_stress_mpa, 3) + " MPa"));
      }
      var apBits = [];
      if (typeof ap.shear_rate_1_s === "number")
        apBits.push("剪切率 " + num(ap.shear_rate_1_s, 0) + " 1/s");
      if (typeof ap.apparent_viscosity_Pas === "number")
        apBits.push("表观黏度 " + num(ap.apparent_viscosity_Pas, 0) + " Pa·s");
      if (ap.sharkskin_risk === true) apBits.push("鲨鱼皮风险: 检出");
      if (apBits.length)
        apd.appendChild(el("div", "hint", apBits.join("，")));
      // calibration honesty flags (engine's own booleans, shown only when
      // they carry information)
      var apCal = [];
      if (ap.viscosity_calibrated === false) apCal.push("黏度未标定");
      if (ap.die_swell_calibrated === false) apCal.push("胀大未标定");
      if (ap.temperature_corrected === true) apCal.push("已做温度修正");
      if (apCal.length)
        apd.appendChild(el("div", "hint", "标定状态: " + apCal.join("，")));
      (ap.suggestions || []).forEach(function (s) {
        if (typeof s === "string" && s)
          apd.appendChild(el("div", "hint", "建议: " + s));
      });
    }
  }

  // rheology block (v0.8.1, --rheology; absent-not-null like appearance)
  var rhBox = $("rheology-box");
  if (rhBox) {
    var rh = d.rheology;
    if (!rh || typeof rh !== "object") {
      rhBox.style.display = "none";
    } else {
      rhBox.style.display = "";
      var rhd = $("rheology-detail");
      rhd.innerHTML = "";
      var rhKv = el("div", "kv");
      [["剪切率", rh.shear_rate_1_s != null
         ? num(rh.shear_rate_1_s, 0) + " 1/s" : null],
       ["表观黏度", rh.apparent_viscosity_Pas != null
         ? num(rh.apparent_viscosity_Pas, 0) + " Pa·s" : null],
       ["喷嘴压力降", rh.pressure_drop_MPa != null
         ? num(rh.pressure_drop_MPa, 2) + " MPa" : null],
       ["挤出稳定性", rh.is_stable === true ? "稳定"
         : rh.is_stable === false ? "不稳定" : null],
       ["胀大比", rh.die_swell_ratio != null
         ? num(rh.die_swell_ratio, 3) : null]].forEach(function (p) {
        if (p[1] === null || p[1] === undefined) return;
        rhKv.appendChild(el("span", "k", p[0]));
        rhKv.appendChild(el("span", "v", String(p[1])));
      });
      rhd.appendChild(rhKv);
      if (typeof rh.weld_bond_assessment === "string" && rh.weld_bond_assessment) {
        rhd.appendChild(el("div", "hint",
          "层间键合: " + rh.weld_bond_assessment +
          (rh.weld_bond_quality != null
            ? "（质量 " + num(rh.weld_bond_quality, 2) +
              (rh.weld_bsf_saturated === true ? "，BSF 已饱和" : "") + "）" : "")));
      }
      if (typeof rh.corner_assessment === "string" && rh.corner_assessment) {
        rhd.appendChild(el("div", "hint", "转角: " + rh.corner_assessment));
      }
      var rhCal = [];
      if (rh.viscosity_calibrated === false) rhCal.push("黏度未标定");
      if (rh.die_swell_calibrated === false) rhCal.push("胀大未标定");
      if (rh.temperature_corrected === true)
        rhCal.push("已按 " + (rh.calibrated_at_c != null
          ? num(rh.calibrated_at_c, 0) + "°C" : "") + " 修正");
      if (rhCal.length)
        rhd.appendChild(el("div", "hint", "标定状态: " + rhCal.join("，")));
      if (typeof rh.warning === "string" && rh.warning) {
        var rw = el("div", "risk-item");
        rw.appendChild(el("span", "sev sev-2", "⚠"));
        rw.appendChild(document.createTextNode("流变: " + rh.warning));
        rhd.appendChild(rw);
      }
    }
  }

  // est_error_profile block (v0.8.1, --est-error-profile). Consumer trap
  // per docs/schema/report-v3.md: err semantics DIFFER by group —
  // elastic rows carry a real extrapolation error ratio (1.0 = perfect),
  // process rows are rerun-blind so err IS the proxy's est_ratio (a caliber
  // value). The group column stays visible and the engine's own
  // process_dims_note is rendered verbatim — the UI does not average or
  // reinterpret anything.
  var eeBox = $("esterr-box");
  if (eeBox) {
    var ee = d.est_error_profile;
    if (!ee || typeof ee !== "object" || !Array.isArray(ee.rows)
        || !ee.rows.length) {
      eeBox.style.display = "none";  // flag not passed / ran:false / no rows
    } else {
      eeBox.style.display = "";
      var eed = $("esterr-detail");
      eed.innerHTML = "";
      if (ee.ran === false) {
        eed.appendChild(el("p", "muted", "引擎已请求但未能评估任何维度。"));
      }
      var et = el("table");
      var eh = el("tr");
      ["维度", "组", "估算比", "真实比", "误差比"].forEach(function (h) {
        eh.appendChild(el("th", null, h)); });
      et.appendChild(eh);
      ee.rows.forEach(function (r) {
        if (!r || typeof r !== "object") return;
        var row = el("tr");
        row.appendChild(el("td", null, r.dim || "—"));
        row.appendChild(el("td", null, r.group || "—"));
        // negatives are the engine's "not assessable" clamp (report-v3.md:
        // "writer clamps negatives to -1", real_ratio=-1 for rerun-blind
        // process dims) — render as —, never as a bogus negative ratio
        [r.est_ratio, r.real_ratio, r.err].forEach(function (v) {
          row.appendChild(el("td", "num",
            v === null || v === undefined || v < 0 ? "—" : Number(v).toFixed(3)));
        });
        et.appendChild(row);
      });
      eed.appendChild(et);
      if (typeof ee.process_dims_note === "string" && ee.process_dims_note) {
        eed.appendChild(el("p", "hint", ee.process_dims_note));
      }
    }
  }

  // calibration block (v0.8.1, --cal-time/--cal-mass): the engine's own
  // disclosure of its estimate calibration — applied state, factors,
  // measured vs predicted, and any reason/notes verbatim. Present whenever
  // a --cal-* flag was requested (an inapplicable calibration is
  // information, not silence — engine C6 shape).
  var calBox = $("calibration-box");
  if (calBox) {
    var cal = d.calibration;
    if (!cal || typeof cal !== "object") {
      calBox.style.display = "none";
    } else {
      calBox.style.display = "";
      var cd = $("calibration-detail");
      cd.innerHTML = "";
      var calKv = el("div", "kv");
      [["状态", cal.applied === true ? "已应用"
         : cal.applied === false ? "未应用" : null],
       ["时间因子", typeof cal.time_factor === "number"
         ? num(cal.time_factor, 4) : null],
       ["质量因子", typeof cal.mass_factor === "number"
         ? num(cal.mass_factor, 4) : null],
       ["实测时长", typeof cal.measured_time_s === "number"
         ? num(cal.measured_time_s, 0) + " s" : null],
       ["实测质量", typeof cal.measured_mass_g === "number"
         ? num(cal.measured_mass_g, 1) + " g" : null],
       ["引擎预测时长", typeof cal.predicted_time_s === "number"
         ? num(cal.predicted_time_s, 0) + " s" : null],
       ["引擎预测质量", typeof cal.predicted_mass_g === "number"
         ? num(cal.predicted_mass_g, 1) + " g" : null]].forEach(function (p) {
        if (p[1] === null || p[1] === undefined) return;
        calKv.appendChild(el("span", "k", p[0]));
        calKv.appendChild(el("span", "v", String(p[1])));
      });
      cd.appendChild(calKv);
      if (typeof cal.reason === "string" && cal.reason) {
        cd.appendChild(el("div", "hint", "原因: " + cal.reason));
      }
      (cal.notes || []).forEach(function (n) {
        if (typeof n === "string" && n)
          cd.appendChild(el("div", "hint", "注: " + n));
      });
    }
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
    // v0.8.1 render gaps: confidence + the engine's own per-item estimates
    // (SF / max stress under the suggested value) — previously dropped
    if (typeof it.confidence === "number") {
      li.appendChild(el("div", "hint",
        "置信度 " + Math.round(it.confidence * 100) + "%"));
    }
    if (typeof it.est_safety_factor === "number"
        || typeof it.est_max_stress === "number") {
      li.appendChild(el("div", "hint",
        "建议值下估算: SF " + num(it.est_safety_factor, 1) + " / 最大应力 " +
        num(it.est_max_stress, 3) + " MPa"));
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
    var nameTd = el("td", null, c.name);
    // v0.8.1: candidate estimate provenance on hover. Same-name trap
    // (engine iter 567): top-level `calibrated` is the SF-extrapolation
    // flag (stays false here) — the cal-time/mass calibration lives in
    // `estimate.calibrated`. policy_applied + verification_dimensions are
    // top-level engine fields. All rendered verbatim; absent → no tooltip.
    (function (cell) {
      var tags = [];
      if (c.estimate && c.estimate.calibrated === true)
        tags.push("已校准估算（cal-time/mass）");
      if (c.policy_applied === false) tags.push("未应用策略");
      if (Array.isArray(c.verification_dimensions) && c.verification_dimensions.length)
        tags.push("验证维: " + c.verification_dimensions.join("/"));
      if (tags.length) cell.setAttribute("title", tags.join(" · "));
    })(nameTd);
    tr.appendChild(nameTd);
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
  // v0.8 params (engine 0.22+ echoes; setParamValue skips null/undefined so
  // pre-0.22 engines without these fields leave the sliders untouched)
  setParamValue("layer_height", inp.layer_height_mm);
  setParamValue("z_ratio", inp.z_strength_ratio);
  // fill angle: requested (raw CLI value) echoes unconditionally; what the
  // model ACTUALLY rotated is disclosed separately as applied_fill_angle_deg
  setParamValue("fill_angle", inp.requested_fill_angle_deg);
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
