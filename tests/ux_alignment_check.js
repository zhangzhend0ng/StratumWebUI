// v0.12 UX-interaction alignment E2E — REAL served page over CDP + REAL
// engine runs (harness cloned from browser_render_check.js). Asserts the
// four aligned interaction patterns, not just markup presence:
//   E1  mode switch (checkbox switch control) — default simple, toggles,
//       persists across reload
//   E2  panel titles carry no pipeline numbering ①-⑦ and use task language
//   E3  upload card: 3 primary actions + collapsible 分析选项 with a live
//       "已开 N 项" badge (collapsed state stays self-descriptive)
//   E4  sliders grouped (结构强度/材料与温度/速度与冷却); param search hides
//       empty groups
//   E5  run-delta chips: absent on the first run, present (SF chip) after a
//       param change re-run — engine numbers only, no first-run fake
//   E10 (v0.18) pristine-empty slimming + detail-wall fold + structured-
//       warning mirror + honest step strip (skip state for preset-less runs)
// Usage: node tests/ux_alignment_check.js   (exit 1 on any FAIL)
"use strict";
const { spawn, execSync } = require("child_process");
const fs = require("fs"), path = require("path"), os = require("os");

const CHROME_CANDIDATES = [
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
  path.join(process.env.LOCALAPPDATA || "", "Google\\Chrome\\Application\\chrome.exe"),
];
const CHROME = CHROME_CANDIDATES.find(p => p && fs.existsSync(p));
if (!CHROME) { console.error("SKIP: no Chrome found"); process.exit(3); }

function freePort() { require("net").createServer(); const n = require("net");
  return new Promise(res => { const s = n.createServer(); s.listen(0, () => {
    const p = s.address().port; s.close(() => res(p)); }); }); }
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function main() {
  const ROOT = path.join(__dirname, "..");
  const port = await freePort();
  const srv = spawn("python", ["server.py"], { cwd: ROOT, detached: false,
    stdio: "ignore",
    env: Object.assign({}, process.env, { STRATUM_UI_PORT: String(port),
                                          STRATUM_UI_NO_BROWSER: "1",
                                          // v0.24 E12: grid 24 makes the
                                          // cube fixture's engine run ~1.3s
                                          // (grid 16 → 0.22s), wide enough to
                                          // land a mid-run upload/cancel
                                          // deterministically; the thin beam
                                          // fixture stays ~30ms either way
                                          STRATUM_UI_GRID: "24" }) });
  const cport = await freePort();
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "stratum-ux-cdp-"));
  const chrome = spawn(CHROME, ["--headless=new", "--disable-gpu",
    "--remote-debugging-port=" + cport, "--user-data-dir=" + profile,
    "--no-first-run", "about:blank"], { stdio: "ignore" });
  const cleanup = () => { try { chrome.kill("SIGKILL"); } catch (e) {}
    try { srv.kill(); } catch (e) {}
    setTimeout(() => { try { execSync('cmd /c rmdir /s /q "' + profile + '"',
      { stdio: "ignore" }); } catch (e) {} }, 300); };
  process.on("exit", cleanup);

  try {
    let targets = null;
    for (let i = 0; i < 100; i++) {
      try {
        const r = await fetch("http://127.0.0.1:" + cport + "/json");
        targets = await r.json(); break;
      } catch (e) { await sleep(150); }
    }
    if (!targets) throw new Error("CDP did not come up");
    for (let i = 0; i < 100; i++) {
      try { const r = await fetch("http://127.0.0.1:" + port + "/api/status");
        if (r.status === 200) break; } catch (e) {}
      await sleep(150);
    }
    const page = targets.find(t => t.type === "page");
    const ws = new WebSocket(page.webSocketDebuggerUrl);
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
    let seq = 0; const pending = new Map();
    ws.onmessage = ev => { const m = JSON.parse(ev.data);
      if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } };
    const send = (method, params) => new Promise(res => {
      const id = ++seq; pending.set(id, res);
      ws.send(JSON.stringify({ id, method, params })); });
    const evalJs = async function (expr) {
      const r = await send("Runtime.evaluate",
        { expression: expr, returnByValue: true, awaitPromise: true });
      if (r.result && r.result.exceptionDetails)
        throw new Error("page exception: " + JSON.stringify(r.result.exceptionDetails).slice(0, 300));
      return r.result ? r.result.result.value : undefined;
    };
    const shot = async (name) => {
      await sleep(500);  // let the compositor pick up the DOM change
      const r = await send("Page.captureScreenshot", { format: "png" });
      const data = r && r.result && r.result.data;
      if (!data) throw new Error("screenshot failed: " + name +
        " — " + JSON.stringify(r).slice(0, 200));
      fs.writeFileSync(path.join(ROOT, "gui-test-screenshots", name),
        Buffer.from(data, "base64"));
      console.log("wrote " + name);
    };

    await send("Page.enable");
    await send("Emulation.setDeviceMetricsOverride",
      { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
    await send("Page.navigate", { url: "http://127.0.0.1:" + port + "/" });
    for (let i = 0; i < 50; i++) {
      if (await evalJs("typeof renderReport") === "function") break;
      await sleep(150);
    }
    // fresh visitor: no saved mode, no dismissed guide
    await evalJs("localStorage.clear(); 1");
    await send("Page.navigate", { url: "http://127.0.0.1:" + port + "/" });
    for (let i = 0; i < 50; i++) {
      if (await evalJs("typeof renderReport") === "function") break;
      await sleep(150);
    }
    for (let i = 0; i < 50; i++) {  // wait for /api/params → tuning panel built
      if (await evalJs("document.querySelectorAll('#tuning-panel .param-row').length") > 0) break;
      await sleep(150);
    }

    let fails = 0;
    const expect = (name, cond, detail) => {
      console.log((cond ? "PASS" : "FAIL") + "  " + name + (cond ? "" : "  " + detail));
      if (!cond) fails++;
    };

    // ---- E10a pristine empty state (v0.18, pre-upload) -------------------
    // boot must apply the no-report gate itself (REFUTE blocker: the gate
    // used to hang off hooks that never fire at boot)
    const boot = JSON.parse(await evalJs("(function(){var k=document.querySelector('.ui-kpis');" +
      "var c=document.getElementById('cand-panel');" +
      "var t=document.getElementById('detail-fold-toggle');" +
      "return JSON.stringify({noReport:document.body.classList.contains('no-report')," +
      "kpiVis:k.offsetParent!==null,candVis:c.offsetParent!==null," +
      "togVis:t.offsetParent!==null})})()"));
    expect("E10a boot: pristine panel hides KPIs/compare/fold toggle",
           boot.noReport && !boot.kpiVis && !boot.candVis && !boot.togVis,
           JSON.stringify(boot));
    // v0.22: onboarding is taught ONCE (#empty-guide). The v0.10 first-run
    // bar and the v0.13 step strip are gone — three copies of the same
    // three steps on a first visit was the clutter being fixed.
    expect("E10a boot: single onboarding surface (no first-guide / flow-steps)",
           await evalJs("!document.getElementById('first-guide')" +
                        " && !document.getElementById('flow-steps')" +
                        " && !!document.getElementById('empty-guide')"));

    // ---- E1 mode switch ------------------------------------------------
    const sw = JSON.parse(await evalJs("(function(){var i=document.getElementById('mode-toggle');" +
      "return JSON.stringify({tag:i.tagName,type:i.type,checked:i.checked," +
      "simple:document.body.classList.contains('mode-simple')," +
      "track:!!document.querySelector('.sw .sw-track')," +
      "lbl:(document.querySelector('.sw').textContent||'').trim()})})()"));
    expect("E1 switch: checkbox control + track + label 高级选项, default simple",
           sw.tag === "INPUT" && sw.type === "checkbox" && !sw.checked
           && sw.simple && sw.track && sw.lbl === "高级选项", JSON.stringify(sw));
    await evalJs("(function(){var l=document.querySelector('.sw');l.click();return 1})()");
    const afterOn = await evalJs("(function(){return JSON.stringify({" +
      "checked:document.getElementById('mode-toggle').checked," +
      "simple:document.body.classList.contains('mode-simple')," +
      "saved:localStorage.getItem('stratum-ui-mode')})})()");
    expect("E1 switch: click toggles advanced on + persists flag",
           afterOn.indexOf('"checked":true') >= 0
           && afterOn.indexOf('"simple":false') >= 0
           && afterOn.indexOf('"saved":"1"') >= 0, afterOn);
    await send("Page.navigate", { url: "http://127.0.0.1:" + port + "/" });
    for (let i = 0; i < 50; i++) {
      if (await evalJs("typeof renderReport") === "function") break;
      await sleep(150);
    }
    const persisted = await evalJs("document.getElementById('mode-toggle').checked && !document.body.classList.contains('mode-simple')");
    expect("E1 switch: advanced survives reload", persisted === true);

    // ---- E2 task-language titles ----------------------------------------
    const titles = await evalJs("(function(){var t=[];" +
      "document.querySelectorAll('main h2, .panel h2, details.ui-group > summary').forEach(function(n){" +
      "t.push(n.textContent.trim().split('\\n')[0])});return t.join(' | ')})()");
    const circled = /[①②③④⑤⑥⑦]/.test(titles);
    expect("E2 titles: no ①-⑦ pipeline numbering anywhere",
           !circled, titles.slice(0, 300));
    for (const t of ["模型", "当前参数", "调参", "环境与载荷", "分析结果",
                     "档位对比", "可信度", "切片软件建议（Orca）"]) {
      expect("E2 titles: task-language name 「" + t + "」 present",
             titles.indexOf(t) >= 0, titles.slice(0, 300));
    }
    expect("E2 titles: no raw CLI flag in the ⑦ panel tag",
           titles.indexOf("--orca-suggest") < 0, titles.slice(0, 300));

    // ---- E3 collapsible analysis options --------------------------------
    const opt = JSON.parse(await evalJs("(function(){var d=document.getElementById('opt-details');" +
      "if(!d)return 'missing';var btns=Array.prototype.map.call(" +
      "d.parentNode.querySelectorAll('.actions > button'),function(b){" +
      "return b.offsetParent===null?'':b.textContent}).filter(Boolean);" +
      "return JSON.stringify({open:d.open," +
      "badge:document.getElementById('opt-count').style.display," +
      "btns:btns.join(',')})})()"));
    // v0.17 added 下载 HTML 快照 to the primary row (4 buttons); this pin was
    // left at 3 and silently red since e7e53c3 — surfaced during v0.18 E10
    // work. Spirit of the pin: the row's composition is deliberate and the
    // dirty chip stays a span (E9 re-checks span-ness).
    expect("E3 options: collapsed by default, badge hidden, primary row = 4 buttons",
           opt !== "missing" && opt.open === false && opt.badge === "none"
           && opt.btns === "分析,优化对比,下载报告 JSON,下载 HTML 快照", JSON.stringify(opt));
    await evalJs("(function(){var c=document.getElementById('opt-fast');" +
      "c.checked=true;c.dispatchEvent(new Event('change'));return 1})()");
    const badgeOn = await evalJs("(function(){var b=document.getElementById('opt-count');" +
      "return b.style.display !== 'none' && b.textContent})()");
    expect("E3 options: enabling 快速预览 surfaces 已开 1 项 badge",
           badgeOn === "已开 1 项", String(badgeOn));
    await evalJs("(function(){var c=document.getElementById('opt-fast');" +
      "c.checked=false;c.dispatchEvent(new Event('change'));return 1})()");
    const badgeOff = await evalJs("document.getElementById('opt-count').style.display");
    expect("E3 options: badge clears when option off", badgeOff === "none");

    // ---- E4 grouped sliders + search-aware groups -----------------------
    const groups = JSON.parse(await evalJs("(function(){var gs=" +
      "document.querySelectorAll('#tuning-panel .param-group-h');" +
      "return JSON.stringify(Array.prototype.map.call(gs,function(g){return g.textContent}))})()"));
    expect("E4 groups: exactly 3 chunks in mental-model order",
           JSON.stringify(groups) === JSON.stringify(["结构强度", "材料与温度", "速度与冷却"]),
           JSON.stringify(groups));
    const strength = await evalJs("(function(){var rows=" +
      "document.querySelectorAll('#tuning-panel .param-row');var names=" +
      "Array.prototype.map.call(rows,function(r){return r.querySelector('input,select').dataset.param});" +
      "return names.indexOf('walls')>-1 && names.indexOf('material')>-1 && names.indexOf('cooling_fan')>-1})()");
    expect("E4 groups: all sliders still present (none dropped)", strength === true);
    await evalJs("(function(){var s=document.getElementById('param-search');" +
      "s.value='温度';s.dispatchEvent(new Event('input'));return 1})()");
    const filtered = JSON.parse(await evalJs("(function(){function vis(n){" +
      "return n.style.display!=='none'}var gs=document.querySelectorAll('#tuning-panel .param-group-h');" +
      "return JSON.stringify(Array.prototype.map.call(gs,function(g){return {t:g.textContent,v:vis(g)}}))})()"));
    expect("E4 search: 温度 hides 结构强度/速度与冷却 headers, keeps 材料与温度",
           filtered.length === 3 && filtered[0].v === false
           && filtered[1].v === true && filtered[2].v === false,
           JSON.stringify(filtered));
    await evalJs("(function(){var s=document.getElementById('param-search');" +
      "s.value='';s.dispatchEvent(new Event('input'));return 1})()");

    // ---- E5 run-delta chips over REAL engine runs ------------------------
    const inject = (name, b64) => evalJs("(function(){var b=atob('" + b64 +
      "');var u=new Uint8Array(b.length);for(var i=0;i<b.length;i++)u[i]=b.charCodeAt(i);" +
      "var f=new File([u],'" + name + "');var dt=new DataTransfer();dt.items.add(f);" +
      "var inp=document.getElementById('model-file');inp.files=dt.files;" +
      "inp.dispatchEvent(new Event('change'));return 'ok'})()");
    const toastState = () => evalJs("(function(){var t=document.querySelectorAll('#toasts .toast');" +
      "return JSON.stringify(Array.prototype.map.call(t,function(n){" +
      "return {cls:n.className,txt:n.textContent.replace(/\\u00d7$/,'')}}))})()");
    const clearToasts = () => evalJs("(function(){var b=document.getElementById('toasts');" +
      "if(b)b.innerHTML='';return 1})()");
    const waitDone = async (label) => {
      clearToasts();
      for (let i = 0; i < 150; i++) {  // engine run, up to ~45s
        const ts = JSON.parse(await toastState());
        if (ts.some(t => t.cls.indexOf("toast ok") >= 0
            && (t.txt === "分析完成" || t.txt === "对比分析完成"))) return true;
        await sleep(300);
      }
      return false;
    };
    const goodB64 = fs.readFileSync(
      path.join(ROOT, "test_data", "beam_100x10x4.stl")).toString("base64");
    await inject("beam.stl", goodB64);
    const run1 = await waitDone("first run");
    const noDeltaFirst = await evalJs("!document.querySelector('#summary-cards .run-delta')");
    expect("E5 delta: first run renders NO delta chips (nothing to compare)",
           run1 && noDeltaFirst, JSON.stringify({ run1: run1, noDeltaFirst: noDeltaFirst }));
    await evalJs("(function(){var i=document.querySelector('[data-param=walls]');" +
      "if(i){i.value='8';i.dispatchEvent(new Event('input'));i.dispatchEvent(new Event('change'));}" +
      "document.getElementById('btn-analyze').click();return 1})()");
    const run2 = await waitDone("re-run");
    const delta = JSON.parse(await evalJs("(function(){var d=" +
      "document.querySelector('#summary-cards .run-delta');if(!d)return 'none';" +
      "return JSON.stringify({chips:Array.prototype.map.call(" +
      "d.querySelectorAll('.delta-chip'),function(c){" +
      "return {txt:c.textContent,cls:c.className}})})})()"));
    const sfChip = delta !== "none"
      && delta.chips.some(c => c.txt.indexOf("SF") === 0
          && /▲|▼/.test(c.txt) && /up|down/.test(c.cls));
    expect("E5 delta: re-run shows an SF ▲/▼ chip with direction class",
           run2 && sfChip, JSON.stringify(delta).slice(0, 300));

    // ---- E6 visual-regression guards (from the v012 vision review) --------
    const overflow = JSON.parse(await evalJs("(function(){var de=" +
      "document.documentElement;var sc=document.getElementById('summary-cards');" +
      "return JSON.stringify({pageX:de.scrollWidth>de.clientWidth+1," +
      "pageW:de.scrollWidth,cw:de.clientWidth," +
      "cardsX:sc?sc.scrollWidth>sc.clientWidth+1:null})})()"));
    expect("E6 layout: no horizontal overflow (page or summary cards)",
           overflow.pageX === false && overflow.cardsX !== true,
           JSON.stringify(overflow));
    const stress = await evalJs("document.getElementById('res-stress').textContent");
    expect("E6 KPI: 最大应力 renders a number + MPa (no mojibake)",
           /MPa\s*$/.test(stress) && /\d/.test(stress) && stress.indexOf("?") < 0,
           String(stress));

    // ---- E9 dirty chip (walls=8 is dirty from the E5 re-run) --------------
    const chip1 = JSON.parse(await evalJs("(function(){var c=document.getElementById('dirty-chip');" +
      "return JSON.stringify({tag:c.tagName,vis:c.style.display!=='none',txt:c.textContent})})()"));
    expect("E9 chip: span (not button), shows 已改 1 项 after walls change",
           chip1.tag === "SPAN" && chip1.vis && chip1.txt === "已改 1 项",
           JSON.stringify(chip1));
    await evalJs("document.getElementById('btn-reset-all').click(); 1");
    const chip2 = JSON.parse(await evalJs("(function(){var c=document.getElementById('dirty-chip');" +
      "return JSON.stringify({vis:c.style.display!=='none'})})()"));
    expect("E9 chip: hidden after 重置全部修改", chip2.vis === false, JSON.stringify(chip2));

    // ---- E8 sticky verdict bar -------------------------------------------
    const sv1 = JSON.parse(await evalJs("(function(){var s=document.getElementById('sticky-verdict');" +
      "return JSON.stringify({disp:s.style.display,pos:getComputedStyle(s).position," +
      "hasSf:s.textContent.indexOf('安全系数')>=0," +
      "hasDelta:!!s.querySelector('.delta-chip')})})()"));
    expect("E8 sticky: visible after render, mirrors SF + delta chips, position sticky",
           sv1.disp === "flex" && sv1.pos === "sticky" && sv1.hasSf && sv1.hasDelta,
           JSON.stringify(sv1));
    await evalJs("document.getElementById('btn-analyze').click(); 1");
    let runningShown = false;
    for (let i = 0; i < 10; i++) {  // catch the running state within ~3s
      const t = await evalJs("(function(){var s=document.getElementById('sticky-verdict');" +
        "return s.style.display==='flex' && s.textContent.indexOf('分析中')>=0})()");
      if (t) { runningShown = true; break; }
      await sleep(300);
    }
    let runDone = false;
    for (let i = 0; i < 150; i++) {
      const t = await evalJs("(function(){var s=document.getElementById('sticky-verdict');" +
        "return s.style.display==='flex' && s.textContent.indexOf('安全系数')>=0})()");
      if (t) { runDone = true; break; }
      await sleep(300);
    }
    expect("E8 sticky: shows 分析中 while running, restores SF after",
           runningShown && runDone, JSON.stringify({ runningShown, runDone }));

    // ---- E7 simple mode = single-column, one-answer stack (v0.22) ---------
    await evalJs("(function(){var i=document.getElementById('mode-toggle');" +
      "if(!i.checked)i.click();return 1})()");  // ensure advanced for contrast check
    const advCols = await evalJs("getComputedStyle(document.querySelector('.grid')).gridTemplateColumns");
    await evalJs("(function(){var i=document.getElementById('mode-toggle');" +
      "if(i.checked)i.click();return 1})()");  // switch to simple
    await sleep(200);
    const simple = JSON.parse(await evalJs("(function(){var cols=" +
      "getComputedStyle(document.querySelector('.grid')).gridTemplateColumns;" +
      "var names=[];document.querySelectorAll('.panel h2').forEach(function(h){" +
      "if(h.offsetParent!==null)names.push(h.textContent.trim().split('\\n')[0].split(' ')[0])});" +
      "var sv=document.getElementById('sticky-verdict');" +
      "var k=document.querySelector('.ui-kpis');" +
      "var rec=document.getElementById('rec-items');" +
      "var cand=document.getElementById('cand-panel');" +
      "function bv(id){var b=document.getElementById(id);return b.offsetParent!==null}" +
      "return JSON.stringify({cols:cols,names:names.join(',')," +
      "svVis:sv.offsetParent!==null," +
      "kpiVis:k.offsetParent!==null,recVis:rec.offsetParent!==null," +
      "candVis:cand.offsetParent!==null," +
      "anz:bv('btn-analyze'),snap:bv('btn-snapshot')," +
      "cmp:bv('btn-compare'),rpt:bv('btn-report')})})()"));
    expect("E7 flow: simple mode is single-column (advanced was 2-col)",
           advCols.indexOf(" ") >= 0 && simple.cols.indexOf(" ") < 0,
           JSON.stringify({ advCols, cols: simple.cols }));
    // v0.23: G-code 工具面板（评分入口）有意暴露给简单模式，插在快速预设之后
    expect("E7 flow: panel order = 模型→快速预设→G-code→分析结果→档位对比, 档位对比 visible",
           simple.names === "模型,快速预设,G-code,分析结果,档位对比" && simple.candVis,
           JSON.stringify(simple));
    expect("E7 v0.22: idle sticky hidden in simple mode (hero carries SF once)",
           !simple.svVis, JSON.stringify(simple));
    expect("E7 v0.22: KPI row + rec list live behind the detail fold",
           !simple.kpiVis && !simple.recVis, JSON.stringify(simple));
    expect("E7 v0.22: primary row = 分析 + 快照 (compare/report advanced-only)",
           simple.anz && simple.snap && !simple.cmp && !simple.rpt,
           JSON.stringify(simple));
    // v0.22: while RUNNING the sticky bar returns even in simple mode —
    // it is the run feedback channel; it hides again when the hero re-renders
    await evalJs("document.getElementById('btn-analyze').click(); 1");
    let simpleRunning = false;
    for (let i = 0; i < 12; i++) {
      const t = await evalJs("(function(){var s=document.getElementById('sticky-verdict');" +
        "return s.style.display==='flex' && s.textContent.indexOf('分析中')>=0})()");
      if (t) { simpleRunning = true; break; }
      await sleep(300);
    }
    let simpleDone = false;
    for (let i = 0; i < 150; i++) {
      const t = await evalJs(
        "document.getElementById('sticky-verdict').style.display==='none'");
      if (t) { simpleDone = true; break; }
      await sleep(300);
    }
    expect("E7 v0.22: sticky shows 分析中 while running in simple, then hides",
           simpleRunning && simpleDone,
           JSON.stringify({ simpleRunning, simpleDone }));
    await evalJs("(function(){var i=document.getElementById('mode-toggle');" +
      "if(!i.checked)i.click();return 1})()");  // back to advanced
    await sleep(200);
    const advBack = JSON.parse(await evalJs("(function(){var sv=document.getElementById('sticky-verdict');" +
      "var k=document.querySelector('.ui-kpis');var r=document.getElementById('rec-items');" +
      "return JSON.stringify({svVis:sv.offsetParent!==null," +
      "kpiVis:k.offsetParent!==null,recVis:r.offsetParent!==null})})()"));
    expect("E7 v0.22: advanced restores sticky bar + KPI row + rec list",
           advBack.svVis && advBack.kpiVis && advBack.recVis,
           JSON.stringify(advBack));

    // ---- E10b detail-wall fold (v0.18; v0.22 wall also owns KPIs + rec) ---
    // Advanced contrast first (E7 left us here): wall visible, toggle hidden
    const adv10 = JSON.parse(await evalJs("(function(){var w=document.getElementById('phase-d-detail');" +
      "var t=document.getElementById('detail-fold-toggle');" +
      "return JSON.stringify({wallVis:w.offsetParent!==null,togVis:t.offsetParent!==null})})()"));
    expect("E10b advanced: wall visible, fold toggle hidden",
           adv10.wallVis && !adv10.togVis, JSON.stringify(adv10));
    await evalJs("(function(){var i=document.getElementById('mode-toggle');" +
      "if(i.checked)i.click();return 1})()");  // switch to simple
    await sleep(200);
    const foldClosed = JSON.parse(await evalJs("(function(){var w1=document.getElementById('structural-summary');" +
      "var w2=document.getElementById('phase-d-detail');" +
      "var m=document.getElementById('pd-warn-promoted');" +
      "var t=document.getElementById('detail-fold-toggle');" +
      "var k=document.querySelector('.ui-kpis');" +
      "var r=document.getElementById('rec-items');" +
      "return JSON.stringify({wall1Vis:w1.offsetParent!==null," +
      "wall2Vis:w2.offsetParent!==null,togVis:t.offsetParent!==null," +
      "kpiVis:k.offsetParent!==null,recVis:r.offsetParent!==null," +
      "noReport:document.body.classList.contains('no-report')," +
      "mirrorTxt:m.textContent.slice(0,60)," +
      "warnLine:(document.querySelector('#phase-d-detail .pd-warn')||{}).textContent})})()"));
    expect("E10b simple+closed: wall + KPIs + rec list hidden, toggle visible",
           !foldClosed.wall1Vis && !foldClosed.wall2Vis && foldClosed.togVis
           && !foldClosed.kpiVis && !foldClosed.recVis && !foldClosed.noReport,
           JSON.stringify(foldClosed));
    expect("E10b mirror: buckling warning echoed above the fold (engine text)",
           foldClosed.mirrorTxt.indexOf("屈曲警示") >= 0,
           JSON.stringify(foldClosed));
    expect("E10b wall line keeps the engine text under pd-warn class",
           (foldClosed.warnLine || "").indexOf("屈曲警示") >= 0,
           JSON.stringify(foldClosed));
    // open → wall + KPIs + rec list visible in place; close → hidden again
    await evalJs("document.getElementById('detail-fold-toggle').click(); 1");
    await sleep(120);
    const foldOpen = JSON.parse(await evalJs("(function(){var w1=document.getElementById('structural-summary');" +
      "var w2=document.getElementById('phase-d-detail');" +
      "var k=document.querySelector('.ui-kpis');var r=document.getElementById('rec-items');" +
      "return JSON.stringify({w1:w1.offsetParent!==null,w2:w2.offsetParent!==null," +
      "kpi:k.offsetParent!==null,rec:r.offsetParent!==null," +
      "arrow:document.getElementById('detail-fold-arrow').textContent})})()"));
    expect("E10b simple+open: wall + KPIs + rec list visible, arrow flips",
           foldOpen.w1 && foldOpen.w2 && foldOpen.kpi && foldOpen.rec
           && foldOpen.arrow !== "▸",
           JSON.stringify(foldOpen));
    await evalJs("document.getElementById('detail-fold-toggle').click(); 1");
    await sleep(120);
    const foldReclosed = JSON.parse(await evalJs("(function(){var w=document.getElementById('phase-d-detail');" +
      "var k=document.querySelector('.ui-kpis');var r=document.getElementById('rec-items');" +
      "return JSON.stringify({w:w.offsetParent===null,k:k.offsetParent===null," +
      "r:r.offsetParent===null})})()"));
    expect("E10b simple+reclosed: wall + KPIs + rec list hidden again",
           foldReclosed.w && foldReclosed.k && foldReclosed.r,
           JSON.stringify(foldReclosed));

    // ---- E11 raw-table fold + outlet invariant (v0.19 round B) ------------
    // Shape-agnostic by design: open state must mirror the cand-bars outlet
    // (bars render only with ≥2 feasible — fold closed; otherwise auto-open)
    const e11 = JSON.parse(await evalJs("(function(){var f=document.getElementById('cand-raw-fold');" +
      "var b=document.getElementById('cand-bars');" +
      "var t=document.getElementById('cand-table');" +
      "var p=document.getElementById('cand-panel');" +
      "return JSON.stringify({hasFold:!!f,hasTable:!!t,inside:!!(f&&t&&f.contains(t))," +
      "barsOutside:!!(f&&b&&!f.contains(b))," +
      "barsRendered:!!(b&&b.children.length>0)," +
      "openState:f?f.open:null," +
      "summary:((f&&f.querySelector('summary'))||{}).textContent||''," +
      "panelVis:!!(p&&p.offsetParent!==null)})})()"));
    expect("E11 fold: in-panel <details> wraps the raw table, bars stay outside",
           e11.hasFold && e11.hasTable && e11.inside && e11.barsOutside && e11.panelVis,
           JSON.stringify(e11));
    expect("E11 fold: open state mirrors the outlet invariant (bars rendered ⇒ closed)",
           e11.openState === !e11.barsRendered, JSON.stringify(e11));
    expect("E11 fold: summary labels the raw table",
           e11.summary.indexOf("原始对比表") >= 0, JSON.stringify(e11));

    await shot("v018_simple_folded.png");  // simple: folded wall + mirror + skip strip

    // E10b leaves us in simple mode — restore advanced for its labeled shot,
    // then switch back for the simple one (byte-identical shots = mode bug,
    // caught by comparing file sizes)
    await evalJs("(function(){var i=document.getElementById('mode-toggle');" +
      "if(!i.checked)i.click();return 1})()");  // to advanced
    await sleep(200);
    await shot("v013_advanced_sticky.png");  // advanced: sticky bar + groups + delta
    await evalJs("(function(){var i=document.getElementById('mode-toggle');" +
      "if(i.checked){i.click()}return 1})()");
    await sleep(200);
    await shot("v013_simple_flow.png");  // simple: single-column task flow + step strip

    // ---- E12 (v0.24) session-change sweep: upload a new model ------------
    // A rendered verdict/KPIs/history must not survive the session change.
    // Fixture: cube_100.stl on the suite's grid-24 server (~1.3s per run —
    // the timing margin that makes the cancel/mid-run windows stable; beam
    // runs ~30ms and cannot hold a race). Setup renders cube with walls=8,
    // then re-uploads the SAME file (a NEW token — session change, not a
    // re-run) and cancels the fresh session's auto-analyze, so the pristine
    // panel is stable to assert against.
    const cubeB64 = fs.readFileSync(
      path.join(ROOT, "test_data", "cube_100.stl")).toString("base64");
    await evalJs("(function(){var i=document.querySelector('[data-param=walls]');" +
      "if(i){i.value='8';i.dispatchEvent(new Event('input'));i.dispatchEvent(new Event('change'));}" +
      "document.getElementById('btn-analyze').click();return 1})()");
    const preRun = await waitDone("walls=8 run before re-upload");
    expect("E12 setup: walls=8 run rendered before the session change",
           preRun, "timeout waiting for the pre-upload run");
    await inject("cube_100.stl", cubeB64);  // new token → resetResultsPanel fires
    let started = false;
    for (let i = 0; i < 60; i++) {  // fresh session's run starts (~1.3s long)
      started = await evalJs("(function(){var b=document.getElementById('btn-analyze');" +
        "return b.className.indexOf('ui-running')>=0})()");
      if (started) break;
      await sleep(50);
    }
    await evalJs("document.getElementById('btn-analyze').click(); 1");  // 取消
    let stopped = false;
    for (let i = 0; i < 60; i++) {
      stopped = await evalJs("(function(){var b=document.getElementById('btn-analyze');" +
        "return b.className.indexOf('ui-running')<0})()");
      if (stopped) break;
      await sleep(50);
    }
    await sleep(500);  // cancel path (abort/toast) settles
    const pristine = JSON.parse(await evalJs("(function(){" +
      "var eg=document.getElementById('empty-guide');" +
      "var sc=document.getElementById('summary-cards');" +
      "var pdw=document.getElementById('pd-warn-promoted');" +
      "var bars=document.getElementById('cand-bars');" +
      "var ac=document.getElementById('alerts-card');" +
      "var up=document.getElementById('upload-msg');" +
      "return JSON.stringify({noReport:document.body.classList.contains('no-report')," +
      "egVis:!!eg&&eg.style.display!=='none'," +
      "cardsEmpty:!sc||sc.children.length===0," +
      "pdwAlive:!!pdw,pdwEmpty:!!pdw&&pdw.childNodes.length===0," +
      "barsEmpty:!bars||bars.children.length===0," +
      "alertsHidden:!ac||ac.style.display==='none'," +
      "cpWalls:document.getElementById('cp-walls').textContent," +
      "histEmpty:(document.getElementById('history-list').textContent||'').indexOf('尚无运行')>=0," +
      "upload:(up&&up.textContent||'').slice(0,40)})})()"));
    expect("E12a pristine: re-upload restores empty-guide + no-report + cleared panel",
           pristine.noReport && pristine.egVis && pristine.cardsEmpty &&
           pristine.barsEmpty && pristine.alertsHidden &&
           pristine.cpWalls === "—" && pristine.histEmpty,
           JSON.stringify(pristine));
    expect("E12a survival: pd-warn mirror node survives the clear (lift-out)",
           pristine.pdwAlive && pristine.pdwEmpty, JSON.stringify(pristine));
    // cross-model delta guard: the new session's first render must not
    // compare against the old session's run (state.history was emptied)
    await evalJs("document.getElementById('btn-analyze').click(); 1");
    const runB = await waitDone("fresh-session run after re-analyze");
    let afterB = null;
    for (let i = 0; i < 20; i++) {  // refreshHistory lands after the toast
      afterB = JSON.parse(await evalJs("(function(){" +
        "var d=document.querySelector('#summary-cards .run-delta');" +
        "var hl=document.getElementById('history-list');" +
        "var rows=Array.prototype.filter.call(hl.children," +
        "function(n){return n.tagName==='DIV'}).length;" +
        "return JSON.stringify({delta:!!d," +
        "cpWalls:document.getElementById('cp-walls').textContent," +
        "runs:rows})})()"));
      if (afterB.runs >= 1) break;
      await sleep(150);
    }
    expect("E12b cross-model delta: fresh session renders NO delta chips",
           runB && !afterB.delta, JSON.stringify(afterB));
    expect("E12b fresh session: history shows exactly its own 1 run (cancelled " +
           "run appended nothing)",
           runB && afterB.runs === 1, JSON.stringify(afterB));

    // ---- E12c (v0.24) mid-run upload race (S7) ----------------------------
    // walls=8 manual run (~1.3s) in flight → the cube re-upload swaps the
    // session mid-run → the late response of the OLD run must be dropped and
    // the queued run for the new session must fire (defaults echo walls=2).
    // sawStale only counts AFTER the reset landed (cp-walls read "—") — the
    // legitimate pre-upload "8" is not a stale render.
    await evalJs("(function(){var i=document.querySelector('[data-param=walls]');" +
      "if(i){i.value='8';i.dispatchEvent(new Event('input'));i.dispatchEvent(new Event('change'));}" +
      "document.getElementById('btn-analyze').click();return 1})()");
    await inject("cube_100.stl", cubeB64);  // session swap inside the window
    let sawReset = false, sawStale = false, finalWalls = "";
    for (let i = 0; i < 200; i++) {
      const st = JSON.parse(await evalJs("(function(){" +
        "var w=document.getElementById('cp-walls').textContent;" +
        "var b=document.getElementById('btn-analyze');" +
        "return JSON.stringify({w:w,run:b.className.indexOf('ui-running')>=0})})()"));
      finalWalls = st.w;
      if (st.w === "—") sawReset = true;
      if (sawReset && st.w === "8") sawStale = true;
      if (sawReset && !st.run && st.w !== "—") break;
      await sleep(100);
    }
    expect("E12c race: old session's late render never lands (cp-walls≠8 " +
           "after reset) and the new session's run fires (walls=2 echo)",
           sawReset && !sawStale && finalWalls === "2",
           JSON.stringify({ sawReset: sawReset, sawStale: sawStale,
                            finalWalls: finalWalls }));

    console.log(fails === 0 ? "ux alignment E2E all green"
                            : fails + " FAILURES");
    process.exit(fails === 0 ? 0 : 1);
  } catch (e) {
    console.error("HARNESS ERROR: " + (e && e.stack || e));
    process.exit(2);
  }
}
main();
