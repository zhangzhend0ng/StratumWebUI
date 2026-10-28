#!/usr/bin/env python3
"""Unit tests for the v0.8 rejected-value repair (stratum_orca.py).

The plugin entry imports `orca` (host-only), so the module is copied to a
temp dir and imported with a stubbed orca; the host read path runs against
a fake preset bundle covering BOTH pybind binding shapes (method /
property) the plugin's callable-dance must survive. No network, no host.

Run: python packaging/orca-plugin/test_repair.py
"""
import importlib.util
import shutil
import sys
import tempfile
import types
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
TMP = Path(tempfile.mkdtemp(prefix="stratum-repair-test-"))
shutil.copy(HERE / "stratum_orca.py", TMP / "stratum_orca.py")
_orca_stub = types.ModuleType("orca")
# module-level class definitions / decorators need these attrs
_orca_stub.script = types.SimpleNamespace(ScriptPluginCapabilityBase=object)
_orca_stub.plugin = lambda *a, **k: (lambda f: f)
_orca_stub.base = object
sys.modules["orca"] = _orca_stub
_spec = importlib.util.spec_from_file_location("stratum_orca_uut", TMP / "stratum_orca.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

# Real engine output (iter 883, format_ignored_keys_warning — physical and
# advisory rejects share this wording; the rejected list is uncapped).
# Engine iter 886+ discloses the same rejects STRUCTURED in the report's
# top-level rejected_values field, so this prose line is now only the
# pre-iter-886 fallback fixture (see t_parse_legacy_fallback).
REAL_WARN = ("3mf project_settings: key 'gap_infill_speed' value '2504' "
             "rejected (out of range or unparsable); value not applied; "
             "key 'reduce_crossing_wall' value 'maybe' rejected "
             "(out of range or unparsable); value not applied; "
             "key 'skirt_loops' value '99' rejected (out of range or "
             "unparsable); value not applied;")

# Real engine output (iter 886, ER-1): rejected_values carries every reject
# the warnings prose discloses, with a machine-readable source. Sources
# observed: "project_settings" (3MF metadata) and "base-profile" (the
# server-side base-profile channel) — ALL are forwarded by the parser.
REAL_REJECTED = [
    {"key": "gap_infill_speed", "value": "2504",
     "reason": "above max 1000", "source": "project_settings"},
    {"key": "skirt_loops", "value": "99",
     "reason": "above max 10", "source": "project_settings"},
    {"key": "wall_loops", "value": "77",
     "reason": "out of range or unparsable (engine loader check)",
     "source": "base-profile"},
]


# ---- pure: parser ----------------------------------------------------------
def t_parse_structured():
    # ER-1 primary path: every entry forwarded, ALL sources included
    # (base-profile rejects are repaired like any other — the source is
    # disclosure, not a filter).
    got = mod._parse_rejected_keys({"rejected_values": REAL_REJECTED})
    assert got == {"gap_infill_speed": "2504", "skirt_loops": "99",
                   "wall_loops": "77"}, got


def t_parse_structured_shapes():
    # malformed entries are skipped fail-soft; a non-string value coerces
    # (the engine spells values as strings; numbers tolerated)
    got = mod._parse_rejected_keys({"rejected_values": [
        {"key": "skirt_loops", "value": "99"},
        {"key": None, "value": "1"}, "junk", {"value": "2"},
        {"key": "wall_loops", "value": 77}]})
    assert got == {"skirt_loops": "99", "wall_loops": "77"}, got
    # present-but-empty field is authoritative: no rejects, no prose fallback
    assert mod._parse_rejected_keys(
        {"rejected_values": [], "warnings": [REAL_WARN]}) == {}


def t_parse_legacy_fallback():
    # pre-iter-886 engines lack rejected_values -> warnings-regex fallback
    got = mod._parse_rejected_keys({"warnings": [REAL_WARN]})
    assert got == {"gap_infill_speed": "2504",
                   "reduce_crossing_wall": "maybe",
                   "skirt_loops": "99"}, got


def t_parse_dict_warning():
    # legacy fallback also accepts dict-shaped warnings
    got = mod._parse_rejected_keys({"warnings": [
        {"message": "key 'skirt_loops' value '99' rejected (x)"}]})
    assert got == {"skirt_loops": "99"}, got


def t_parse_no_match_and_shapes():
    assert mod._parse_rejected_keys({"warnings": ["别的提示"]}) == {}
    assert mod._parse_rejected_keys({"warnings": []}) == {}
    assert mod._parse_rejected_keys({}) == {}
    assert mod._parse_rejected_keys(None) == {}


# ---- pure: serialization ----------------------------------------------------
def t_serialize():
    s = mod._serialize_orca_value
    assert s("150,150") == "150,150"
    assert s(True) == "1" and s(False) == "0"
    assert s(20.0) == "20" and s(0.15) == "0.15"
    assert s(["150", "150"]) == "150,150"


# ---- pure: note -------------------------------------------------------------
def t_note():
    n = mod._repair_note([("skirt_loops", "99", "10")], [])
    assert "1 项" in n and "skirt_loops 99→10" in n and "出厂默认" in n, n
    n2 = mod._repair_note([], ["weird_key"])
    assert "未能修复 1 项" in n2 and "weird_key" in n2, n2
    assert mod._repair_note([], []) == ""


# ---- fake host: preset read -------------------------------------------------
class FakePresetMethod:
    """pybind method shape: is_default()/config_keys() are callables."""

    def __init__(self, name, is_default, cfg):
        self._n, self._d, self._c = name, is_default, cfg

    def name(self):
        return self._n

    def is_default(self):
        return self._d

    def config_keys(self):
        return list(self._c)

    def config_value(self, key):
        return self._c[key]


class FakePresetProp(FakePresetMethod):
    """pybind property shape: is_default/config_keys are plain attrs."""

    @property
    def is_default(self):
        return self._d

    @property
    def config_keys(self):
        return list(self._c)


class FakeColl:
    def __init__(self, presets):
        self._p = presets

    def size(self):
        return len(self._p)

    def preset(self, i):
        return self._p[i]


def _install_fake(preset_cls, cfg):
    presets = [preset_cls("0.06 Standard", False, {}),
               preset_cls("Default Setting", True, cfg)]
    fake = types.ModuleType("orca")
    host = types.SimpleNamespace(
        preset_bundle=lambda: types.SimpleNamespace(
            prints=FakeColl(presets)))
    fake.host = host
    mod.orca = fake


def _install_broken():
    def boom():
        raise RuntimeError("no preset surface")
    fake = types.ModuleType("orca")
    fake.host = types.SimpleNamespace(preset_bundle=boom)
    mod.orca = fake


CFG = {"gap_infill_speed": "150,150", "skirt_loops": 10,
       "reduce_crossing_wall": 0}
REJECTED = {"gap_infill_speed": "2504", "skirt_loops": "99",
            "reduce_crossing_wall": "maybe", "ghost_key": "?"}


def t_default_method_shape():
    _install_fake(FakePresetMethod, CFG)
    repairs, unrep = mod._factory_default_repairs(REJECTED, {})
    got = {k: (o, n) for k, o, n in repairs}
    # ghost_key absent from the default preset's config -> unrepairable
    assert set(got) == {"gap_infill_speed", "skirt_loops",
                        "reduce_crossing_wall"}, got
    assert unrep == ["ghost_key"], unrep
    assert got["gap_infill_speed"] == ("2504", "150,150")
    assert got["skirt_loops"] == ("99", "10")
    assert got["reduce_crossing_wall"] == ("maybe", "0")


def t_default_property_shape():
    _install_fake(FakePresetProp, CFG)
    repairs, unrep = mod._factory_default_repairs(REJECTED, {})
    assert {k for k, _o, _n in repairs} == {
        "gap_infill_speed", "skirt_loops", "reduce_crossing_wall"}


def t_suggestion_wins():
    _install_fake(FakePresetMethod, CFG)
    repairs, _ = mod._factory_default_repairs(
        REJECTED, {"skirt_loops": "10"})  # already suggested
    assert "skirt_loops" not in {k for k, _o, _n in repairs}


def t_broken_host_degrades():
    _install_broken()
    repairs, unrep = mod._factory_default_repairs(REJECTED, {})
    assert repairs == []
    assert set(unrep) == set(REJECTED), unrep


def t_no_default_preset():
    fake = types.ModuleType("orca")
    fake.host = types.SimpleNamespace(
        preset_bundle=lambda: types.SimpleNamespace(
            prints=FakeColl([FakePresetMethod("X", False, CFG)])))
    mod.orca = fake
    repairs, unrep = mod._factory_default_repairs(REJECTED, {})
    assert repairs == [] and set(unrep) == set(REJECTED)


def t_nothing_to_repair():
    _install_fake(FakePresetMethod, CFG)
    assert mod._factory_default_repairs({}, {"skirt_loops": "10"}) == ([], [])


# ---- global-preset commit: schema-drift self-healing ------------------------
class FakeTxn:
    def __init__(self, bad_keys):
        self.sets = []
        self._bad = set(bad_keys)

    def set(self, k, v):
        self.sets.append((k, v))

    def commit(self):
        if self._bad:
            bad = sorted(self._bad)[0]
            raise ValueError('Unknown process preset setting "%s"' % bad)
        return None


class FakeEditor:
    """begin_update() yields one txn per attempt; every key in bad_keys
    makes that attempt's commit fail naming the first bad key."""

    def __init__(self, plan):
        self._plan = list(plan)  # list of bad-key sets, one per attempt
        self.txns = []

    def begin_update(self):
        bad = self._plan.pop(0) if self._plan else set()
        txn = FakeTxn(bad)
        self.txns.append(txn)
        return txn


def t_commit_drift_dropped_and_retried():
    ed = FakeEditor([{"enable_overhang_bridge_fan"}, set()])
    values = {"skirt_loops": "10",
              "enable_overhang_bridge_fan": "1",
              "gap_infill_speed": "20"}
    applied, dropped = mod._commit_global_preset(ed, dict(values))
    assert dropped == ["enable_overhang_bridge_fan"], dropped
    assert set(applied) == {"skirt_loops", "gap_infill_speed"}, applied
    # two fresh transactions: failed attempt + clean retry
    assert len(ed.txns) == 2
    assert ("enable_overhang_bridge_fan", "1") in ed.txns[0].sets


def t_commit_non_drift_error_reraised():
    ed = FakeEditor([{"some_key"}, {"some_key"}])  # key NOT in values
    try:
        mod._commit_global_preset(ed, {"other": "1"})
    except ValueError as exc:
        assert "some_key" in str(exc)
    else:
        raise AssertionError("non-drift ValueError was swallowed")


def t_commit_all_dropped_converges():
    ed = FakeEditor([{"a"}, {"b"}, {"c"}])
    applied, dropped = mod._commit_global_preset(ed, {"a": "1", "b": "1", "c": "1"})
    assert applied == {} and sorted(dropped) == ["a", "b", "c"]


def t_commit_clean_first_try():
    ed = FakeEditor([set()])
    applied, dropped = mod._commit_global_preset(ed, {"skirt_loops": "10"})
    assert applied == {"skirt_loops": "10"} and dropped == []


# ---- pick upload payload: 3mf export preferred, STL fallback ---------------
class FakeObj:
    name = "测试件"


class FakePlaterExport:
    """plater with export_object_3mf writing a canned 3mf file."""

    def __init__(self, tmpdir):
        self._tmp = tmpdir
        self.calls = []

    def export_object_3mf(self, idx, path):
        self.calls.append((idx, path))
        with open(path, "wb") as fh:
            fh.write(b"PK-fake-3mf-with-project-settings")


def _install_plater(plater):
    fake = types.ModuleType("orca")
    fake.host = types.SimpleNamespace(plater=lambda: plater)
    mod.orca = fake


def t_upload_payload_3mf_preferred(tmpdir=None):
    # v0.9.1 contract: the export is identity-checked via triangle totals —
    # stub the two counters (their parsers are the engine-side layer's own
    # tests); matching numbers take the 3mf path, mismatch must degrade.
    import tempfile, os
    tmp = tmpdir or tempfile.mkdtemp(prefix="stratum-pick-test-")
    old_tmpdir = mod._TMP_BASE
    orig = (mod._object_triangle_totals, mod._3mf_triangle_count)
    mod._TMP_BASE = tmp
    try:
        mod._object_triangle_totals = lambda obj: (5, 7)
        mod._3mf_triangle_count = lambda path: 5
        plater = FakePlaterExport(tmp)
        _install_plater(plater)
        blob, filename, note = mod._collect_upload_payload(FakeObj(), 2)
        assert blob == b"PK-fake-3mf-with-project-settings", blob
        assert filename.endswith("测试件.3mf"), filename
        assert "已携带当前预设配置" in note
        assert plater.calls and plater.calls[0][0] == 2
        leftovers = [f for f in os.listdir(tmp) if f.startswith("pick_")]
        assert leftovers == [], leftovers
    finally:
        mod._TMP_BASE = old_tmpdir
        mod._object_triangle_totals, mod._3mf_triangle_count = orig


def t_upload_payload_identity_mismatch_degrades():
    # exported 3mf triangle count disagrees with the object -> STL fallback
    # with the mismatch reason disclosed (v0.9.1 never analyzes a silent
    # wrong object)
    import tempfile, os
    tmp = tempfile.mkdtemp(prefix="stratum-pick-mm-")
    old_tmpdir = mod._TMP_BASE
    orig = (mod._object_triangle_totals, mod._3mf_triangle_count,
            mod._collect_mesh_payload, mod._pack_binary_stl)
    mod._TMP_BASE = tmp
    try:
        mod._object_triangle_totals = lambda obj: (5, 7)
        mod._3mf_triangle_count = lambda path: 999
        mod._collect_mesh_payload = lambda obj: ([], None)
        mod._pack_binary_stl = lambda payload: b"PK-stl-bytes"
        _install_plater(FakePlaterExport(tmp))
        blob, filename, note = mod._collect_upload_payload(FakeObj(), 0)
        assert blob == b"PK-stl-bytes" and filename.endswith("测试件.stl")
        assert "内容与对象不符" in note and "未携带预设配置" in note, note
    finally:
        mod._TMP_BASE = old_tmpdir
        (mod._object_triangle_totals, mod._3mf_triangle_count,
         mod._collect_mesh_payload, mod._pack_binary_stl) = orig


def t_upload_payload_stl_fallback():
    # plater WITHOUT export_object_3mf + a stubbed mesh collector
    _install_plater(types.SimpleNamespace())
    orig = (mod._collect_mesh_payload, mod._pack_binary_stl)
    mod._collect_mesh_payload = lambda obj: ([], "忽略 1 个修饰/负体积")
    mod._pack_binary_stl = lambda payload: b"PK-stl-bytes"
    try:
        blob, filename, note = mod._collect_upload_payload(FakeObj(), 0)
        assert blob == b"PK-stl-bytes"
        assert filename.endswith("测试件.stl"), filename
        assert "未携带预设配置" in note and "忽略 1 个修饰/负体积" in note
    finally:
        mod._collect_mesh_payload, mod._pack_binary_stl = orig


for _name, _fn in sorted(
        ((k, v) for k, v in list(globals().items())
         if k.startswith("t_")), key=lambda kv: kv[0]):
    check(_name, _fn)

shutil.rmtree(TMP, ignore_errors=True)
_bad = [r for r in RESULTS if not r[0]]
print("%d/%d checks passed" % (len(RESULTS) - len(_bad), len(RESULTS)))
if _bad:
    sys.exit(1)
print("ALL GREEN")
