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


# ==== §2 red lines ==========================================================

_FORBIDDEN = [r"stratum_orca", r"\borca\.host\b", r"^\s*import orca\b",
              r"^\s*from orca", r"^\s*import server\b", r"stratum_server"]


def test_red_lines():
    for fname in ("agent_tools.py", "agent_harness.py"):
        path = os.path.join(ROOT, fname)
        if not os.path.isfile(path):
            check("T2 红线 %s 存在且干净" % fname, False, "file missing")
            continue
        src = open(path, encoding="utf-8").read()
        for pat in _FORBIDDEN:
            check("T2 红线 %s 无 %s" % (fname, pat),
                  re.search(pat, src, re.M) is None)


_LEGACY_LISTING = """- get_print_context: 盘面对象清单（名称/实例/体积数/选中态）
- run_analysis: 对当前选中对象跑完整 Stratum 分析（真实引擎，重；每次提问至多调用 1 次）
- get_analysis: 当前会话分析事实块（SF/结论/警告/建议/调优）
- read_gcode: 已挂载切片 G-code 的有界摘录，args={head_lines,tail_lines}（0-200）
- propose_settings: 生成对象参数修改提案：args={values:{键:值}}。只读比对不写入；面板向用户展示 diff，用户点「应用」后才真正写回"""


def test_legacy_parity(at):
    check("T2 文本清单与 v0.39 字节等价", at.text_listing() == _LEGACY_LISTING,
          repr(at.text_listing()[:120]))
    reg = at.text_registry()
    check("T2 text_registry 形状=旧 ASSISTANT_TOOLS",
          list(reg.items()) == [
              ("get_print_context", ("host", "盘面对象清单（名称/实例/体积数/选中态）")),
              ("run_analysis", ("host", "对当前选中对象跑完整 Stratum 分析（真实引擎，重；每次提问至多调用 1 次）")),
              ("get_analysis", ("server", "当前会话分析事实块（SF/结论/警告/建议/调优）")),
              ("read_gcode", ("server", "已挂载切片 G-code 的有界摘录，args={head_lines,tail_lines}（0-200）")),
              ("propose_settings", ("host", "生成对象参数修改提案：args={values:{键:值}}。只读比对不写入；面板向用户展示 diff，用户点「应用」后才真正写回"))])


# ==== §3 event bus / tickets ================================================

def test_event_bus(ah):
    store = ah.Store()
    conv = store.create("q", None, [])
    check("T3 conv 创建可查", conv.id and store.get(conv.id) is conv)
    t1 = store.issue_ticket(conv.id)
    check("T3 ticket 一次性：首次消费成功", store.consume_ticket(t1) is conv)
    check("T3 ticket 一次性：二次消费失败", store.consume_ticket(t1) is None)
    t2 = store.issue_ticket(conv.id)
    check("T3 新票可用", store.consume_ticket(t2) is conv)
    e1 = conv.publish("turn_start", question="q")
    e2 = conv.publish("tool_done", tool="x", ok=True)
    check("T3 seq 单调", e2["seq"] == e1["seq"] + 1 == 2)
    check("T3 游标补拉只给更新的",
          [e["seq"] for e in conv.events_since(1)] == [2])
    check("T3 游标补拉全量",
          [e["seq"] for e in conv.events_since(0)] == [1, 2])
    slot = conv.reserve_host("call-1")
    check("T3 host 槽位初始无结果", slot["result"] is None)
    got = conv.resolve_host("call-1", True, result={"a": 1})
    check("T3 host 结果置位",
          got and slot["event"].is_set()
          and slot["result"] == {"ok": True, "result": {"a": 1}, "error": None})
    check("T3 未知 call_id 解析失败", conv.resolve_host("nope", True) is False)
    conv.created = time.time() - ah.CONV_TTL_S - 1
    conv.done = True
    store.sweep()
    check("T3 TTL 清扫过期会话", store.get(conv.id) is None)


# ==== §4 events channel gates (SSE + poll) ==================================

def start_server_for_agent(extra_env=None):
    port = free_port()
    env = dict(os.environ)
    env.update({"STRATUM_UI_NO_BROWSER": "1", "STRATUM_UI_PORT": str(port),
                "STRATUM_UI_LOG_DIR": os.path.join(tempfile.gettempdir(),
                                                    "stratum-agent-test-logs"),
                "STRATUM_UI_LOG_OPEN": "0"})
    env.update(extra_env or {})
    proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "server.py")],
                            env=env, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    deadline = time.time() + 25
    while time.time() < deadline:
        try:
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            c.request("GET", "/api/status")
            if c.getresponse().read():
                return proc, port
        except OSError:
            time.sleep(0.2)
    proc.kill()
    raise RuntimeError("agent test server did not come up")


def test_http_agent_channel():
    proc = port = None
    try:
        proc, port = start_server_for_agent()
        # 无效 ticket → 404 JSON（GET 无 UI 头要求，Host 门照常）
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", "/api/agent/events?ticket=deadbeef&cursor=0")
        r = conn.getresponse()
        body = json.loads(r.read())
        check("T4 无效 ticket 404", r.status == 404 and not body.get("ok"))
        # 非本机 Host → 403（同现有 GET 门）
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", "/api/agent/events?ticket=x",
                     headers={"Host": "evil.example.com"})
        r = conn.getresponse()
        check("T4 非本机 Host 403", r.status == 403)
        # resubscribe 未知会话 → ok:false
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("POST", "/api/agent/resubscribe",
                     body=json.dumps({"conv_id": "nope"}),
                     headers={"Content-Type": "application/json",
                              "X-Stratum-UI": "1"})
        r = conn.getresponse()
        body = json.loads(r.read())
        check("T4 resubscribe 未知会话 ok:false",
              r.status == 200 and not body.get("ok"))
        # host-result 未知会话 → ok:false（幂等，不炸）
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("POST", "/api/agent/host-result",
                     body=json.dumps({"conv_id": "nope", "id": "x",
                                      "ok": True}),
                     headers={"Content-Type": "application/json",
                              "X-Stratum-UI": "1"})
        r = conn.getresponse()
        body = json.loads(r.read())
        check("T4 host-result 未知会话 ok:false",
              r.status == 200 and body.get("ok") is False)
        # POST 门：缺 X-Stratum-UI 403
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("POST", "/api/agent/host-result",
                     body=json.dumps({}),
                     headers={"Content-Type": "application/json"})
        r = conn.getresponse()
        check("T4 host-result 缺 UI 头 403", r.status == 403)
    finally:
        if proc:
            proc.kill()


# ==== §5 turn machine (fake model_fn; no engine, no HTTP) ====================

class _FakeModel(object):
    def __init__(self, script):
        self.script = list(script)  # one dict consumed per SEND
        self.seen = []

    def __call__(self, messages, tools):
        self.seen.append((messages, tools))
        step = self.script.pop(0) if self.script else {"content": "兜底"}
        msg = dict(step)
        msg.setdefault("role", "assistant")
        return msg


def _fc_call(cid, name, args=None):
    return {"id": cid, "type": "function",
            "function": {"name": name,
                         "arguments": json.dumps(args or {})}}


_FAKE_ACTIONS = {"写回": "apply", "写入全局预设": "apply-global",
                 "切片评估": "slice", "选取模型": "pick"}


def _fake_actions_fn(text):
    """Mirror of server._parse_actions for the fake deps — run_turn's job
    under test is the WIRING (actions_fn output lands in the final event),
    the real parser stays server-side (covered by legacy parity)."""
    m = re.search(r"^\s*ACTIONS\s*[:：]\s*(.+)$", text, re.M)
    if not m:
        return text, []
    acts = [_FAKE_ACTIONS[t.strip()]
            for t in re.split(r"[,，、]", m.group(1).strip())
            if t.strip() in _FAKE_ACTIONS]
    return (text[:m.start()] + text[m.end():]).strip(), acts


def _mkdeps(ah, at, model):
    tier_calls = [0]

    def facts(token):
        return True, "模型: t\n参考阈值: 70 0.5 2 1 3"

    def run_server_tool(name, args, token):
        # no ctx on the under-test instance — answer the tier stub directly
        if name == "get_tier_comparison":
            tier_calls[0] += 1
            return True, {"tiers": [{"name": "safe"}]}
        return at.run_server_tool(name, args, token)

    return ah.TurnDeps(
        model_fn=model,
        tools_array_fn=lambda ctx: at.fc_tools_array(ctx),
        tool_ctx_fn=lambda token: {"gcode_attached": False, "has_report": True},
        facts_fn=facts,
        audit_fn=lambda text, base: (text, 0),
        actions_fn=_fake_actions_fn,
        run_server_tool=run_server_tool,
        tools_lookup=at.TOOLS,
        host_timeout_s=0.3)


def test_turn_final(ah, at):
    model = _FakeModel([
        {"content": None, "tool_calls": [_fc_call("t1", "get_tier_comparison")]},
        {"content": "结论：安全档最稳。\nACTIONS: 写回"},
    ])
    conv = ah.HARNESS_STORE.create("q", "tok", [])
    ah.run_turn(conv, _mkdeps(ah, at, model))
    types = [e["type"] for e in conv.events]
    check("T5 事件序: tool_done→final→turn_end",
          types == ["turn_start", "tool_done", "final", "turn_end"], str(types))
    fin = [e for e in conv.events if e["type"] == "final"][0]
    check("T5 final 过 ACTIONS 解析",
          fin["reply"] == "结论：安全档最稳。" and fin["actions"] == ["apply"],
          str(fin))
    check("T5 final 后会话关闭", conv.done)


def test_turn_budget(ah, at):
    model = _FakeModel([{"content": None,
                         "tool_calls": [_fc_call("t%d" % i,
                                                 "get_tier_comparison")]}
                        for i in range(20)])

    def run_server_tool(name, args, token):
        # no ctx on the under-test instance — answer tier calls directly
        if name == "get_tier_comparison":
            return True, {"tiers": [{"name": "safe"}]}
        return at.run_server_tool(name, args, token)

    conv = ah.HARNESS_STORE.create("q", "tok", [])
    deps = _mkdeps(ah, at, model)
    deps.run_server_tool = run_server_tool
    ah.run_turn(conv, deps)
    done = [e for e in conv.events if e["type"] == "tool_done"]
    fin = [e for e in conv.events if e["type"] == "final"]
    check("T5 调用数不超 MAX_CALLS", len(done) <= ah.MAX_CALLS, str(len(done)))
    check("T5 预算耗尽仍有披露 final",
          len(fin) == 1 and "上限" in fin[0]["reply"],
          str([f.get("reply") for f in fin]))


def test_turn_cap(ah, at):
    calls = [0]

    def run_server_tool(name, args, token):
        if name == "what_if":
            calls[0] += 1
            return True, {"note": "ok"}
        return at.run_server_tool(name, args, token)

    model = _FakeModel([{"content": None, "tool_calls": [
        _fc_call("a", "what_if"), _fc_call("b", "what_if")]},
        {"content": "两次都看完了"}])
    conv = ah.HARNESS_STORE.create("q", "tok", [])
    deps = _mkdeps(ah, at, model)
    deps.run_server_tool = run_server_tool
    ah.run_turn(conv, deps)
    check("T5 per_turn_call_cap=1 只执行一次", calls[0] == 1, str(calls[0]))
    msgs = model.seen[-1][0]
    tool_msgs = [m for m in msgs if m.get("role") == "tool"]
    check("T5 超帽调用收到停叫信号",
          any("不再重复" in (m.get("content") or "") for m in tool_msgs),
          json.dumps(tool_msgs, ensure_ascii=False)[:200])


def test_turn_host_loop(ah, at):
    model = _FakeModel([
        {"content": None, "tool_calls": [_fc_call("h1", "get_print_context")]},
        {"content": "盘上共 1 件"},
    ])
    conv = ah.HARNESS_STORE.create("q", "tok", [])

    def resolver():
        time.sleep(0.05)
        conv.resolve_host("h1", True, result={"objects": []})

    threading.Thread(target=resolver, daemon=True).start()
    ah.run_turn(conv, _mkdeps(ah, at, model))
    check("T5 host 回环置位后走到 final",
          any(e["type"] == "final" for e in conv.events))


def test_turn_host_timeout(ah, at):
    model = _FakeModel([
        {"content": None, "tool_calls": [_fc_call("h2", "get_print_context")]},
        {"content": "工具没回，我先说明"},
    ])
    conv = ah.HARNESS_STORE.create("q", "tok", [])
    deps = _mkdeps(ah, at, model)
    deps.host_timeout_s = 0.15
    ah.run_turn(conv, deps)
    msgs = model.seen[-1][0]
    tool_msgs = [m for m in msgs if m.get("role") == "tool"]
    check("T5 host 超时返回错误工具结果且会话不悬挂",
          conv.done and any("超时" in (m.get("content") or "")
                            for m in tool_msgs))


def test_turn_audit(ah, at):
    model = _FakeModel([{"content": "SF 是 9.9，阈值 70"}])
    conv = ah.HARNESS_STORE.create("q", "tok", [])
    deps = _mkdeps(ah, at, model)
    deps.audit_fn = lambda text, base: (text.replace("9.9", "□"), 1)
    ah.run_turn(conv, deps)
    fin = [e for e in conv.events if e["type"] == "final"][0]
    check("T5 终答走注入审计", "□" in fin["reply"] and fin["stripped"] == 1)


def test_lock_boundary(ah, at):
    """R6: 工具段不持 _CHAT_LOCK；模型段在锁内。工具走 server 侧注册表
    实例（ctx 只注入在 server.agent_tools 上）。"""
    srv = import_server()
    srv_agent = srv.agent_tools
    ok, payload = srv_agent.run_server_tool("get_tier_comparison", {}, "tok")
    check("T5 server 工具可执行（前置）", ok and "tiers" in payload)
    held = srv._CHAT_LOCK.acquire(timeout=1.0)
    check("T5 测试先抢到 _CHAT_LOCK", held)
    try:
        ok, payload = srv_agent.run_server_tool("get_tier_comparison", {},
                                                "tok")
        check("T5 持锁状态下 server 工具照常执行（工具段无锁）",
              ok and payload and "tiers" in payload)
    finally:
        srv._CHAT_LOCK.release()
    # 模型段在锁内：假 urlopen 记录锁态
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["locked"] = srv._CHAT_LOCK.locked()

        class _R(object):
            def read(self):
                return json.dumps(
                    {"choices": [{"message": {"content": "ok"}}]}).encode(
                        "utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return _R()

    orig = srv.urllib.request.urlopen
    srv.urllib.request.urlopen = fake_urlopen
    try:
        msg = srv._openai_complete_fc([{"role": "user", "content": "x"}],
                                      None)
        check("T5 模型 HTTP 段持 _CHAT_LOCK", seen.get("locked") is True)
        check("T5 FC 返回 message", msg.get("content") == "ok")
    finally:
        srv.urllib.request.urlopen = orig


def main():
    at = import_agent_tools()
    test_registry(at)
    test_red_lines()
    test_legacy_parity(at)
    ah = import_agent_harness()
    test_event_bus(ah)
    test_http_agent_channel()
    test_turn_final(ah, at)
    test_turn_budget(ah, at)
    test_turn_cap(ah, at)
    test_turn_host_loop(ah, at)
    test_turn_host_timeout(ah, at)
    test_turn_audit(ah, at)
    test_lock_boundary(ah, at)
    print("\n%d/%d checks passed%s" % (TOTAL - len(FAILURES), TOTAL,
          "" if not FAILURES else " — failed: %s" % ", ".join(FAILURES)))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
