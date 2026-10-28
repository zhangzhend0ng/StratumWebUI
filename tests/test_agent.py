#!/usr/bin/env python3
"""Agent 一期测试：注册表一致性 / 隔离红线 / harness 状态机 / HTTP 面。

Run: python tests/test_agent.py
脚本式（与 test_smoke.py 同约定），零第三方依赖。
"""
import http.client
import importlib.util
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

FAILURES = []
TOTAL = 0


def check(name, cond, detail=""):
    global TOTAL
    TOTAL += 1
    print("%-52s %s %s" % (name, "PASS" if cond else "FAIL",
                           detail if not cond else ""))
    if not cond:
        FAILURES.append(name)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def import_agent_tools():
    return _load_module(os.path.join(ROOT, "agent_tools.py"),
                        "agent_tools_under_test")


def import_agent_harness():
    return _load_module(os.path.join(ROOT, "agent_harness.py"),
                        "agent_harness_under_test")


_SRV = None


def import_server():
    """In-process server import for unit-level checks. Chat settings are
    pinned to a temp file FIRST so no test ever reads the machine's real
    chat_settings.json (an OpenAI key there would make tests hit the net)."""
    global _SRV
    if _SRV is not None:
        return _SRV
    settings = os.path.join(tempfile.gettempdir(), "stratum-agent-unit-chat.json")
    with open(settings, "w", encoding="utf-8") as fh:
        json.dump({"backend": "openai", "codex_bin": "", "cli_args": "",
                   "model": "unit-model", "api_base": "http://127.0.0.1:1/v1",
                   "api_key": "sk-unit", "extra_json": ""}, fh)
    os.environ["STRATUM_UI_CHAT_SETTINGS"] = settings
    os.environ["STRATUM_UI_NO_BROWSER"] = "1"
    sys.path.insert(0, ROOT)
    import server
    _SRV = server
    return _SRV


# ==== §1 registry ===========================================================

def test_registry(at):
    tools = at.TOOLS
    legacy = ["get_print_context", "run_analysis", "get_analysis",
              "read_gcode", "propose_settings"]
    for n in legacy:
        check("T1 %s 迁入注册表" % n, n in tools)
    fc = [t["function"]["name"]
          for t in at.fc_tools_array({"gcode_attached": True,
                                      "has_report": True})]
    expected = set(legacy) | {"what_if", "get_tier_comparison",
                              "read_object_config"}
    check("T1 FC 数组=legacy+3 新工具（fc 轨）", set(fc) == expected,
          str(sorted(set(fc) ^ expected)))
    listing = at.text_listing()
    for n in legacy:
        check("T1 文本清单含 %s" % n, ("- %s: " % n) in listing)
    check("T1 文本清单不含 FC-only 工具", "what_if" not in listing)
    for t in at.fc_tools_array({}):
        f = t["function"]
        check("T1 FC schema 非空 %s" % f["name"],
              isinstance(f["parameters"], dict)
              and f["parameters"].get("type") == "object")
    fc_nogcode = [t["function"]["name"]
                  for t in at.fc_tools_array({"gcode_attached": False})]
    check("T1 visibility 无 gcode 藏 read_gcode", "read_gcode" not in fc_nogcode)
    fc_gcode = [t["function"]["name"]
                for t in at.fc_tools_array({"gcode_attached": True})]
    check("T1 visibility 有 gcode 现 read_gcode", "read_gcode" in fc_gcode)
    fc_noreport = [t["function"]["name"]
                   for t in at.fc_tools_array({"has_report": False})]
    check("T1 visibility 无报告藏 what_if", "what_if" not in fc_noreport)
    check("T1 run_analysis cap=1", tools["run_analysis"].per_turn_call_cap == 1)
    check("T1 propose_settings cap=1",
          tools["propose_settings"].per_turn_call_cap == 1)
    check("T1 what_if cap=1", tools["what_if"].per_turn_call_cap == 1)
    check("T1 无 cap 默认 0",
          tools["get_tier_comparison"].per_turn_call_cap == 0)
    writers = [n for n, d in tools.items() if not d.read_only]
    check("T1 read_only=False 仅 propose_settings", writers == ["propose_settings"],
          str(writers))
    check("T1 freshness 默认 session",
          all(d.freshness == "session" for d in tools.values()))
    ok, err = at.validate_args("read_gcode", {"head_lines": 40, "tail_lines": 40})
    check("T1 read_gcode 合法入参过", ok, err)
    ok, err = at.validate_args("read_gcode", {"head_lines": 999})
    check("T1 read_gcode 越界被拒", not ok, err)
    ok, err = at.validate_args("read_gcode", {"bogus": 1})
    check("T1 read_gcode 多余键被拒", not ok, err)
    ok, err = at.validate_args("propose_settings", {})
    check("T1 propose_settings 缺 values 被拒", not ok, err)
    ok, err = at.validate_args("propose_settings", {"values": {}})
    check("T1 propose_settings 空 values 被拒", not ok, err)
    ok, err = at.validate_args("no_such_tool", {})
    check("T1 未知工具被拒", not ok, err)
    ok, err = at.validate_args("read_object_config", {"keys": ["walls"]})
    check("T1 read_object_config 合法入参过", ok, err)
    ok, err = at.validate_args("read_object_config", {"keys": []})
    check("T1 read_object_config 空键表被拒", not ok, err)
    text, cut = at.truncate_result("get_tier_comparison", {"x": "a" * 9999})
    check("T1 result_budget 截断+披露",
          cut and len(text) <= at.TOOLS["get_tier_comparison"].result_budget + 60
          and "截断" in text)
    text2, cut2 = at.truncate_result("get_tier_comparison", {"x": 1})
    check("T1 小结果不截断", not cut2 and text2 == '{"x": 1}')


def main():
    at = import_agent_tools()
    test_registry(at)
    print("\n%d/%d checks passed%s" % (TOTAL - len(FAILURES), TOTAL,
          "" if not FAILURES else " — failed: %s" % ", ".join(FAILURES)))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
