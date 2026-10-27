#!/usr/bin/env python3
"""Headless chain test for the Stratum Orca plugin packaging.

Boots a standalone copy of the plugin's vendored server (repo server.py —
the same file make-plugin.sh ships unchanged under app/), then drives the
plugin-era API chain without Orca:

    POST /api/sample        stage the bundled beam sample as a model session
    POST /api/upload        UPPERCASE .3MF gate (case-insensitive suffix,
                            engine 0.27 / server alignment) + multislot flag
    POST /api/gcode-attach  attach a synthetic plate-slice.gcode to it
    POST /api/analyze       full engine run; assert ok AND gcode_attached
    POST /api/chat          grounded AI Q&A smoke (codex CLI; skipped with
                            a note when the companion is unavailable)

This is the server-side half of the panel's「从盘选取 → 分析盘上 G-code」
loop: it proves the sample/attach/analyze plumbing (tokens, raw-body
upload, --gcode-in channel) end to end against the real engine binary.

Usage:  python packaging/orca-plugin/test_chain.py
Exit 0 = all green. Acceptance: run it twice in a row, both green. The
server process is always killed on exit (STRATUM_UI_PORT pins it to 8799
so the kill target is unambiguous).
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

PORT = 8799  # pinned: never collides with the standalone default 8765
BASE = "http://127.0.0.1:%d" % PORT
HEADERS = {"X-Stratum-UI": "1"}  # POST gate (server._origin_allowed)

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
_SERVER_PY = os.path.join(_REPO, "server.py")


def _post(path, body=None, data=None, timeout=300):
    """POST with the UI marker header. `data` (raw bytes) wins over `body`."""
    payload = data if data is not None else (
        json.dumps(body).encode("utf-8") if body is not None else b"")
    headers = dict(HEADERS)
    headers["Content-Type"] = ("application/json" if data is None and
                               body is not None else
                               "application/octet-stream")
    req = urllib.request.Request(BASE + path, data=payload,
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # 4xx bodies carry the server's JSON error — return ok:false so
        # contract assertions can check the message instead of raising
        return json.loads(exc.read().decode("utf-8"))


def _get(path, timeout=10):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _minimal_3mf(fillet_slots=1):
    """A minimal but structurally valid 3MF as in-memory bytes: unit
    tetrahedron mesh + content types + rels + Metadata/project_settings
    (+ filament_settings_1.config when fillet_slots==2, i.e. multi-extruder).
    Built for the upload GATE only — never analyzed (handcrafted XML is not
    worth betting the engine's parser on)."""
    model = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<model unit="millimeter" xml:lang="en-US"'
        ' xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
        '<resources><object id="1" type="model"><mesh><vertices>'
        '<vertex x="0" y="0" z="0"/><vertex x="10" y="0" z="0"/>'
        '<vertex x="0" y="10" z="0"/><vertex x="0" y="0" z="10"/>'
        '</vertices><triangles>'
        '<triangle v1="0" v2="2" v3="1"/><triangle v1="0" v2="1" v3="3"/>'
        '<triangle v1="0" v2="3" v3="2"/><triangle v1="1" v2="2" v3="3"/>'
        '</triangles></mesh></object></resources>'
        '<build><item objectid="1"/></build></model>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml",
                    '<?Types xmlns="http://schemas.openxmlformats.org/package/'
                    '2006/content-types"><Default Extension="rels" ContentType='
                    '"application/vnd.openxmlformats-package.relationships+xml"/>'
                    '<Default Extension="model" ContentType='
                    '"application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
                    '<Default Extension="config" ContentType='
                    '"application/octet-stream"/></Types>')
        zf.writestr("_rels/.rels",
                    '<?Relationships xmlns="http://schemas.openxmlformats.org/'
                    'package/2006/relationships"><Relationship Target='
                    '"/3D/3dmodel.model" Id="rel0" Type="http://schemas.'
                    'microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
                    '</Relationships>')
        zf.writestr("3D/3dmodel.model", model)
        zf.writestr("Metadata/project_settings.config",
                    '<?xml version="1.0"?><config/>')
        if fillet_slots >= 2:
            zf.writestr("Metadata/filament_settings_1.config",
                        '<?xml version="1.0"?><config/>')
    return buf.getvalue()


def _synthetic_gcode():
    """A small Marlin-flavored print over the beam sample's envelope
    (100x10x4 mm): two perimeter loops plus one zigzag infill line per
    0.2 mm layer. The engine's --gcode-in channel samples the FEM along
    these extrusion moves — coordinates must land inside the model."""
    lines = [
        ";FLAVOR:Marlin",
        "; synthetic plate-slice for stratum test_chain",
        "M201 X1000 Y1000", "G21", "G90", "M83", "G28", "M104 S220",
        ";TYPE:WALL-OUTER",
    ]
    e = 0.0
    for layer in range(1, 21):  # z = 0.2 .. 4.0 mm
        z = 0.2 * layer
        lines.append(";LAYER:%d" % (layer - 1))
        lines.append("G1 Z%.2f F600" % z)
        for x0, y0, x1, y1 in ((0.4, 0.4, 99.6, 9.6), (0.8, 0.8, 99.2, 9.2)):
            for seg in ((x0, y0, x1, y0), (x1, y0, x1, y1),
                        (x1, y1, x0, y1), (x0, y1, x0, y0)):
                e += 1.0
                lines.append("G1 X%.2f Y%.2f E%.3f F1200" % (seg[2], seg[3], e))
        for i in range(10):  # one infill zigzag per layer
            y = 1.5 + i * 0.8
            e += 4.0
            lines.append("G1 X%.2f Y%.2f E%.3f F1800" % (1.5, y, e))
            e += 4.0
            lines.append("G1 X%.2f Y%.2f E%.3f F1800" % (98.5, y, e))
    lines += ["M104 S0", "G28 X0 Y0", "M84"]
    return ("\n".join(lines) + "\n").encode("ascii")


def _chain():
    # -- wait for the server to come up ----------------------------------
    deadline = time.monotonic() + 30.0
    status = None
    while time.monotonic() < deadline:
        try:
            status = _get("/api/status")
            if status.get("ok"):
                break
        except (urllib.error.URLError, ConnectionError, OSError):
            pass
        time.sleep(0.2)
    if not (status or {}).get("ok"):
        raise AssertionError("server did not become healthy on port %d" % PORT)
    print("[1/7] /api/status ok  (engine %s)" % status.get("engine_version"))

    # -- sample -> model session ------------------------------------------
    sample = _post("/api/sample", body={})
    assert sample.get("ok"), "sample failed: %r" % sample
    token = sample["token"]
    print("[2/7] /api/sample ok  (token %s, %s)" % (token, sample.get("name")))

    # -- uppercase .3MF gate + multislot flag (engine 0.27 alignment) ------
    up1 = _post("/api/upload?name=UPPER.3MF", data=_minimal_3mf(1))
    assert up1.get("ok"), "UPPERCASE .3MF rejected: %r" % up1
    assert up1.get("is_3mf") is True and up1.get("writable") is True, \
        "UPPER.3MF misclassified: %r" % up1
    assert up1.get("multislot") is False, \
        "single-slot 3mf flagged multislot: %r" % up1
    up2 = _post("/api/upload?name=DUAL.3mf", data=_minimal_3mf(2))
    assert up2.get("ok") and up2.get("multislot") is True, \
        "filament_settings_1 not detected: %r" % up2
    print("[3/7] .3MF gate case-insensitive; multislot %s/%s"
          % (up1.get("multislot"), up2.get("multislot")))

    # -- attach synthetic slice gcode --------------------------------------
    gcode = _synthetic_gcode()
    att = _post("/api/gcode-attach?token=%s&name=plate-slice.gcode" % token,
                data=gcode)
    assert att.get("ok"), "gcode-attach failed: %r" % att
    print("[4/7] /api/gcode-attach ok  (%d KB synthetic slice)"
          % (len(gcode) // 1024))

    # -- analyze with the attachment riding --gcode-in ---------------------
    t0 = time.monotonic()
    result = _post("/api/analyze", body={"token": token})
    assert result.get("ok"), "analyze failed: %r" % (
        {k: result.get(k) for k in ("ok", "error")})
    assert result.get("gcode_attached") is True, \
        "gcode_attached is %r (expected True)" % result.get("gcode_attached")
    report = result.get("report") or {}
    tune = result.get("gcode_tune")
    print("[5/7] /api/analyze ok  gcode_attached=True  "
          "(%.1fs, gcode_tune=%s, orca_suggestions=%d)"
          % (time.monotonic() - t0,
             "present" if tune else "absent",
             len(((report.get("orca_suggestions") or {}).get("items")) or [])))

    # -- grounded chat smoke (codex CLI companion; degrade = skip+note) ----
    if status.get("chat_available"):
        chat = _post("/api/chat", timeout=180,
                     body={"token": token, "question": "用一句话总结当前报告的结论",
                           "history": []})
        assert chat.get("ok"), "chat failed: %r" % chat
        assert isinstance(chat.get("reply"), str) and chat["reply"].strip(), \
            "chat reply empty: %r" % chat
        print("[6/7] /api/chat ok  (reply %d chars, stripped=%s, actions=%s)"
              % (len(chat["reply"]), chat.get("stripped"), chat.get("actions")))
    else:
        print("[6/7] /api/chat skipped (chat_available false — codex CLI absent)")

    # -- assistant server tools + step smoke (host tools need Orca) ---------
    ga = _post("/api/assistant/tool",
               body={"token": token, "tool": "get_analysis", "args": {}})
    assert ga.get("ok") and "安全系数" in (ga.get("result") or ""), ga
    rg = _post("/api/assistant/tool",
               body={"token": token, "tool": "read_gcode",
                     "args": {"head_lines": 5, "tail_lines": 5}})
    assert rg.get("ok") and rg["result"]["total_lines"] > 0 and \
        len(rg["result"]["excerpt"]) < 20000, rg
    hr = _post("/api/assistant/tool",
               body={"token": token, "tool": "run_analysis", "args": {}})
    assert not hr.get("ok") and "宿主工具" in (hr.get("error") or ""), hr
    if status.get("chat_available"):
        st = _post("/api/assistant/step", timeout=180,
                   body={"token": token,
                         "question": "直接给最终回答，不要调用任何工具：报告的安全系数是多少？",
                         "history": [], "results": []})
        assert st.get("ok") and st.get("type") in ("final", "tool_calls"), st
        print("[7/7] assistant ok  (type=%s, stripped=%s)"
              % (st.get("type"), st.get("stripped")))
    else:
        print("[7/7] assistant step skipped (chat_available false)")
    print("ALL GREEN")
    return 0


def main():
    tmp = tempfile.mkdtemp(prefix="stratum-chain-test-")
    env = dict(os.environ)
    env["STRATUM_UI_PORT"] = str(PORT)
    env["STRATUM_UI_NO_BROWSER"] = "1"
    # keep the test off the user's standalone rolling logs
    env["STRATUM_UI_LOG_DIR"] = os.path.join(tmp, "logs")
    errpath = os.path.join(tmp, "server-stderr.log")
    errfh = open(errpath, "wb")
    proc = subprocess.Popen([sys.executable, _SERVER_PY],
                            stdout=subprocess.DEVNULL, stderr=errfh, env=env)
    try:
        result = _chain()
        # Impostor guard: if OUR process died, every answer above came from
        # a stale listener that already owned 8799 (old code, old engine —
        # seen in the field: tests stayed green against a days-old server).
        assert proc.poll() is None, (
            "our server process exited early — port %d is owned by a stale "
            "listener; kill it (netstat -ano | grep %d) and rerun" % (PORT, PORT))
        return result
    except BaseException:
        # surface the server's own words — they usually name the cause
        try:
            with open(errpath, "rb") as fh:
                tail = fh.read()[-3000:].decode("utf-8", "replace").strip()
            if tail:
                print("--- server stderr tail ---\n%s" % tail, file=sys.stderr)
        except OSError:
            pass
        raise
    finally:
        proc.kill()  # acceptance: the script must never leak the server
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        errfh.close()
        print("server killed; logs kept at %s" % tmp, file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
