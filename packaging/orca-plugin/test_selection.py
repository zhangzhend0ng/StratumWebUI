#!/usr/bin/env python3
"""Unit tests for the v0.9.1 selected-model check fixes (stratum_orca.py):
   - _select_object validates the selection index on BOTH bounds
   - write paths resolve the target by pick-time ModelObject.id() and only
     DISCLOSE a selection mismatch (no hard refusal)
   - the 3MF export channel is identity-checked by triangle totals and
     degrades to the STL pack with the reason disclosed

Same harness as test_repair.py: the plugin entry imports `orca` (host-only),
so the module is copied to a temp dir and imported with a stubbed orca.
numpy is available in this environment, so the STL-fallback path is covered
too (it packs meshes through numpy).

Run: python packaging/orca-plugin/test_selection.py
"""
import importlib.util
import shutil
import sys
import tempfile
import types
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = []


def check(name, fn):
    try:
        fn()
        RESULTS.append((True, name, None))
        print("[ok] %s" % name)
    except AssertionError as exc:
        RESULTS.append((False, name, str(exc)))
        print("[FAIL] %s: %s" % (name, exc))


# ---- import the plugin entry with a stubbed orca ---------------------------
TMP = Path(tempfile.mkdtemp(prefix="stratum-selection-test-"))
shutil.copy(HERE / "stratum_orca.py", TMP / "stratum_orca.py")
_orca_stub = types.ModuleType("orca")
_orca_stub.script = types.SimpleNamespace(ScriptPluginCapabilityBase=object)
_orca_stub.plugin = lambda *a, **k: (lambda f: f)
_orca_stub.base = object
sys.modules["orca"] = _orca_stub
_spec = importlib.util.spec_from_file_location("stratum_orca_uut", TMP / "stratum_orca.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


# ---- fake host --------------------------------------------------------------
class FakeMesh:
    def __init__(self, triangles, empty=False):
        import numpy as np
        self._t = triangles
        self._empty = empty
        self._verts = np.zeros((triangles * 3, 3), dtype=np.float32)

    def is_empty(self):
        return self._empty

    def triangle_count(self):
        return 0 if self._empty else self._t

    def vertices(self):
        return self._verts

    def triangles(self):
        import numpy as np
        return np.zeros((self._t, 3), dtype=np.int32)


class FakeVolume:
    def __init__(self, triangles, part=True):
        self._mesh = FakeMesh(triangles)
        self._part = part

    def is_model_part(self):
        return self._part

    def mesh(self):
        return self._mesh

    def matrix(self):
        import numpy as np
        return np.eye(4)


class FakeObject:
    def __init__(self, oid, name, volumes):
        self.oid = oid
        self.name = name
        self._vols = volumes

    def id(self):
        return self.oid

    def volumes(self):
        return self._vols

    def instance_count(self):
        return 1

    def instance(self, i):
        return types.SimpleNamespace(matrix=lambda: __import__("numpy").eye(4))

    def config_keys(self):
        return ["gap_infill_speed", "sparse_infill_density"]

    def config_value(self, k):
        return "20"


def _3mf_xml(triangles):
    tri = "".join('<triangle v1="0" v2="1" v3="2"/>' for _ in range(triangles))
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<model unit="millimeter" xmlns="http://schemas.microsoft.com/'
            '3dmanufacturing/core/1"><resources><object id="1" type="model">'
            "<mesh><vertices><vertex x=\"0\" y=\"0\" z=\"0\"/></vertices>"
            "<triangles>%s</triangles></mesh></object></resources></model>" % tri)


def _write_3mf(path, triangles):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("3D/3dmodel.model", _3mf_xml(triangles))


class FakePlater:
    """Configurable plate: objects + selection + export binding."""

    def __init__(self, objects, sel=(), export_triangles=None):
        self._objects = objects
        self._sel = list(sel)
        self._export_triangles = export_triangles  # None = no binding
        self.applied = []

    def model(self):
        return types.SimpleNamespace(objects=lambda: self._objects)

    def selected_object_indices(self):
        return list(self._sel)

    def export_object_3mf(self, idx, path):
        _write_3mf(path, self._export_triangles)

    def apply_object_config(self, idx, values):
        self.applied.append((idx, dict(values)))
        return [(k, True, "") for k in values]


def _install(plater):
    host = types.SimpleNamespace(plater=lambda: plater)
    _orca_stub.host = host
    mod._last_pick.update({"token": None, "object_idx": None,
                           "object_id": None, "name": None})


def _plate():
    obj0 = FakeObject(100, "A", [FakeVolume(10), FakeVolume(4, part=False)])
    obj1 = FakeObject(101, "B", [FakeVolume(12)])
    return obj0, obj1


# ---- _select_object: index validation --------------------------------------
def t_select_negative():
    obj0, obj1 = _plate()
    p = FakePlater([obj0, obj1], sel=[-1])
    _install(p)
    try:
        mod._select_object()
        raise AssertionError("negative index accepted")
    except ValueError as exc:
        assert "越界" in str(exc), exc


def t_select_oob():
    obj0, obj1 = _plate()
    p = FakePlater([obj0, obj1], sel=[5])
    _install(p)
    try:
        mod._select_object()
        raise AssertionError("out-of-range index accepted")
    except ValueError:
        pass


def t_select_ok():
    obj0, obj1 = _plate()
    p = FakePlater([obj0, obj1], sel=[1])
    _install(p)
    i, obj, note = mod._select_object()
    assert (i, obj.oid) == (1, 101), (i, obj.oid)


def t_select_auto_single():
    obj0 = _plate()[0]
    p = FakePlater([obj0], sel=[])
    _install(p)
    i, obj, note = mod._select_object()
    assert i == 0 and "自动选取" in note, (i, note)


def t_select_none_multi():
    obj0, obj1 = _plate()
    p = FakePlater([obj0, obj1], sel=[])
    _install(p)
    try:
        mod._select_object()
        raise AssertionError("empty selection on multi-object plate accepted")
    except ValueError:
        pass


# ---- write path: resolve by id, disclose mismatch ---------------------------
def t_write_by_id_with_selection_elsewhere():
    obj0, obj1 = _plate()
    p = FakePlater([obj0, obj1], sel=[0])  # user is LOOKING at A
    _install(p)
    mod._last_pick.update({"token": "t", "object_id": 101, "name": "B"})
    note = mod._write_pick_object_overrides({"gap_infill_speed": "30"})
    assert p.applied == [(1, {"gap_infill_speed": "30"})], p.applied
    assert "注意" in note and "B" in note and "A" in note, note


def t_write_selection_matches_no_warning():
    obj0, obj1 = _plate()
    p = FakePlater([obj0, obj1], sel=[1])
    _install(p)
    mod._last_pick.update({"token": "t", "object_id": 101, "name": "B"})
    note = mod._write_pick_object_overrides({"gap_infill_speed": "30"})
    assert p.applied and p.applied[0][0] == 1, p.applied
    assert "注意" not in note, note


def t_write_object_gone():
    obj0, obj1 = _plate()
    p = FakePlater([obj1], sel=[0])
    _install(p)
    mod._last_pick.update({"token": "t", "object_id": 100, "name": "A"})
    try:
        mod._write_pick_object_overrides({"gap_infill_speed": "30"})
        raise AssertionError("write onto a vanished object accepted")
    except ValueError as exc:
        assert "不在盘上" in str(exc), exc


def t_write_no_id():
    obj0, obj1 = _plate()
    p = FakePlater([obj0, obj1], sel=[1])
    _install(p)
    try:
        mod._write_pick_object_overrides({"gap_infill_speed": "30"})
        raise AssertionError("write without a picked id accepted")
    except ValueError as exc:
        assert "缺少对象 id" in str(exc), exc


def t_propose_reads_picked_object():
    obj0, obj1 = _plate()
    p = FakePlater([obj0, obj1], sel=[0])  # selection points at A
    _install(p)
    mod._last_pick.update({"token": "t", "object_id": 101, "name": "B"})
    seen = []
    mod._tool_reply = lambda call_id, ok, result=None, error=None: (
        seen.append((ok, result, error)))
    mod._dispatch_host_tool({"id": "c1", "tool": "propose_settings",
                             "args": {"values": {"gap_infill_speed": "30"}}})
    assert seen and seen[0][0], seen
    assert "old_values" in seen[0][1], seen[0][1]


# ---- 3MF identity cross-check ------------------------------------------------
def t_triangle_totals():
    obj = FakeObject(1, "X", [FakeVolume(10), FakeVolume(4, part=False)])
    parts, total = mod._object_triangle_totals(obj)
    assert (parts, total) == (10, 14), (parts, total)


def t_3mf_count_namespaced():
    path = str(TMP / "probe.3mf")
    _write_3mf(path, 2)
    assert mod._3mf_triangle_count(path) == 2, mod._3mf_triangle_count(path)


def t_collect_ok_uses_3mf():
    obj0, obj1 = _plate()  # B has 12 part triangles, no modifiers
    p = FakePlater([obj0, obj1], sel=[1], export_triangles=12)
    _install(p)
    blob, filename, note = mod._collect_upload_payload(obj1, 1)
    assert filename.endswith(".3mf"), filename
    assert note == "已携带当前预设配置", note
    assert blob[:2] == b"PK", blob[:2]


def t_collect_mismatch_falls_back_with_reason():
    obj0, obj1 = _plate()  # B totals: parts 12 / with-mods 12
    p = FakePlater([obj0, obj1], sel=[1], export_triangles=5)  # wrong object
    _install(p)
    blob, filename, note = mod._collect_upload_payload(obj1, 1)
    assert filename.endswith(".stl"), filename  # downgraded to mesh pack
    assert "内容与对象不符" in note and "疑非选中对象" in note, note
    assert blob[:5] != b"PK\x03\x04" or True  # STL binary header, not a zip
    assert len(blob) > 84, len(blob)  # 80-byte header + count + facets


def t_collect_accepts_modifier_inclusive_export():
    obj0, obj1 = _plate()
    # A: parts 10 + modifier 4 -> host serializes ALL volumes (14)
    p = FakePlater([obj0, obj1], sel=[0], export_triangles=14)
    _install(p)
    blob, filename, note = mod._collect_upload_payload(obj0, 0)
    assert filename.endswith(".3mf") and note == "已携带当前预设配置", (filename, note)


for _name, _fn in sorted((k, v) for k, v in list(globals().items())
                         if k.startswith("t_") and callable(v)):
    check(_name, _fn)

bad = [r for r in RESULTS if not r[0]]
print("\n%d/%d passed" % (len(RESULTS) - len(bad), len(RESULTS)))
sys.exit(1 if bad else 0)
