// v0.10 productization screenshots — drives the REAL served page over CDP
// (same zero-dep pattern as browser_render_check.js) and captures the
// product-p1/p2/p3 evidence shots into gui-test-screenshots/.
// Usage: node tests/product_shots.js
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

function freePort() { return new Promise(res => { const s = require("net")
  .createServer(); s.listen(0, () => { const p = s.address().port;
    s.close(() => res(p)); }); }); }
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function main() {
  const ROOT = path.join(__dirname, "..");
  const outDir = path.join(ROOT, "gui-test-screenshots");
  fs.mkdirSync(outDir, { recursive: true });
  const port = await freePort();
  const srv = spawn("python", ["server.py"], { cwd: ROOT, detached: false,
    stdio: "ignore",
    env: Object.assign({}, process.env, { STRATUM_UI_PORT: String(port),
                                          STRATUM_UI_NO_BROWSER: "1" }) });
  const cport = await freePort();
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "stratum-ui-shot-"));
  const chrome = spawn(CHROME, ["--headless=new", "--disable-gpu",
    "--window-size=1440,900", "--remote-debugging-port=" + cport,
    "--user-data-dir=" + profile, "--no-first-run", "about:blank"],
    { stdio: "ignore" });
  const cleanup = () => { try { chrome.kill("SIGKILL"); } catch (e) {}
    try { srv.kill(); } catch (e) {} };
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
        throw new Error("page exception: " +
          JSON.stringify(r.result.exceptionDetails).slice(0, 300));
      return r.result ? r.result.result.value : undefined;
    };
    const shot = async name => {
      await sleep(500);  // let the compositor pick up the DOM change
      const r = await send("Page.captureScreenshot", { format: "png" });
      const data = r && r.result && r.result.data;
      if (!data) throw new Error("screenshot failed: " + name +
        " — " + JSON.stringify(r).slice(0, 200));
      fs.writeFileSync(path.join(outDir, name), Buffer.from(data, "base64"));
      console.log("wrote " + name);
    };

    await send("Page.enable");
    await send("Emulation.setDeviceMetricsOverride",
      { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
    await send("Page.navigate", { url: "http://127.0.0.1:" + port + "/" });
    for (let i = 0; i < 50; i++) {
      if (await evalJs("typeof renderReport") === "function") break;
      await sleep(200);
    }
    // hide the session-restore toast noise if any; fresh profile = no session
    await evalJs("document.getElementById('toasts').innerHTML=''");
    await sleep(300);

    // P1 — empty state + first-run guide (default simple mode)
    await shot("product-p1-empty.png");

    // P1 — verdict-first summary cards + warnings badge on the real v2 report
    const report = fs.readFileSync(
      path.join(ROOT, "test_data", "real3mf-results", "report.json"), "utf8");
    await evalJs("window.__r = " + report + "; renderReport(window.__r, '')");
    await shot("product-p1-summary.png");

    // P1 — actionable error card (validation refusal shape)
    await evalJs("renderAnalyzeError({status:'validation_refused'," +
      "error:'输入拓扑校验拒绝（--validate strict）：网格含 41 个几何部件'})");
    await shot("product-p1-error.png");
    await evalJs("renderReport(window.__r, '')");

    // P2 — hero + SF band + candidate bars: advanced mode + v3 report +
    // warnings expanded
    const report3 = fs.readFileSync(
      path.join(ROOT, "test_data", "real3mf-results", "report-v3.json"), "utf8");
    await evalJs("window.__r3 = " + report3 + ";" +
      "applyMode(true);" +
      "var wc=document.getElementById('warnings-card');wc.dataset.open='1';" +
      "renderReport(window.__r3, '')");
    await shot("product-p2-results.png");

    // P2 — loading skeleton + progress bar mid-run state (simulated: the
    // indicator helpers are page functions; no engine run needed)
    await evalJs("startRunIndicator()");
    await sleep(400);
    await shot("product-p2-loading.png");
    await evalJs("stopRunIndicator()");

    // P3 — guide bar + param hints: the guide is already visible on a fresh
    // profile; scroll the walls row into view and outline its hint label
    await evalJs("var i=document.querySelector('[data-param=walls]');" +
      "i.scrollIntoView({block:'center'});" +
      "var l=i.parentNode.querySelector('.lbl');l.style.outline='2px solid var(--accent)'");
    await shot("product-p3-guide.png");
    await evalJs("document.getElementById('first-guide').style.display='none'");

    // P1 — mobile 640px upload card + single-column cards
    await send("Emulation.setDeviceMetricsOverride",
      { width: 640, height: 900, deviceScaleFactor: 1, mobile: true });
    await evalJs("document.getElementById('first-guide').style.display='none'");
    await sleep(300);
    await shot("product-p1-mobile.png");

    ws.close(); cleanup();
    console.log("done");
    process.exit(0);
  } catch (e) {
    cleanup();
    console.error("ERROR: " + (e && e.message));
    process.exit(2);
  }
}
main();
