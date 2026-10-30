#!/usr/bin/env python3
"""Headless chain test for the Stratum Orca plugin packaging.

Phase 1 (in-process, no Orca, v0.12): pure-function unit checks for the
plugin's ambient-grounding env card — _assemble_env_card against fake
plater/bundle stubs (card structure, the ten normalized config keys with
omit-when-missing semantics, filament slots, plate overview, slice_state
word), the merge-window coalescer (an N-event storm arms exactly ONE
flush), the lifecycle filter, and the host-tool registration degrade
(refresh_env_card undeclared in an older agent_tools must not raise).

Phase 2 (subprocess): boots a standalone copy of the plugin's vendored
server (repo server.py — the same file make-plugin.sh ships unchanged
under app/), then drives the plugin-era API chain without Orca:

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
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types
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


# ---- v0.12 plugin pure-function checks (ambient grounding, no Orca) --------

class _FakeModelObject(object):
    """ModelObject stub: the exact surface _plate_objects_summary reads."""
    def __init__(self, name, instances=1, volumes=1, facets=10):
        self.name = name
        self._counts = (instances, volumes, facets)

    def instance_count(self):
        return self._counts[0]

    def volume_count(self):
        return self._counts[1]

    def facets_count(self):
        return self._counts[2]


class _FakePlater(object):
    """Plater stub WITHOUT a slice-state query (slice_state must omit)."""
    def __init__(self, objects, selected=(), eff=None):
        self._objects = list(objects)
        self._selected = list(selected)
        self._eff = eff

    def model(self):
        return self

    def objects(self):
        return list(self._objects)

    def selected_object_indices(self):
        return list(self._selected)

    def get_effective_config(self):
        return dict(self._eff or {})


class _FakeSlicingPlater(_FakePlater):
    """Adds the is_slicing query _card_slice_state probes for."""
    def __init__(self, objects, selected=(), eff=None, slicing=False):
        _FakePlater.__init__(self, objects, selected, eff)
        self._slicing = slicing

    def is_slicing(self):
        return self._slicing


class _FakePreset(object):
    """Preset stub; config_keys as property (the method shape is the same
    discipline — the plugin resolves callable-or-property at read time)."""
    def __init__(self, values):
        self._values = dict(values)

    @property
    def config_keys(self):
        return sorted(self._values)

    def config_value(self, key):
        return self._values[key]


class _FakePresetCollection(object):
    """Both selection shapes the plugin probes: selected_preset (singular,
    config-value reads) and selected_presets (plural, filament slots)."""
    def __init__(self, presets):
        self._presets = list(presets)

    def selected_preset(self):
        return self._presets[0] if self._presets else None

    def selected_presets(self):
        return list(self._presets)


class _FakeBundle(object):
    def __init__(self, filaments, prints):
        self.filaments = filaments
        self.prints = prints


class _FakePlateModule(object):
    """orca.host.plate stub — the accessor names ENV first-hit candidates."""
    def __init__(self, current=0, per_plate=(3, 1)):
        self._current = current
        self._per_plate = list(per_plate)

    def get_curr_plate_index(self):
        return self._current

    def get_plate_object_counts(self):
        return list(self._per_plate)


_ENV_CARD_TEN_KEYS = {"material", "nozzle_temperature", "bed_temperature",
                      "nozzle_diameter", "layer_height", "walls",
                      "infill_density", "infill_pattern", "print_speed",
                      "cooling_fan"}

_EFF_FULL = {  # Orca-side keys -> verbatim string values (host norm)
    "filament_type": "PLA",
    "nozzle_temperature": "220",
    "bed_temperature": "65",
    "nozzle_diameter": "0.4",
    "layer_height": "0.16",
    "wall_loops": "2",
    "sparse_infill_density": "15",
    "sparse_infill_pattern": "gyroid",
    "inner_wall_speed": "50",
    "fan_max_speed": "100",
}


def _plugin_env_card_checks():
    """Phase 1: pure-function checks for the v0.12 env card. The plugin
    entry imports `orca` (host-only), so it is copied to a temp dir and
    imported against a stub orca — the same harness pattern as
    packaging/orca-plugin/test_selection.py. Only dependency-injected
    surfaces run: no host, no HTTP, no timers."""
    tmp = tempfile.mkdtemp(prefix="stratum-envcard-test-")
    shutil.copy(os.path.join(_HERE, "stratum_orca.py"),
                os.path.join(tmp, "stratum_orca.py"))
    orca_stub = types.ModuleType("orca")
    orca_stub.script = types.SimpleNamespace(
        ScriptPluginCapabilityBase=object)
    orca_stub.plugin = lambda *a, **k: (lambda f: f)
    orca_stub.base = object
    orca_stub.host = types.SimpleNamespace(plate=_FakePlateModule())
    sys.modules["orca"] = orca_stub
    saved_tempdir = tempfile.tempdir  # the plugin entry pins tempfile at
    # import; restore so the chain's server-log tempdir policy is unchanged
    spec = importlib.util.spec_from_file_location(
        "stratum_orca_envcard_test", os.path.join(tmp, "stratum_orca.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    tempfile.tempdir = saved_tempdir

    # -- ENV_KEY_MAP pins the shared contract: exactly the ten card keys ----
    assert set(mod.ENV_KEY_MAP) == _ENV_CARD_TEN_KEYS, \
        "ENV_KEY_MAP left side drifted from the ten contract keys: %r" \
        % sorted(mod.ENV_KEY_MAP)

    # -- full assembly: structure, ten keys verbatim, slots, plate, state ---
    plater = _FakeSlicingPlater(
        objects=[_FakeModelObject("bracket", instances=2, volumes=3,
                                  facets=1234),
                 _FakeModelObject("gear", facets=456)],
        selected=(1,), eff=_EFF_FULL, slicing=True)
    bundle = _FakeBundle(
        filaments=_FakePresetCollection(
            [_FakePreset({"filament_type": "PLA"}),
             _FakePreset({"filament_type": "PLA"})]),
        prints=_FakePresetCollection([_FakePreset({"layer_height": "0.2"})]))
    card = mod._assemble_env_card(plater, bundle)
    assert card["objects"][0] == {"idx": 0, "name": "bracket", "instances": 2,
                                  "volumes": 3, "facets": 1234,
                                  "selected": False}, card["objects"][0]
    assert card["objects"][1]["selected"] is True
    assert card["selected_count"] == 1
    assert set(card["config"]) == _ENV_CARD_TEN_KEYS, card["config"]
    assert card["config"]["material"] == "PLA"
    assert card["config"]["nozzle_temperature"] == "220"
    assert card["config"]["bed_temperature"] == "65"
    assert card["config"]["walls"] == "2"
    assert card["config"]["infill_density"] == "15"
    assert card["config"]["infill_pattern"] == "gyroid"
    assert card["config"]["print_speed"] == "50"   # inner_wall_speed alias
    assert card["config"]["cooling_fan"] == "100"  # fan_max_speed alias
    assert card["filaments"] == ["PLA", "PLA"]
    assert card["plate"] == {"current": 0, "count": 2,
                             "objects_per_plate": [3, 1]}
    assert card["slice_state"] == "slicing"
    assert json.dumps({"card": card, "event": "ObjectAdded"})  # wire-ready

    # -- idle word + slice-query-absent omission ----------------------------
    idle = mod._assemble_env_card(
        _FakeSlicingPlater([_FakeModelObject("m")], slicing=False), bundle)
    assert idle["slice_state"] == "idle"
    bare = mod._assemble_env_card(_FakePlater([_FakeModelObject("m")]),
                                  _FakeBundle(
                                      _FakePresetCollection([]),
                                      _FakePresetCollection([])))
    assert "slice_state" not in bare, "absent query surface must omit"
    # bare has no filament presets and no eff: filaments omit too
    assert "filaments" not in bare

    # -- omission semantics: partial eff + per-key preset fallback ----------
    partial = mod._assemble_env_card(
        _FakePlater([_FakeModelObject("m")],
                    eff={"filament_type": "PLA", "layer_height": "0.16"}),
        _FakeBundle(_FakePresetCollection([]),
                    _FakePresetCollection([_FakePreset({"wall_loops": "3"})])))
    assert partial["config"] == {"material": "PLA", "layer_height": "0.16",
                                 "walls": "3"}, partial["config"]
    assert "nozzle_temperature" not in partial["config"]  # absent -> omitted
    assert all(v is not None for v in partial["config"].values())
    # verbatim values: an int from the host stays an int (原样, no stringify)
    verbatim = mod._assemble_env_card(
        _FakePlater([_FakeModelObject("m")], eff={"wall_loops": 2}),
        _FakeBundle(_FakePresetCollection([]),
                    _FakePresetCollection([])))
    assert verbatim["config"] == {"walls": 2}, verbatim["config"]

    # -- merge window: an event storm arms exactly ONE flush ----------------
    co = mod._EnvCardCoalescer()
    actions = [co.add_event() for _ in range(25)]
    assert actions[0] == "arm" and set(actions[1:]) == {"skip"}, actions
    co.flush_fired()  # timer shipped the pending card
    assert co.add_event() == "arm"  # next burst opens a new window
    assert co.add_event() == "skip"

    # -- lifecycle filter (keyword domains, excluded noise) ------------------
    assert mod._is_env_card_event("PresetValueChanged")
    assert mod._is_env_card_event("ObjectAdded")
    assert mod._is_env_card_event("PlateSelected")
    assert mod._is_env_card_event("ProjectOpened")
    assert not mod._is_env_card_event("SlicingUpdate")      # slice domain
    assert not mod._is_env_card_event("PlateGcodeExported")  # plate+export
    assert not mod._is_env_card_event("DeviceStatus")
    assert not mod._is_env_card_event("UploadTaskProgress")
    assert not mod._is_env_card_event("")
    class _EnumEvt(object):  # enum-member shape (defensive normalization)
        value = "ObjectRemoved"
    assert mod._env_card_event_text(_EnumEvt()) == "ObjectRemoved"
    assert mod._env_card_event_text({"code": "PlateCreated"}) == "PlateCreated"

    # -- host-tool registration degrade (older agent_tools w/o the decl) ----
    at_spec = importlib.util.spec_from_file_location(
        "agent_tools_envcard_test", os.path.join(_REPO, "agent_tools.py"))
    at = importlib.util.module_from_spec(at_spec)
    at_spec.loader.exec_module(at)
    fake_srv = types.SimpleNamespace(agent_tools=at)
    mod._register_host_tools(fake_srv)  # must not raise either way
    assert at.TOOLS["get_print_context"].handler is not None

    print("[1/8] plugin env-card checks ok  "
          "(config 10 keys + omit/fallback, storm 25->1 flush, "
          "registry degrade ok)")


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
    print("[2/8] /api/status ok  (engine %s)" % status.get("engine_version"))

    # -- sample -> model session ------------------------------------------
    sample = _post("/api/sample", body={})
    assert sample.get("ok"), "sample failed: %r" % sample
    token = sample["token"]
    print("[3/8] /api/sample ok  (token %s, %s)" % (token, sample.get("name")))

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
    print("[4/8] .3MF gate case-insensitive; multislot %s/%s"
          % (up1.get("multislot"), up2.get("multislot")))

    # -- attach synthetic slice gcode --------------------------------------
    gcode = _synthetic_gcode()
    att = _post("/api/gcode-attach?token=%s&name=plate-slice.gcode" % token,
                data=gcode)
    assert att.get("ok"), "gcode-attach failed: %r" % att
    print("[5/8] /api/gcode-attach ok  (%d KB synthetic slice)"
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
    print("[6/8] /api/analyze ok  gcode_attached=True  "
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
        print("[7/8] /api/chat ok  (reply %d chars, stripped=%s, actions=%s)"
              % (len(chat["reply"]), chat.get("stripped"), chat.get("actions")))
    else:
        print("[7/8] /api/chat skipped (chat_available false — codex CLI absent)")

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
        print("[8/8] assistant ok  (type=%s, stripped=%s)"
              % (st.get("type"), st.get("stripped")))
    else:
        print("[8/8] assistant step skipped (chat_available false)")
    print("ALL GREEN")
    return 0


def main():
    # phase 1 first: in-process pure-function checks (also pins the plugin
    # module import before any server state exists)
    _plugin_env_card_checks()
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
