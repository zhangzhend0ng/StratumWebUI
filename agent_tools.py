"""Stratum agent tool registry — the single source of truth for every tool
the conversational agent can call (spec §4).

One declaration here auto-generates: the OpenAI function-calling `tools`
array, the legacy text-protocol listing (frozen codex track), the server/
host dispatch metadata, per-tool JSON-Schema argument validators, and the
result budget applied when feeding results back to the model.

RED LINE (spec §2): this module and agent_harness.py must never import or
reference the plugin entry module or any orca host symbol (the grep
red-line test forbids even naming it here). Host-side handlers are INJECTED
as callables by the plugin entry (register_host_handler); server-side
capabilities arrive as a ctx dict (init_server_ctx). tests/test_agent.py
greps this file to keep the boundary honest.

Track model: tracks=("fc","text") for the five v0.9 tools (the codex text
track is FROZEN — its listing must stay byte-identical, so new tools ride
the fc track only).
"""

import json


class ToolDecl(object):
    """One tool declaration. Fields the harness/dispatchers read:
    name, side ('server'|'host'), description (含使用纪律句，喂模型的
    唯一文案源), input_schema (JSON Schema 子集), read_only (False → 返回值
    必须是提案结构，红线测试断言), result_budget (回灌模型字符上限),
    visibility (可选 callable(ctx)->bool，按上下文藏工具), freshness
    ('session' — token 作用域即失效档位；FC 工具消息仅当轮构建，跨轮
    天然不复用), per_turn_call_cap (0=不限；收编页面防抖闸门), tracks
    ('fc'/'text' 协议轨), host_mode ('sync'=UI 线程同步返回 /
    'threaded'=处理函数自管线程与异步回复), handler (注入的实现)."""

    __slots__ = ("name", "side", "description", "input_schema", "read_only",
                 "result_budget", "visibility", "freshness",
                 "per_turn_call_cap", "tracks", "host_mode", "handler")

    def __init__(self, name, side, description, input_schema=None,
                 read_only=True, result_budget=3000, visibility=None,
                 freshness="session", per_turn_call_cap=0,
                 tracks=("fc", "text"), host_mode="sync"):
        self.name = name
        self.side = side
        self.description = description
        self.input_schema = input_schema or {"type": "object", "properties": {}}
        self.read_only = read_only
        self.result_budget = result_budget
        self.visibility = visibility
        self.freshness = freshness
        self.per_turn_call_cap = per_turn_call_cap
        self.tracks = tuple(tracks)
        self.host_mode = host_mode
        self.handler = None


TOOLS = {}  # insertion-ordered; the legacy five come FIRST (byte-parity)


def tool(name, side, description, **kw):
    decl = ToolDecl(name, side, description, **kw)
    TOOLS[name] = decl
    return decl


# ---- generated artifacts ----------------------------------------------------

def fc_tools_array(ctx=None):
    """OpenAI function-calling tools array, filtered by track + visibility.
    ctx keys used today: gcode_attached, has_report."""
    ctx = ctx or {}
    out = []
    for d in TOOLS.values():
        if "fc" not in d.tracks:
            continue
        if d.visibility is not None and not d.visibility(ctx):
            continue
        out.append({"type": "function", "function": {
            "name": d.name, "description": d.description,
            "parameters": d.input_schema}})
    return out


def text_listing():
    """Legacy text-protocol tool listing (codex track, frozen face)."""
    return "\n".join("- %s: %s" % (d.name, d.description)
                     for d in TOOLS.values() if "text" in d.tracks)


def text_registry():
    """Legacy ASSISTANT_TOOLS shape: {name: (side, description)}."""
    return {d.name: (d.side, d.description)
            for d in TOOLS.values() if "text" in d.tracks}


# ---- argument validation (JSON Schema subset) -------------------------------

_PY_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool}


def _type_ok(value, t):
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "boolean":
        return isinstance(value, bool)
    py = _PY_TYPES.get(t)
    return py is not None and isinstance(value, py)


def _validate(node, schema, path):
    if schema is None or schema is True:
        return None
    if not isinstance(schema, dict):
        return None
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(_type_ok(node, x) for x in types):
            return "%s 类型不符（需 %s）" % (path, "|".join(map(str, types)))
    if "enum" in schema and node not in schema["enum"]:
        return "%s 必须是 %s 之一" % (path, "|".join(map(str, schema["enum"])))
    if isinstance(node, dict):
        props = schema.get("properties") or {}
        for req in schema.get("required") or []:
            if req not in node:
                return "%s.%s 缺失（必填）" % (path, req)
        mp = schema.get("minProperties")
        if isinstance(mp, int) and mp > 0 and len(node) < mp:
            return "%s 至少需 %d 个键" % (path, mp)
        ap = schema.get("additionalProperties")
        for k in node:
            if k in props:
                err = _validate(node[k], props[k], "%s.%s" % (path, k))
                if err:
                    return err
            elif ap is False:
                return "%s.%s 不在允许的参数内" % (path, k)
            elif isinstance(ap, dict):
                err = _validate(node[k], ap, "%s.%s" % (path, k))
                if err:
                    return err
    if isinstance(node, list):
        items = schema.get("items")
        if isinstance(items, dict):
            for i, x in enumerate(node):
                err = _validate(x, items, "%s[%d]" % (path, i))
                if err:
                    return err
        mn, mx = schema.get("minItems"), schema.get("maxItems")
        if isinstance(mn, int) and len(node) < mn:
            return "%s 至少 %d 项" % (path, mn)
        if isinstance(mx, int) and len(node) > mx:
            return "%s 至多 %d 项" % (path, mx)
    if isinstance(node, (int, float)) and not isinstance(node, bool):
        mn, mx = schema.get("minimum"), schema.get("maximum")
        if isinstance(mn, (int, float)) and node < mn:
            return "%s 低于下限 %s" % (path, mn)
        if isinstance(mx, (int, float)) and node > mx:
            return "%s 超过上限 %s" % (path, mx)
    return None


def validate_args(name, args):
    """(ok, error) — contract edge: every tool call is schema-checked before
    its handler runs, on BOTH the server and host paths."""
    decl = TOOLS.get(name)
    if decl is None:
        return False, "unknown tool: %r" % (name,)
    if not isinstance(args, dict):
        return False, "args 必须是对象"
    err = _validate(args, decl.input_schema, "args")
    return (err is None), err


def truncate_result(name, result):
    """(json_text, cut_flag) — result_budget guard for the model feed. What
    the model sees is what the exit audit whitelists, so truncation happens
    HERE, once, for both consumers."""
    decl = TOOLS.get(name)
    budget = decl.result_budget if decl is not None else 3000
    text = json.dumps(result, ensure_ascii=False)
    if len(text) <= budget:
        return text, False
    return text[:budget] + "…(结果超长已截断；要细节请改用更窄的查询)", True


# ---- server-side execution (ctx injected by server.py) ----------------------

_CTX = None


def init_server_ctx(ctx):
    """server.py injects its capabilities ONCE (dict of callables/data).
    Keys consumed today: sessions, session_lock, facts(token),
    gcode_excerpt(token, head, tail), presets(), param_meta(),
    validate_env(env), run_analysis(session, params, env, persist=False)."""
    global _CTX
    _CTX = ctx


def server_tool_names():
    return [d.name for d in TOOLS.values() if d.side == "server"]


def run_server_tool(name, args, token):
    """Execute a server tool in-process → (ok, result|error_text). ValueError
    from a handler is the actionable-Chinese-error contract (stale token,
    no report, ...) and lands in the error channel, never a crash."""
    decl = TOOLS.get(name)
    if decl is None or decl.side != "server":
        return False, "%s 不是服务端工具" % (name,)
    ok, err = validate_args(name, args)
    if not ok:
        return False, err
    if decl.handler is None:
        return False, "%s 未注册实现（server ctx 未注入？）" % name
    try:
        return True, decl.handler(_CTX, args, token)
    except ValueError as exc:
        return False, str(exc)


# ---- host-side dispatch (handlers injected by the plugin entry) -------------

def register_host_handler(name, mode, fn):
    """The plugin entry registers ITS functions here at startup — the only
    direction across the red line that is allowed (callables in; the
    registry never reaches back into plugin/host symbols)."""
    TOOLS[name].handler = fn
    TOOLS[name].host_mode = mode


def dispatch_host(call, reply):
    """Generic host-tool executor, registry-driven (spec §4.5): replaces the
    old if-elif in the plugin entry's host dispatch. `reply` is the plugin's
    _tool_reply(call_id, ok, result, error). threaded handlers own their
    async reply (UI thread collects, worker posts)."""
    call = call or {}
    tid = str(call.get("id") or "?")
    name = call.get("tool")
    args = call.get("args") if isinstance(call.get("args"), dict) else {}
    decl = TOOLS.get(name)
    if decl is None or decl.side != "host":
        reply(tid, False, error="unknown host tool: %r" % (name,))
        return
    ok, err = validate_args(name, args)
    if not ok:
        reply(tid, False, error=err)
        return
    if decl.handler is None:
        reply(tid, False,
              error="host tool %s 未注册实现（插件侧未启动？）" % name)
        return
    if decl.host_mode == "threaded":
        try:
            decl.handler(tid, args, reply)  # owns its async reply
        except Exception as exc:  # noqa: BLE001 - sync-phase failure (e.g.
            # run_analysis's busy guard / invalid selection) must reach the
            # model as a tool error, never escape onto the UI thread
            reply(tid, False, error="%s: %s" % (type(exc).__name__, exc))
        return
    try:
        reply(tid, True, result=decl.handler(args))
    except Exception as exc:  # noqa: BLE001 - tool result line, never a crash
        reply(tid, False, error="%s: %s" % (type(exc).__name__, exc))


# ==== tool declarations ======================================================

# -- the five v0.9 tools: descriptions VERBATIM from server.py v0.39
#    ASSISTANT_TOOLS (byte-parity is test-asserted — the codex text track
#    is frozen). Declaration order = the old dict order.
tool("get_print_context", "host",
     "盘面对象清单（名称/实例/体积数/选中态）")

tool("run_analysis", "host",
     "对当前选中对象跑完整 Stratum 分析（真实引擎，重；每次提问至多调用 1 次）",
     per_turn_call_cap=1, host_mode="threaded")

tool("get_analysis", "server",
     "当前会话分析事实块（SF/结论/警告/建议/调优）")

tool("read_gcode", "server",
     "已挂载切片 G-code 的有界摘录，args={head_lines,tail_lines}（0-200）",
     input_schema={
         "type": "object",
         "properties": {
             "head_lines": {"type": "integer", "minimum": 0, "maximum": 200},
             "tail_lines": {"type": "integer", "minimum": 0, "maximum": 200}},
         "additionalProperties": False},
     visibility=lambda ctx: bool(ctx.get("gcode_attached")))

tool("propose_settings", "host",
     "生成对象参数修改提案：args={values:{键:值}}。只读比对不写入；"
     "面板向用户展示 diff，用户点「应用」后才真正写回",
     input_schema={
         "type": "object",
         "properties": {"values": {
             "type": "object", "minProperties": 1,
             "additionalProperties": {"type": ["string", "number", "boolean"]}}},
         "required": ["values"], "additionalProperties": False},
     read_only=False, per_turn_call_cap=1)

# -- phase-1 batch (fc track only; the codex text track is frozen)
tool("what_if", "server",
     "参数/服役条件假设重跑：args={params:{参数名:值}, env:{环境名:值}}，在"
     "最近一次分析的基线上叠加覆盖后真实重跑引擎（不是推算），返回前后对比"
     "（SF/结论/警告数）。改填充率/壁数/疲劳周期/服役温度/湿度等「会怎样」"
     "的问题用它；params 键与 env 键必须来自事实块或工具结果，不要虚构。",
     input_schema={
         "type": "object",
         "properties": {
             "params": {"type": "object"},
             "env": {"type": "object"}},
         "additionalProperties": False},
     per_turn_call_cap=1,
     tracks=("fc",),
     visibility=lambda ctx: bool(ctx.get("has_report")))

tool("get_tier_comparison", "server",
     "四个基线档位（安全/均衡/高速/外观）的参数对比表：各档 walls/infill/"
     "速度/层高等取值与适用场景。回答「安全档和均衡档差在哪/该选哪档」"
     "用它，不要凭记忆报数。",
     tracks=("fc",))

tool("read_object_config", "host",
     "读取选取对象当前的对象级参数配置：args={keys:[参数名]}（可选，缺省="
     "最近报告涉及的建议/非法键，至多 50 个）。返回 {键: 值}，null 表示该"
     "键无对象级覆盖（继承预设）。只读，不写入。",
     input_schema={
         "type": "object",
         "properties": {"keys": {
             "type": "array", "items": {"type": "string"},
             "minItems": 1, "maxItems": 50}},
         "additionalProperties": False},
     per_turn_call_cap=4,
     tracks=("fc",))


# ---- server tool implementations (ctx-injected; see init_server_ctx) --------

def _srv_get_analysis(ctx, args, token):
    ok, payload = ctx["facts"](token)
    if not ok:
        raise ValueError(payload)
    return payload


def _srv_read_gcode(ctx, args, token):
    ok, payload = ctx["gcode_excerpt"](
        token, args.get("head_lines", 40), args.get("tail_lines", 40))
    if not ok:
        raise ValueError(payload)
    return payload


def _srv_tier_comparison(ctx, args, token):
    return {"tiers": ctx["presets"]()}


def _param_in_range(meta_row, value):
    if meta_row["kind"] == "select":
        return value if value in meta_row["options"] else None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    if not (meta_row["min"] <= value <= meta_row["max"]):
        return None
    return value


def _srv_what_if(ctx, args, token):
    """Baseline = the session's last PERSISTED run (history tail); the
    overrides stack on top, then a REAL engine rerun (persist=False — a
    what_if must never masquerade as the user's analysis). All numbers in
    the reply are json verbatim from the two reports (engine is the single
    source of truth)."""
    with ctx["session_lock"]:
        sess = (ctx["sessions"] or {}).get(token) or {}
        report = sess.get("last_report")
        hist = list(sess.get("history") or [])
    if not report or not hist:
        raise ValueError("还没有分析会话——先 run_analysis 建立基线")
    meta = {m["name"]: m for m in ctx["param_meta"]()}
    params = dict(hist[-1].get("params") or {})
    for k, v in (args.get("params") or {}).items():
        if k not in meta:
            raise ValueError("unknown parameter: %r（键名取自事实块/报告 input 节）" % k)
        v2 = _param_in_range(meta[k], v)
        if v2 is None:
            raise ValueError("params.%s 的值 %r 超出 UI 域 %s..%s"
                             % (k, v, meta[k]["min"], meta[k]["max"]))
        params[k] = v2
    env = ctx["validate_env"](dict(hist[-1].get("env") or {}))
    env.update(ctx["validate_env"](args.get("env") or {}))

    def _pb(rep):
        pb = (rep or {}).get("phase_b") or {}
        return {"safety_factor": pb.get("safety_factor"),
                "safety_factor_envelope": pb.get("safety_factor_envelope"),
                "assessment": pb.get("assessment")}

    base = {"params": params, "env": env,
            "phase_b": _pb(report), "warnings": len(report.get("warnings") or [])}
    ok, payload = ctx["run_analysis"](sess, params, env)
    if not ok:
        raise ValueError(payload if isinstance(payload, str)
                         else json.dumps(payload, ensure_ascii=False))
    after = {"params": params, "env": env, "phase_b": _pb(payload),
             "warnings": len(payload.get("warnings") or []),
             "new_warnings": [w for w in (payload.get("warnings") or [])[:5]]}
    return {"baseline": base, "what_if": after,
            "note": "真实重跑引擎（非推算）；数字逐字来自两次报告"}


# bind server-tool handlers to their declarations
TOOLS["get_analysis"].handler = _srv_get_analysis
TOOLS["read_gcode"].handler = _srv_read_gcode
TOOLS["get_tier_comparison"].handler = _srv_tier_comparison
TOOLS["what_if"].handler = _srv_what_if
