"use strict";
// Extracted from index.html (zero-build split, see ROADMAP):
// loaded as a classic <script src> before the main inline script.
// All helpers ($, el, num, numEnv, state, ...) are globals resolved
// at CALL time — this file only declares functions, runs nothing.

// ---------- v0.10 static term glossary ----------
// Plain-language hover explanations for the engine's technical vocabulary.
// STATIC COPY ONLY (sources: docs/parameter-research-2026-09.md consensus +
// engine schema docs) — never derived from, nor overriding, engine output.
var TERM_INFO = {
  hill48: "Hill48 屈服准则：考虑 FDM 打印各向异性（X/Y/Z 方向强度不同）的屈服判定，比各向同性的 von Mises 更贴近层间真实强度。",
  weibull: "Weibull 统计强度：把材料内部缺陷分布计入的可靠性模型。Pf=失效概率，R=可靠度；等级 A+ 为最优。",
  // (v0.30) a standalone `interlaminar` entry used to live here — deleted
  // as a dead key: zero consumers (termQ sites are hill48/thermal_stress/
  // delamination/weibull only). The layer-strength concept stays alive
  // inside the delamination text below.
  delamination: "分层（delamination）：层间结合失效，载荷沿层界面拉开——FDM 件在 Z 向载荷下的典型失效模式；与层间强度 Z/XY 直接相关。",
  thermal_stress: "热应力：打印过程不均匀冷却留下的残余应力；服役温度变化会叠加到载荷应力上（引擎标注 (上界) 时为保守估计）。",
};

// v0.28 term popup — the touch-discoverable sibling of the title hover.
// Reads the TRIGGER's own title attribute (single source: desktop hover and
// card body can never drift; EN mode reuses the _langAttrs translation the
// MutationObserver already applies to [title] elements — no second hop).
// Zero dependencies (red line 1). Singleton on document.body; renderReport
// calls closeTermPop() so a re-render (which rebuilds the trigger rows)
// never leaves an orphaned card. vm-stub safety: report.js only declares
// functions — the listeners are installed lazily on first open, and every
// touch on document/body/getBoundingClientRect is guarded (the render_check
// stub has none of them).
var _termPop = null, _termPopWired = false;
function closeTermPop() {
  if (_termPop && _termPop.parentNode && _termPop.parentNode.removeChild)
    _termPop.parentNode.removeChild(_termPop);
  _termPop = null;
}
function openTermPop(btn) {
  if (typeof document === "undefined" || !document.body
      || !document.createElement) return;
  var text = btn && btn.title;
  if (typeof text !== "string" || !text) return;
  closeTermPop();  // only one card at a time
  if (!_termPopWired && document.addEventListener) {
    _termPopWired = true;
    // click-outside: the same click that OPENED the card has the .term-q
    // trigger as its target — must not insta-close (bubbling race)
    document.addEventListener("click", function (ev) {
      var t = ev.target;
      if (_termPop && t && !(t.closest && t.closest("#term-pop"))
          && !(t.closest && t.closest(".term-q"))) closeTermPop();
    });
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") closeTermPop();
    });
  }
  _termPop = document.createElement("div");
  _termPop.id = "term-pop";
  var body = document.createElement("div");
  body.className = "term-pop-body";
  body.textContent = text;  // locale-correct by construction (see above)
  _termPop.appendChild(body);
  if (btn.getBoundingClientRect) {
    var r = btn.getBoundingClientRect();
    _termPop.style.left =
      Math.max(8, Math.min(r.left, (window.innerWidth || 1200) - 320)) + "px";
    _termPop.style.top = (r.bottom + 8) + "px";
  }
  document.body.appendChild(_termPop);
}
// "?" affordance for a glossary term: title carries the explanation (hover
// on desktop, popup text on click — one string, both surfaces).
function termQ(key) {
  var b = el("button", "term-q", "?");
  b.type = "button";
  b.title = TERM_INFO[key] || "";
  b.onclick = function () { openTermPop(b); };
  return b;
}

// v0.16 (engine 0.26): recommendation motivation tokens → zh display label.
// The token is an engine enum (same mapping practice as LOAD_LABELS / goal
// tags — chrome, not engine prose); null = engine-declared "unclassified"
// (safety margin / material window) → no badge. Unknown future tokens fall
// through to the raw string so a newer engine never breaks this UI
// (WEBUI-MIGRATION.md: closed set, consumers must tolerate unknowns).
var MOTIVATION_LABELS = {
  layer_bond: "层间键合",
  shrinkage_gradient: "收缩梯度",
  thinwall_shape: "薄壁成形",
  appearance_gloss: "外观光泽",
};
// v0.16 (engine 0.26): suppression reason_codes → plain-language chrome.
// detail stays engine-authored verbatim (skip-flagged at the render site).
// Unknown codes render raw — forward compatibility over completeness.
var SUPPRESSION_REASONS = {
  solid_part_uniform_scaling:
    "体素分辨率不足，薄特征读作实心 — 提高网格精度（--grid）后重跑可解除",
  machine_nozzle_variant_unavailable:
    "当前机型无该喷嘴变体 — 更换喷嘴/机型后可解除",
};

// ---------- v0.19 numeric denoise (round B) ----------
// Candidate-table cells: engine floats carry arithmetic noise (observed
// 70.712937, report-v3.json) that reads as fake precision. 6 significant
// digits kills the noise while keeping real distinctions — 71.812937 vs
// 71.814511 stay 71.8129 vs 71.8145 (fixed-decimal rounding was explicitly
// rejected: it collapses that pair — ROADMAP v0.18「明确不做」).
// Non-numbers pass through untouched (iter 76: a string here threw inside
// toFixed — same guard convention).
function fmtSig(x) {
  return typeof x !== "number" || !isFinite(x)
    ? x : parseFloat(Number(x).toPrecision(6));
}

// ---------- v0.27 verdict rank + auto-tune decision ----------
// verdictRank: the v0.22 hero worst-of edge color, extracted top-level so
// the auto-tune loop driver (index.html) reuses the SAME display mapping
// instead of a drifting copy. Engine signals only (emoji chars in the
// engine-authored assessment, structured phase_d warning, SF<1) — pure
// display mapping, no UI-side re-scoring (red line 2; same precedent as the
// SF band colors). 0 = engine wrote no rank-bearing signal.
//   rank 1 ✅ emoji < rank 2 ⚠ emoji / phase_d buckling|fracture warning
//   < rank 3 ❌ emoji / SF < 1
function safetyFactorScalar(pb) {
  if (!pb) return null;
  var sf = pb.safety_factor;
  if (sf !== null && sf !== undefined && typeof sf === "object")
    return sf.nominal;
  return sf;
}
function verdictRank(pb, pd) {
  var txt = (pb && typeof pb.assessment === "string") ? pb.assessment : "";
  var rank = txt.indexOf("❌") >= 0 ? 3
    : txt.indexOf("⚠") >= 0 ? 2
    : txt.indexOf("✅") >= 0 ? 1 : 0;
  // structured phase_d warning present? Engine payload, not the mirror DOM
  // (immune to DOM textContent semantics in vm stubs — v0.22 lesson)
  var hasPdWarn = !!((typeof pd !== "undefined" && pd)
              && (pd.buckling_warning
                  || (pd.fracture_risk_detected === true && pd.fracture_assessment)));
  if (hasPdWarn) rank = Math.max(rank, 2);
  var sf = safetyFactorScalar(pb);
  if (typeof sf === "number" && isFinite(sf) && sf < 1)
    rank = Math.max(rank, 3);
  return rank;
}

// Auto-tune round cap. Each round is a FULL engine run, so the loop is
// bounded for cost as much as for patience (a novice clicking away at 3
// rounds has seen the pattern; the stop toast invites a fresh click to
// continue — product decision, not an engine contract).
var AUTO_TUNE_MAX_ROUNDS = 3;

// autoTuneStepDecision — the pure per-round policy of the v0.27 auto-tune
// loop (driver in index.html). Pure so render_check can exercise every stop
// shape with synthetic inputs; the driver owns toasts/DOM/analyze. Returns:
//   {action:"stop", code:"safe"|"exhausted"|"unchanged"|"cap"}
//   {action:"apply", sig, picked}
// Stop precedence: verdict safe → cap reached → no applicable suggestions →
// suggestion signature unchanged (oscillation guard: engine re-suggesting
// the same key:value pair after a round would ping-pong within the cap).
function autoTuneStepDecision(opts) {
  var rank = opts.rank, round = opts.round, maxRounds = opts.maxRounds,
      lastSig = opts.lastSig, applyable = opts.applyable || [];
  if (rank === 1) return { action: "stop", code: "safe" };
  if (round >= maxRounds) return { action: "stop", code: "cap" };
  var picked = [];
  for (var i = 0; i < applyable.length; i++)
    if (applyable[i] && applyable[i].applicable) picked.push(applyable[i]);
  if (!picked.length) return { action: "stop", code: "exhausted" };
  var bits = [];
  for (var j = 0; j < picked.length; j++)
    bits.push(picked[j].ui_key + ":" + picked[j].recommended_value);
  bits.sort();
  var sig = bits.join("|");
  if (sig === lastSig) return { action: "stop", code: "unchanged" };
  return { action: "apply", sig: sig, picked: picked };
}

// ---------- render ----------
function renderReport(d, consoleText, applyable) {
  // v0.28: a re-render rebuilds the term-popup trigger rows — no orphaned
  // card may survive pointing at a dead trigger
  closeTermPop();
  // v0.10: a successful render supersedes the empty-state guide (「分析结果」) and any
  // error card from a previous failed run
  var eg = $("empty-guide");
  if (eg) eg.style.display = "none";
  var aerr = $("analyze-error");
  if (aerr) { aerr.style.display = "none"; aerr.innerHTML = ""; }
  // a successful render supersedes any --validate refusal listing (「分析结果」)
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
  // v0.16 HTML snapshot shares the JSON download's gate: a rendered result
  // is what gets serialized, so it unlocks on the same successful render
  var snapBtn = $("btn-snapshot");
  if (snapBtn) snapBtn.disabled = false;
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
  // fast_mode: the --fast disclosure must be VISIBLE in 「分析结果」, not just live in
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
    // prefix is UI chrome (translatable); the engine's analysis_material_note
    // is engine-authored prose → skip span (textContent identical to the old
    // single-string form)
    fnote.appendChild(document.createTextNode("多喷嘴文件（" + slotBits + "）。"));
    if (typeof inp.analysis_material_note === "string"
        && inp.analysis_material_note) {
      var noteSpan = el("span", null, inp.analysis_material_note);
      noteSpan.setAttribute("data-i18n-skip", "1");
      fnote.appendChild(noteSpan);
    }
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
  // v0.9 verdict line: the engine's own phase_b assessment string, verbatim,
  // under the KPI cards (engine-authored conclusion; no UI-invented summary).
  // Hidden when absent (older engines) — absent-not-null.
  var pbaBox = $("phase-b-assessment");
  if (pbaBox) {
    if (typeof pb.assessment === "string" && pb.assessment) {
      pbaBox.textContent = "结论: " + pb.assessment;
      pbaBox.style.display = "";
    } else {
      pbaBox.style.display = "none";
    }
  }

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
    item.setAttribute("data-i18n-skip", "1");
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
    item.setAttribute("data-i18n-skip", "1");
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
  // v0.9 verdict-first split: solver internals (CG convergence / adaptive
  // grid / ZZ-SPR discretization / voxel mesh quality / preconditioner /
  // --resolution-check deltas) render into a collapsed advanced-only
  // <details> box; user-facing SF/criterion lines stay in the main flow.
  // Wrapper is reset to hidden EVERY render (absent-not-null: no internals
  // data → no box), same lifecycle as the phase boxes above.
  var pbiBox = $("phase-b-internals");
  if (pbiBox) {
    pbiBox.innerHTML = "";
    if (pbd.cg_converged === true) {
      pbiBox.appendChild(el("div", "hint",
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
      pbiBox.appendChild(el("div", "hint",
        "网格: " + pg.nx + "×" + pg.ny + "×" + pg.nz +
        (typeof pg.nodes === "number" ? "（" + pg.nodes + " 节点）" : "")));
    }
    // v0.8.1 render gaps (all engine-echoed, null-gated):
    // ZZ-SPR discretization error — how adequate the voxel grid actually is
    var ra = pb.resolution_adequacy;
    if (ra && ra.assessed === true && typeof ra.rel_index === "number") {
      pbiBox.appendChild(el("div", "hint",
        "离散误差 (ZZ-SPR): η_rms " + num(ra.eta_rms_mpa, 4) + " / η_max " +
        num(ra.eta_max_mpa, 4) + " MPa（相对指标 " +
        (ra.rel_index * 100).toFixed(1) + "%）"));
    }
    // voxel mesh quality (uniform-cubic voxels are by-construction; the
    // shape string is still rendered verbatim for future element types)
    var mq = pb.mesh_quality;
    if (mq && typeof mq === "object" && typeof mq.element_shape === "string"
        && mq.element_shape) {
      pbiBox.appendChild(el("div", "hint",
        "网格质量: " + mq.element_shape +
        (typeof mq.scaled_jacobian === "number"
          ? " · SJ " + num(mq.scaled_jacobian, 3) : "") +
        (typeof mq.aspect_ratio === "number"
          ? " · AR " + num(mq.aspect_ratio, 3) : "") +
        (mq.by_construction === true ? "（结构保证）" : "")));
    }
    // preconditioner identity + non-positive-pivot fallback count (ic0→Jacobi)
    if (typeof pbd.preconditioner === "string" && pbd.preconditioner) {
      pbiBox.appendChild(el("div", "hint",
        "预条件子: " + pbd.preconditioner +
        (typeof pbd.precond_fallback_count === "number"
         && pbd.precond_fallback_count > 0
          ? "（非正主元回退 ×" + pbd.precond_fallback_count + "）" : "")));
    }
    // --resolution-check (v0.8.1): the engine's own 2x-grid discretization
    // deltas, verbatim numbers — no UI-side judgement of what a delta "means"
    var rc = pb.resolution_check;
    if (rc && typeof rc === "object") {
      pbiBox.appendChild(el("div", "hint",
        "分辨率校验: " + num(rc.coarse_grid, 0) + "→" + num(rc.fine_grid, 0) +
        " 网格，位移 Δ" + num(rc.disp_delta_pct, 1) + "% / 应力 Δ" +
        num(rc.stress_delta_pct, 1) + "%" +
        (rc.fine_converged === true ? "（细网格收敛）"
          : rc.fine_converged === false ? "（细网格未收敛）" : "") +
        (rc.capped === true ? "［已封顶 128］" : "")));
      if (typeof rc.zz_rel_coarse === "number"
          && typeof rc.zz_rel_fine === "number") {
        pbiBox.appendChild(el("div", "hint",
          "分辨率校验 ZZ 相对指标: 粗 " + num(rc.zz_rel_coarse, 3) + " / 细 " +
          num(rc.zz_rel_fine, 3)));
      }
    }
    var pbsWrap = $("phase-b-solver");
    if (pbsWrap) pbsWrap.style.display = pbiBox.childNodes.length ? "" : "none";
  }
  if (pbdBox) {
    pbdBox.innerHTML = "";
    // Tsai-Wu criterion SF alongside the headline Tsai-Hill number —
    // a safety factor stays in the main flow (verdict-first: only solver
    // internals moved out, never conclusions)
    if (typeof pb.tsai_wu_safety_factor === "number") {
      pbdBox.appendChild(el("div", "hint",
        "Tsai-Wu SF: " + num(pb.tsai_wu_safety_factor, 1)));
    }
  }
  if (pbd.cg_converged === false) {
    var w1 = el("div", "risk-item");
    // no data-i18n-skip here (unlike w2/w3 below): this line is fully
    // static UI copy — zero engine-authored content — so EN mode may
    // translate it (keyed in LANG_EN)
    w1.appendChild(el("span", "sev sev-2", "⚠"));
    w1.appendChild(document.createTextNode(
      "Phase B: 线性求解器未收敛 — 数值结果不可靠"));
    warnBox.appendChild(w1);
  }
  if (typeof pbd.part_visibility_warning === "string" && pbd.part_visibility_warning) {
    var w2 = el("div", "risk-item");
    w2.setAttribute("data-i18n-skip", "1");
    w2.appendChild(el("span", "sev sev-2", "⚠"));
    w2.appendChild(document.createTextNode("Phase B: " + pbd.part_visibility_warning));
    warnBox.appendChild(w2);
  }
  if (typeof pbd.warning === "string" && pbd.warning) {
    var w3 = el("div", "risk-item");
    w3.setAttribute("data-i18n-skip", "1");
    w3.appendChild(el("span", "sev sev-2", "⚠"));
    w3.appendChild(document.createTextNode("Phase B: " + pbd.warning));
    warnBox.appendChild(w3);
  }

  // v0.22: the standalone warnings-card count/toggle is gone — warnings and
  // geometric risks share ONE 「风险与提示」 card (#alerts-card) whose header
  // is written in the risks section below (both counts are known there). The
  // list itself stays visible; the #alerts-body wrapper owns the fold.
  warnBox.style.display = "";

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
  // v0.9 verdict-first split (mirror of phase-b): constitutive/model-internal
  // numbers (Hill48 yield index, ABS WLF shift, annealing crystallinity,
  // infill-aware weld internals) → collapsed advanced-only details; SF and
  // risk lines stay in the main flow. Reset to hidden EVERY render.
  var pciBox = $("phase-c-internals");
  if (pciBox) {
    pciBox.innerHTML = "";
    if (pc.run && pc.max_hill48_yield_index != null) {
      pciBox.appendChild(el("div", "hint",
        "Hill48 屈服指数: " + numEnv(pc.max_hill48_yield_index, 4)));
    }
    if (pc.run && pc.abs_wlf_shift_factor != null) {
      pciBox.appendChild(el("div", "hint",
        "ABS WLF: 移位因子 " + numEnv(pc.abs_wlf_shift_factor, 4) +
        "，折算时间 " + numEnv(pc.abs_wlf_reduced_time_s, 1) + " s" +
        (pc.abs_viscoelastic_creep_risk != null
          ? "，蠕变风险 " + numEnv(pc.abs_viscoelastic_creep_risk, 4) : "")));
    }
    if (pc.run && pc.crystallinity_modulus_factor != null) {
      pciBox.appendChild(el("div", "hint",
        "退火结晶模量因子: " + numEnv(pc.crystallinity_modulus_factor, 4)));
    }
    // infill-aware weld bond internals (v0.8.1 render gap): effective bond
    // accounting for the infill structure; disclosure tag verbatim
    var wi = pc.weld_infill_aware;
    if (pc.run && wi && typeof wi === "object") {
      var wiLine = el("div", "hint",
        "有效键合(含填充): a_eff " + num(wi.a_eff, 4) +
        "，键合质量 " + num(wi.bond_quality_eff, 4));
      // disclosure tag is engine-authored prose → skip span (verbatim)
      if (typeof wi.disclosure === "string" && wi.disclosure) {
        var wiDisc = el("span", null, "（" + wi.disclosure + "）");
        wiDisc.setAttribute("data-i18n-skip", "1");
        wiLine.appendChild(wiDisc);
      }
      pciBox.appendChild(wiLine);
    }
    var pcsWrap = $("phase-c-solver");
    if (pcsWrap) pcsWrap.style.display = pciBox.childNodes.length ? "" : "none";
  }
  if (pcd) {
    pcd.innerHTML = "";
    if (pc.run) {
    if (pc.hill48_safety_factor != null) {
      var h48 = el("div", "hint",
        "Hill48 SF: " + numEnv(pc.hill48_safety_factor, 1));
      h48.title = TERM_INFO.hill48;  // v0.10 term glossary hover
      h48.appendChild(termQ("hill48"));  // v0.28 touch popup
      pcd.appendChild(h48);
    }
    if (pc.plastic_safety_factor != null) {
      pcd.appendChild(el("div", "hint",
        "塑性 SF: " + numEnv(pc.plastic_safety_factor, 1) +
        (pc.max_plastic_strain != null
          ? "（最大塑性应变 " + numEnv(pc.max_plastic_strain, 4) + "）" : "")));
    }
    if (pc.max_thermal_stress_mpa != null) {
      var ths = el("div", "hint",
        "热应力: " + numEnv(pc.max_thermal_stress_mpa, 3,
                           pc.max_thermal_stress_mpa_envelope) + " MPa" +
        (pc.thermal_is_upper_bound === true ? "（上界）" : ""));
      ths.title = TERM_INFO.thermal_stress;
      ths.appendChild(termQ("thermal_stress"));  // v0.28 touch popup
      pcd.appendChild(ths);
    }
    if (pc.max_layer_residual_stress_mpa != null) {
      pcd.appendChild(el("div", "hint",
        "层间残余: max " + numEnv(pc.max_layer_residual_stress_mpa, 3) +
        " / mean " + numEnv(pc.mean_layer_residual_stress_mpa, 3) + " MPa" +
        (pc.residual_safety_factor != null
          ? "（SF " + numEnv(pc.residual_safety_factor, 1) + "）" : "")));
    }
    if (pc.max_delamination_risk != null) {
      var dlr = el("div", "hint",
        "分层风险: " + numEnv(pc.max_delamination_risk, 6) +
        (pc.delamination_risk_layers != null
          ? "（" + pc.delamination_risk_layers + " 层）" : ""));
      dlr.title = TERM_INFO.delamination;
      dlr.appendChild(termQ("delamination"));  // v0.28 touch popup
      pcd.appendChild(dlr);
    }
    if (pc.max_fracture_peel_risk != null || pc.max_fracture_shear_risk != null) {
      pcd.appendChild(el("div", "hint",
        "剥离/剪切断裂风险: " + numEnv(pc.max_fracture_peel_risk, 6) + " / " +
        numEnv(pc.max_fracture_shear_risk, 6)));
    }
    // Weibull numbers live in phase_c too; the A+ grade shows in the summary
    // via phase_d — these rows keep the numeric Pf/R from being lost.
    if (pc.weibull_failure_probability != null) {
      var wbr = el("div", "hint",
        "Weibull: Pf " + numEnv(pc.weibull_failure_probability, 6) +
        " / R " + numEnv(pc.weibull_reliability_factor, 4));
      wbr.title = TERM_INFO.weibull;
      wbr.appendChild(termQ("weibull"));  // v0.28 touch popup
      pcd.appendChild(wbr);
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
    // thermal-speed closed loop (v0.8.1 render gap): bed/substrate heat-up
    // vs the material's cap; overheated → the engine's own suggested speed +
    // layer time, rationale verbatim. Fields all engine-authored.
    // (v0.9: stays in the MAIN flow — it carries an actionable suggestion.)
    var ts = pc.thermal_speed;
    if (ts && typeof ts === "object" && ts.assessable === true) {
      var tsLine = el("div", "hint",
        "热-速闭环: 基板温 " + num(ts.t_sub_current_c, 1) + "°C / 上限 " +
        num(ts.cap_c, 1) + "°C" +
        (ts.overheated === true
          ? " — 超温，建议速度 " + num(ts.suggested_speed_mms, 1) +
            " mm/s（层时间 " + num(ts.suggested_layer_time_s, 1) + " s）"
          : " — 未超温") +
        (typeof ts.tier === "string" && ts.tier ? "［" + ts.tier + "］" : ""));
      // rationale is engine-authored prose → skip span (verbatim)
      if (typeof ts.rationale === "string" && ts.rationale) {
        tsLine.appendChild(document.createTextNode("；"));
        var tsR = el("span", null, ts.rationale);
        tsR.setAttribute("data-i18n-skip", "1");
        tsLine.appendChild(tsR);
      }
      pcd.appendChild(tsLine);
    }
    // (v0.9: ABS WLF / crystallinity / weld-infill-aware moved above into
    // #phase-c-internals — model-internal numbers, not conclusions.)
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
  // v0.18 structured-warning mirror: cleared every render (a warning-free
  // report after a warned one must not keep the old alarm — false positive).
  // Simple mode folds the wall, and these two engine channels
  // (phase_d.buckling_warning / fracture_risk_detected) have no other
  // above-the-fold outlet, so the same value echoes above it. Same-render
  // echo of the wall's label + VERBATIM prose — never a rephrasing of the
  // engine text (v0.28 adds a banner-only plain-language prefix sentence
  // naming the failure mechanism; it grades nothing and the engine prose
  // stays verbatim in the skip span); CSS shows the mirror in simple mode
  // only (snapshot-safe: buildSnapshotDoc copies no body class and the
  // mirror defaults hidden).
  var pdw = $("pd-warn-promoted");
  if (pdw) pdw.innerHTML = "";
  if (pd.run) {
    // [label, prose, warnClass]: warnClass marks the engine's own structured
    // warning channels — buckling_warning (truthy string = warning) and
    // fracture_risk_detected === true. fatigue has no structured
    // discriminator and is never marked (always-on = noise).
    // The label is UI chrome (translatable); the assessment prose is
    // engine-authored → skip span. Same-render echo discipline: the mirror
    // below re-renders the exact label+prose pair, never a rephrase.
    // v0.28 banner-only humanNote: ONE plain-language sentence naming the
    // physical failure mode, prefixed to the verbatim prose (「…——引擎原文：」
    // separates UI chrome from engine text). It carries NO severity grading —
    // the word describes the mechanism (buckling = bending/collapse,
    // fracture = crack growth), the engine's own text stays the verdict.
    // The wall (#phase-d-detail) keeps the bare label+prose — the human
    // sentence targets the novice banner only.
    function assessLine(box, labelText, proseText, warnClass, prefix, humanNote) {
      var line = el("div", ("hint " + (warnClass || "")).trim());
      line.appendChild(document.createTextNode(
        (prefix || "") + labelText + ": "
        + (humanNote ? humanNote + "——引擎原文：" : "")));
      var prose = el("span", null, proseText);
      prose.setAttribute("data-i18n-skip", "1");
      line.appendChild(prose);
      box.appendChild(line);
    }
    [["疲劳判定", pd.fatigue_assessment, ""],
     ["断裂判定", pd.fracture_assessment,
      pd.fracture_risk_detected === true ? "pd-warn" : ""],
     ["屈曲警示", pd.buckling_warning, "pd-warn"]].forEach(function (pair) {
      if (!pair[1]) return;
      assessLine(pdd, pair[0], pair[1], pair[2]);
    });
    if (pdw) {
      // truthy guard on the assessment text too: risk_detected=true with a
      // null assessment must not render "null" (REFUTE P-shape fix)
      if (pd.buckling_warning)
        assessLine(pdw, "屈曲警示", pd.buckling_warning, "", "⚠ ",
                   "零件可能被压弯/压塌（屈曲）");
      if (pd.fracture_risk_detected === true && pd.fracture_assessment)
        assessLine(pdw, "断裂判定", pd.fracture_assessment, "", "⚠ ",
                   "零件可能出现裂纹并扩展（断裂风险）");
    }
    // skipped sub-modules with the engine's own reasons (v0.8.1 render gap —
    // previously only visible if the user opened the raw console)
    (pd.skipped_reasons || []).forEach(function (r) {
      if (typeof r === "string" && r) {
        var sk = el("div", "hint");
        sk.appendChild(document.createTextNode("跳过: "));
        var skR = el("span", null, r);  // engine-authored reason → verbatim
        skR.setAttribute("data-i18n-skip", "1");
        sk.appendChild(skR);
        pdd.appendChild(sk);
      }
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
      var wbd = el("div", "hint", wb);
      wbd.title = TERM_INFO.weibull;
      wbd.appendChild(termQ("weibull"));  // v0.28 touch popup
      pdd.appendChild(wbd);
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
        item.setAttribute("data-i18n-skip", "1");
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
          : topo.consistently_oriented === false ? " · 朝向不一致（可在「环境与载荷」面板用「修复网格朝向」）" : "") +
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
          "无机器约束（可在「环境与载荷」面板手动选机型，或让 3MF 的 printer_model 自动识别）。"));
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
        if (typeof s === "string" && s) {
          var apS = el("div", "hint", "建议: " + s);
          apS.setAttribute("data-i18n-skip", "1");
          apd.appendChild(apS);
        }
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
        var rhW = el("div", "hint",
          "层间键合: " + rh.weld_bond_assessment +
          (rh.weld_bond_quality != null
            ? "（质量 " + num(rh.weld_bond_quality, 2) +
              (rh.weld_bsf_saturated === true ? "，BSF 已饱和" : "") + "）" : ""));
        rhW.setAttribute("data-i18n-skip", "1");
        rhd.appendChild(rhW);
      }
      if (typeof rh.corner_assessment === "string" && rh.corner_assessment) {
        var rhC = el("div", "hint", "转角: " + rh.corner_assessment);
        rhC.setAttribute("data-i18n-skip", "1");
        rhd.appendChild(rhC);
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
        rw.setAttribute("data-i18n-skip", "1");
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
        var pdn = el("p", "hint", ee.process_dims_note);
        pdn.setAttribute("data-i18n-skip", "1");  // engine-authored, verbatim
        eed.appendChild(pdn);
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
      // reason/notes are the engine's own disclosure → prefix chrome +
      // verbatim skip span (textContent identical to the old concat form)
      if (typeof cal.reason === "string" && cal.reason) {
        var cr = el("div", "hint");
        cr.appendChild(document.createTextNode("原因: "));
        var crR = el("span", null, cal.reason);
        crR.setAttribute("data-i18n-skip", "1");
        cr.appendChild(crR);
        cd.appendChild(cr);
      }
      (cal.notes || []).forEach(function (n) {
        if (typeof n === "string" && n) {
          var cn = el("div", "hint");
          cn.appendChild(document.createTextNode("注: "));
          var cnR = el("span", null, n);
          cnR.setAttribute("data-i18n-skip", "1");
          cn.appendChild(cnR);
          cd.appendChild(cn);
        }
      });
    }
  }

  // risks — severity shown verbatim on the engine's 1..5 scale (the old
  // Math.min(3, …) clamp silently relabelled S5 items as S3)
  var riskBox = $("risk-list");
  riskBox.innerHTML = "";
  var risks = ((d.phase_a || {}).risks) || [];
  var sevOf = function (r) {
    return Math.max(1, Math.min(5, Math.round(r.severity || 1)));
  };
  risks.forEach(function (r) {
    var item = el("div", "risk-item");
    item.setAttribute("data-i18n-skip", "1");
    var sev = sevOf(r);
    item.appendChild(el("span", "sev sev-" + sev, "S" + sev));
    item.appendChild(el("strong", null, r.type + " · "));
    item.appendChild(document.createTextNode(r.description || ""));
    if (r.suggestion) {
      item.appendChild(el("div", "hint", "建议: " + r.suggestion));
    }
    riskBox.appendChild(item);
  });
  // v0.22 merged 「风险与提示」 card: engine warnings + geometric risks
  // behind ONE toggle (two same-looking ⚠ cards read as duplication). The
  // default adapts to the verdict until the user clicks (dataset.user):
  // ⚠/❌ expand — the risks ARE the evidence for a non-ok verdict —, ✅
  // collapses so the advice / preset-comparison areas below stay in view.
  var ac = $("alerts-card");
  if (ac) {
    var wCount = warnBox.childNodes.length;
    var rCount = risks.length;
    if (wCount || rCount) {
      ac.style.display = "";
      var maxSev = 1;
      for (var rIdx = 0; rIdx < risks.length; rIdx++)
        maxSev = Math.max(maxSev, sevOf(risks[rIdx]));
      $("alerts-count").textContent = String(wCount + rCount);
      // headline chrome (translatable): 「条提示 · N 条几何风险 · 最高 SX」
      // assembled from the two engine streams; each part shown only when its
      // stream is non-empty
      var head = wCount ? "条提示" : "";
      if (rCount)
        head += (head ? " · " : "") + rCount + " 条几何风险 · 最高 S" + maxSev;
      $("alerts-headline").textContent = head;
      var wh = $("alerts-warn-h");
      wh.style.display = wCount ? "" : "none";
      wh.textContent = "引擎提示（" + wCount + "）";
      var rh = $("alerts-risk-h");
      rh.style.display = rCount ? "" : "none";
      rh.textContent = rCount ? "几何风险（" + rCount + " · 最高 S" + maxSev + "）" : "";
      if (ac.dataset.user !== "1") {
        var vAssess = typeof pb.assessment === "string" ? pb.assessment : "";
        ac.dataset.open = vAssess.indexOf("✅") >= 0 ? "0" : "1";
      }
      $("alerts-body").style.display = ac.dataset.open === "1" ? "" : "none";
    } else {
      ac.style.display = "none";
      $("alerts-body").style.display = "none";
    }
  }

  // recommendations. v0.9: the server pairs each engine item with an
  // "applyable" projection (same order, one entry per item) — applicable
  // items get a checkbox and a single "apply checked" CTA above the list.
  // The identity-key whitelist and unit/range/step decisions live entirely
  // server-side (PARAM_META is the one owner of the control semantics); the
  // client holds no engine-name knowledge. No applyable data (older caller /
  // direct fixture render) → plain text exactly as before.
  var recBox = $("rec-items");
  recBox.innerHTML = "";
  var items = rec.items || [];
  if (!items.length) { recBox.appendChild(el("p", "muted", "无参数建议。")); }
  var applyCta = null, nApplicable = 0;
  if (items.length && Array.isArray(applyable)) {
    applyCta = el("button", "rec-apply");
    applyCta.style.display = "none";
    applyCta.title = "按勾选项写入参数滑杆并立即重新分析";
    applyCta.onclick = function () {
      // collect checked entries at click time (checkboxes and items share
      // one lifecycle — every renderReport rebuilds both, so no stale sheet)
      var picked = [];
      var cbs = recBox.querySelectorAll("input[data-apply-idx]");
      for (var i = 0; i < cbs.length; i++) {
        if (cbs[i].checked && applyable[cbs[i].getAttribute("data-apply-idx")])
          picked.push(applyable[cbs[i].getAttribute("data-apply-idx")]);
      }
      if (typeof applyCheckedSuggestions === "function")
        applyCheckedSuggestions(picked);
    };
  }
  items.forEach(function (it, idx) {
    var li = el("div", "risk-item");
    // priority badge (iter 69; unconsumed engine field): displayed, order
    // stays engine-authoritative — the UI never re-sorts recommendations.
    li.appendChild(el("strong", null,
      (typeof it.priority === "number" ? "[P" + it.priority + "] " : "")
      + "[" + it.action + "] " + it.parameter));
    // v0.16 (engine 0.26): motivation badge — which goal the suggestion
    // serves. null/absent = unclassified → no badge; unknown token shows
    // raw (title always carries the raw token for bug reports).
    if (typeof it.motivation === "string" && it.motivation) {
      var mot = el("span", "mot-badge",
                   MOTIVATION_LABELS[it.motivation] || it.motivation);
      mot.setAttribute("title", "建议动机: " + it.motivation);
      li.appendChild(mot);
    }
    var ap = Array.isArray(applyable) ? applyable[idx] : null;
    if (ap && ap.applicable) {
      nApplicable++;
      var cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = true;
      cb.setAttribute("data-apply-idx", idx);
      cb.className = "rec-apply-cb";
      cb.title = "勾选后随上方按钮一并应用（当前 "
        + ap.current_value + " → 建议 " + ap.recommended_value + "）";
      li.appendChild(cb);
    } else if (ap && ap.reason) {
      var nr = el("span", "hint", "（不可一键应用: " + ap.reason + "）");
      li.appendChild(nr);
    }
    var rr = el("span", null, " — " + (it.reason || ""));
    rr.setAttribute("data-i18n-skip", "1");
    li.appendChild(rr);
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
    // v0.9.1 engine alignment (docs/webui-alignment-response-2026-09.md):
    // cooling-fan suggestions come from the warping heuristic band (engine
    // self-declared uncalibrated, autosuggest.cpp iter 244) and do NOT read
    // the residual-stress margin. When this sample's residual safety factor
    // is enormous the fan cut buys little strength — surface that instead
    // of letting the tradeoff note carry the whole story.
    if (it.parameter === "cooling_fan"
        && typeof pc.residual_safety_factor === "number"
        && pc.residual_safety_factor > 100) {
      li.appendChild(el("div", "hint",
        "注：本样本残余应力安全系数 " + num(pc.residual_safety_factor, 1) +
        "，此项建议对强度的收益可能有限（打印质量权衡见上）"));
    }
    recBox.appendChild(li);
  });
  if (applyCta && nApplicable > 0) {
    applyCta.textContent = "应用勾选建议 (" + nApplicable + ")";
    applyCta.style.display = "";
    recBox.insertBefore(applyCta, recBox.firstChild);
  }

  // v0.16 (engine 0.26) suppressions: parameters whose suggestions were
  // GATED, not "no advice exists". Rendered only when the engine actually
  // sent a non-empty array (key absent = nothing this run — absent-not-null
  // lifecycle, same as the phase boxes). Answers "why is there no
  // walls/infill suggestion" which the items list alone cannot.
  (rec.suppressions || []).forEach(function (s) {
    if (!s || typeof s !== "object") return;
    var li = el("div", "risk-item");
    li.appendChild(el("span", "sev sev-2", "抑制"));
    li.appendChild(document.createTextNode(" " + (s.parameter || "?") + " "));
    var gate = el("span", null, "建议被闸");
    li.appendChild(gate);
    li.appendChild(document.createTextNode(" — "));
    // known reason_code → UI chrome sentence; unknown → raw token verbatim
    li.appendChild(el("span", null,
      (typeof s.reason_code === "string" && s.reason_code
       ? (SUPPRESSION_REASONS[s.reason_code] || s.reason_code)
       : "未知原因")));
    // detail is engine-authored prose → skip i18n, render verbatim
    if (typeof s.detail === "string" && s.detail) {
      var dt = el("span", null, "（" + s.detail + "）");
      dt.setAttribute("data-i18n-skip", "1");
      li.appendChild(dt);
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
  // v0.19 (REFUTE blocker): the raw table folds into #cand-raw-fold; its
  // outside-the-fold outlet is #cand-bars, which renders only with ≥2
  // feasible rows (gate below + #cand-bars:empty CSS). Whenever the bars
  // can't render, the folded table IS the only outlet for the caveat/note
  // rows — auto-expand so a fold never buries an unchanneled signal.
  // Auto-open only, never auto-close: fold state stays user-owned across
  // renders (same ownership rule as body.detail-open).
  var rawFold = $("cand-raw-fold");
  if (rawFold) {
    var feasCount = cands.filter(function (c) { return c.feasible !== false; }).length;
    if (!cands.length || feasCount < 2) rawFold.open = true;
  }
  if (!cands.length) {
    // (v0.19 round B bugfix, found by the §26 fold test) the old one-liner
    // appended `el("td", …).parentNode` — null on an unattached node, so a
    // report without process_optimization crashed renderReport with
    // appendChild(null). Standard pattern (same as the note/caveat rows) +
    // the colSpan the 15-column table needs.
    var ncRow = el("tr", null);
    var ncTd = el("td", "muted", "无候选（报告缺少 process_optimization 数据）");
    ncTd.colSpan = 15;
    ncRow.appendChild(ncTd);
    body.appendChild(ncRow);
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
    td(p.infill_pct !== undefined && p.infill_pct !== null ? fmtSig(p.infill_pct) + "%" : "—");
    td(p.wall_count !== undefined && p.wall_count !== null ? p.wall_count : "—");
    td(p.print_speed !== undefined && p.print_speed !== null ? fmtSig(p.print_speed) + "mm/s" : "—");
    td(fmtSig(s.overall)); td(fmtSig(s.strength)); td(fmtSig(s.time)); td(fmtSig(s.material)); td(fmtSig(s.reliability));
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
    td(fmtSig(s.quality));
    body.appendChild(tr);
    if (!c.feasible && c.note) {
      var note = el("tr", "infeasible");
      var nd = el("td", "muted", c.note); nd.colSpan = 15;
      // c.note is engine-authored prose → verbatim (skip i18n)
      nd.setAttribute("data-i18n-skip", "1");
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

  // v0.10 candidate comparison bars — pure-CSS relative widths within THIS
  // report's candidate set (zero dependencies; display only — the engine's
  // own ranking/order stays authoritative, the UI re-sorts nothing). Bars are
  // normalized per-metric against the max of the feasible rows.
  var cbBox = $("cand-bars");
  if (cbBox) {
    cbBox.innerHTML = "";
    var feas = cands.filter(function (c) { return c.feasible !== false; });
    if (feas.length >= 2) {
      var mx = { sf: 0, t: 0, m: 0 };
      feas.forEach(function (c) {
        var e = c.estimate || {};
        if (typeof c.search_est_safety_factor === "number")
          mx.sf = Math.max(mx.sf, c.search_est_safety_factor);
        if (typeof e.print_time_min === "number")
          mx.t = Math.max(mx.t, e.print_time_min);
        if (typeof e.material_volume_mm3 === "number")
          mx.m = Math.max(mx.m, e.material_volume_mm3);
      });
      feas.forEach(function (c) {
        var e = c.estimate || {};
        var row = el("div", "cbar");
        row.appendChild(el("span", "cb-name", c.name || "?"));
        var track = el("div", "cb-track");
        [["SF", typeof c.search_est_safety_factor === "number"
            ? c.search_est_safety_factor : null, mx.sf, "var(--green)"],
         ["时间", typeof e.print_time_min === "number"
            ? e.print_time_min : null, mx.t, "var(--amber)"],
         ["材料", typeof e.material_volume_mm3 === "number"
            ? e.material_volume_mm3 : null, mx.m, "var(--cyan)"]]
          .forEach(function (m) {
            var lab = el("span", "cb-lab", m[0]);
            var bar = el("div", "cb-bar");
            var fill = el("i");
            if (m[1] !== null && m[2] > 0)
              fill.style.width = Math.max(2, (m[1] / m[2]) * 100) + "%";
            fill.style.background = m[3];
            bar.appendChild(fill);
            var line = el("div", "cb-row");
            line.appendChild(lab);
            line.appendChild(bar);
            track.appendChild(line);
          });
        row.appendChild(track);
        cbBox.appendChild(row);
      });
      cbBox.appendChild(el("p", "hint",
        // v0.19: one line (page-height budget, round B) — semantics unchanged
        "条长=组内相对值：绿=安全系数 / 琥珀=时间 / 蓝=材料；排序以引擎为准。"));
    }
  }
  // v0.28 novice summary (re-homed v0.29): ONE line stating the enumeration
  // fact — the first FEASIBLE row of the engine's candidate list. Candidates
  // carry NO rank field (probed report.json: the array is the preset
  // enumeration safe/balanced/fast/appearance), so "first" states table
  // order only — never a claim that the engine ranked it, and no
  // recommendation tone. SF rounds like the table's own SF column
  // (Math.round; fmtSig is the scores/infill/speed convention — REFUTE).
  // Lives OUTSIDE #cand-bars: the bars joined the detail wall in simple
  // mode (v0.29 budget) and this line is the above-the-fold replacement —
  // cleared every render so a bars-less report drops it (false-positive
  // guard, same discipline as the pd-warn mirror).
  var noviceLine = $("cand-novice-line");
  if (noviceLine) {
    noviceLine.style.display = "none";
    noviceLine.textContent = "";
    var feasAll = (po.candidates || []).filter(function (c) {
      return c.feasible !== false; });
    if (feasAll.length >= 2) {
      var top = feasAll[0];
      noviceLine.textContent =
        "第一个可行档位（引擎枚举序）：" + (top.name || "??")
        + (typeof top.search_est_safety_factor === "number"
           ? " —— 安全系数 " + Math.round(top.search_est_safety_factor)
           : "");
      noviceLine.style.display = "";
    }
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
      row.setAttribute("data-i18n-skip", "1");
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

    // ---------- v0.10 verdict-first summary cards ----------
  // Three plain-language cards above the KPI row: 结论 (engine assessment
  // verbatim + SF band) / 风险 (first 3 warnings) / 建议 (apply CTA front and
  // center). Red line: the verdict text is the engine's own — the SF band
  // colors are a DISPLAY mapping of the engine's own number (<1 / 1–3 / >3);
  // no SF → no color, no guess. Cards are rebuilt every render (empty box =
  // hidden via CSS :empty).
  var scBox = $("summary-cards");
  if (scBox) {
  // v0.22: lift the pd-warn mirror node OUT before the container reset
  // (innerHTML below would destroy it) and re-seat it INSIDE the grid,
  // directly under the verdict hero — an attached banner reads as part of
  // the verdict row; after the advice card it read as a stray third card.
  // vm-stub safety: fake parents have no removeChild — skip the move there
  // (position is cosmetic; content rendering is position-independent).
  var pdwNode = $("pd-warn-promoted");
  var pdwMoved = false;
  if (pdwNode && pdwNode.parentNode && pdwNode.parentNode.removeChild) {
    pdwNode.parentNode.removeChild(pdwNode);
    pdwMoved = true;
  }
  scBox.innerHTML = "";
  // ---- v0.22 verdict hero: ONE card above the fold answering "能不能用".
  // Edge color = worst-of the engine's own signals, so a ✅ phrase can no
  // longer sit green next to an amber buckling banner (they fought):
  //   rank 1 ✅ emoji < rank 2 ⚠ emoji / structured phase_d warning
  //   < rank 3 ❌ emoji / SF < 1 (engine numbers, display mapping only —
  //   same class as the SF band colors, no UI-side re-scoring)
  var vc = el("div", "sum-card sum-verdict");
  vc.appendChild(el("h3", null, "结论"));
  var verdictTxt = typeof pb.assessment === "string" && pb.assessment
    ? pb.assessment : "";
  var vRank = verdictRank(pb, pd);
  if (vRank) vc.className += ["", " ok", " warn", " bad"][vRank];
  var sfNum = safetyFactorScalar(pb);
  var vBig = el("div", "big", verdictTxt
      || "引擎未给出结论短语 — 见下方各项数值。");
    vBig.setAttribute("data-i18n-skip", "1");
    vc.appendChild(vBig);
    // SF band: engine scalar (v2 object shape → nominal); display-only
    var sfCls = null;
    if (typeof sfNum === "number" && isFinite(sfNum))
      sfCls = sfNum < 1 ? "low" : sfNum <= 3 ? "mid" : "high";
    var rsEl = $("res-sf");
    if (rsEl) rsEl.className = "v" + (sfCls ? " sf-" + sfCls : "");
    if (sfCls) {
      var band = el("div", "sf-band sf-" + sfCls);
      var bi = el("i");
      bi.style.width = Math.max(6, Math.min(100, (sfNum / 6) * 100)) + "%";
      band.appendChild(bi);
      vc.appendChild(band);
      vc.appendChild(el("div", "hint",
        sfNum < 1 ? "安全系数低于 1 — 应力已超过材料强度"
        : sfNum <= 3 ? "安全系数 1–3 — 有余量但不宽裕"
        : "安全系数 > 3 — 余量充足"));
    }
    scBox.appendChild(vc);
    // banner directly under the hero (simple mode: between hero and advice;
    // advanced: display:none, so the grid is unaffected)
    if (pdwNode && pdwMoved) scBox.appendChild(pdwNode);
    // ---- v0.22 advice card: ONE primary action. Simple mode gets an
    // apply-ALL CTA (no checkbox ceremony — the per-item list is behind the
    // detail fold); advanced keeps the checkbox-respecting CTA that reads
    // #rec-items state. The compact 将调整 line states what would change in
    // plain slider labels (server-owned labels looked up from the tuning
    // rows — the client still holds no engine-name knowledge; raw key is the
    // fallback). v0.14's summary risk-preview card is gone — ONE ⚠ surface
    // (#alerts-card) carries risks now.
    var acard = el("div", "sum-card sum-advice");
    acard.appendChild(el("h3", null, "建议"));
    var nRecs = (rec.items || []).length;
    if (nApplicable > 0) {
      acard.appendChild(el("div", "big",
        "引擎建议 " + nRecs + " 项参数调整（" + nApplicable + " 项可一键应用）"));
      var changeBits = [];
      items.forEach(function (it, idx) {
        var ap = Array.isArray(applyable) ? applyable[idx] : null;
        if (!(ap && ap.applicable)) return;
        var lbl = it.parameter || "?";
        try {
          var rowInput = document.querySelector
            ? document.querySelector('#tuning-panel [data-param="' + it.parameter + '"]')
            : null;
          var lblEl = rowInput && rowInput.parentNode
            ? rowInput.parentNode.querySelector(".lbl") : null;
          if (lblEl && lblEl.textContent) lbl = lblEl.textContent.trim();
        } catch (e) { /* label lookup is best-effort; raw key is honest */ }
        changeBits.push(lbl + " " + it.current_value + "→" + it.recommended_value);
      });
      if (changeBits.length) {
        var line = el("div", "hint",
          "将调整：" + changeBits.slice(0, 3).join("、")
          + (changeBits.length > 3 ? " 等 " + changeBits.length + " 项" : ""));
        acard.appendChild(line);
      }
      var sumCtaAll = el("button", "sum-cta simple-only",
        "应用全部建议并重新分析 (" + nApplicable + ")");
      sumCtaAll.title = "写入全部可应用的参数建议并立即重新分析";
      sumCtaAll.onclick = function () {
        var picked = [];
        for (var i = 0; i < applyable.length; i++)
          if (applyable[i] && applyable[i].applicable) picked.push(applyable[i]);
        if (typeof applyCheckedSuggestions === "function")
          applyCheckedSuggestions(picked);
      };
      acard.appendChild(sumCtaAll);
      var sumCta = el("button", "sum-cta advanced-only",
        "应用可行建议 (" + nApplicable + ")");
      sumCta.title = "按下方列表的勾选状态写入参数滑杆并立即重新分析";
      sumCta.onclick = function () {
        var picked = [];
        var ri = $("rec-items");
        var cbs = ri && ri.querySelectorAll ? ri.querySelectorAll("input[data-apply-idx]") : [];
        for (var i = 0; i < cbs.length; i++) {
          if (cbs[i].checked && applyable[cbs[i].getAttribute("data-apply-idx")])
            picked.push(applyable[cbs[i].getAttribute("data-apply-idx")]);
        }
        if (typeof applyCheckedSuggestions === "function")
          applyCheckedSuggestions(picked);
      };
      acard.appendChild(sumCta);
      // v0.27 auto-tune: multi-round apply→re-analyze loop (driver in
      // index.html). Offered ONLY on a rank≥2 verdict — the loop exists to
      // work a risk down, and on a ✅ verdict (or a verdict with no
      // rank-bearing signal, rank 0) the one-shot apply-all CTA above is the
      // honest entry. Display mapping of engine signals, same as the hero
      // edge (verdictRank); never "调到绿" phrasing — stops are honest
      // (safe / exhausted / unchanged / cap).
      var vRankAll = verdictRank(pb, pd);
      if (vRankAll >= 2) {
        var tuneCta = el("button", "sum-cta tune simple-only",
          "自动调参（最多 " + AUTO_TUNE_MAX_ROUNDS + " 轮）");
        tuneCta.id = "btn-auto-tune";
        tuneCta.title = "每轮自动应用引擎全部可应用建议并重新分析；结论变安全、建议用尽、建议不再变化或满 "
          + AUTO_TUNE_MAX_ROUNDS + " 轮即停（每轮都是一次真实引擎分析）";
        tuneCta.onclick = function () {
          if (typeof startAutoTune === "function") startAutoTune();
        };
        acard.appendChild(tuneCta);
      }
    } else if (nRecs) {
      acard.appendChild(el("div", "big",
        "引擎建议 " + nRecs + " 项（无可一键应用项，见下方明细）"));
    } else {
      acard.appendChild(el("div", "big", "无参数建议。"));
    }
    // 3.4 engine appendix C: part_visibility_warning → actionable grid hint
    if (pbd && typeof pbd.part_visibility_warning === "string"
        && pbd.part_visibility_warning) {
      acard.appendChild(el("div", "hint",
        "网格分辨率不足以覆盖全部几何部件 — 可提高网格精度（--grid）后重跑："));
      var gbtn = el("button", null, "提高网格精度（--grid ×2）并重跑");
      gbtn.onclick = function () {
        var inp = $("opt-grid");
        var cur = parseInt(inp && inp.value, 10);
        if (isNaN(cur))
          cur = (typeof state !== "undefined" && state.serverGrid) || 16;
        if (inp) inp.value = Math.min(128, cur * 2);
        if (typeof analyze === "function") analyze(false);
      };
      acard.appendChild(gbtn);
    }
    scBox.appendChild(acard);
  }

    // trust badges — level styling keyed on the engine's own levels; the
  // citation string rides along in the title (hover)
  var trust = d.trust || {};  $("trust-material").textContent = trust.material || "";
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
    // label + source citation are engine-authored → verbatim (skip i18n;
    // the level class above is the UI's only interpretation)
    b.setAttribute("data-i18n-skip", "1");
    row.appendChild(b);
    row.appendChild(document.createTextNode(" " + k));
    tBox.appendChild(row);
  });
}

// ---------- v0.10 actionable error card ----------
// Renders a failed analyze payload into 「分析结果」 with NEXT-STEP buttons instead of
// a bare toast. The error/findings text is verbatim; the actions only flip
// UI knobs the user already owns (validate tier select, per-run --grid box)
// and re-run the standard analyze channel — no new endpoints.
function renderAnalyzeError(j) {
  var box = $("analyze-error");
  if (!box) return;
  box.innerHTML = "";
  box.style.display = "none";
  if (!j || !j.error) return;
  // "block" (not "") — the element's stylesheet default is display:none, so
  // an empty inline value would fall back to hidden
  box.style.display = "block";
  box.appendChild(el("div", "err", String(j.error)));
  var acts = el("div", "actions");
  function act(label, fn) {
    var b = el("button", null, label);
    b.onclick = fn;
    acts.appendChild(b);
  }
  // --validate strict/paranoid refusal → one click back to standard + rerun
  if (j.status === "validation_refused") {
    act("把校验档位改回 standard 并重跑", function () {
      var sel = (typeof document !== "undefined" && document.querySelector)
        ? document.querySelector('[data-env="validate_tier"]') : null;
      if (sel) sel.value = "standard";
      if (typeof markChanged === "function") markChanged("validate_tier");
      if (typeof analyze === "function") analyze(false);
    });
  }
  // grid / resolution / multi-part errors → double --grid and rerun (the
  // engine's own appendix-C guidance surfaced as a button)
  var msg = String(j.error);
  // v0.28: the rc=124 timeout text itself contains 「分辨率」 (it suggests
  // LOWERING the voxel resolution) — doubling the grid there would make the
  // next run slower still, so the button is suppressed for timeout-class
  // errors (harmful-action fix found by REFUTE while extending this card)
  var timedOut = /超时|timed out|timeout/i.test(msg);
  if (/网格|分辨率|部件|grid|resolution/i.test(msg) && !timedOut) {
    act("提高网格精度（--grid ×2）并重跑", function () {
      var inp = $("opt-grid");
      var cur = parseInt(inp && inp.value, 10);
      if (isNaN(cur))
        cur = (typeof state !== "undefined" && state.serverGrid) || 16;
      if (inp) inp.value = Math.min(128, cur * 2);
      if (typeof analyze === "function") analyze(false);
    });
  }
  // v0.28 memory-class failures → quick preview + rerun: --fast caps the
  // FEM voxel grid (12³), which is where engine OOM actually allocates.
  // Timeout-class gets NO button (mesh-parse time dominates it and --fast
  // does not touch that — the verbatim server text already names the levers)
  if (/内存|bad_alloc|out of memory/i.test(msg)) {
    act("开快速预览并重跑", function () {
      var cb = $("opt-fast");
      if (cb) cb.checked = true;
      if (typeof analyze === "function") analyze(false);
    });
  }
  if (acts.childNodes.length) box.appendChild(acts);
  // v0.28 queue full: the verbatim server text already guides (稍后重试或
  // 取消其他任务), so the UI adds only the one fact the error cannot state:
  // THIS request never started. No retry button — the standing 分析 button
  // (restored by now) is the retry path; a second CTA would duplicate the
  // guidance the engine-adjacent text already carries verbatim.
  if (/排队已满|引擎忙/.test(msg))
    box.appendChild(el("div", "hint", "本次请求未开始——稍后重新点「分析」即可。"));
}

// ---------- v0.23 G-code companion tools (gcode-diff) ----------
// Both functions render into #gcode-result (index.html); the main inline
// script owns the mutual exclusion with the model report — showing this
// container hides the engine-result containers and vice versa. Every
// verdict label / issue sentence / suggestion string is gcode-diff-authored
// text, rendered VERBATIM (red line 2 — same discipline as the stratum
// engine's Chinese prose staying untranslated). The severity→color maps
// below are display-only chrome, same class as the SF band colors.
//
// Two-state sentinels honored here (null ≠ 0):
//   dimensions[].score === null  → "不可评估" dash, never 0
//   dimensions_scored === 0      → whole-report 不可评估 card (the rc=2
//                                  fail-closed outcome; overall_score's 0.0
//                                  doubles as "nothing was evaluated")
//   geometry/physics scalars null → "—" via num()

// verdict enum (gcode-diff DiffOrchestrator) → hero-card tone. Unknown
// future labels render neutral — forward compatibility over completeness
// (same practice as MOTIVATION_LABELS).
var GCODE_VERDICT_CLASS = {
  CLEAN: " ok",
  FLOW_CHANGE: " warn",
  DEGRADATION: " bad",
};

// severity tokens (observed: CRITICAL / WARNING_MAJOR / WARNING_MINOR /
// BENIGN) → row/card tone. Substring match keeps future WARNING_* variants
// toning correctly without enumerating them.
function _gcodeSevClass(sev) {
  var s = String(sev || "").toUpperCase();
  if (s.indexOf("CRITICAL") >= 0) return " bad";
  if (s.indexOf("WARNING") >= 0) return " warn";
  if (s.indexOf("MINOR") >= 0 || s.indexOf("BENIGN") >= 0) return " ok";
  return "";
}

// shared tail for both modes: collapsible console (gcode-diff's one-line
// stderr summary) + the self-contained HTML deep link (served by
// /api/gcode-report — diff reports are zh, score reports en, engine
// output language passes through untouched).
function _gcodeFooter(box, consoleText, token) {
  if (consoleText) {
    var cd = el("details", "opt-group");
    cd.appendChild(el("summary", null, "gcode-diff 控制台"));
    var pre = el("pre");
    pre.textContent = consoleText;
    cd.appendChild(pre);
    box.appendChild(cd);
  }
  if (token) {
    var row = el("div", "actions");
    var a = el("a", "btn-a", "查看完整报告 (HTML)");
    a.href = "/api/gcode-report?token=" + encodeURIComponent(token);
    a.target = "_blank";
    a.title = "gcode-diff 生成的自包含 HTML 报告（对比报告为中文、评分报告为英文——引擎产物语言原样保留）";
    row.appendChild(a);
    box.appendChild(row);
  }
}

function renderGcodeDiff(report, consoleText, meta) {
  meta = meta || {};
  var box = $("gcode-result");
  if (!box) return;
  box.innerHTML = "";
  box.style.display = "";
  var d = report || {};
  // ---- verdict hero ----
  var vc = el("div", "sum-card sum-verdict"
              + (GCODE_VERDICT_CLASS[d.overall_verdict] || ""));
  vc.appendChild(el("h3", null, "对比结论"));
  var vb = el("div", "big", d.overall_verdict || "—");
  vb.setAttribute("data-i18n-skip", "1");
  vc.appendChild(vb);
  if (d.overall_detail) {
    var dt = el("div", "hint");
    dt.textContent = d.overall_detail;
    dt.setAttribute("data-i18n-skip", "1");
    vc.appendChild(dt);
  }
  // display names: the UI's own upload names beat the report's file_a/file_b
  // (the argv paths carry the WORK_DIR prefix and read as noise)
  var names = Array.isArray(meta.names) && meta.names.length >= 2
    ? meta.names : [d.file_a || "A", d.file_b || "B"];
  var nf = el("div", "hint", "A: " + names[0] + "  ⇄  B: " + names[1]);
  nf.setAttribute("data-i18n-skip", "1");
  vc.appendChild(nf);
  if (d.slicer_format) {
    var sf = el("div", "hint", "切片器: " + d.slicer_format);
    sf.setAttribute("data-i18n-skip", "1");
    vc.appendChild(sf);
  }
  box.appendChild(vc);
  // ---- layer KPI ----
  var kp = el("div", "sum-card");
  kp.appendChild(el("h3", null, "层差异"));
  kp.appendChild(el("div", "big",
    "修改 " + num(d.layers_modified, 0) + " 层 · 新增 "
    + num(d.layers_added, 0) + " · 删除 " + num(d.layers_removed, 0)));
  box.appendChild(kp);
  // ---- global metric diffs table ----
  if (Array.isArray(d.global_diffs) && d.global_diffs.length) {
    var gc = el("div", "sum-card");
    gc.appendChild(el("h3", null, "全局指标差异"));
    var t = el("table");
    var hr = el("tr");
    ["指标", "A", "B", "Δ", "Δ%", "显著"].forEach(function (h) {
      hr.appendChild(el("th", null, h)); });
    t.appendChild(hr);
    d.global_diffs.forEach(function (g) {
      var r = el("tr");
      r.appendChild(el("td", null, g.metric || "—"));
      r.appendChild(el("td", "num", num(g.a, 2)));
      r.appendChild(el("td", "num", num(g.b, 2)));
      r.appendChild(el("td", "num", num(g.delta, 2)));
      r.appendChild(el("td", "num", g.delta_pct == null
        ? "—" : Number(g.delta_pct).toFixed(1) + "%"));
      r.appendChild(el("td", g.significant ? "num sig" : "num",
                       g.significant ? "✓" : ""));
      t.appendChild(r);
    });
    gc.appendChild(t);
    box.appendChild(gc);
  }
  // ---- geometry summary (absent-not-null: available !== true hides the
  // WHOLE card — a hidden distance must never read as "geometries agree")
  var gd = d.geometry_diff;
  if (gd && gd.available === true) {
    var gk = el("div", "sum-card");
    gk.appendChild(el("h3", null, "几何差异"));
    gk.appendChild(el("div", "kv-lines",
      "Chamfer " + num(gd.chamfer_distance, 3)
      + " · Hausdorff " + num(gd.hausdorff_distance, 3)
      + " · Fréchet " + num(gd.frechet_distance, 3)
      + " · 重合率 " + (gd.overlap_ratio == null
          ? "—" : Number(gd.overlap_ratio).toFixed(3))));
    box.appendChild(gk);
  }
  // ---- physics delta scalars (per-layer array stays in the full report) ----
  var pd = d.physics_delta;
  if (pd && pd.assessable === true) {
    var pc = el("div", "sum-card");
    pc.appendChild(el("h3", null, "物理后果（对比）"));
    pc.appendChild(el("div", "kv-lines",
      "新过热层 " + num(pd.newly_overheated_layers, 0)
      + " · 焊合回退层 " + num(pd.weld_regressed_layers, 0)
      + " · 超机器上限层 " + num(pd.over_machine_limit_layers, 0)
      + " · 超熔体上限层 " + num(pd.over_melt_ceiling_layers, 0)));
    if (pd.worst_weld_delta_pct != null)
      pc.appendChild(el("div", "hint",
        "最差焊合强度变化 " + Number(pd.worst_weld_delta_pct).toFixed(1) + "%"));
    box.appendChild(pc);
  }
  // ---- slicer issues (severity-toned, engine prose verbatim) ----
  if (Array.isArray(d.slicer_issues) && d.slicer_issues.length) {
    var ic = el("div", "sum-card");
    ic.appendChild(el("h3", null, "问题与建议（" + d.slicer_issues.length + "）"));
    d.slicer_issues.forEach(function (iss) {
      var it = el("div", "rec-row" + _gcodeSevClass(iss.severity));
      var head = el("div", null,
        "[" + (iss.severity || "?") + "] " + (iss.summary || ""));
      head.setAttribute("data-i18n-skip", "1");
      it.appendChild(head);
      if (iss.recommendation) {
        var rc2 = el("div", "hint");
        rc2.textContent = "→ " + iss.recommendation;
        rc2.setAttribute("data-i18n-skip", "1");
        it.appendChild(rc2);
      }
      if (iss.confidence != null && iss.confidence !== "")
        it.appendChild(el("div", "hint", "置信度: " + iss.confidence));
      ic.appendChild(it);
    });
    box.appendChild(ic);
  }
  _gcodeFooter(box, consoleText, meta.token);
}

function renderGcodeScore(report, consoleText, meta) {
  meta = meta || {};
  var box = $("gcode-result");
  if (!box) return;
  box.innerHTML = "";
  box.style.display = "";
  var d = report || {};
  // ---- fail-closed outcome: zero dimensions scored (gcode-diff rc=2) is a
  // legitimate "nothing to evaluate" state — its own card, NOT a score of 0
  if (d.dimensions_scored === 0) {
    var na = el("div", "sum-card sum-verdict warn");
    na.appendChild(el("h3", null, "评分结果"));
    na.appendChild(el("div", "big", "整体不可评估"));
    var why = el("div", "hint",
      (d.summary || "") + "——该 G-code 没有任何可评分的维度（无有效挤出/运动证据）。"
      + "请确认上传的是切片器导出的 G-code 而非空文件。");
    why.setAttribute("data-i18n-skip", "1");
    na.appendChild(why);
    box.appendChild(na);
    _gcodeFooter(box, consoleText, meta.token);
    return;
  }
  // ---- score hero ----
  var vc = el("div", "sum-card sum-verdict"
              + (d.has_critical ? " bad" : d.overall_score >= 80 ? " ok" : " warn"));
  vc.appendChild(el("h3", null, "评分结果"));
  var vb = el("div", "big",
    num(d.overall_score, 1) + " / 100" + (d.has_critical ? " · 含 CRITICAL 项" : ""));
  vb.setAttribute("data-i18n-skip", "1");
  vc.appendChild(vb);
  if (d.summary) {
    var sm = el("div", "hint", d.summary + " · 可评估维度 " + num(d.dimensions_scored, 0)
      + "/" + (Array.isArray(d.dimensions) ? d.dimensions.length : "—"));
    sm.setAttribute("data-i18n-skip", "1");
    vc.appendChild(sm);
  }
  var metaBits = [];
  if (d.material) metaBits.push("材料 " + d.material);
  if (d.slicer) metaBits.push("切片器 " + d.slicer);
  if (metaBits.length) {
    var mb = el("div", "hint", metaBits.join(" · "));
    mb.setAttribute("data-i18n-skip", "1");
    vc.appendChild(mb);
  }
  box.appendChild(vc);
  // ---- dimension table (score null = 不可评估 dash, never 0) ----
  if (Array.isArray(d.dimensions) && d.dimensions.length) {
    var dc = el("div", "sum-card");
    dc.appendChild(el("h3", null, "维度明细"));
    var t = el("table");
    var hr = el("tr");
    ["维度", "得分", "等级", "判定"].forEach(function (h) {
      hr.appendChild(el("th", null, h)); });
    t.appendChild(hr);
    d.dimensions.forEach(function (dim) {
      var r = el("tr", dim.assessable === false ? "muted" : "");
      r.appendChild(el("td", null, dim.name || "—"));
      r.appendChild(el("td", "num", dim.score == null ? "—" : num(dim.score, 1)));
      r.appendChild(el("td", null, dim.severity || "—"));
      var vd = el("td", null, dim.verdict || (dim.assessable === false ? "不可评估" : "—"));
      vd.setAttribute("data-i18n-skip", "1");
      r.appendChild(vd);
      t.appendChild(r);
    });
    dc.appendChild(t);
    box.appendChild(dc);
  }
  // ---- tuning suggestions (gcode-diff-authored, same card shape as the
  // engine's recommendation rows) ----
  if (Array.isArray(d.suggestions) && d.suggestions.length) {
    var sc2 = el("div", "sum-card sum-advice");
    sc2.appendChild(el("h3", null, "调参建议（" + d.suggestions.length + "）"));
    d.suggestions.forEach(function (s) {
      var it = el("div", "rec-row");
      var head = el("div", null,
        (s.parameter || "?") + (s.suggested_value != null
          ? " → " + s.suggested_value : ""));
      head.setAttribute("data-i18n-skip", "1");
      it.appendChild(head);
      if (s.reason) {
        var rn = el("div", "hint");
        rn.textContent = s.reason;
        rn.setAttribute("data-i18n-skip", "1");
        it.appendChild(rn);
      }
      if (s.expected_effect) {
        var ee = el("div", "hint");
        ee.textContent = "预期效果: " + s.expected_effect;
        ee.setAttribute("data-i18n-skip", "1");
        it.appendChild(ee);
      }
      sc2.appendChild(it);
    });
    box.appendChild(sc2);
  }
  // ---- appearance block (present only when gcode-diff could assess it) ----
  if (d.appearance) {
    var ap = d.appearance;
    var ac2 = el("div", "sum-card");
    ac2.appendChild(el("h3", null, "外观"));
    var bits = [];
    if (ap.overhang && ap.overhang.assessable) {
      bits.push("悬垂评分 " + num(ap.overhang.score, 1)
        + "（最差层 " + num(ap.overhang.worst_layer, 0)
        + "，" + num(ap.overhang.worst_overhang_angle_deg, 0) + "°）");
    }
    if (ap.bridge && ap.bridge.verdict)
      bits.push("桥接: " + ap.bridge.verdict);
    if (bits.length) {
      var bt = el("div", "kv-lines", bits.join(" · "));
      bt.setAttribute("data-i18n-skip", "1");
      ac2.appendChild(bt);
      box.appendChild(ac2);
    }
  }
  _gcodeFooter(box, consoleText, meta.token);
}

// ---------- v0.25 slice-gcode stress-tune audit card ----------
// Renders the engine's <out>.tune.json sidecar (coordinate-level stress
// tuning along the attached slice gcode). Pure display of engine numbers —
// NO UI-side thresholds: coverage 50%/70% are the ENGINE's own console
// warning semantics and stay in the console verbatim; here every stat is a
// plain number. Engine prose (alignment / blind_spots) carries the i18n
// skip marker like every other engine-authored string.
function renderGcodeTune(tune, token) {
  var box = $("gcode-tune-box");
  if (!box) return;
  var body = $("gcode-tune-body");
  if (!tune || !tune.gcode_tune) {
    box.style.display = "none";   // absent = channel off (no attachment /
    if (body) body.innerHTML = ""; // old engine dropped the flags)
    return;
  }
  var t = tune.gcode_tune;
  box.style.display = "";
  body.innerHTML = "";
  // -1 is the engine's "not applicable" sentinel for patch coverage when
  // nothing was tuned (two-state sentinel: -1 ≠ a real ratio, never show it
  // as a number)
  var pcr = t.patch_coverage_ratio;
  var rows = [
    ["段总数", num(t.segments, 0)],
    ["挤出段", num(t.extrude_segments, 0)],
    ["空驶段", num(t.travel_segments, 0)],
    ["圆弧段", num(t.arc_segments, 0)],
    ["未解析行", num(t.unparsed_lines, 0)],
    ["忽略行", num(t.ignored_lines, 0)],
    ["热区候选", num(t.candidates, 0)],
    ["已调节数", num(t.tuned, 0)],
    ["无应力跳过", num(t.no_stress, 0)],
    ["特征排除", num(t.excluded_feature, 0)],
    ["应力覆盖率", num(t.coverage_pct, 1) + "%"],
    ["E 漂移", (t.e_drift_pct >= 0 ? "+" : "") + num(t.e_drift_pct, 2) + "%"],
    ["热区覆盖率", pcr === -1 || pcr === null || pcr === undefined
      ? "—" : num(pcr, 2)],
    ["热区百分位", num(t.p_hi, 2)],
    ["热区倍率", num(t.m_hot, 2)],
    ["应力下限", num(t.vm_floor_mpa, 1) + " MPa"],
  ];
  var tbl = el("table");
  var tb = el("tbody", null, "");
  rows.forEach(function (r) {
    var tr = el("tr", null, "");
    tr.appendChild(el("td", "k", r[0]));
    var v = el("td", "v", String(r[1]));
    v.setAttribute("data-i18n-skip", "1");
    tr.appendChild(v);
    tb.appendChild(tr);
  });
  tbl.appendChild(tb);
  body.appendChild(tbl);
  // v0.31 mismatch guidance (adjudicated iter 104 C5): tuned===0 is the one
  // honest trigger for "why did nothing change". The engine ships no
  // dedicated mismatch field and the three plausible causes are
  // observationally indistinguishable in tune.json (geometry mismatch / all
  // segments feature-excluded / hot-zone gate empty), so this states the
  // FACT and offers a self-check list — it must never assert a cause
  // (engine is the only source of truth). Strict ===0: a missing field is
  // not evidence of zero.
  if (t.tuned === 0) {
    var gz = el("div", "hint", "本次未改写任何挤出段。可自查的常见原因：");
    gz.style.marginTop = "6px";
    [
      "① 这份 G-code 是否用当前模型切片（几何对不上就采不到应力）",
      "② 挤出段是否全部被特征排除（例如填充段不参与采样）",
      "③ 热区门槛内是否没有挤出段（应力下限 / 热区百分位）",
    ].forEach(function (line) {
      var g = el("div", null, line);
      g.style.paddingLeft = "12px";
      gz.appendChild(g);
    });
    body.appendChild(gz);
  }
  if (t.alignment || t.alignment_blind_spots) {
    var al = el("div", "hint",
      "对齐: " + (t.alignment || "—") +
      (t.alignment_blind_spots
        ? "（盲区: " + t.alignment_blind_spots + "）" : ""));
    al.setAttribute("data-i18n-skip", "1");
    al.style.marginTop = "6px";
    body.appendChild(al);
  }
  if (token) {
    var a = el("button", null, "下载调优后 G-code");
    a.style.marginTop = "6px";
    a.onclick = function () {
      window.open("/api/gcode-tuned?token=" + encodeURIComponent(token),
                  "_blank");
    };
    body.appendChild(a);
  }
}
