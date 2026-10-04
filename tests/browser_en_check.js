// EN-mode i18n browser sweep (companion to i18n_coverage_check.js).
// The static checker validates dictionary keys against string literals; this
// one drives the REAL served page in EN mode (headless Chrome over CDP, same
// plumbing as browser_render_check.js), renders the real sample report, and
// sweeps the live DOM: no Chinese may survive outside data-i18n-skip nodes
// (engine-authored output stays Chinese by design — that red line is itself
// asserted as a positive control). Also pins the zh round-trip and the
// document.title path (<head> is outside translateDom's walker).
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

function freePort() { return new Promise(res => { const s = require("net").createServer();
  s.listen(0, () => { const p = s.address().port; s.close(() => res(p)); }); }); }
const sleep = ms => new Promise(r => setTimeout(r, ms));

// Sweep the live DOM for untranslated chrome: text nodes + title/placeholder
// attributes carrying CJK outside data-i18n-skip containers.
const SWEEP = `(function(){
  var bad = [], w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT), n;
  while ((n = w.nextNode())) {
    var tag = n.parentElement && n.parentElement.tagName;
    if (tag === "SCRIPT" || tag === "STYLE") continue;  // source, not UI
    var t = n.textContent;
    if (!/[\\u4e00-\\u9fff]/.test(t)) continue;
    var p = n.parentElement;
    if (p && p.closest && p.closest("[data-i18n-skip]")) continue;
    // the lang-toggle always shows the language it can switch TO ("中" in EN
    // mode) — translating it would defeat it
    if (p && p.closest && p.closest("#lang-toggle")) continue;
    bad.push(t.trim().slice(0, 80));
  }
  var attrs = [];
  Array.prototype.forEach.call(
    document.body.querySelectorAll("[title],[placeholder]"), function (el) {
    if (el.closest && (el.closest("[data-i18n-skip]") ||
                       el.closest("#lang-toggle"))) return;
    var tag = el.tagName;
    if (tag === "SCRIPT" || tag === "STYLE") return;
    ["title", "placeholder"].forEach(function (a) {
      var v = el.getAttribute(a);
      if (v && /[\\u4e00-\\u9fff]/.test(v))
        attrs.push(a + "=" + v.slice(0, 60));
    });
  });
  return { bad: bad.slice(0, 20), badCount: bad.length,
           attrs: attrs.slice(0, 10), attrCount: attrs.length,
           title: document.title };
})()`;

async function main() {
  const ROOT = path.join(__dirname, "..");
  const port = await freePort();
  const srv = spawn("python", ["server.py"], { cwd: ROOT, detached: false,
    stdio: "ignore",
    env: Object.assign({}, process.env, { STRATUM_UI_PORT: String(port),
      STRATUM_UI_NO_BROWSER: "1",
      STRATUM_UI_LOG_DIR: path.join(os.tmpdir(), "stratum-ui-e2e-logs") }) });
  const cport = await freePort();
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "stratum-ui-cdp-"));
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

    await send("Page.enable");
    await send("Network.enable");
    // fresh profile per run, but the SECOND navigation would still hit
    // Chrome's memory cache — bust it so the sweep always runs current JS
    await send("Network.setCacheDisabled", { cacheDisabled: true });
    // boot once to own the origin, persist EN, reload so applyLang("en")
    // runs at script-eval time (the exact path a real EN user takes)
    await send("Page.navigate", { url: "http://127.0.0.1:" + port + "/?encheck=1" });
    for (let i = 0; i < 50; i++) {
      if (await evalJs("document.readyState") === "complete") break;
      await sleep(150);
    }
    await evalJs("try{localStorage.setItem('stratum-ui-lang','en')}catch(e){}; 1");
    await send("Page.navigate", { url: "http://127.0.0.1:" + port + "/?encheck=2" });
    for (let i = 0; i < 50; i++) {
      if (await evalJs("typeof renderReport") === "function") break;
      await sleep(150);
    }
    let fails = 0;
    const expect = (name, cond, detail) => {
      console.log((cond ? "PASS" : "FAIL") + "  " + name + (cond ? "" : "  " + detail));
      if (!cond) fails++;
    };
    expect("boot: EN mode active at load (lang attr + toggle)",
           await evalJs("document.documentElement.getAttribute('lang')==='en' && " +
             "document.getElementById('lang-toggle').textContent==='中'"));

    // render the real sample report (full dynamic surface), let the
    // MutationObserver settle, force one idempotent pass for determinism
    const report = fs.readFileSync(
      path.join(ROOT, "test_data", "real3mf-results", "report.json"), "utf8");
    await evalJs("window.__r = " + report + "; 1");
    const threw = await evalJs(
      "(function(){try{renderReport(window.__r,'');return 'no'}catch(e){return String(e)}})()");
    expect("renderReport did not throw", threw === "no", threw);
    // positive control — the design red line: engine-authored channels stay
    // Chinese. If this ever passes, the skip flags broke (over-translation).
    // Checked on THIS fixture (its warnings list is populated; the v3 one
    // rendered below has an empty engine warning list)
    expect("skip red line intact: engine warning still Chinese",
           await evalJs("/[\\u4e00-\\u9fff]/.test(document.getElementById('warning-list').textContent)"));
    const report3 = fs.readFileSync(
      path.join(ROOT, "test_data", "real3mf-results", "report-v3.json"), "utf8");
    await evalJs("window.__r3 = " + report3 + "; renderReport(window.__r3,''); 1");
    await sleep(300);
    await evalJs("translateDom(); 1");

    const sweep = await evalJs(SWEEP);
    if (sweep.badCount || sweep.attrCount) {
      // one-shot diagnostics: is the page running current JS, and what does
      // the offending node actually contain (byte-level)?
      console.log("DIAG typeof trTextKeepWs=" + await evalJs("typeof trTextKeepWs") +
                  " LANG_EN.size=" + await evalJs("Object.keys(LANG_EN).length") +
                  " state.lang=" + await evalJs("state.lang"));
      console.log("DIAG " + await evalJs(
        "(function(){var out=[];" +
        "var w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT),n;" +
        "while((n=w.nextNode())){if(n.textContent.indexOf('拖放模型')>=0){" +
        "var t=n.textContent;out.push('len='+t.length);" +
        "for(var i=0;i<Math.min(t.length,40);i++)out.push(t.charCodeAt(i).toString(16));" +
        "out.push('keyhit='+Object.prototype.hasOwnProperty.call(LANG_EN,t));" +
        "var k=Object.keys(LANG_EN).find(function(x){return x.indexOf('拖放模型')===0});" +
        "if(k)out.push('keylen='+k.length+' eqlen='+(k.length===t.length));" +
        "break;}}return out.join(' ')})()"));
    }
    expect("document.title translated (head is outside the body walker)",
           !/[\u4e00-\u9fff]/.test(sweep.title), sweep.title);
    expect("EN sweep: no Chinese text nodes outside data-i18n-skip",
           sweep.badCount === 0, JSON.stringify(sweep.bad));
    expect("EN sweep: no Chinese title/placeholder attributes",
           sweep.attrCount === 0, JSON.stringify(sweep.attrs));

    // runtime-composed fragment paths (the exact-key traps this sweep exists
    // for): set them the way the app does — the log tooltip ONCE on a fresh
    // element, before any __zh expando exists (the expando would rightly skip
    // a later overwrite; the app only ever sets that title once at boot)
    await evalJs(
      "document.getElementById('history-cap-note').textContent = '本会话最近 7 次（仅 nominal 值）';" +
      "var lg = document.createElement('span'); lg.title = '打开运行日志目录\\nC:\\\\logs';" +
      "document.body.appendChild(lg); translateDom(); 1");
    expect("composed fragment: history cap note (cap≠10)",
           await evalJs("document.getElementById('history-cap-note').textContent === " +
             "'last 7 runs this session (nominal only)'"),
           await evalJs("document.getElementById('history-cap-note').textContent"));
    expect("composed fragment: log-path tooltip (trailing \\n)",
           await evalJs("lg.title === 'Open the log folder\\nC:\\\\logs'"),
           await evalJs("lg.title"));

    // zh round-trip: restore is lossless (the __zh snapshot), then EN again
    await evalJs("applyLang('zh'); 1");
    expect("zh round-trip: title restored",
           await evalJs("document.title === 'Stratum WebUI · 强度分析工作台'"),
           await evalJs("document.title"));
    expect("zh round-trip: chrome text restored",
           await evalJs("document.querySelector('.panel h2').textContent.trim() === '模型'"));
    await evalJs("applyLang('en'); translateDom(); 1");
    expect("zh round-trip: back to EN cleanly",
           await evalJs("document.querySelector('.panel h2').textContent.trim() === 'Model'"));

    console.log(fails ? ("\nFAIL " + fails) : "\nALL PASS");
    process.exitCode = fails ? 1 : 0;
  } finally {
    cleanup();
  }
}
main().catch(e => { console.error("ERROR:", e.message); process.exit(2); });
