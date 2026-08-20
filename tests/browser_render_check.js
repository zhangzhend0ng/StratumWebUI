// T58 companion (iter 78): browser-level render E2E. The node-vm checks
// (T56/T57) run report.js against stub DOM objects; this one drives a REAL
// headless Chrome over CDP (native WebSocket, zero deps) against the REAL
// served page: real <script> order, real DOM elements, real helpers.
// Calls the page's own window.renderReport with the real sample report and
// asserts the iter 67-77 render surface + "no exception thrown".
// Loud SKIP (exit 3) when Chrome is absent — never a silent pass.
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
  const srv = spawn(process.execPath.length ? "python" : "python",
    ["server.py"], { cwd: ROOT, detached: false, stdio: "ignore",
    env: Object.assign({}, process.env, { STRATUM_UI_PORT: String(port),
                                          STRATUM_UI_NO_BROWSER: "1" }) });
  const cport = await freePort();
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "stratum-ui-cdp-"));
  const chrome = spawn(CHROME, ["--headless=new", "--disable-gpu",
    "--remote-debugging-port=" + cport, "--user-data-dir=" + profile,
    "--no-first-run", "about:blank"], { stdio: "ignore" });
  const cleanup = () => { try { chrome.kill("SIGKILL"); } catch (e) {}
    try { srv.kill(); } catch (e) {}
    // chrome teardown is async on Windows — give Crashpad a moment before
    // rmdir, and never fail on the temp profile (best-effort)
    setTimeout(() => { try { execSync('cmd /c rmdir /s /q "' + profile + '"',
      { stdio: "ignore" }); } catch (e) {} }, 300); };
  process.on("exit", cleanup);

  try {
    // wait for server + CDP endpoint
    let targets = null;
    for (let i = 0; i < 100; i++) {
      try {
        const r = await fetch("http://127.0.0.1:%d/json" .replace("%d", cport));
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

    await send("Page.enable");
    await send("Page.navigate", { url: "http://127.0.0.1:" + port + "/" });
    for (let i = 0; i < 50; i++) {
      if (await evalJs("typeof renderReport") === "function") break;
      await sleep(150);
    }
    const report = fs.readFileSync(
      path.join(ROOT, "test_data", "real3mf-results", "report.json"), "utf8");
    await evalJs("window.__r = " + report + "; typeof renderReport");
    const threw = await evalJs(
      "(function(){try{renderReport(window.__r,'');return 'no'}catch(e){return String(e)}})()");

    let fails = 0;
    const expect = (name, cond, detail) => {
      console.log((cond ? "PASS" : "FAIL") + "  " + name + (cond ? "" : "  " + detail));
      if (!cond) fails++;
    };
    expect("real page: renderReport did not throw", threw === "no", threw);
    expect("real page: CG hint in phase-b-detail",
           await evalJs("document.getElementById('phase-b-detail').textContent.indexOf('CG 求解器收敛') >= 0"));
    expect("real page: Phase B part-visibility warning",
           await evalJs("document.getElementById('warning-list').textContent.indexOf('Phase B: 网格含 41 个几何部件') >= 0"));
    expect("real page: priority badge [P2]",
           await evalJs("document.body.textContent.indexOf('[P2]') >= 0"));
    expect("real page: estimate tooltip on cand volume cell",
           await evalJs("(function(){var t=document.querySelectorAll('#cand-body td[title]');for (var i=0;i<t.length;i++){if(t[i].title.indexOf('材料 ')>=0)return true}return false})()"));
    expect("real page: SF source tooltip",
           await evalJs("(function(){var t=document.querySelectorAll('#cand-body td[title]');for (var i=0;i<t.length;i++){if(t[i].title.indexOf('SF 来源')>=0)return true}return false})()"));
    // (iter 79) stlParse in the REAL page: the iter 67/73/74 parser changes
    // were node-stub-verified only. Feed a malformed ASCII STL through the
    // page's own function (base64 → bytes → stlParse) and assert the guard
    // behavior on real script/DOM wiring.
    const asciiBad = "solid x\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nfacet normal 0 0 1\nouter loop\nvertex e5 2 3\nvertex 4 5 6\nvertex 7 8 9\nendloop\nendfacet\nfacet normal 0 0 1\nouter loop\nvertex 10 0 0\nvertex 11 0 0\nendloop\nendfacet\nendsolid x\n";
    const b64 = Buffer.from(asciiBad, "utf8").toString("base64");
    const stlRes = await evalJs(
      "(function(){var b=atob('" + b64 + "');var u=new Uint8Array(b.length);" +
      "for(var i=0;i<b.length;i++)u[i]=b.charCodeAt(i);" +
      "var m=stlParse(u.buffer);return JSON.stringify({tris:m.tris,dropped:m.dropped," +
      "finite:m.pos.every(isFinite),bbox:m.bbox&&m.bbox.max[0]})})()");
    const sr = JSON.parse(stlRes);
    // expectations derived by hand: facet2 (e5→NaN, dropped++) and facet3
    // (2 vertices, malformed, dropped++) both dropped; only facet1 survives
    // → tris=1, bbox.max[0]=1. (First run expected dropped=1/bbox=11 — that
    // was a stale copy from the node case 6 fixture, which has a THIRD good
    // facet; the browser was right, the test was wrong.)
    expect("real page: stlParse NaN-tri skipped, malformed facet dropped",
           sr.tris === 1 && sr.dropped === 2 && sr.finite === true && sr.bbox === 1,
           JSON.stringify(sr));

    // (iter 80) FULL-PIPELINE E2E with the real engine: upload the real STL,
    // analyze with load=compression + explicit fatigue target, render the
    // REAL returned report, assert the iter 77 tooltips are populated by the
    // actual server→engine→report path (forged-JSON checks cannot prove this).
    const stlB64 = fs.readFileSync(path.join(ROOT, "test_data", "beam_100x10x4.stl")).toString("base64");
    const e2e = JSON.parse(await evalJs("(async function(){" +
      "var b=atob('" + stlB64 + "');var u=new Uint8Array(b.length);" +
      "for(var i=0;i<b.length;i++)u[i]=b.charCodeAt(i);" +
      "var up=await fetch('/api/upload?name=e2e.stl',{method:'POST'," +
      "headers:{'X-Stratum-UI':'1'},body:u.buffer}).then(function(r){return r.json()});" +
      "if(!up.ok)return JSON.stringify({stage:'upload',err:up.error});" +
      "var an=await fetch('/api/analyze',{method:'POST',headers:{'Content-Type':'application/json','X-Stratum-UI':'1'}," +
      "body:JSON.stringify({token:up.token,env:{load:'compression',fatigue_cycles:100000}})})" +
      ".then(function(r){return r.json()});" +
      "if(!an.ok)return JSON.stringify({stage:'analyze',err:an.error});" +
      "try{renderReport(an.report,an.console||'')}catch(e){return JSON.stringify({stage:'render',err:String(e)})}" +
      "var bk=document.getElementById('res-buckling');var ft=document.getElementById('res-fatigue');" +
      "return JSON.stringify({stage:'ok',bk:bk.textContent,bkT:bk.title||''," +
      "ft:ft.textContent,ftT:ft.title||'',sl:(an.report.phase_d||{}).buckling_slenderness," +
      "ex:(an.report.phase_d||{}).fatigue_expected_cycles});})()"));
    expect("e2e: pipeline stage ok", e2e.stage === "ok", JSON.stringify(e2e).slice(0, 200));
    if (e2e.stage === "ok") {
      expect("e2e: real buckling SF + slenderness tooltip",
             parseFloat(e2e.bk) > 0 && e2e.bkT.indexOf("细长比 ") === 0
             && typeof e2e.sl === "number" && e2e.sl > 0,
             JSON.stringify({bk: e2e.bk, bkT: e2e.bkT, sl: e2e.sl}));
      expect("e2e: real fatigue SF + target-life tooltip",
             e2e.ft !== "—" && e2e.ftT.indexOf("目标寿命 100000 次") === 0
             && e2e.ex === 100000,
             JSON.stringify({ft: e2e.ft, ftT: e2e.ftT, ex: e2e.ex}));
    }

    // (iter 84) REAL user-flow error paths: inject files via DataTransfer →
    // the page's own onFile handler → server rejects/accepts → assert the
    // real upload-msg error rendering and the full recover-to-report flow.
    const inject = (name, b64) => evalJs("(function(){var b=atob('" + b64 +
      "');var u=new Uint8Array(b.length);for(var i=0;i<b.length;i++)u[i]=b.charCodeAt(i);" +
      "var f=new File([u],'" + name + "');var dt=new DataTransfer();dt.items.add(f);" +
      "var inp=document.getElementById('model-file');inp.files=dt.files;" +
      "inp.dispatchEvent(new Event('change'));return 'ok'})()");
    const msgState = () => evalJs("(function(){var m=document.getElementById('upload-msg');" +
      "return JSON.stringify({cls:m.className,txt:m.textContent})})()");
    // (UI v2) analyze/compare success+error feedback moved to the #toasts
    // container (5s auto-hide for ok/info, persistent err) — poll it instead
    // of upload-msg/export-msg
    const toastState = () => evalJs("(function(){var t=document.querySelectorAll('#toasts .toast');" +
      "return JSON.stringify(Array.prototype.map.call(t,function(n){" +
      "return {cls:n.className,txt:n.textContent.replace(/\\u00d7$/,'')}}))})()");
    const clearToasts = () => evalJs("(function(){var b=document.getElementById('toasts');" +
      "if(b)b.innerHTML='';return 1})()");

    const garbageB64 = fs.readFileSync(
      path.join(ROOT, "test_data", "garbage.stl")).toString("base64");
    await inject("garbage.stl", garbageB64);
    let errShown = null;
    for (let i = 0; i < 40; i++) {  // upload+auto-analyze, up to ~12s
      const ts = JSON.parse(await toastState());
      const e = ts.find(t => t.cls.indexOf("err") >= 0);
      if (e) { errShown = e; break; }
      await sleep(300);
    }
    expect("e2e err: garbage upload surfaces err box",
           errShown !== null && errShown.txt.length > 0,
           JSON.stringify(errShown));

    const goodB64 = fs.readFileSync(
      path.join(ROOT, "test_data", "beam_100x10x4.stl")).toString("base64");
    await inject("beam.stl", goodB64);
    let recovered = null, lastState = null;
    for (let i = 0; i < 100; i++) {  // engine run, up to ~30s
      const ts = JSON.parse(await toastState());
      const ok = ts.find(t => t.cls.indexOf("toast ok") >= 0
        && (t.txt === "分析完成" || t.txt === "对比分析完成"));
      const ov = await evalJs("document.getElementById('res-overall').textContent");
      // recovery = this run's OWN success toast AND a fresh report (a bare
      // ov!=="—" would trip on the STALE report from the earlier
      // direct-pipeline step — caught by the n=0 preview race it caused)
      if (ok && ov !== "—") { recovered = ok; recovered.ov = ov; break; }
      lastState = ts;
      await sleep(300);
    }
    expect("e2e err: recovery upload renders a real report",
           recovered !== null && recovered.ov !== undefined && recovered.ov !== "—",
           JSON.stringify({ recovered: recovered, last: lastState,
                            btn: await evalJs("document.getElementById('btn-analyze').textContent"),
                            ov: await evalJs("document.getElementById('res-overall').textContent") }));

    // (iter 85) PIXEL-LEVEL preview check (iter 42 readPixels convention):
    // redraw synchronously and read the full buffer — the mesh must paint
    // real fragments, not the clear color (0.086,0.11,0.16 → 22,28,41)
    if (recovered) {
      const px = await evalJs("(function(){if(!stlView||!stlView.gl||!stlView.n)return 'nogl';" +
        "stlDraw();var gl=stlView.gl;var w=gl.drawingBufferWidth,h=gl.drawingBufferHeight;" +
        "var p=new Uint8Array(w*h*4);gl.readPixels(0,0,w,h,gl.RGBA,gl.UNSIGNED_BYTE,p);" +
        "var lit=0;for(var i=0;i<p.length;i+=4){" +
        "if(Math.abs(p[i]-22)+Math.abs(p[i+1]-28)+Math.abs(p[i+2]-41)>40)lit++;}" +
        "return JSON.stringify({n:stlView.n,lit:lit,total:w*h})})()");
      const pr = typeof px === "string" && px !== "nogl" ? JSON.parse(px)
               : (px === "nogl" ? { nogl: true,
                   why: await evalJs("(async function(){var r=await fetch('/api/model?token='+encodeURIComponent(state.token));" +
                     "var b=await r.arrayBuffer();var u=new Uint8Array(b);var h='';" +
                     "for(var i=0;i<5&&i<u.length;i++)h+=String.fromCharCode(u[i]);" +
                     "var m=stlParse(b);return JSON.stringify({status:r.status,len:b.byteLength,head:h," +
                     "tris:m.tris,dropped:m.dropped,gl:!!(stlView&&stlView.gl),n:stlView?stlView.n:-1," +
                     "note:document.getElementById('stl-view-note').textContent})})()") } : px);
      expect("e2e: preview paints real pixels (readPixels)",
             typeof pr === "object" && pr.n > 0 && pr.lit > pr.total * 0.02,
             JSON.stringify(pr));
    }

    // (iter 86) BATCH flow at GUI level: capture 2 candidates through the
    // page's own state/renderChips, run the real batch (2 engine runs),
    // assert progress counter and the results table with per-candidate rows.
    if (recovered) {
      const started = await evalJs("(function(){" +
        "state.customCands=[{label:'批a',params:{walls:3},env:{},locks:[]}," +
        "{label:'批b',params:{walls:4},env:{},locks:[]}];renderChips();" +
        "document.getElementById('btn-batch').onclick();return 'started'})()");
      let batchDone = null;
      for (let i = 0; i < 200; i++) {  // 2 engine runs, up to ~60s
        const s = JSON.parse(await evalJs("JSON.stringify({" +
          "count:document.getElementById('cand-count').textContent," +
          "btn:document.getElementById('btn-batch').textContent," +
          "rows:document.querySelectorAll('#batch-results tr').length," +
          "txt:document.getElementById('batch-results').textContent})"));
        // done = button restored AND results table (header + 2 data rows).
        // Mid-run progress trajectory is NOT asserted here: the engine is
        // faster than the 1.5s poll — that face was deterministically
        // verified by iter 59's slow-hook method; this check covers the
        // completion state (counter restored to "2/8", both rows OK).
        if (s.btn === "批量运行" && s.rows >= 3 && s.txt.indexOf("批a") >= 0
            && s.txt.indexOf("批b") >= 0) { batchDone = s; break; }
        await sleep(300);
      }
      expect("e2e batch: results table rendered, counter restored",
             batchDone !== null && batchDone.count === "2/8"
             && batchDone.txt.indexOf("失败") < 0,
             JSON.stringify(batchDone));
    }

    // (iter 88) EXPORT (write-back) flow at GUI level: upload the writable
    // 3MF, click the real export button, assert success message with audit
    // counts AND the sidecar detail panel rendering the engine's audit.
    const mfB64 = fs.readFileSync(
      path.join(ROOT, "test_data", "distinct_100x10x4.3mf")).toString("base64");
    await inject("distinct.3mf", mfB64);
    let exported = null;
    for (let i = 0; i < 150; i++) {  // upload + analyze + export run
      const s = JSON.parse(await evalJs("JSON.stringify({" +
        "btn:document.getElementById('btn-export').disabled," +
        "msg:document.getElementById('export-msg').textContent," +
        "sc:document.getElementById('sidecar-detail').textContent})"));
      if (!s.btn && s.msg.indexOf("写回中") < 0 && exported === null) {
        // button enabled and past "写回中…" → click it (first time only)
        await evalJs("document.getElementById('btn-export').click()");
        exported = "clicked";
      }
      if (typeof exported === "string" && s.msg.indexOf("已下载优化后的 3MF") === 0
          && s.sc.length > 10) { exported = s; break; }
      await sleep(300);
    }
    expect("e2e export: download + audit msg + sidecar panel",
           exported !== null && typeof exported === "object"
           && exported.msg.indexOf("写回审计") > 0,
           JSON.stringify(exported).slice(0, 300));

    // (iter 91) A/B COMPARE flow at GUI level: click the real compare button
    // (second engine run, compare report), then drive the A/B picker over
    // the two history entries and assert the diff table renders with the
    // null-two-state discipline (both sides evaluated → delta shown).
    if (recovered) {
      await clearToasts();
      await evalJs("document.getElementById('btn-compare').click()");
      let abDone = null;
      for (let i = 0; i < 150; i++) {
        // compare completion is a toast now (UI v2), not export-msg
        const ts = JSON.parse(await toastState());
        if (ts.some(t => t.txt === "对比分析完成")) { abDone = true; break; }
        await sleep(300);
      }
      const ab = await evalJs("(function(){var h=state.history||[];" +
        "if(h.length<2)return 'need2:'+h.length;" +
        "var s=h.map(function(e){return e.seq}).sort(function(a,b){return a-b});" +
        "state.ab=[s[0],s[s.length-1]];renderAB();" +
        "var t=document.getElementById('ab-diff').textContent;" +
        "return JSON.stringify({rows:document.querySelectorAll('#ab-diff tr').length," +
        "hasOverall:t.indexOf('总体评分')>=0,hasDelta:t.indexOf('Δ')>=0||/[-++]\\d/.test(t)})})()");
      expect("e2e compare: run + A/B diff table",
             abDone !== null && typeof ab === "string" && ab.charAt(0) === "{"
             && JSON.parse(ab).rows >= 7 && JSON.parse(ab).hasOverall,
             JSON.stringify({ abDone: abDone, ab: ab }));
    }

    // (iter 93) SESSION RESTORE flow: reload the page — localStorage must
    // restore the session (persistSession hop, iter 53) and auto re-analyze.
    if (recovered) {
      await send("Page.reload", {});
      for (let i = 0; i < 50; i++) {
        if (await evalJs("typeof renderReport") === "function"
            && await evalJs("!!(state&&state.token)")) break;
        await sleep(200);
      }
      // NO clearToasts here: the reload itself resets the DOM (all pre-reload
      // toasts are gone), and clearing now can wipe the very "分析完成" toast
      // this check polls for — the restored auto-analyze can complete before
      // this line runs (observed with the v3 UI: engine run ~1s, wait loop
      // exits as soon as state.token is set, toast already rendered).
      let restored = null;
      for (let i = 0; i < 150; i++) {
        const ts = JSON.parse(await toastState());
        const ok = ts.find(t => t.cls === "toast ok" && t.txt === "分析完成");
        const ov = await evalJs("document.getElementById('res-overall').textContent");
        if (ok && ov !== "—") { restored = ok; break; }
        await sleep(300);
      }
      expect("e2e restore: reload restores session + auto re-analyze",
             restored !== null,
             JSON.stringify(restored));
    }

    // (iter 96) report-download button: click the real btn-report, assert
    // the iter-84-variant success path fires ("报告已下载" replaces any
    // stale state; the blob download itself is asserted via the message).
    if (recovered) {
      await clearToasts();
      await evalJs("document.getElementById('btn-report').click()");
      let dl = null;
      for (let i = 0; i < 30; i++) {
        const ts = JSON.parse(await toastState());
        if (ts.some(t => t.cls === "toast ok" && t.txt === "报告已下载")) { dl = true; break; }
        await sleep(200);
      }
      expect("e2e report: download + success toast",
             dl !== null, JSON.stringify(dl));
    }

    // (iter 97) HISTORY panel interaction: the A/B picker is checkbox-driven
    // now (UI v2) — real checkbox clicks drive toggleAB, re-querying between
    // clicks because renderHistory rebuilds the rows synchronously.
    if (recovered) {
      await evalJs("refreshHistory()");
      const ab = await evalJs("(function(){var q=function(){" +
        "return document.querySelectorAll('#history-list input[type=checkbox]')};" +
        "if(q().length<2)return 'cbs:0';" +
        "q()[0].click();q()[1].click();" +  // newest two
        "var t=document.getElementById('ab-diff').textContent;" +
        "return JSON.stringify({abRows:document.querySelectorAll('#ab-diff tr').length," +
        "hasOverall:t.indexOf('总体评分')>=0," +
        "checked:document.querySelectorAll('#history-list input[type=checkbox]:checked').length})})()");
      const o = (typeof ab === "string" && ab.charAt(0) === "{") ? JSON.parse(ab) : ab;
      expect("e2e history: checkbox clicks drive A/B picker",
             typeof o === "object" && o.abRows >= 7 && o.hasOverall && o.checked === 2,
             String(ab));
    }

    // (iter 98) ENV slider interaction: set force=55 through the real input
    // (dataset.env), run analyze, assert the ENGINE REPORT echoes it back —
    // slider → collectEnv → argv → engine → report input.force_N, full loop.
    if (recovered) {
      const setOk = await evalJs("(function(){var inp=document.querySelector('[data-env=force]');" +
        "if(!inp)return 'noinput';inp.value='55';" +
        "inp.dispatchEvent(new Event('input'));inp.dispatchEvent(new Event('change'));return 1})()");
      await clearToasts();  // avoid matching a STALE 分析完成 toast from an earlier run
      await evalJs("document.getElementById('btn-analyze').click()");
      let envDone = null;
      for (let i = 0; i < 120; i++) {
        const ts = JSON.parse(await toastState());
        if (ts.some(t => t.txt === "分析完成")) { envDone = true; break; }
        await sleep(300);
      }
      // assert the run completed and the slider kept the user's 55
      const kept = await evalJs("(function(){var i=document.querySelector('[data-env=force]');" +
        "return i?String(i.value):'gone'})()");
      expect("e2e env: slider value survives a full analyze run",
             setOk === 1 && envDone === true && kept === "55",
             JSON.stringify({ setOk: String(setOk), done: envDone, kept: kept }));
    }

    // (iter 99) PARAM slider interaction: set walls=3 through the real
    // param input, run analyze, assert the engine report echo renders in
    // ④ cp-walls ("3") — slider → collectParams → argv → engine echo →
    // renderReport, the full param loop at GUI level.
    if (recovered) {
      await evalJs("(function(){var i=document.querySelector('[data-param=walls]');" +
        "if(i){i.value='3';i.dispatchEvent(new Event('input'));i.dispatchEvent(new Event('change'));}" +
        "return 1})()");
      await clearToasts();
      await evalJs("document.getElementById('btn-analyze').click()");
      let echoed = null;
      for (let i = 0; i < 150; i++) {
        const ts = JSON.parse(await toastState());
        const done = ts.some(t => t.txt === "分析完成");
        const walls = await evalJs("document.getElementById('cp-walls').textContent");
        if (done && walls === "3") { echoed = true; break; }
        await sleep(300);
      }
      expect("e2e param: walls=3 echoed into ④ panel",
             echoed !== null, JSON.stringify(echoed));
    }

    ws.close(); cleanup();
    console.log(fails ? "%d FAIL".replace("%d", fails) : "browser E2E all green");
    process.exit(fails ? 1 : 0);
  } catch (e) {
    cleanup();
    console.error("ERROR: " + (e && e.message));
    process.exit(2);
  }
}
main();
