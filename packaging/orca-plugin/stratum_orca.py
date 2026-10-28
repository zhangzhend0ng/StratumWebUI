# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy"]
#
# [tool.orcaslicer.plugin]
# name = "Stratum"
# description = "Stratum 工艺参数调参台 — FDM 可打印性分析引擎的嵌入式 Web UI（插件内起本地服务，停靠面板内嵌 iframe；支持一键选取盘上选中模型送入分析）"
# author = "Stratum-WebUI"
# version = "0.10.0"
# ///
"""Stratum Orca plugin — embeds the Stratum WebUI (server.py + zero-build web
assets, vendored unchanged under app/) into an Orca dock panel.

v0.10.0 (embedded agent, phase 1):
  - the agent tool surface is now a REGISTRY (app/agent_tools.py, single
    source of truth): one declaration generates the FC tools array, the
    frozen codex text-protocol listing, argument validators and the
    dispatch metadata. _dispatch_host_tool's if-elif is gone — a generic
    registry-driven executor with plugin-injected host handlers (sync on
    the UI thread / threaded for run_analysis) took its place.
  - the conversation LOOP moved into the python harness (app/
    agent_harness.py): OpenAI-compatible backends ride NATIVE function
    calling over /api/agent/start + the /api/agent/events channel (SSE,
    poll fallback, one-time tickets + cursor replay); host tool calls
    round-trip harness→event→page bridge→on_message→tool-done→POST
    /api/agent/host-result (spec §3 v2 direction). The codex text track
    and its old endpoints stay FROZEN (page picks the track by backend).
  - new tools: what_if (real engine rerun with param/service overrides,
    never persists over the user's session), get_tier_comparison,
    read_object_config (host-side object-level config read). The page's
    propose_settings anti-dither gate became per_turn_call_cap (enforced
    harness-side).

v0.9.1 (selected-model check fixes):
  - the write paths (写回对象 / AI proposal apply+revert / propose_settings)
    resolve the target by the pick-time ModelObject.id() instead of
    demanding the user's 3D-view selection still be the picked object.
    Identity is the id; attention is the selection — a selection mismatch
    is disclosed in the result note instead of a hard refusal (the old
    guard made any conversation-driven apply fail the moment the user
    clicked another object to look at it). An object no longer on the
    plate is refused honestly（「已不在盘上」）.
  - _select_object validates the selection index on BOTH bounds: a
    negative sentinel (e.g. -1) used to index objects[-1] silently — the
    LAST object got picked with every downstream identity check
    "passing" on the wrong object.
  - the v0.8 3MF export channel is cross-checked: the exported 3MF's
    triangle total must match the picked object (model parts only, or
    parts+modifiers — both host serializations accepted). A mismatch
    falls back to the mesh-only STL pack WITH THE REASON DISCLOSED
    instead of silently analyzing whatever the host exported.
  - server-side assistant step no longer dies on a stale token (server
    restart / eviction): it degrades to the no-facts placeholder and
    flags stale_token so the page drops the dead token (the page
    previously never cleared it — every turn errored until a new pick).
    get_analysis / read_gcode answer a stale token with an actionable
    Chinese message instead of "unknown token (upload expired?)".
  - assistant instructions gain the facts-vs-selection rule: the facts
    block's 模型 is the LAST analyzed object, not necessarily the
    currently selected one; when the user says 「这个/选中的」, the model
    must reconcile with get_print_context first (re-run run_analysis on
    the selection, or declare 「以下基于上次分析的 X」).

v0.9.0 (conversation-first UI):
  - the plugin's face is now ONE conversation (orca-complaint-risk pattern):
    the page opens on a full-height chat; the step cards / verdict / warnings
    / suggestions become a compact report card appended INTO the conversation
    after each analysis, with a "查看完整报告" link into the folded 报告
    view (button paths unchanged there). Talking needs no prior pick — the
    assistant's run_analysis tool picks from the plate itself.
  - server-side assistant upgraded to true conversation mode: full history
    resent (50-turn stdin bound, not a UX cap), follow-up messages merged
    with context ("换个模型再看看"), clarify-when-insufficient (judgement
    first, ≤3 numbered questions), spoken-style replies ≤300 chars, and a
    new 写入全局预设 action chip (panel relay wired) so repair flows can
    be finished from the conversation.

v0.8.0 (rejected-value repair, plugin-side):
  - 写回对象/写入全局预设 now also REPAIR rejected values: the engine's
    iter 883 legality gate discloses illegal 3mf values in warnings[]; keys
    not covered by a suggestion get the factory-default preset's serialized
    value ('Default Setting', read via preset_bundle().prints) written back
    VERBATIM — no parsing, no range table, legality authority stays in
    Orca. Repairs are itemized in the result note (key old→new); keys with
    no default available are disclosed as unrepairable, never guessed.
    Fail-soft: a host without the preset read surface only loses repair.
  - _host_probe gains a permanent preset-default-read step so the repair
    channel's health is visible in python_*.log at every launch.
  - robustness (found by fresh-install redeploy): wheel extraction now
    skips /tests/ members and tolerates per-file audit denies — the host
    sandbox denied numpy/typing/tests/data/mypy.ini outright, which killed
    the server thread on any install without a cached __extracted__.
    _run_server's except now prints the traceback to python_*.log too
    (panel-less failures were previously invisible).
  - global-preset write self-heals schema drift: commit() is retried with
    the host-rejected key dropped and disclosed (the engine can suggest
    filament-scope keys — enable_overhang_bridge_fan — that the process
    preset has no slot for; the whole transaction used to die on them).
  - 从盘选取 (panel button and the AI run_analysis tool) now uploads the
    host's export_object_3mf output instead of a mesh-only STL: the engine
    sees the REAL preset config (current values in suggestions stop being
    a fiction of defaults, and rejected-value repair finally fires on
    live-preset values like the 2003/3001mm/s speed family). Hosts without
    the binding fall back to the STL pack with a disclosure note.

v0.7.4 (engine f3bb89f repack):
  - vendored engine swapped to the 0.27.0 rebuild (hash de744ae8…, version
    string unchanged — md5 is the swap signal): iter 883 advisory legality
    gate — 55 advisory keys now carry per-key ranges/bool/enum/percent checks
    (Snapmaker Orca PrintConfig @bac6fd5c1), illegal values join the
    disclosure channel as "rejected, not applied" warning lines (loader
    reject-forwarding overwrite->append fix included). UI renders warnings[]
    verbatim — zero UI-side changes.

v0.7.3 (dual write-back targets + sandbox-friendly temp):
  - toolbar now has TWO write targets: 写回对象 (per-object process
    overrides, unchanged) and 写入全局预设 (writes the current process
    preset through the host's preset-transaction API — the parameter panel
    refreshes immediately, the preset goes dirty until the user saves it).
  - tempfile.tempdir is pinned to <plugin>/tmp: the host audit sandbox
    prompts per fresh filesystem path, and tempfile.mkdtemp picks a NEW
    random directory under %TEMP% every launch — always outside the allowed
    roots, one permission dialog per launch. Python-level only; the host
    process env is untouched.

v0.7.2 (numpy ships as a bundled wheel, self-extracted):
  - vendor/numpy-2.5.4-cp312-cp312-win_amd64.whl rides in vendor/ (NOT the
    plugin root — discovery rejects a root .whl next to the .py entry as a
    second entry). The server thread extracts it once to
    vendor/__extracted__/ and appends that to sys.path: zero-prerequisite
    install, no uv build, no manual cp312 package dir. _host_probe logs
    numpy's version AND resolved origin so the serving channel is visible
    in python_*.log.

v0.7.1 (engine c65c12c repack):
  - vendored engine swapped to the repacked 0.27.0 dist (hash 0ba69e97…):
    input-shape guardrails (spiral/arachne/support/brim/ironing), layer-time
    cooling floor + chamber ambient override lines, honest emitter froms,
    stale-enable filtering — all ride the existing JSON warnings[] channel.
  - the page's verdict card now shows the FULL warnings list (up to 8 +
    overflow note) instead of top-3: the engine can emit 7 guardrail lines
    at once and a cap would hide exactly the lines it wants surfaced.
  - zero server-side changes (warnings/strings/schema unchanged).

v0.7.0 (AI print assistant, agentic):
  - the 对话 card becomes a page-driven AGENT LOOP (pattern adopted from
    the Snorca ai-print-assistant branch; plugin-only, zero Orca changes):
    /api/assistant/step returns final answers or TOOL_CALLS; the page
    executes host tools through the bridge (UI-thread, deterministic) and
    server tools via /api/assistant/tool, then steps again (≤6 rounds,
    ≤8 calls). Grounding + number audit retained on every final answer.
  - host tool registry: get_print_context (plate objects), run_analysis
    (full pick→upload→analyze with page-card sync), propose_settings —
    READ-ONLY (diffs proposed values against the object's CURRENT config
    via the existing ModelObject.config_keys/config_value bindings; no
    write). The write happens only on the user's「应用到对象」click, which
    stores a checkpoint; 「撤销」restores the old values (keys that merely
    inherited the preset before are disclosed as non-restorable — the
    binding surface has no override-delete).
  - T1 identity guard covers proposals and reverts too.

v0.6.0 (AI-conversational layer):
  - the plugin page gains a 对话 card: grounded Q&A over the current
    report, served by the WebUI server's new /api/chat endpoint. LLM
    backend = local codex CLI (pattern ported from orca-complaint-risk:
    stdin-only payload, read-only sandbox, empty workdir, -o channel,
    --ephemeral, no repo-side secrets; CODEX_BIN / STRATUM_CHAT_MODEL /
    STRATUM_CHAT=0 knobs). Anti-hallucination discipline mirrors engine
    iter 876: replies audited against a facts-spelling whitelist
    (violations stripped + counted), zero tools registered — the model can
    only PROPOSE actions from a fixed enum, rendered as user-clicked chips
    (写回 / 切片评估 / 选取模型). Degrade-never-block: no codex → card
    hidden, workflow unaffected.

v0.5.0 (dedicated plugin UI):
  - the panel iframe now loads /plugin.html — a purpose-built workflow page
    (shipped by make-plugin.sh, served by the vendored server.py via its
    UI_STATIC allowlist) instead of the full standalone WebUI. The plugin
    and the WebUI are now distinct product faces; plugin workflow:
    ① 从盘选取 → ② 参数优化 (preset baseline → engine suggestions → 写回)
    → ③ 切片评估 (real reslice → attach → along-path stress tune)
    → ④ 迭代优化 (round-2 suggestions from real G-code stresses, loop).
  - the top document now also RELAYS page-initiated commands: the plugin
    page posts stratum-orca-pick / stratum-orca-gcode to the parent, which
    forwards them as orca pick/gcode commands (source-checked against the
    iframe). The toolbar buttons stay as a fallback.
  - index.html (standalone WebUI) still ships under app/ for browser-tab
    debugging; its build-time injection is unchanged but no longer the
    plugin's surface.

v0.4.0 (productization):
  - apply identity guard: pick records ModelObject.id() alongside the token;
    写回 refuses when the object currently selected is not the pick source
    (「分析对象与当前选中不一致」) — a re-selection mid-flow can no longer
    send suggestions onto the wrong object.
  - in-iframe apply CTA: make-plugin.sh's injected bridge adds an
    「应用到盘上对象」button under #summary-cards; the click relays
    iframe -> top document -> orca.postMessage({command:'apply'}), reusing
    the toolbar apply flow (kept as fallback) including the identity guard.
  - PEP 723 dependencies=["numpy"] (uv-capable loaders auto-install; the
    manual cp312 package dir keeps working where no uv ships); make-plugin.sh
    now also emits dist/stratum-orca-<version>.zip for distribution.

Architecture (validated by the stratum_embed_spike experiment, see
sandboxes/stratum_embed_spike.py in the Orca worktree and
sandboxes/stratum_spike_evidence_final.jsonl):

  - Orca's embedded CPython runs this entry file. The plugin context the audit
    sandbox tracks is thread_local, so the HTTP server runs inside one
    plugin-spawned thread where audited events are out of plugin scope; the
    only audited steps on the plugin thread are thread starts (Threading
    "thread" sentinel, pre-seeded in .install_state.json).
  - app/server.py is imported INSIDE that thread on purpose: its import-time
    side effects (tempfile.mkdtemp into %TEMP%, log dir setup) must not run
    under the plugin audit context, where they would be denied.
  - The server binds port 0 (kernel-picked): an embedded panel has no
    fixed-port contract, and it never collides with a standalone Stratum
    WebUI on 8765 the user may keep running. The real port is read back from
    the bound socket, baked into the panel's iframe src, and written to
    port.txt for operators.
  - server.py is vendored UNCHANGED: all its path derivations come from
    HERE = dirname(__file__), so index.html / report.js / stl-preview.js /
    sample/ / bin/stratum.exe resolve by placement, no patching. The ONLY
    build-time touch is an additive <script> appended to index.html by
    make-plugin.sh (the orca-session message listener; inert standalone).

Plate pick flow (v0.2, "从盘选取" button in the panel toolbar):

  button --orca.postMessage({command:'pick'})-->  plugin.on_message (UI thread)
  UI thread: selection -> ModelObject -> part volumes' numpy mesh views
             (zero-copy snapshots, safe across threads by binding contract)
  worker thread (fresh, un-audited): transform to world coords via
             instance0.matrix @ volume.matrix, pack binary STL, POST
             /api/upload (X-Stratum-UI: 1), get {token, name, ...}
  plugin --panel.post({command:'pick-done', session})--> top document
  top doc --iframe.contentWindow.postMessage(stratum-orca-session)--> iframe
  injected listener: applySession + analyze (same path as a file upload)

V1 pick semantics (disclosed in the result note): exactly one object; first
instance's placement (analysis is as-laid-on-plate); modifier / negative
volumes ignored (parts analyzed as their union). Requires the fork's
Plater.selected_object_indices() host binding.
"""
import importlib.util
import json
import os
import re
import struct
import sys
import tempfile
import threading
import time
import urllib.request

import orca

_HERE = os.path.dirname(os.path.abspath(__file__))
_APP_DIR = os.path.join(_HERE, "app")
_SERVER_PY = os.path.join(_APP_DIR, "server.py")

# Keep Python's tempfile inside this plugin's own (sandbox-granted) tree.
# The host audit sandbox prompts per fresh filesystem path; tempfile.mkdtemp
# picks a NEW random directory under %TEMP% on every launch, which is always
# outside the allowed roots and would raise a permission dialog per launch
# (and per workdir). Pinning tempfile.tempdir here confines all temp usage
# to <plugin>/tmp — Python-level only, the host process env is untouched.
_TMP_BASE = os.path.join(_HERE, "tmp")
try:
    os.makedirs(_TMP_BASE, exist_ok=True)
    tempfile.tempdir = _TMP_BASE
except OSError:
    pass

_state = {"httpd": None, "port": None, "error": None, "binding": None}
_start_lock = threading.Lock()
_panel = None
_picking = threading.Event()  # set while a pick is in flight (busy guard)
_gcoding = threading.Event()  # set while a gcode attach is in flight
# Last successful plate pick: the apply (写回) flow reads this session's
# report. Set on the UI thread at pick time; token filled in by the upload
# worker on success. object_id is the pick-time ModelObject.id() — apply
# refuses to write onto an object whose id differs (mid-flow re-selection
# guard); it is updated TOGETHER with the token in the worker so a failed
# upload can never pair the old token with a new object id.
_last_pick = {"token": None, "object_idx": None, "object_id": None, "name": None}


def _install_bundled_wheels():
    """Un-audited thread: one-time extraction of bundled dependency wheels
    (vendor/*.whl) onto sys.path. The loader's own .whl-dependency channel
    cannot be used here: plugin discovery treats ANY root .whl next to the
    .py entry as a second entry and rejects the plugin ("contains both .py
    and .whl entry files", PluginFsUtils) — so the wheels ride in vendor/
    (the entry scan only looks at the root), extraction happens in this
    un-audited thread (zip writes under the plugin dir would be audited on
    the plugin thread), and the appended path serves the UI-thread numpy
    import too (interpreter-wide sys.path; the pick flow can only run
    after this server thread is up)."""
    import zipfile

    vendor = os.path.join(_HERE, "vendor")
    if not os.path.isdir(vendor):
        return
    for fname in sorted(os.listdir(vendor)):
        if not fname.lower().endswith(".whl"):
            continue
        dest = os.path.join(vendor, "__extracted__", fname[:-4])
        if not os.path.isdir(dest):
            import shutil
            tmp = dest + ".tmp"
            if os.path.isdir(tmp):  # interrupted extraction
                shutil.rmtree(tmp, ignore_errors=True)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            # v0.8: member-filtered extraction. The host audit sandbox
            # denies some wheel members outright (observed: numpy/typing/
            # tests/data/mypy.ini — an .ini under tests/data; earlier
            # members in the same tree wrote fine, so the deny is
            # file-specific, not plugin-dir-wide). Runtime never imports
            # bundled test data, so /tests/ members are skipped up front
            # and any remaining per-file PermissionError is tolerated
            # (counted + logged) instead of killing the server thread —
            # a fresh install must not depend on audit mood.
            denied = []
            with zipfile.ZipFile(os.path.join(vendor, fname)) as zf:
                for member in zf.namelist():
                    if "/tests/" in member or "/__pycache__/" in member:
                        continue
                    try:
                        zf.extract(member, tmp)
                    except PermissionError:
                        denied.append(member)
            if denied:
                sys.stderr.write(
                    "[stratum] wheel %s: %d member(s) denied by host audit,"
                    " skipped (test/data files, runtime unaffected): %s\n"
                    % (fname, len(denied), ", ".join(denied[:5])))
            os.replace(tmp, dest)
        if dest not in sys.path:
            sys.path.append(dest)


def _run_server():
    """Server thread body: no plugin audit context (thread_local is empty)."""
    try:
        _install_bundled_wheels()
        os.environ["STRATUM_UI_NO_BROWSER"] = "1"
        # Separate rolling logs from any standalone install (%LOCALAPPDATA%\
        # StratumWebUI\logs) so the two never rotate each other's files.
        os.environ.setdefault("STRATUM_UI_LOG_DIR",
                              os.path.join(_HERE, "logs"))
        # agent modules ride next to server.py in app/ (repo root in dev) —
        # server.py's plain `import agent_tools` needs the dir on sys.path
        # (the exec_module loader does not add it).
        if _APP_DIR not in sys.path:
            sys.path.append(_APP_DIR)
        spec = importlib.util.spec_from_file_location("stratum_server", _SERVER_PY)
        module = importlib.util.module_from_spec(spec)
        sys.modules["stratum_server"] = module
        spec.loader.exec_module(module)
        module._setup_file_logging()
        module._sweep_orphan_workdirs()
        # register the HOST tool handlers into the registry (injection — the
        # registry never imports plugin symbols; red line R2)
        _register_host_tools(module)
        # Port 0 = kernel-picked; the actual port is read back below. Not
        # going through module main(): it prints banners, sets a console
        # title and arms a browser timer — all standalone-process concerns.
        httpd = module._ExclusiveServer((module.HOST, 0), module.StratumHandler)
        _state["httpd"] = httpd
        _state["port"] = httpd.server_address[1]
        # Port disclosure for operators (curl probes, opening the UI in a
        # desktop browser tab). Inside data_dir(), an audit-allowed root —
        # and this thread is outside the plugin audit context anyway.
        try:
            with open(os.path.join(_HERE, "port.txt"), "w", encoding="ascii") as fh:
                fh.write("%d\n" % _state["port"])
        except OSError:
            pass
        httpd.serve_forever()
    except Exception as exc:  # noqa: BLE001 - surface anything to the panel
        # v0.8: also print to stderr — python_*.log is the only channel an
        # operator can read when the panel never opens (start() returns a
        # failure result but on_load continues, so nothing else shows it).
        import traceback
        traceback.print_exc()
        _state["error"] = "%s: %s" % (type(exc).__name__, exc)


def _wait_for_port(timeout_s=15.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _state["port"] is not None or _state["error"] is not None:
            break
        time.sleep(0.05)
    return _state["port"]


def _panel_doc(port):
    # {PORT} placeholder + replace, NOT %-formatting: the HTML/CSS/JS payload
    # carries literal '%' (CSS "width: 100%") that a % operator would eat.
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<style>"
        "  body { margin: 0; display: flex; flex-direction: column; height: 100vh; }"
        # v0.9: the bar is HIDDEN — its buttons and status moved into the
        # page (对话 chips + 报告视图 buttons); the element stays because the
        # routing JS still references #pickstat.
        "  #bar { display: none; align-items: center; gap: 8px; padding: 4px 8px;"
        "         border-bottom: 1px solid #d0d0d0; background: #f7f7f7;"
        "         font: 12px/1.4 system-ui, sans-serif; }"
        "  #pick { padding: 2px 10px; font: 12px system-ui, sans-serif; cursor: pointer; }"
        "  #pickstat { color: #555; overflow: hidden; text-overflow: ellipsis;"
        "              white-space: nowrap; }"
        "  iframe { flex: 1; border: 0; width: 100%; }"
        "</style></head><body>"
        "<div id='bar'>"
        "<button id='pick' type='button'>&#8681; 从盘选取</button>"
        "<button id='gcode' type='button'>&#8680; 分析盘上 G-code</button>"
        "<button id='apply' type='button'>&#8691; 写回对象</button>"
        "<button id='applyg' type='button'>&#9851; 写入全局预设</button>"
        "<span id='pickstat'>选中盘上模型后点此送入分析</span>"
        "</div>"
        "<iframe id='sf' src='http://127.0.0.1:{PORT}/plugin.html'></iframe>"
        "<script>"
        "(function () {"
        "  var stat = document.getElementById('pickstat');"
        "  var btn = document.getElementById('pick');"
        "  var app = document.getElementById('apply');"
        "  var agb = document.getElementById('applyg');"
        "  var gcb = document.getElementById('gcode');"
        "  btn.addEventListener('click', function () {"
        "    btn.disabled = true;"
        "    stat.textContent = '正在导出选中模型…';"
        "    try {"
        "      orca.postMessage({ command: 'pick' });"
        "    } catch (e) {"
        "      btn.disabled = false;"
        "      stat.textContent = '\\u2717 桥调用失败: ' + e;"
        "    }"
        "  });"
        "  gcb.addEventListener('click', function () {"
        "    gcb.disabled = true;"
        "    stat.textContent = '正在切片并导出盘上 G-code…（切片进度看主窗口）';"
        "    try {"
        "      orca.postMessage({ command: 'gcode' });"
        "    } catch (e) {"
        "      gcb.disabled = false;"
        "      stat.textContent = '\\u2717 桥调用失败: ' + e;"
        "    }"
        "  });"
        "  function doApply() {"
        # in-flight guard: the iframe CTA and the toolbar button share it
        "    if (app.disabled) return;"
        "    app.disabled = true;"
        "    stat.textContent = '正在写回对象参数…';"
        "    try {"
        "      orca.postMessage({ command: 'apply' });"
        "    } catch (e) {"
        "      app.disabled = false;"
        "      stat.textContent = '\\u2717 桥调用失败: ' + e;"
        "    }"
        "  }"
        "  function doApplyGlobal() {"
        # separate guard: only one preset transaction at a time
        "    if (agb.disabled) return;"
        "    agb.disabled = true;"
        "    stat.textContent = '正在写入全局预设…';"
        "    try {"
        "      orca.postMessage({ command: 'apply-global' });"
        "    } catch (e) {"
        "      agb.disabled = false;"
        "      stat.textContent = '\\u2717 桥调用失败: ' + e;"
        "    }"
        "  }"
        "  app.addEventListener('click', doApply);"
        "  agb.addEventListener('click', doApplyGlobal);"
        # v0.4 relay: commands arriving FROM the plugin page (dedicated UI or
        # the injected bridge): apply (写回), pick (从盘选取), gcode (切片评
        # 估). Source-checked so stray messages from other embedders can't
        # trigger host actions.
        "  window.addEventListener('message', function (ev) {"
        "    var f = document.getElementById('sf');"
        "    if (!ev.data || !f || ev.source !== f.contentWindow) return;"
        "    var t = ev.data.type;"
        "    if (t === 'stratum-orca-apply') doApply();"
        "    else if (t === 'stratum-orca-apply-global')"
        "      orca.postMessage({ command: 'apply-global' });"
        "    else if (t === 'stratum-orca-pick')"
        "      orca.postMessage({ command: 'pick' });"
        "    else if (t === 'stratum-orca-gcode')"
        "      orca.postMessage({ command: 'gcode' });"
        "    else if (t === 'stratum-orca-tool')"
        "      orca.postMessage({ command: 'tool', call: ev.data.call });"
        "    else if (t === 'stratum-orca-apply-proposal')"
        "      orca.postMessage({ command: 'apply-proposal',"
        "        values: ev.data.values, old_values: ev.data.old_values });"
        "    else if (t === 'stratum-orca-apply-global-proposal')"
        "      orca.postMessage({ command: 'apply-global-proposal',"
        "        values: ev.data.values });"
        "    else if (t === 'stratum-orca-revert-proposal')"
        "      orca.postMessage({ command: 'revert-proposal' });"
        "  });"
        "  orca.onMessage(function (msg) {"
        "    if (!msg) return;"
        "    if (msg.command === 'tool-done') {"
        "      var ft = document.getElementById('sf');"
        "      if (ft) ft.contentWindow.postMessage("
        "        { type: 'stratum-orca-tool-result', id: msg.id, ok: msg.ok,"
        "          result: msg.result, error: msg.error },"
        "        'http://127.0.0.1:{PORT}');"
        "      return;"
        "    }"
        "    if (msg.command === 'gcode-progress') {"
        "      stat.textContent = '切片导出中… ' +"
        "        (msg.bytes / 1048576).toFixed(1) + ' MB';"
        "      var fg = document.getElementById('sf');"
        "      if (fg) fg.contentWindow.postMessage("
        "        { type: 'stratum-orca-gcode-progress', bytes: msg.bytes },"
        "        'http://127.0.0.1:{PORT}');"
        "      return;"
        "    }"
        "    if (msg.command === 'apply-done') {"
        "      app.disabled = false;"
        "      agb.disabled = false;"
        "      stat.textContent = (msg.ok ? '\\u2713 ' : '\\u2717 ') +"
        "        (msg.ok ? msg.note : (msg.error || '写回失败'));"
        # echo next to the iframe CTA button (the click point may be
        # scrolled far below this toolbar - feedback must be local too)
        "      var fe = document.getElementById('sf');"
        "      if (fe) fe.contentWindow.postMessage("
        "        { type: 'stratum-orca-apply-done', ok: msg.ok,"
        "          note: msg.note, error: msg.error },"
        "        'http://127.0.0.1:{PORT}');"
        "      return;"
        "    }"
        "    if (msg.command === 'gcode-done') {"
        "      gcb.disabled = false;"
        "      if (msg.ok) {"
        "        stat.textContent = '\\u2713 ' + (msg.note || 'G-code 已挂载');"
        "        var f = document.getElementById('sf');"
        "        f.contentWindow.postMessage("
        "          { type: 'stratum-orca-analyze' },"
        "          'http://127.0.0.1:{PORT}');"
        "      } else {"
        "        stat.textContent = '\\u2717 ' + (msg.error || 'G-code 分析失败');"
        "      }"
        "      return;"
        "    }"
        "    if (msg.command !== 'pick-done') return;"
        "    btn.disabled = false;"
        "    if (msg.ok) {"
        "      stat.textContent = '\\u2713 ' + (msg.note || '已送入分析');"
        "      var f = document.getElementById('sf');"
        "      f.contentWindow.postMessage("
        "        { type: 'stratum-orca-session', session: msg.session, note: msg.note,"
        "          suppress_auto_analyze: msg.suppress_auto_analyze },"
        "        'http://127.0.0.1:{PORT}');"
        "    } else {"
        "      stat.textContent = '\\u2717 ' + (msg.error || '选取失败');"
        "    }"
        "  });"
        "})();"
        "</script></body></html>"
    ).replace("{PORT}", str(port))


# ---- plate pick ----------------------------------------------------------

def _select_object():
    """UI thread: resolve the object to analyze from the 3D-view selection.

    Returns (object_idx, object, note) or raises ValueError with a
    user-facing message.
    """
    plater = orca.host.plater()
    model = plater.model()
    objects = model.objects()
    getter = getattr(plater, "selected_object_indices", None)
    if getter is None:
        raise ValueError("宿主缺少 selected_object_indices 绑定（需含该绑定的 Orca 构建）")
    idxs = list(getter())
    if not idxs:
        # novice fallback: nothing selected and exactly one object on the
        # plate — that one is unambiguously what they mean
        if len(objects) == 1:
            return 0, objects[0], "盘上仅一个对象，未选中也已自动选取"
        raise ValueError("请先在 3D 视图选中一个对象（盘上共 %d 个）" % len(objects))
    if len(idxs) > 1:
        names = ", ".join((objects[i].name or "(未命名)")
                          for i in idxs if isinstance(i, int) and 0 <= i < len(objects))
        raise ValueError("一次只支持一个对象（选中了 %d 个: %s）" % (len(idxs), names))
    i = idxs[0]
    # both bounds: a negative sentinel from the binding (e.g. -1 for
    # "none") used to index objects[-1] silently — the LAST object got
    # picked and every downstream id check then "passed" on it
    if not isinstance(i, int) or not 0 <= i < len(objects):
        raise ValueError("选中的对象索引越界（%r，盘上共 %d 个）" % (i, len(objects)))
    return i, objects[i], None


def _collect_mesh_payload(obj):
    """UI thread: read the object's part meshes as numpy snapshots.

    Per the TriangleMesh binding contract, mesh arrays handed to Python are
    copy-on-write snapshots shared across threads — safe to pack in a worker.
    Returns (payload, note) where payload is a list of
    (vertices Nx3 f32, triangles Mx3 i32, world 4x4 f32) per part volume.
    """
    import numpy as np

    if obj.instance_count() < 1:
        raise ValueError("对象没有实例（未摆放到盘上）")
    world_base = np.asarray(obj.instance(0).matrix(), dtype=np.float64)
    payload = []
    skipped = 0
    for vol in obj.volumes():
        if not vol.is_model_part():
            skipped += 1
            continue
        mesh = vol.mesh()
        if mesh.is_empty() or mesh.triangle_count() == 0:
            continue
        world = world_base @ np.asarray(vol.matrix(), dtype=np.float64)
        payload.append((np.asarray(mesh.vertices()), np.asarray(mesh.triangles()), world))
    if not payload:
        raise ValueError("对象没有可分析的实体网格")
    notes = []
    if skipped:
        notes.append("忽略 %d 个修饰/负体积" % skipped)
    if obj.instance_count() > 1:
        notes.append("取第 1 个摆放（共 %d 实例）" % obj.instance_count())
    return payload, ("；".join(notes) if notes else None)


def _object_triangle_totals(obj):
    """UI thread: (parts, with_modifiers) triangle totals of the object's
    volumes — identity data for the 3MF cross-check below. Hosts serialize
    either every volume or model parts only; both are accepted, so both
    sums are needed."""
    parts = total = 0
    for vol in obj.volumes():
        mesh = vol.mesh()
        if mesh.is_empty() or mesh.triangle_count() == 0:
            continue
        n = mesh.triangle_count()
        total += n
        if vol.is_model_part():
            parts += n
    return parts, total


def _3mf_triangle_count(path):
    """Count <triangle> elements across the 3MF's model entries (stdlib
    only; streaming iterparse keeps large meshes off the heap)."""
    import zipfile
    import xml.etree.ElementTree as ET

    count = 0
    with zipfile.ZipFile(path) as zf:
        for entry in zf.namelist():
            if not entry.lower().endswith(".model"):
                continue
            with zf.open(entry) as fh:
                for _ev, el in ET.iterparse(fh, events=("end",)):
                    if el.tag.rsplit("}", 1)[-1] == "triangle":
                        count += 1
                    el.clear()
    return count


def _collect_upload_payload(obj, object_idx):
    """UI thread: build the analyze upload blob for the picked object.

    v0.8: prefers the host's export_object_3mf — a standalone 3MF carrying
    the CURRENT PRESET CONFIG (illegal values included), so the engine's
    legality gate sees the real config instead of a fiction of defaults,
    and rejected-value repair has something to fire on. Falls back to the
    mesh-only STL pack on hosts without the binding; the note discloses
    the downgrade (engine then analyzes default parameters and can neither
    see nor reject preset values).
    v0.9.1: the export is identity-CHECKED — the binding takes an index we
    derived from model.objects(); if its index space means something else,
    the file silently carries another object. Triangle totals must match
    this object, else export-failure semantics (STL fallback + reason in
    the note), never a silent wrong-object analysis.
    """
    name = (obj.name or "model")
    exporter = getattr(orca.host.plater(), "export_object_3mf", None)
    if exporter is not None:
        path = os.path.join(_TMP_BASE, "pick_%d.3mf" % int(time.time() * 1000))
        down_reason = None
        try:
            exporter(object_idx, path)
            parts, with_mods = _object_triangle_totals(obj)
            got = _3mf_triangle_count(path)
            if got not in (parts, with_mods):
                down_reason = ("内容与对象不符（导出 %d 个三角形，对象为 "
                               "%d/%d），疑非选中对象" % (got, parts, with_mods))
                raise ValueError(down_reason)
            with open(path, "rb") as fh:
                blob = fh.read()
            return blob, ("%s.3mf" % name).strip(), "已携带当前预设配置"
        except Exception:  # noqa: BLE001 - fall back to STL, disclose
            import traceback
            traceback.print_exc()
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        payload, note = _collect_mesh_payload(obj)
        down = ("未携带预设配置（3MF 导出%s，引擎按默认参数分析）"
                % (down_reason or "失败"))
        return (_pack_binary_stl(payload), ("%s.stl" % name).strip(),
                "；".join(x for x in (note, down) if x))
    payload, note = _collect_mesh_payload(obj)
    down = "未携带预设配置（宿主无 3MF 导出绑定，引擎按默认参数分析）"
    return (_pack_binary_stl(payload), ("%s.stl" % name).strip(),
            "；".join(x for x in (note, down) if x))


def _pack_binary_stl(payload):
    """Worker thread: transform to world coords and pack one binary STL."""
    import numpy as np

    chunks = []
    total = 0
    for vertices, triangles, world in payload:
        verts = vertices.astype(np.float64) @ world[:3, :3].T + world[:3, 3]
        tri = verts[triangles.astype(np.int64)]  # (M, 3, 3)
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        lengths = np.linalg.norm(n, axis=1)
        lengths[lengths == 0.0] = 1.0  # degenerate facet: zero normal (engine-side mesh check will flag it)
        n = (n / lengths[:, None]).astype(np.float32)
        rec = np.zeros(tri.shape[0], dtype=np.dtype(
            [("n", "<f4", (3,)), ("v", "<f4", (3, 3)), ("a", "<u2")]))
        rec["n"] = n
        rec["v"] = tri.astype(np.float32)
        chunks.append(rec)
        total += tri.shape[0]
    blob = b"".join(c.tobytes() for c in chunks)
    return b"stratum-orca plate export".ljust(80, b"\0") + struct.pack("<I", total) + blob


def _upload_worker(payload, filename, note, object_idx, object_id):
    """Worker thread (un-audited): pack STL, POST to the plugin's own server,
    relay the result into the panel. Errors land in the toolbar status line.
    """
    def reply(ok, session=None, error=None, extra_note=None):
        try:
            if _panel is not None:
                _panel.post({"command": "pick-done", "ok": ok,
                             "session": session, "error": error,
                             "note": "；".join(x for x in (note, extra_note) if x)})
        finally:
            _picking.clear()

    try:
        blob = payload  # packed on the UI thread (3MF bytes or binary STL)
        port = _state["port"]
        req = urllib.request.Request(
            "http://127.0.0.1:%d/api/upload?name=%s" % (port, urllib.parse.quote(filename)),
            data=blob,
            headers={"X-Stratum-UI": "1", "Content-Type": "application/octet-stream"},
            method="POST")
        with urllib.request.urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        if not result.get("ok"):
            return reply(False, error=result.get("error") or "上传失败")
        _last_pick.update({"token": result["token"], "name": result["name"],
                           "object_idx": object_idx, "object_id": object_id})
        reply(True, session={"token": result["token"], "name": result["name"],
                             "is_3mf": result.get("is_3mf", False),
                             "writable": result.get("writable", False)},
              extra_note="%d KB — 分析后可点「写回 Orca」" % (len(blob) // 1024))
    except Exception as exc:  # noqa: BLE001 - surfaced in the toolbar
        reply(False, error="%s: %s" % (type(exc).__name__, exc))


# ---- plate gcode (分析真实切片 G-code) -----------------------------------

_UPLOAD_LIMIT_BYTES = 64 * 1024 * 1024  # server _read_body cap; disclose, don't surprise


def _gcode_attach_worker(token, gcode_path):
    """Worker thread (un-audited): wait for Orca's export to finish writing the
    scheduled G-code file, then attach it to the pick session via
    POST /api/gcode-attach. Every later analyze of that token rides
    --gcode-in/--gcode-out (stress-sampled, hot-zone flow-tuned G-code + tune
    audit in the results panel)."""

    def reply(ok, note=None, error=None):
        try:
            if _panel is not None:
                _panel.post({"command": "gcode-done", "ok": ok,
                             "note": note, "error": error})
        finally:
            _gcoding.clear()

    try:
        # The binding schedules the export and reslices; the file appears when
        # the background process finalizes it. Poll: exists + size stable.
        deadline = time.monotonic() + 600.0
        stable_since = None
        last_size = -1
        reported = -1
        while time.monotonic() < deadline:
            try:
                size = os.path.getsize(gcode_path)
            except OSError:
                size = -1
            if size > 0:
                if size == last_size:
                    if stable_since is None:
                        stable_since = time.monotonic()
                    elif time.monotonic() - stable_since >= 1.0:
                        break  # present and quiet for 1s — export finished
                else:
                    stable_since = None
                last_size = size
                # relay growing-file progress to the panel (toolbar status +
                # iframe slice-status); no total size exists, bytes ARE the
                # progress. Only post on change to keep the bridge quiet.
                if _panel is not None and size != reported:
                    reported = size
                    _panel.post({"command": "gcode-progress", "bytes": size})
            time.sleep(0.5)
        else:
            return reply(False, error="切片 10 分钟内未产出 G-code 文件（被取消或失败？）")
        if last_size <= 0:
            return reply(False, error="G-code 文件为空（切片失败？）")
        if last_size > _UPLOAD_LIMIT_BYTES:
            return reply(False, error="G-code %d MB 超过服务端 64MB 上限（缩短打印或简化模型后重试）"
                        % (last_size // (1024 * 1024)))
        with open(gcode_path, "rb") as fh:
            blob = fh.read()
        try:
            os.remove(gcode_path)  # best-effort temp cleanup
        except OSError:
            pass
        req = urllib.request.Request(
            "http://127.0.0.1:%d/api/gcode-attach?token=%s&name=%s"
            % (_state["port"], token, urllib.parse.quote("plate-slice.gcode")),
            data=blob,
            headers={"X-Stratum-UI": "1", "Content-Type": "application/octet-stream"},
            method="POST")
        with urllib.request.urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        if not result.get("ok"):
            return reply(False, error=result.get("error") or "挂载失败")
        reply(True, note="真实切片 G-code 已挂载（%d KB），重新分析中…" % (last_size // 1024))
    except Exception as exc:  # noqa: BLE001 - surfaced in the toolbar
        reply(False, error="%s: %s" % (type(exc).__name__, exc))


def _start_gcode_flow():
    """UI thread: schedule a real slice of the current plate with its G-code
    exported to a temp path, then hand off to the attach worker."""
    import tempfile

    if not _last_pick.get("token"):
        raise ValueError("先点「从盘选取」并分析模型，再挂载它的切片 G-code")
    plater = orca.host.plater()
    exporter = getattr(plater, "schedule_plate_gcode_export", None)
    if exporter is None:
        raise ValueError("宿主缺少 schedule_plate_gcode_export 绑定（需含该绑定的 Orca 构建）")
    if not plater.model().objects():
        raise ValueError("盘是空的——没有可切片的模型")
    # path only (no file yet — the Orca background process writes it)
    gcode_path = os.path.join(
        tempfile.gettempdir(), "orca_stratum_plate_%d.gcode" % int(time.time() * 1000))
    exporter(gcode_path)
    threading.Thread(target=_gcode_attach_worker, daemon=True,
                     name="stratum-orca-gcode",
                     args=(_last_pick["token"], gcode_path)).start()


# ---- v0.8 rejected-value repair (engine iter 883 consumption) -----------
#
# The engine's legality gate rejects illegal values at 3MF load. Since
# engine iter 886 (ER-1) the rejects are disclosed STRUCTURED in the
# report's top-level rejected_values field ({key, value, reason, source});
# before that they were only parseable from warnings[] prose (one wording
# for physical and advisory keys alike, uncapped). _parse_rejected_keys
# reads the field first and keeps the prose regex only as the pre-iter-886
# fallback. Suggestions
# already carry legal values for the keys they touch; the repair closes
# the remaining gap: a rejected key WITHOUT a suggestion gets the
# factory-default preset's serialized value written back VERBATIM. No
# parsing, no range table, no defaults hardcoded here — the legality
# authority stays inside Orca itself ('Default Setting', is_default).

# Engine iter 886 (ER-1): rejected values are disclosed STRUCTURED at the
# report top level — rejected_values: [{key, value, reason, source}] — and
# warnings[] keeps a human-worded line whose wording is free to change. The
# regex below parses that wording and is ONLY the fallback for engines
# built before iter 886 (old-engine coexistence).
_RE_REJECT_LEGACY = re.compile(r"key '([^']+)' value '([^']+)' rejected")


def _parse_rejected_keys(report):
    """Report -> {key: raw illegal value}.

    Primary source (ER-1): the structured report field `rejected_values`
    ([{key, value, reason, source}]). ALL sources are forwarded —
    project_settings / base-profile / parse / advisory / legality — the
    repair fixes the KEY and the source is disclosure only, never a filter.
    The field is authoritative whenever present (empty list = no rejects);
    when absent (engine < iter 886) we fall back to the legacy warnings-text
    regex. Fail-soft: any shape; no match -> {}."""
    report = report or {}
    if "rejected_values" in report:
        out = {}
        for e in (report.get("rejected_values") or []):
            if not isinstance(e, dict):
                continue
            key = e.get("key")
            if not isinstance(key, str) or not key:
                continue
            raw = e.get("value")
            out[key] = raw if isinstance(raw, str) else str(raw)
        return out
    out = {}
    for w in (report.get("warnings") or []):
        text = w if isinstance(w, str) else str(
            (w.get("message") if isinstance(w, dict) else w) or "")
        for key, raw in _RE_REJECT_LEGACY.findall(text):
            out[key] = raw
    return out


def _serialize_orca_value(v):
    """Preset config_value() return -> Orca config serialization string.
    Strings (the normal case, incl. multi-extruder '150,150') pass through
    untouched; bools/numbers/lists fall back to Orca's serialization."""
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    if isinstance(v, (list, tuple)):
        return ",".join(_serialize_orca_value(x) for x in v)
    return str(v)


def _factory_default_repairs(rejected, suggestion_values):
    """UI thread: rejected keys not covered by a suggestion get the
    factory-default preset's value. Returns (repairs, unrepairable):
    repairs = [(key, raw_illegal, serialized_default)], unrepairable =
    keys we could not source a default for (host surface missing, no
    is_default preset, or key absent from its config) — disclosed, never
    guessed."""
    todo = [k for k in rejected if k not in suggestion_values]
    if not todo:
        return [], []
    try:
        coll = orca.host.preset_bundle().prints
        default = None
        for i in range(coll.size()):
            p = coll.preset(i)
            isdef = p.is_default
            if callable(isdef):
                isdef = isdef()
            if isdef:
                default = p
                break
        if default is None:
            return [], todo
        keys = default.config_keys
        if callable(keys):
            keys = keys()
        repairs, unrepairable = [], []
        for k in todo:
            if k not in keys:
                unrepairable.append(k)
                continue
            repairs.append(
                (k, rejected[k], _serialize_orca_value(default.config_value(k))))
        return repairs, unrepairable
    except Exception:  # noqa: BLE001 - repair degrades, never blocks apply
        import traceback
        traceback.print_exc()
        return [], todo


def _repair_note(repairs, unrepairable):
    """Disclosure suffix for the apply note — repairs are itemized with
    old→new so nothing is written silently."""
    if not repairs and not unrepairable:
        return ""
    parts = []
    if repairs:
        parts.append("顺带修复非法值 %d 项（%s，取出厂默认）" % (
            len(repairs),
            "; ".join("%s %s→%s" % (k, old, new)
                      for k, old, new in repairs)))
    if unrepairable:
        parts.append("未能修复 %d 项（无出厂默认可取：%s）" % (
            len(unrepairable), ", ".join(unrepairable)))
    return "；" + "；".join(parts)


# ---- apply (写回 Orca) ---------------------------------------------------

def _orca_serialize(value):
    """JSON value -> Orca config serialization string."""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(value)


def _collect_suggestion_values():
    """UI thread: the pick session's engine suggestions as an Orca
    {key: serialized value} dict, plus the keys skipped for having no
    recommended value and the repair disclosure suffix. Shared by 写回对象
    and 写入全局预设. v0.8: values also carries factory-default repairs
    for rejected keys without a suggestion (merged; the suffix itemizes
    them — nothing repairs silently)."""
    if not _last_pick.get("token"):
        raise ValueError("先点「从盘选取」并完成一次分析，再写回")
    module = sys.modules.get("stratum_server")
    if module is None:
        raise RuntimeError("server module not loaded")
    with module._session_lock:
        sess = module._sessions.get(_last_pick["token"]) or {}
        report = sess.get("last_report")
    if not report:
        raise ValueError("该会话还没有分析报告——先在面板里跑一次分析")

    items = ((report.get("orca_suggestions") or {}).get("items")) or []
    values, skipped = {}, []
    for item in items:
        key = item.get("parameter")
        if not key:
            continue
        if item.get("recommended_value") is not None:
            values[key] = _orca_serialize(item["recommended_value"])
        elif item.get("recommended_text"):
            # ER-4 (engine iter 886): machine-usable value token for set
            # items whose recommended_value is null (e.g. brim_type ->
            # "auto_brim") — written back verbatim, never skipped.
            values[key] = str(item["recommended_text"])
        else:
            skipped.append(key)
            continue
    rejected = _parse_rejected_keys(report)
    repairs, unrepairable = _factory_default_repairs(rejected, values)
    for key, _raw, val in repairs:
        values[key] = val
    note_suffix = _repair_note(repairs, unrepairable)
    if not values:
        raise ValueError("报告里没有可写回的建议（%d 项无推荐值）" % len(skipped))
    return values, skipped, note_suffix


def _apply_suggestions():
    """UI thread: write the pick session's engine suggestions (Orca keys,
    report orca_suggestions channel) back as per-object process overrides.

    All host work stays on the UI thread (ModelConfig::touch is main-thread
    only); the report is read from the in-process server module under its
    session lock — no HTTP, no audit surface.
    """
    values, skipped, repair_suffix = _collect_suggestion_values()
    note = _write_pick_object_overrides(values)
    if skipped:
        note += "；跳过 %d 项无推荐值（%s）" % (len(skipped), ", ".join(skipped))
    note += repair_suffix
    return note


_RE_UNKNOWN_SETTING = re.compile(r'Unknown \w+ preset setting "([^"]+)"')


def _commit_global_preset(editor, values):
    """Background thread: run the preset transaction, self-healing against
    schema drift. commit() is all-or-nothing per transaction and the host
    throws ValueError naming the first key its process tab doesn't know
    (observed: the engine suggests filament-scope keys — e.g.
    enable_overhang_bridge_fan — that have no slot in the process preset).
    On such an error the named key is dropped, disclosed, and a FRESH
    transaction re-commits the rest; keys set before the throw are re-set
    idempotently. Returns (applied_values, dropped_keys)."""
    dropped = []
    while values:
        txn = editor.begin_update()
        for k, v in values.items():
            txn.set(k, v)
        try:
            txn.commit()
            return values, dropped
        except ValueError as exc:
            m = _RE_UNKNOWN_SETTING.search(str(exc))
            if not m or m.group(1) not in values:
                raise  # not a schema-drift reject — surface it
            dropped.append(m.group(1))
            values.pop(m.group(1))
    return values, dropped


def _apply_global_worker(values, skipped, repair_suffix=""):
    """Background thread: write the suggestions into the CURRENT process
    preset through the host's preset-transaction API
    (orca.host.preset.process begin_update/set/commit). The transaction API
    must run off the UI thread by contract — it can block on preset-selection
    dialogs. commit() applies through the GUI's own change path: the
    parameter panel refreshes immediately and the preset goes dirty (saved
    only when the user saves it)."""

    def reply(ok, note=None, error=None):
        if _panel is not None:
            _panel.post({"command": "apply-done", "ok": ok, "note": note,
                         "error": error})

    try:
        editor = getattr(getattr(orca.host, "preset", None), "process", None)
        if editor is None or not hasattr(editor, "begin_update"):
            raise ValueError("宿主缺少 preset.process 事务接口（需含该接口的构建）")
        applied_values, dropped = _commit_global_preset(editor, values)
        applied = ["%s=%s" % (k, applied_values[k]) for k in applied_values]
        note = ("全局预设已更新 %d 项（%s）——参数面板即刻生效，预设已标记为已修改，"
                "可在参数面板保存" % (len(applied), ", ".join(applied)))
        if dropped:
            note += ("；跳过 %d 项宿主工艺预设不支持的键（%s，非本机作用域/版本差异）"
                     % (len(dropped), ", ".join(dropped)))
        if skipped:
            note += "；跳过 %d 项无推荐值（%s）" % (len(skipped), ", ".join(skipped))
        note += repair_suffix
        reply(True, note=note)
    except Exception as exc:  # noqa: BLE001 - toolbar line
        import traceback
        traceback.print_exc()
        reply(False, error="%s: %s" % (type(exc).__name__, exc))


def _picked_object_index():
    """UI thread: resolve the write target by the pick-time ModelObject.id()
    — ids stay with the object while indices shift on add/remove and the
    3D-view selection drifts with user attention. Returns
    (object_idx, obj, objects) or raises a user-facing ValueError."""
    picked_id = _last_pick.get("object_id")
    if picked_id is None:
        raise ValueError("选取会话缺少对象 id（插件重启过？请重新「从盘选取」）")
    objects = orca.host.plater().model().objects()
    for i, obj in enumerate(objects):
        if obj.id() == picked_id:
            return i, obj, objects
    raise ValueError("分析对象已不在盘上（被删除或撤销？）——请对新对象重新「从盘选取」")


def _write_pick_object_overrides(values):
    """UI thread: resolve the write target by pick-time id + apply_object_
    config + result note. Shared by 写回（report suggestions）, the AI
    proposal Apply, and its Revert — one resolver, one writer, no drift
    between entry points.

    v0.9.1: the target is the object whose id was recorded at pick time —
    the write can never be redirected by a selection change. The user's
    current selection is ATTENTION, not addressing: a mismatch is
    disclosed in the note (so nothing writes silently) instead of the old
    hard refusal, which made every conversation-driven apply fail the
    moment the user clicked another object to look at it."""
    plater = orca.host.plater()
    applier = getattr(plater, "apply_object_config", None)
    if applier is None:
        raise ValueError("宿主缺少 apply_object_config 绑定（需含该绑定的构建）")
    object_idx, obj, objects = _picked_object_index()
    results = list(applier(object_idx, values))
    applied = ["%s=%s" % (k, values[k]) for k, ok, _err in results if ok]
    failed = ["%s: %s" % (k, err) for k, ok, err in results if not ok]
    parts = ["写回 %d 项（%s）" % (len(applied), ", ".join(applied))]
    if failed:
        parts.append("失败 %d 项（%s）" % (len(failed), "; ".join(failed)))
    getter = getattr(plater, "selected_object_indices", None)
    if getter is not None:
        sel = [i for i in list(getter())
               if isinstance(i, int) and 0 <= i < len(objects)]
        if len(sel) == 1 and sel[0] != object_idx:
            parts.append("注意：写入对象是「%s」，当前选中的是「%s」"
                         % (obj.name or "(未命名)",
                            objects[sel[0]].name or "(未命名)"))
    return "；".join(parts)


# ---- v0.7 host tool registry (AI assistant) --------------------------------
# Deterministic UI-thread dispatch — the same surface pick/apply use. The
# AI path NEVER writes directly: propose_settings only reads current values
# for a diff; writes happen on the user's Apply click with a checkpoint
# kept for partial revert (T1 guard on every write path).

_proposal_checkpoint = {"old_values": None}


def _tool_reply(call_id, ok, result=None, error=None):
    if _panel is not None:
        _panel.post({"command": "tool-done", "id": call_id, "ok": ok,
                     "result": result, "error": error})


def _print_context():
    plater = orca.host.plater()
    model = plater.model()
    objects = model.objects()
    getter = getattr(plater, "selected_object_indices", None)
    idxs = set(list(getter())) if getter is not None else set()
    return {"objects": [
        {"idx": i, "name": obj.name or "(未命名)",
         "instances": obj.instance_count(),
         "volumes": obj.volume_count(),
         "facets": obj.facets_count(),
         "selected": i in idxs}
        for i, obj in enumerate(objects)],
        "selected_count": len(idxs)}


def _analysis_tool_worker(call_id, payload, filename, object_idx, picked_id,
                          note):
    """Worker thread (un-audited): run_analysis tool body — pick upload +
    engine analyze, then a compact summary for the model. The session
    adoption relay carries suppress_auto_analyze so the page does not
    double-run the analysis the tool just performed."""

    def reply(ok, result=None, error=None):
        try:
            _tool_reply(call_id, ok, result=result, error=error)
        finally:
            _picking.clear()

    try:
        blob = payload  # packed on the UI thread (3MF bytes or binary STL)
        port = _state["port"]
        req = urllib.request.Request(
            "http://127.0.0.1:%d/api/upload?name=%s"
            % (port, urllib.parse.quote(filename)),
            data=blob, headers={"X-Stratum-UI": "1",
                                "Content-Type": "application/octet-stream"},
            method="POST")
        with urllib.request.urlopen(req, timeout=300) as resp:
            up = json.loads(resp.read().decode("utf-8"))
        if not up.get("ok"):
            return reply(False, error=up.get("error") or "上传失败")
        token = up["token"]
        _last_pick.update({"token": token, "name": up["name"],
                           "object_idx": object_idx, "object_id": picked_id})
        if _panel is not None:
            _panel.post({"command": "pick-done", "ok": True,
                         "session": {"token": token, "name": up["name"],
                                     "is_3mf": up.get("is_3mf", False),
                                     "writable": up.get("writable", False)},
                         "note": "；".join(x for x in (note, "AI 分析中") if x),
                         "suppress_auto_analyze": True})
        req2 = urllib.request.Request(
            "http://127.0.0.1:%d/api/analyze" % port,
            data=json.dumps({"token": token, "params": {}}).encode("utf-8"),
            headers={"X-Stratum-UI": "1",
                     "Content-Type": "application/json"},
            method="POST")
        with urllib.request.urlopen(req2, timeout=300) as resp:
            an = json.loads(resp.read().decode("utf-8"))
        if not an.get("ok"):
            return reply(False, error=an.get("error") or "分析失败")
        rep = an.get("report") or {}
        pb = rep.get("phase_b") or {}
        items = ((rep.get("orca_suggestions") or {}).get("items")) or []
        reply(True, result={
            "sf": pb.get("safety_factor"),
            "verdict": pb.get("assessment"),
            "warnings": (rep.get("warnings") or [])[:5],
            "suggestions": [{"parameter": s.get("parameter"),
                             "recommended": s.get("recommended_value"),
                             "reason": (s.get("reason") or "")[:80]}
                            for s in items[:10]],
            "gcode_attached": bool(an.get("gcode_attached"))})
    except Exception as exc:  # noqa: BLE001 - tool result line
        reply(False, error="%s: %s" % (type(exc).__name__, exc))


def _register_host_tools(srv_module):
    """Plug the plugin's host handlers into the registry (spec §4.5): the
    if-elif dispatch is gone — _dispatch_host_tool below is a generic,
    registry-driven executor. Handlers:
      sync(args) -> result            (UI-thread read, dispatcher replies)
      threaded(tid, args, reply)      (UI thread collects, owns async reply)
    """
    reg = getattr(srv_module, "agent_tools", None)
    if reg is None:
        return
    reg.register_host_handler("get_print_context", "sync",
                              lambda args: _print_context())
    reg.register_host_handler("run_analysis", "threaded", _host_run_analysis)
    reg.register_host_handler("propose_settings", "sync",
                              _host_propose_settings)
    reg.register_host_handler("read_object_config", "sync",
                              _host_read_object_config)


def _agent_registry():
    srv = sys.modules.get("stratum_server")
    return getattr(srv, "agent_tools", None) if srv is not None else None


def _dispatch_host_tool(call):
    """UI thread entry for the AI assistant's host tools — generic executor,
    registry-driven since v0.10 (no per-tool branches here)."""
    reg = _agent_registry()
    if reg is None:
        _tool_reply(str((call or {}).get("id") or "?"), False,
                    error="server module not loaded — host tools unavailable")
        return
    reg.dispatch_host(call, _tool_reply)


def _host_propose_settings(args):
    """sync host handler (old elif body, unchanged semantics)."""
    values = args.get("values")
    if not isinstance(values, dict) or not values:
        raise ValueError("propose_settings 需要 args.values 参数字典")
    if not _last_pick.get("token"):
        raise ValueError("还没有选取/分析会话——先 run_analysis")
    # v0.9.1: read current values from the PICKED object (by id), not from
    # whatever is currently selected — the diff must describe the object the
    # proposal will be applied to.
    _idx, obj, _objs = _picked_object_index()
    keys = list(obj.config_keys())
    old = {k: (obj.config_value(k) if k in keys else None) for k in values}
    return {
        "old_values": old,
        "note": "提案已生成（只读比对，未写入）；用户在面板确认后才应用"}


def _host_run_analysis(tid, args, reply):
    """threaded host handler (old elif body, unchanged semantics): UI thread
    collects the payload, the worker uploads + analyzes and replies."""
    if _picking.is_set():
        raise ValueError("一项选取/分析已在进行中——稍候再试")
    _picking.set()
    try:
        object_idx, obj, note0 = _select_object()
        picked_id = obj.id()
        payload, filename, note1 = _collect_upload_payload(obj, object_idx)
    except Exception:
        _picking.clear()
        raise
    threading.Thread(
        target=_analysis_tool_worker, daemon=True,
        name="stratum-orca-ai-run",
        args=(tid, payload, filename, object_idx, picked_id,
              "；".join(x for x in (note0, note1) if x))).start()


def _default_config_keys():
    """Conversation-relevant default keys for read_object_config: the last
    report's suggestion parameters + engine-rejected keys (capped at 24 —
    a full object config is hundreds of keys, noise for the model)."""
    keys = []
    module = sys.modules.get("stratum_server")
    report = None
    if module is not None and _last_pick.get("token"):
        try:
            with module._session_lock:
                sess = module._sessions.get(_last_pick["token"]) or {}
                report = sess.get("last_report")
        except AttributeError:
            report = None
    if report:
        for it in (((report.get("orca_suggestions") or {}).get("items"))
                   or []):
            k = it.get("parameter")
            if k and k not in keys:
                keys.append(k)
        keys += [k for k in _parse_rejected_keys(report) if k not in keys]
    return keys[:24]


def _host_read_object_config(args):
    """sync host handler (v0.10): current OBJECT-LEVEL config values of the
    pick-time object (by id). Keys default to the report-relevant slice;
    null = no object override (inherits the preset) — the same semantics
    propose_settings' diff uses."""
    if not _last_pick.get("token"):
        raise ValueError("还没有选取/分析会话——先 run_analysis")
    keys = args.get("keys")
    if not isinstance(keys, list) or not keys \
            or not all(isinstance(k, str) for k in keys):
        keys = _default_config_keys()
        if not keys:
            raise ValueError("没有默认可读的键（还没有分析报告）——显式传 keys")
    _idx, obj, _objs = _picked_object_index()
    have = set(obj.config_keys())
    return {"values": {k: (obj.config_value(k) if k in have else None)
                       for k in keys},
            "note": "null=该键无对象级覆盖（继承预设）；值来自宿主当前状态"}


class StratumPanel(orca.script.ScriptPluginCapabilityBase):
    def get_name(self):
        return "Stratum"

    def on_load(self):
        self.start()
        # Probe from a timer thread that waits for the plater (on_load runs
        # before the main window exists — same reason create_dock_panel
        # defers). Off-UI-thread reads are racy in general, but this probe
        # only needs to reproduce a cast/conversion failure, not race-free
        # state. Runs in an un-audited thread (spawned thread, empty
        # thread_local audit context).
        def _probe_when_ready(attempt):
            try:
                orca.host.plater()
            except Exception as exc:  # noqa: BLE001 - retry until plater up
                sys.stderr.write("[stratum-probe] plater not ready (attempt %d): %s: %s\n"
                                 % (attempt, type(exc).__name__, exc))
                if attempt < 30:
                    threading.Timer(2.0, lambda: _probe_when_ready(attempt + 1)).start()
                return
            self._host_probe()

        threading.Timer(3.0, lambda: _probe_when_ready(0)).start()

    def _host_probe(self):
        """Self-check of every host call the pick path depends on.

        Stepwise so the FIRST failure is isolated; full tracebacks go to
        stderr, which the app persists to its python_*.log. Remove once the
        pick path is proven.
        """
        import traceback

        def step(name, fn):
            try:
                value = fn()
                sys.stderr.write("[stratum-probe] %s OK -> %s\n" % (name, type(value).__name__))
                return value
            except Exception:  # noqa: BLE001 - probe reports, never raises
                sys.stderr.write("[stratum-probe] %s FAILED:\n" % name)
                traceback.print_exc()
                return None

        # v0.7.2: which channel is serving numpy — the plugin's bundled
        # wheel (vendor/__extracted__) or a manual/uv install dir? Runs
        # FIRST: unlike the host steps below it needs no plater and no
        # objects on the plate.
        def _numpy_origin():
            import numpy
            # step() only prints the value's type — write the origin line
            # ourselves (version + resolved parent dir) so python_*.log
            # shows WHICH channel is serving numpy.
            sys.stderr.write("[stratum-probe] numpy %s @ %s\n" % (
                numpy.__version__,
                os.path.dirname(os.path.dirname(numpy.__file__))))
            return True
        step("numpy", _numpy_origin)

        # v0.8: factory-default read — the repair flow's legal-value source
        # (rejected keys without a suggestion get 'Default Setting' values).
        # Fail-soft by design: a build without the read surface only loses
        # repair (apply still works, rejects stay disclosed).
        def _preset_default_read():
            coll = orca.host.preset_bundle().prints
            for i in range(coll.size()):
                p = coll.preset(i)
                isdef = p.is_default
                if callable(isdef):
                    isdef = isdef()
                if not isdef:
                    continue
                name = p.name
                name = name() if callable(name) else name
                keys = p.config_keys
                if callable(keys):
                    keys = keys()
                if "gap_infill_speed" in keys:
                    sys.stderr.write(
                        "[stratum-probe] preset default %r: gap_infill_speed=%r\n"
                        % (name, p.config_value("gap_infill_speed")))
                else:
                    sys.stderr.write(
                        "[stratum-probe] preset default %r: gap_infill_speed absent\n"
                        % (name,))
                return True
            sys.stderr.write("[stratum-probe] preset default: none found\n")
            return True
        step("preset-default-read", _preset_default_read)

        plater = step("plater()", lambda: orca.host.plater())
        if plater is None:
            return
        step("selected_object_indices()", lambda: plater.selected_object_indices())
        model = step("plater.model()", lambda: plater.model())
        if model is None:
            return
        objects = step("model.objects()", lambda: model.objects())
        if not objects:
            sys.stderr.write("[stratum-probe] plate empty — model-object steps skipped\n")
            return
        step("objects[0].name", lambda: objects[0].name)
        step("objects[0].instance(0).matrix()", lambda: objects[0].instance(0).matrix())
        volumes = step("objects[0].volumes()", lambda: objects[0].volumes())
        if volumes:
            step("volumes[0].mesh().vertices()", lambda: volumes[0].mesh().vertices())
            step("volumes[0].mesh().triangles()", lambda: volumes[0].mesh().triangles())

    def execute(self):
        return self.start()

    def start(self):
        global _panel
        with _start_lock:
            if _state["error"] and _state["port"] is None:
                return orca.ExecutionResult.failure(
                    orca.PluginResult.FatalError,
                    "Stratum server failed: %s" % _state["error"])
            if _state["port"] is None:
                threading.Thread(target=_run_server, daemon=True,
                                 name="stratum-orca-server").start()
        port = _wait_for_port()
        if port is None:
            detail = _state["error"] or "server did not bind within 15s"
            return orca.ExecutionResult.failure(
                orca.PluginResult.FatalError, "Stratum server: %s" % detail)
        try:
            if _panel is not None and _panel.is_open():
                _panel.show()
            else:
                _panel = orca.host.ui.create_dock_panel(
                    html=_panel_doc(port),
                    title="Stratum",
                    width=560,
                    height=900,
                    on_message=self.on_message,
                    on_close=self.on_close,
                    dock="right",
                )
            return orca.ExecutionResult.success(
                "Stratum 调参台已打开 (http://127.0.0.1:%d)" % port)
        except Exception as exc:  # noqa: BLE001
            return orca.ExecutionResult.failure(
                orca.PluginResult.RecoverableError, "panel failed: %s" % exc)

    def on_message(self, message):
        command = (message or {}).get("command")
        if command == "apply":
            try:
                note = _apply_suggestions()
                if _panel is not None:
                    _panel.post({"command": "apply-done", "ok": True, "note": note})
            except Exception as exc:  # noqa: BLE001 - toolbar line
                import traceback
                traceback.print_exc()
                if _panel is not None:
                    _panel.post({"command": "apply-done", "ok": False,
                                 "error": "%s: %s" % (type(exc).__name__, exc)})
            return
        if command == "apply-global":
            try:
                values, skipped, repair_suffix = _collect_suggestion_values()
            except Exception as exc:  # noqa: BLE001 - toolbar line
                if _panel is not None:
                    _panel.post({"command": "apply-done", "ok": False,
                                 "error": "%s: %s" % (type(exc).__name__, exc)})
                return
            threading.Thread(target=_apply_global_worker, daemon=True,
                             name="stratum-orca-apply-global",
                             args=(values, skipped, repair_suffix)).start()
            return
        if command == "gcode":
            if _gcoding.is_set():
                return  # busy: a gcode attach is already in flight
            _gcoding.set()
            try:
                _start_gcode_flow()
            except Exception as exc:  # noqa: BLE001 - toolbar line
                _gcoding.clear()
                import traceback
                traceback.print_exc()
                if _panel is not None:
                    _panel.post({"command": "gcode-done", "ok": False,
                                 "error": "%s: %s" % (type(exc).__name__, exc)})
            return
        if command == "tool":
            # AI assistant host tool (v0.7): deterministic UI-thread dispatch
            _dispatch_host_tool((message or {}).get("call"))
            return
        if command == "apply-proposal":
            # v0.7: the ONLY write path for AI proposals — user-clicked,
            # checkpointed (see revert-proposal)
            try:
                msg = message or {}
                raw = msg.get("values")
                if not isinstance(raw, dict) or not raw:
                    raise ValueError("提案缺少 values")
                values = {str(k): _orca_serialize(v) for k, v in raw.items()}
                old = msg.get("old_values")
                old = old if isinstance(old, dict) else {}
                note = _write_pick_object_overrides(values)
                _proposal_checkpoint["old_values"] = old
                if _panel is not None:
                    _panel.post({"command": "apply-done", "ok": True,
                                 "note": note + "；已存回滚点，可「撤销」"})
            except Exception as exc:  # noqa: BLE001 - surfaced in the panel
                import traceback
                traceback.print_exc()
                if _panel is not None:
                    _panel.post({"command": "apply-done", "ok": False,
                                 "error": "%s: %s" % (type(exc).__name__, exc)})
            return
        if command == "apply-global-proposal":
            # v0.9.1: AI proposal -> GLOBAL process preset (the card's
            # second target). Same transaction worker as 写入全局预设
            # (schema-drift drop loop included); NO revert checkpoint —
            # preset writes are undone by the user's own preset handling.
            try:
                raw = (message or {}).get("values")
                if not isinstance(raw, dict) or not raw:
                    raise ValueError("提案缺少 values")
                values = {str(k): _orca_serialize(v) for k, v in raw.items()}
            except Exception as exc:  # noqa: BLE001 - surfaced in the panel
                if _panel is not None:
                    _panel.post({"command": "apply-done", "ok": False,
                                 "error": "%s: %s" % (type(exc).__name__, exc)})
                return
            threading.Thread(
                target=_apply_global_worker, daemon=True,
                name="stratum-orca-apply-global",
                args=(values, [], "（来自 AI 提案，写入全局预设）")).start()
            return
        if command == "revert-proposal":
            try:
                old = _proposal_checkpoint.get("old_values") or {}
                restore = {str(k): _orca_serialize(v)
                           for k, v in old.items() if v is not None}
                skipped = len(old) - len(restore)
                if not restore:
                    raise ValueError("没有可回滚的旧值（提案前这些键没有对象级覆盖"
                                     "——请在对象参数里手动重置）")
                note = _write_pick_object_overrides(restore)
                if skipped:
                    note += ("；%d 项原本继承预设（无旧值可写回），"
                             "请在对象参数里手动重置" % skipped)
                _proposal_checkpoint["old_values"] = None
                if _panel is not None:
                    _panel.post({"command": "apply-done", "ok": True,
                                 "note": note})
            except Exception as exc:  # noqa: BLE001 - surfaced in the panel
                import traceback
                traceback.print_exc()
                if _panel is not None:
                    _panel.post({"command": "apply-done", "ok": False,
                                 "error": "%s: %s" % (type(exc).__name__, exc)})
            return
        if command != "pick":
            return
        if _picking.is_set():
            return  # busy: a pick is already in flight
        _picking.set()
        try:
            # UI thread: selection + host export/mesh reads must not race the
            # GUI model; only packing/upload go to the worker.
            object_idx, obj, note0 = _select_object()
            picked_id = obj.id()  # UI-thread host call (see identity guard in _apply_suggestions)
            payload, filename, note1 = _collect_upload_payload(obj, object_idx)
        except Exception as exc:  # noqa: BLE001 - user-facing toolbar line
            _picking.clear()
            import traceback
            traceback.print_exc()  # full context to the persisted python log
            if _panel is not None:
                _panel.post({"command": "pick-done", "ok": False,
                             "error": "%s: %s" % (type(exc).__name__, exc)})
            return
        threading.Thread(
            target=_upload_worker, daemon=True, name="stratum-orca-pick",
            args=(payload, filename,
                  "；".join(x for x in (note0, note1) if x), object_idx, picked_id),
        ).start()

    def on_close(self):
        global _panel
        _panel = None


@orca.plugin
class StratumPlugin(orca.base):
    def register_capabilities(self):
        orca.register_capability(StratumPanel)
