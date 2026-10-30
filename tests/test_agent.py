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
    # superset semantics: the phase-1 tools must be present; the registry
    # grows by design (one declaration per new tool) so a closed equality
    # would break on every legitimate addition
    check("T1 FC 数组含 legacy+3 新工具（fc 轨，超集）",
          expected <= set(fc), str(sorted(expected - set(fc))))
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
    # T10 acceptance assertions (red until the demo commit lands the tool)
    check("T10 get_report_section 已声明", "get_report_section" in tools)
    fc_all = [t["function"]["name"]
              for t in at.fc_tools_array({"gcode_attached": True,
                                          "has_report": True})]
    check("T10 FC 数组含 get_report_section", "get_report_section" in fc_all)
    ok, err = at.validate_args("get_report_section", {"section": "phase_b"})
    check("T10 get_report_section 合法枚举过", ok, err)
    ok, err = at.validate_args("get_report_section", {"section": "nope"})
    check("T10 get_report_section 非法枚举被拒", not ok, err)


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
    # isolate from THIS process's unit-test chat settings (import_server
    # pins STRATUM_UI_CHAT_SETTINGS globally — an inherited openai backend
    # would flip the degrade gates): default to a nonexistent path, which
    # _load_chat_settings answers with the codex-backend defaults.
    if not (extra_env or {}) .get("STRATUM_UI_CHAT_SETTINGS"):
        env["STRATUM_UI_CHAT_SETTINGS"] = os.path.join(
            tempfile.gettempdir(), "stratum-agent-nonexistent.json")
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


# ==== §6 end-to-end FC loop over HTTP (stub OpenAI) ==========================

class _StubOpenAI(object):
    """Serves /chat/completions with a scripted FC sequence."""

    def __init__(self, script=None):
        self.calls = []
        self.script = script or [
            {"choices": [{"message": {
                "role": "assistant", "content": None,
                "tool_calls": [{"id": "t1", "type": "function",
                                "function": {"name": "get_tier_comparison",
                                             "arguments": "{}"}}]}}]},
            {"choices": [{"message": {
                "role": "assistant",
                "content": "安全档壁多填充高，最稳。\nACTIONS: 写回"}}]},
        ]

    def handle(self, body):
        self.calls.append(body)
        return self.script.pop(0) if self.script else \
            {"choices": [{"message": {"role": "assistant", "content": "结束"}}]}


def _serve_stub(stub, port):
    import http.server

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n))
            out = json.dumps(stub.handle(body)).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _write_chat_settings(fname, api_base):
    path = os.path.join(tempfile.gettempdir(), fname)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"backend": "openai", "codex_bin": "", "cli_args": "",
                   "model": "stub-model", "api_base": api_base,
                   "api_key": "sk-test", "extra_json": ""}, fh)
    return path


def test_agent_start_gates():
    proc = port = None
    try:
        proc, port = start_server_for_agent()
        # 未配 OpenAI 后端（默认 codex 无 CLI）→ degrade，不建会话
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("POST", "/api/agent/start",
                     body=json.dumps({"question": "hi"}),
                     headers={"Content-Type": "application/json",
                              "X-Stratum-UI": "1"})
        r = conn.getresponse()
        body = json.loads(r.read())
        check("T6 start 无后端 degrade",
              r.status == 200 and body.get("ok") is False
              and body.get("degrade") is True and body.get("error"))
        # 空问题 400
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("POST", "/api/agent/start",
                     body=json.dumps({"question": "  "}),
                     headers={"Content-Type": "application/json",
                              "X-Stratum-UI": "1"})
        r = conn.getresponse()
        check("T6 start 空问题 400", r.status == 400)
        # 缺 UI 头 403
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("POST", "/api/agent/start",
                     body=json.dumps({"question": "hi"}),
                     headers={"Content-Type": "application/json"})
        r = conn.getresponse()
        check("T6 start 缺 UI 头 403", r.status == 403)
    finally:
        if proc:
            proc.kill()


def _poll_turn(port, ticket, cursor=0, timeout=20):
    events = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
        c.request("GET", "/api/agent/events?ticket=%s&cursor=%d&poll=1"
                  % (ticket, cursor))
        j = json.loads(c.getresponse().read())
        if not j.get("ok"):
            return events, j, ticket, cursor
        events += j.get("events") or []
        cursor = j.get("cursor") or cursor
        ticket = j.get("next_ticket") or ticket
        if j.get("done") and not j.get("events"):
            break
        time.sleep(0.3)
    return events, {"ok": True}, ticket, cursor


def test_e2e_fc_loop():
    stub = _StubOpenAI()
    stub_port = free_port()
    _serve_stub(stub, stub_port)
    settings = _write_chat_settings(
        "stratum-agent-e2e-chat.json", "http://127.0.0.1:%d/v1" % stub_port)
    proc = port = None
    try:
        proc, port = start_server_for_agent(
            {"STRATUM_UI_CHAT_SETTINGS": settings})
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
        conn.request("POST", "/api/agent/start",
                     body=json.dumps({"question": "安全档和均衡档差在哪"}),
                     headers={"Content-Type": "application/json",
                              "X-Stratum-UI": "1"})
        r = conn.getresponse()
        start = json.loads(r.read())
        check("T6 start ok+ticket",
              start.get("ok") and start.get("conv_id") and start.get("ticket"))
        events, j, _t, _c = _poll_turn(port, start["ticket"])
        types = [e["type"] for e in events]
        check("T6 轮询事件含 tool_done+final+turn_end",
              "tool_done" in types and "final" in types and "turn_end" in types,
              str(types))
        fin = [e for e in events if e["type"] == "final"][0]
        check("T6 final 动作解析", fin["actions"] == ["apply"], str(fin))
        check("T6 stub 收到 FC tools 数组",
              stub.calls and stub.calls[0].get("tools")
              and any(t["function"]["name"] == "get_tier_comparison"
                      for t in stub.calls[0]["tools"]))
        # resubscribe 换新票（游标补拉从 0 重放）
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("POST", "/api/agent/resubscribe",
                     body=json.dumps({"conv_id": start["conv_id"]}),
                     headers={"Content-Type": "application/json",
                              "X-Stratum-UI": "1"})
        j2 = json.loads(conn.getresponse().read())
        check("T6 resubscribe ok", j2.get("ok") and j2.get("ticket"))
        if j2.get("ok"):
            replay, _j3, _t2, _c2 = _poll_turn(port, j2["ticket"], cursor=0,
                                               timeout=5)
            check("T6 游标补拉重放全量事件", len(replay) == len(events),
                  "%d vs %d" % (len(replay), len(events)))
    finally:
        if proc:
            proc.kill()
        try:
            os.remove(settings)
        except OSError:
            pass


def test_sse_stream():
    """SSE: 逐帧 data: 到达，done 后连接关闭（spike 的 HTTP 层验证）。"""
    stub = _StubOpenAI(script=[{"choices": [{"message": {
        "role": "assistant", "content": "直接回答：稳。"}}]}])
    stub_port = free_port()
    _serve_stub(stub, stub_port)
    settings = _write_chat_settings(
        "stratum-agent-sse-chat.json", "http://127.0.0.1:%d/v1" % stub_port)
    proc = port = None
    chunk = b""
    try:
        proc, port = start_server_for_agent(
            {"STRATUM_UI_CHAT_SETTINGS": settings})
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
        conn.request("POST", "/api/agent/start",
                     body=json.dumps({"question": "q"}),
                     headers={"Content-Type": "application/json",
                              "X-Stratum-UI": "1"})
        start = json.loads(conn.getresponse().read())
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
        c.request("GET", "/api/agent/events?ticket=%s&cursor=0"
                  % start["ticket"])
        r = c.getresponse()
        check("T6 SSE Content-Type",
              "text/event-stream" in (r.getheader("Content-Type") or ""))
        buf = b""
        deadline = time.time() + 20
        while time.time() < deadline:
            chunk = r.read(256)
            if not chunk:
                break
            buf += chunk
            # keep draining past turn_end until the server closes the stream
        text = buf.decode("utf-8", "replace")
        check("T6 SSE 收到 data 帧(final)",
              "data:" in text and '"final"' in text, text[:200])
        check("T6 SSE done 后服务端断流", not chunk, "stream still open")
    finally:
        if proc:
            proc.kill()
        try:
            os.remove(settings)
        except OSError:
            pass


# ==== §7 plugin-side host dispatch (stubbed orca) ===========================

def test_host_dispatch():
    tmp = tempfile.mkdtemp(prefix="stratum-agent-plugin-")
    import shutil as _sh
    _sh.copy(os.path.join(ROOT, "packaging", "orca-plugin",
                          "stratum_orca.py"),
             os.path.join(tmp, "stratum_orca.py"))
    _sh.copy(os.path.join(ROOT, "agent_tools.py"),
             os.path.join(tmp, "agent_tools.py"))
    saved_modules = {k: sys.modules.pop(k, None)
                     for k in ("orca", "stratum_server",
                               "stratum_orca_under_test",
                               "agent_tools_plugin_under_test")}
    saved_path = list(sys.path)
    sys.path.insert(0, tmp)
    try:
        # --- orca host stub (test_selection.py pattern) ---
        orca_stub = types.ModuleType("orca")
        orca_stub.script = types.SimpleNamespace(
            ScriptPluginCapabilityBase=object)
        orca_stub.plugin = lambda *a, **k: (lambda f: f)
        orca_stub.base = object
        sys.modules["orca"] = orca_stub

        class FakeObject(object):
            def __init__(self, oid, name):
                self.oid, self.name = oid, name

            def id(self):
                return self.oid

            def instance_count(self):
                return 1

            def volume_count(self):
                return 2

            def facets_count(self):
                return 100

            def config_keys(self):
                return ["gap_infill_speed", "sparse_infill_density"]

            def config_value(self, k):
                return "20"

        objects = [FakeObject(7, "件A")]

        def fake_plater():
            return types.SimpleNamespace(
                model=lambda: types.SimpleNamespace(objects=lambda: objects),
                selected_object_indices=lambda: [0])

        orca_stub.host = types.SimpleNamespace(plater=fake_plater)

        # --- plugin module ---
        so = _load_module(os.path.join(tmp, "stratum_orca.py"),
                          "stratum_orca_under_test")
        replies = []
        so._panel = types.SimpleNamespace(
            post=lambda msg: replies.append(msg))

        # --- stratum_server stub: only .agent_tools is read by the plugin ---
        at = _load_module(os.path.join(tmp, "agent_tools.py"),
                          "agent_tools_plugin_under_test")
        srv_stub = types.SimpleNamespace(
            agent_tools=at, _sessions={}, _session_lock=threading.Lock())
        sys.modules["stratum_server"] = srv_stub
        so._register_host_tools(srv_stub)

        # 1) sync 工具 get_print_context 经注册表分派
        so._dispatch_host_tool({"id": "c1", "tool": "get_print_context",
                                "args": {}})
        check("T7 sync host 工具经注册表分派",
              replies and replies[-1]["command"] == "tool-done"
              and replies[-1]["ok"]
              and replies[-1]["result"]["objects"][0]["name"] == "件A",
              str(replies[-1] if replies else None))
        # 2) read_object_config（新工具；keys 显式）
        so._last_pick.update({"token": "tok", "object_id": 7, "name": "件A"})
        so._dispatch_host_tool({"id": "c5", "tool": "read_object_config",
                                "args": {"keys": ["gap_infill_speed"]}})
        check("T7 read_object_config 返回对象级配置",
              replies[-1]["ok"]
              and replies[-1]["result"]["values"] ==
              {"gap_infill_speed": "20"},
              str(replies[-1]))
        # 3) propose_settings 提案结构（R3 红线：read_only=False → 提案结构）
        so._dispatch_host_tool({"id": "c6", "tool": "propose_settings",
                                "args": {"values": {"gap_infill_speed": 30}}})
        res = replies[-1]
        check("T7 propose_settings 返回提案结构",
              res["ok"] and "old_values" in res["result"]
              and "note" in res["result"], str(res))
        # 3b) v0.11 提案值闸门：null/none/空串 文案值被拒（可操作错误）
        so._dispatch_host_tool({"id": "c7", "tool": "propose_settings",
                                "args": {"values": {"gap_infill_speed": "null"}}})
        check("T7 propose null 值被拒",
              replies[-1]["ok"] is False
              and "null" in replies[-1]["error"], str(replies[-1]))
        so._dispatch_host_tool({"id": "c8", "tool": "propose_settings",
                                "args": {"values": {"gap_infill_speed": " "}}})
        check("T7 propose 空串值被拒", replies[-1]["ok"] is False)
        # 4) 未知工具
        so._dispatch_host_tool({"id": "c2", "tool": "nope", "args": {}})
        check("T7 未知 host 工具错误回复",
              replies[-1]["ok"] is False
              and "unknown host tool" in replies[-1]["error"])
        # 5) 入参校验拒绝
        so._dispatch_host_tool({"id": "c3", "tool": "read_object_config",
                                "args": {"keys": []}})
        check("T7 host 入参 schema 拒绝",
              replies[-1]["ok"] is False and "keys" in replies[-1]["error"])
        # 6) run_analysis threaded 分支：非法选择 → 同步错误（不起线程）
        started = []
        orig_thread = so.threading.Thread

        class _T(orig_thread):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                started.append(a)

        so.threading.Thread = _T
        orca_stub.host = types.SimpleNamespace(
            plater=lambda: (_ for _ in ()).throw(ValueError("无选中对象")))
        so._dispatch_host_tool({"id": "c4", "tool": "run_analysis",
                                "args": {}})
        so.threading.Thread = orig_thread
        check("T7 run_analysis 非法选择→同步错误回复（未起线程）",
              replies[-1]["ok"] is False and not started,
              str(replies[-1] if replies else None))
        # 7) 版本号
        check("T7 插件版本 0.11.1",
              re.search(r'^# version = "0\.11\.1"$',
                        open(os.path.join(ROOT, "packaging", "orca-plugin",
                                          "stratum_orca.py"),
                             encoding="utf-8").read(), re.M) is not None)
    finally:
        sys.path[:] = saved_path
        for k, v in saved_modules.items():
            if v is not None:
                sys.modules[k] = v


# ==== §8 ER-4 proposal key-set invariant (engine iter-886 contract) ========

def _plugin_with_report(report, preset_cfg):
    """Load stratum_orca.py under the orca stub with `report` installed as
    the pick session's last_report (the same surface §7 builds) and a fake
    factory-default preset (test_repair.py shape) so rejected-key repairs
    can source defaults. Returns (module, restore_fn)."""
    tmp = tempfile.mkdtemp(prefix="stratum-agent-er4-")
    import shutil as _sh
    _sh.copy(os.path.join(ROOT, "packaging", "orca-plugin",
                          "stratum_orca.py"),
             os.path.join(tmp, "stratum_orca.py"))
    saved_modules = {k: sys.modules.pop(k, None)
                     for k in ("orca", "stratum_server",
                               "stratum_orca_er4")}
    saved_path = list(sys.path)
    sys.path.insert(0, tmp)

    class _Preset(object):
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

    class _Coll(object):
        def __init__(self, presets):
            self._p = presets

        def size(self):
            return len(self._p)

        def preset(self, i):
            return self._p[i]

    orca_stub = types.ModuleType("orca")
    orca_stub.script = types.SimpleNamespace(
        ScriptPluginCapabilityBase=object)
    orca_stub.plugin = lambda *a, **k: (lambda f: f)
    orca_stub.base = object
    orca_stub.host = types.SimpleNamespace(
        preset_bundle=lambda: types.SimpleNamespace(prints=_Coll([
            _Preset("0.06 Standard", False, {}),
            _Preset("Default Setting", True, preset_cfg)])))
    sys.modules["orca"] = orca_stub
    so = _load_module(os.path.join(tmp, "stratum_orca.py"),
                      "stratum_orca_er4")
    srv_stub = types.SimpleNamespace(
        _sessions={"er4tok": {"last_report": report}},
        _session_lock=threading.Lock())
    sys.modules["stratum_server"] = srv_stub
    so._last_pick.update({"token": "er4tok", "object_id": 1,
                          "name": "er4"})

    def restore():
        sys.path[:] = saved_path
        for k, v in saved_modules.items():
            if v is not None:
                sys.modules[k] = v
    return so, restore


def test_proposal_keyset():
    """ER-4 acceptance: 提案键集 = 有实值建议 ∪ rejected 键。

    The invariant asserted over _collect_suggestion_values (the write-back
    proposal collector): set(proposed keys) == (orca_suggestions items with
    recommended_value != null OR recommended_text present) ∪ (report
    rejected_values keys). LEGITIMATE DIVERGENCE (documented, not asserted
    here): a rejected key that cannot be sourced a factory default is
    disclosed in the repair note suffix and NOT proposed — never guessed —
    so the fixture makes every rejected key repairable and the equality is
    exact; the real-engine part below re-derives the expected side from
    the engine's own output (对拍)."""
    report = {
        "orca_suggestions": {"items": [
            {"parameter": "brim_width", "action": "set",
             "recommended_value": 20.0},
            {"parameter": "brim_type", "action": "set",
             "recommended_value": None,
             "recommended_text": "auto_brim"},
            {"parameter": "pressure_advance", "action": "note",
             "recommended_value": None},
        ]},
        "rejected_values": [
            {"key": "skirt_loops", "value": "99",
             "reason": "above max 10", "source": "project_settings"},
            {"key": "gap_infill_speed", "value": "2504",
             "reason": "above max 1000", "source": "base-profile"},
        ],
    }
    preset_cfg = {"skirt_loops": 10, "gap_infill_speed": "150,150"}
    so, restore = _plugin_with_report(report, preset_cfg)
    try:
        values, skipped, note = so._collect_suggestion_values()
        expected = ({"brim_width", "brim_type"}   # 有实值建议（值或 token）
                    | {"skirt_loops", "gap_infill_speed"})  # rejected 键
        check("T8 提案键集 = 有实值建议 ∪ rejected 键",
              set(values) == expected,
              "%s vs %s" % (sorted(values), sorted(expected)))
        check("T8 recommended_text 进提案（值逐字）",
              values.get("brim_type") == "auto_brim",
              repr(values.get("brim_type")))
        check("T8 note 项不进提案（披露为跳过）",
              skipped == ["pressure_advance"]
              and "pressure_advance" not in values, str(skipped))
        check("T8 rejected 键修复取出厂默认值",
              values.get("skirt_loops") == "10"
              and values.get("gap_infill_speed") == "150,150",
              "%r %r" % (values.get("skirt_loops"),
                         values.get("gap_infill_speed")))
        check("T8 修复披露进 note（不静默）",
              "skirt_loops 99→10" in note and "gap_infill_speed" in note,
              note)
    finally:
        restore()
    # 与引擎输出对拍：同一不变式对真引擎报告成立（sample STL 无拒收值，
    # rejected 侧为空 → 等式退化为建议侧，期望集逐项来自真报告）
    srv = import_server()
    tok = _upload_sample_session(srv)
    with srv._session_lock:
        real = srv._sessions[tok].get("last_report") or {}
    so, restore = _plugin_with_report(real, {})
    try:
        # point the plugin at the REAL server module + session
        sys.modules["stratum_server"] = srv
        so._last_pick["token"] = tok
        values, _skipped, _note = so._collect_suggestion_values()
        items = ((real.get("orca_suggestions") or {}).get("items")) or []
        expected = {i["parameter"] for i in items
                    if isinstance(i, dict) and i.get("parameter")
                    and (i.get("recommended_value") is not None
                         or i.get("recommended_text"))}
        expected |= set(so._parse_rejected_keys(real))
        check("T8 真引擎报告提案键集不变式", set(values) == expected,
              "%s vs %s" % (sorted(values), sorted(expected)))
    finally:
        restore()


# ==== §9 first-batch server tools over the REAL registry ctx ==============

def _upload_sample_session(srv):
    """上传 sample STL + 程序化跑一次分析建立基线（persist=True，真引擎）。"""
    with open(os.path.join(ROOT, "sample", "beam_100x10x4.stl"), "rb") as fh:
        blob = fh.read()
    tok = "agenttest" + secrets.token_hex(4)
    path = os.path.join(srv.WORK_DIR, tok + ".stl")
    with open(path, "wb") as fh:
        fh.write(blob)
    with srv._session_lock:
        srv._sessions[tok] = {"token": tok, "path": path, "name": "beam.stl",
                              "is_3mf": False, "writable": None,
                              "kind": "model"}
    ok, rep = srv.run_programmatic_analyze(srv._sessions[tok], {}, {},
                                           persist=True)
    assert ok, rep
    return tok


def test_first_batch_tools():
    srv = import_server()
    srv_agent = srv.agent_tools
    ok, payload = srv_agent.run_server_tool("get_tier_comparison", {}, None)
    check("T9 tier 对比表返回 4 档",
          ok and len(payload["tiers"]) == 4,
          str(payload)[:120] if ok else payload)
    ok, err = srv_agent.run_server_tool("what_if", {"params": {"walls": 4}},
                                        None)
    check("T9 what_if 无会话可操作错误", not ok and "分析会话" in err, str(err))
    tok = _upload_sample_session(srv)
    ok, err = srv_agent.run_server_tool("what_if",
                                        {"params": {"no_such_param": 1}},
                                        tok)
    check("T9 what_if 未知参数白名单拒绝",
          not ok and "unknown parameter" in err, str(err))
    ok, err = srv_agent.run_server_tool("what_if",
                                        {"params": {"infill": 999}}, tok)
    check("T9 what_if 越界值拒绝", not ok and "超出 UI 域" in err, str(err))
    with srv._session_lock:
        baseline_report = srv._sessions[tok].get("last_report")
    ok, res = srv_agent.run_server_tool("what_if",
                                        {"env": {"fatigue_cycles": 100000}},
                                        tok)
    check("T9 what_if 疲劳工况真实重跑成功",
          ok and res.get("what_if", {}).get("phase_b") is not None
          and res.get("baseline", {}).get("phase_b") is not None,
          str(res)[:160] if ok else str(res))
    with srv._session_lock:
        after_report = srv._sessions[tok].get("last_report")
    check("T9 what_if 不覆写会话报告（persist=False）",
          after_report is baseline_report)
    ok, err = srv_agent.run_server_tool("read_object_config", {}, tok)
    check("T9 read_object_config 服务端拒绝", not ok)


def test_report_section_tool():
    srv = import_server()
    srv_agent = srv.agent_tools
    ok, payload = srv_agent.run_server_tool("get_report_section",
                                            {"section": "phase_b"}, None)
    check("T10 get_report_section 无会话可操作错误",
          not ok and "还没有分析报告" in str(payload), str(payload))
    tok = _upload_sample_session(srv)
    ok, payload = srv_agent.run_server_tool("get_report_section",
                                            {"section": "phase_b"}, tok)
    check("T10 get_report_section 返回分节原文",
          ok and "phase_b" in payload and payload["phase_b"],
          str(payload)[:120] if ok else str(payload))
    ok, payload = srv_agent.run_server_tool("get_report_section",
                                            {"section": "calibration"}, tok)
    check("T10 get_report_section 缺节走可操作错误或整节返回",
          (not ok and "没有分节" in str(payload))
          or (ok and "calibration" in payload), str(payload)[:120])


# ==== §11 engine 0.28.0 wiring: session warm path, estimate, gcode tools ====

def test_engine_session_warm():
    srv = import_server()
    sess = srv.engine_session()
    check("T11 会话可用（capabilities 门控通过，引擎 0.28.0）", sess is not None)
    if sess is None:
        return
    r = sess.call("hello")
    check("T11 hello ok", bool(r.get("ok")), str(r)[:120])
    M = os.path.join(ROOT, "sample", "beam_100x10x4.stl")
    r1 = sess.call("analyze", model_path=M, params={}, env={})
    check("T11 会话分析 ok+schema4",
          r1.get("ok") and (r1.get("report") or {}).get("schema_version") == 4,
          str(r1)[:150])
    r2 = sess.call("analyze", model_path=M, params={"infill": 40}, env={})
    pb = (r2.get("report") or {}).get("phase_b") or {}
    check("T11 温跑第二次 ok+SF 在场",
          r2.get("ok") and pb.get("safety_factor") is not None)
    rb = sess.call("analyze", model_path="NOPE.stl", params={}, env={})
    check("T11 坏查询结构化错误且会话存活",
          (not rb.get("ok")) and isinstance(rb.get("error"), dict)
          and sess.call("hello").get("ok"))


def test_what_if_estimate_and_warm():
    srv = import_server()
    srv_agent = srv.agent_tools
    tok = _upload_sample_session(srv)
    ok, res = srv_agent.run_server_tool(
        "what_if", {"params": {"infill": 10}, "quick": True}, tok)
    check("T11 what_if quick 走估价档",
          ok and "估价" in str(res.get("note")), str(res)[:140])
    ok, res = srv_agent.run_server_tool(
        "what_if", {"params": {"infill": 40}}, tok)
    check("T11 what_if 全跑（会话温跑路径）",
          ok and "全量 FEM" in str(res.get("note")), str(res)[:140])


def _mk_gcode_upload_session(srv, fixture):
    import shutil as _sh
    t = "agentgc" + secrets.token_hex(4)
    p = os.path.join(srv.WORK_DIR, t + ".gcode")
    _sh.copy(os.path.join(ROOT, "test_data", "gcode", fixture), p)
    with srv._session_lock:
        srv._sessions[t] = {"token": t, "path": p, "name": fixture,
                            "is_3mf": False, "writable": None, "kind": "gcode"}
    return t


def test_gcode_agent_tools():
    srv = import_server()
    srv_agent = srv.agent_tools
    ok, err = srv_agent.run_server_tool("gcode_score", {}, None)
    check("T11 gcode_score 无会话可操作错误",
          not ok and "G-code" in str(err), str(err))
    # 模型会话 + 挂载切片 → score（缺省 token=对话会话）
    tok = _upload_sample_session(srv)
    with srv._session_lock:
        srv._sessions[tok]["gcode_path"] = os.path.join(
            ROOT, "test_data", "gcode", "a.gcode")
        srv._sessions[tok]["gcode_name"] = "a.gcode"
    ok, res = srv_agent.run_server_tool("gcode_score", {}, tok)
    check("T11 gcode_score 门面评分返回",
          ok and isinstance(res.get("overall_score"), (int, float)),
          str(res)[:150] if ok else str(res))
    check("T11 gcode_score ER-9 字段（L145 伴生）",
          ok and res.get("assessable") is True
          and res.get("schema_version") == "gcode-score-report/v1",
          str(res)[:120])
    # kind=gcode 上传会话 × 2 → diff（--structure 路径，sf_degenerate 对拍）
    ta = _mk_gcode_upload_session(srv, "a.gcode")
    tb = _mk_gcode_upload_session(srv, "b.gcode")
    ok, res = srv_agent.run_server_tool(
        "gcode_diff", {"token_a": ta, "token_b": tb}, None)
    check("T11 gcode_diff 门面差异返回", ok and isinstance(res, dict),
          str(res)[:150] if ok else str(res))
    ok, res = srv_agent.run_server_tool(
        "gcode_diff", {"token_a": _mk_gcode_upload_session(srv, "t_abs.gcode"),
                       "token_b": _mk_gcode_upload_session(srv, "t_dual.gcode"),
                       "structure": True}, None)
    sa = (res or {}).get("structure_a") if ok else None
    check("T11 gcode_diff --structure 带 sf_degenerate（L145）",
          ok and isinstance(sa, dict) and "sf_degenerate" in sa,
          str(res)[:150] if ok else str(res))


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
    test_agent_start_gates()
    test_e2e_fc_loop()
    test_sse_stream()
    test_host_dispatch()
    test_proposal_keyset()
    test_first_batch_tools()
    test_report_section_tool()
    test_engine_session_warm()
    test_what_if_estimate_and_warm()
    test_gcode_agent_tools()
    print("\n%d/%d checks passed%s" % (TOTAL - len(FAILURES), TOTAL,
          "" if not FAILURES else " — failed: %s" % ", ".join(FAILURES)))
    rc = 1 if FAILURES else 0
    # tear down the shared engine session (spawned subprocess) on exit
    try:
        if _SRV is not None and _SRV._ENGINE_SESSION is not None:
            _SRV._ENGINE_SESSION.shutdown()
    except Exception:
        pass
    return rc


if __name__ == "__main__":
    sys.exit(main())
