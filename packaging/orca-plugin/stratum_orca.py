# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy"]
#
# [tool.orcaslicer.plugin]
# name = "Stratum"
# description = "Stratum 工艺参数调参台 — FDM 可打印性分析引擎的嵌入式 Web UI（插件内起本地服务，停靠面板内嵌 iframe；支持一键选取盘上选中模型送入分析）"
# author = "Stratum-WebUI"
# version = "0.7.3"
# ///
"""Stratum Orca plugin — embeds the Stratum WebUI (server.py + zero-build web
assets, vendored unchanged under app/) into an Orca dock panel.

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
            with zipfile.ZipFile(os.path.join(vendor, fname)) as zf:
                zf.extractall(tmp)
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
        spec = importlib.util.spec_from_file_location("stratum_server", _SERVER_PY)
        module = importlib.util.module_from_spec(spec)
        sys.modules["stratum_server"] = module
        spec.loader.exec_module(module)
        module._setup_file_logging()
        module._sweep_orphan_workdirs()
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
        "  #bar { display: flex; align-items: center; gap: 8px; padding: 4px 8px;"
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
        "    else if (t === 'stratum-orca-pick')"
        "      orca.postMessage({ command: 'pick' });"
        "    else if (t === 'stratum-orca-gcode')"
        "      orca.postMessage({ command: 'gcode' });"
        "    else if (t === 'stratum-orca-tool')"
        "      orca.postMessage({ command: 'tool', call: ev.data.call });"
        "    else if (t === 'stratum-orca-apply-proposal')"
        "      orca.postMessage({ command: 'apply-proposal',"
        "        values: ev.data.values, old_values: ev.data.old_values });"
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
        names = ", ".join((objects[i].name or "(未命名)") for i in idxs if i < len(objects))
        raise ValueError("一次只支持一个对象（选中了 %d 个: %s）" % (len(idxs), names))
    i = idxs[0]
    if i >= len(objects):
        raise ValueError("选中的对象索引越界（%d）" % i)
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
        blob = _pack_binary_stl(payload)
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
    recommended value. Shared by 写回对象 and 写入全局预设."""
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
        if item.get("recommended_value") is None:
            skipped.append(key)
            continue
        values[key] = _orca_serialize(item["recommended_value"])
    if not values:
        raise ValueError("报告里没有可写回的建议（%d 项无推荐值）" % len(skipped))
    return values, skipped


def _apply_suggestions():
    """UI thread: write the pick session's engine suggestions (Orca keys,
    report orca_suggestions channel) back as per-object process overrides.

    All host work stays on the UI thread (ModelConfig::touch is main-thread
    only); the report is read from the in-process server module under its
    session lock — no HTTP, no audit surface.
    """
    values, skipped = _collect_suggestion_values()
    note = _write_pick_object_overrides(values)
    if skipped:
        note += "；跳过 %d 项无推荐值（%s）" % (len(skipped), ", ".join(skipped))
    return note


def _apply_global_worker(values, skipped):
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
        txn = editor.begin_update()
        for k, v in values.items():
            txn.set(k, v)
        txn.commit()
        applied = ["%s=%s" % (k, values[k]) for k in values]
        note = ("全局预设已更新 %d 项（%s）——参数面板即刻生效，预设已标记为已修改，"
                "可在参数面板保存" % (len(applied), ", ".join(applied)))
        if skipped:
            note += "；跳过 %d 项无推荐值（%s）" % (len(skipped), ", ".join(skipped))
        reply(True, note=note)
    except Exception as exc:  # noqa: BLE001 - toolbar line
        import traceback
        traceback.print_exc()
        reply(False, error="%s: %s" % (type(exc).__name__, exc))


def _write_pick_object_overrides(values):
    """UI thread: T1 identity guard + apply_object_config + result note.
    Shared by 写回（report suggestions）, the AI proposal Apply, and its
    Revert — one guard, one writer, no drift between entry points."""
    plater = orca.host.plater()
    applier = getattr(plater, "apply_object_config", None)
    if applier is None:
        raise ValueError("宿主缺少 apply_object_config 绑定（需含该绑定的 Orca 构建）")
    object_idx, obj, _ = _select_object()
    # v0.4 identity guard: suggestions belong to the PICKED object. Compare
    # the pick-time ModelObject.id() with the currently selected one — a
    # selection change between pick and apply must not redirect the write
    # onto whatever is selected now. id (not idx): indices shift when
    # objects are added/removed; ModelObject ids stay with the object.
    picked_id = _last_pick.get("object_id")
    if picked_id is None:
        raise ValueError("选取会话缺少对象 id（旧版会话残留？请重新「从盘选取」）")
    if obj.id() != picked_id:
        raise ValueError(
            "分析对象与当前选中不一致——请重新选中「%s」再写回，或对其重新「从盘选取」"
            % (_last_pick.get("name") or "原分析对象"))
    results = list(applier(object_idx, values))
    applied = ["%s=%s" % (k, values[k]) for k, ok, _err in results if ok]
    failed = ["%s: %s" % (k, err) for k, ok, err in results if not ok]
    parts = ["写回 %d 项（%s）" % (len(applied), ", ".join(applied))]
    if failed:
        parts.append("失败 %d 项（%s）" % (len(failed), "; ".join(failed)))
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
        blob = _pack_binary_stl(payload)
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


def _dispatch_host_tool(call):
    """UI thread entry for the AI assistant's host tools."""
    call = call or {}
    tid = str(call.get("id") or "?")
    name = call.get("tool")
    args = call.get("args") if isinstance(call.get("args"), dict) else {}
    try:
        if name == "get_print_context":
            _tool_reply(tid, True, result=_print_context())
        elif name == "run_analysis":
            if _picking.is_set():
                raise ValueError("一项选取/分析已在进行中——稍候再试")
            _picking.set()
            try:
                object_idx, obj, note0 = _select_object()
                picked_id = obj.id()
                payload, note1 = _collect_mesh_payload(obj)
                filename = ("%s.stl" % (obj.name or "model")).strip()
            except Exception:
                _picking.clear()
                raise
            threading.Thread(
                target=_analysis_tool_worker, daemon=True,
                name="stratum-orca-ai-run",
                args=(tid, payload, filename, object_idx, picked_id,
                      "；".join(x for x in (note0, note1) if x))).start()
        elif name == "propose_settings":
            values = args.get("values")
            if not isinstance(values, dict) or not values:
                raise ValueError("propose_settings 需要 args.values 参数字典")
            if not _last_pick.get("token"):
                raise ValueError("还没有选取/分析会话——先 run_analysis")
            _idx, obj, _ = _select_object()
            if obj.id() != _last_pick.get("object_id"):
                raise ValueError("分析对象与当前选中不一致——提案要求选中的仍是分析对象")
            keys = list(obj.config_keys())
            old = {k: (obj.config_value(k) if k in keys else None)
                   for k in values}
            _tool_reply(tid, True, result={
                "old_values": old,
                "note": "提案已生成（只读比对，未写入）；用户在面板确认后才应用"})
        else:
            raise ValueError("unknown host tool: %r" % name)
    except Exception as exc:  # noqa: BLE001 - tool result line
        import traceback
        traceback.print_exc()
        _tool_reply(tid, False, error="%s: %s" % (type(exc).__name__, exc))


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
                values, skipped = _collect_suggestion_values()
            except Exception as exc:  # noqa: BLE001 - toolbar line
                if _panel is not None:
                    _panel.post({"command": "apply-done", "ok": False,
                                 "error": "%s: %s" % (type(exc).__name__, exc)})
                return
            threading.Thread(target=_apply_global_worker, daemon=True,
                             name="stratum-orca-apply-global",
                             args=(values, skipped)).start()
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
            # UI thread: selection + zero-copy mesh reads must not race the
            # GUI model; only packing/upload go to the worker.
            object_idx, obj, note0 = _select_object()
            picked_id = obj.id()  # UI-thread host call (see identity guard in _apply_suggestions)
            payload, note1 = _collect_mesh_payload(obj)
            filename = ("%s.stl" % (obj.name or "model")).strip()
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
