# Agent Ambient Grounding — 用户对引擎无感知（v0.12.0 / UI 0.43.0）

日期：2026-10-30
状态：已实现（插件 v0.12.0 / UI 0.43.0，三线并行 + 集成，同日）
前置：2026-10-28-orca-embedded-agent-design.md（agent 骨架）、2026-10-28-orca-embedded-agent-phase1.md
宿主面权威：orca 仓 `docs/plugins/API_REFERENCE.md` §3（API_VERSION 6，批 7；本引用以该节为准）

## 1. 背景与问题

事故回放（2026-10-30 会话）：agent 向用户确认"是不是 PLA？用的材料是 PLA 吗？"——
而引擎报告 input 节里 material PLA、220/65 等实值一直可读。用户反问"是不是 pla
你自己不会读耗材？"。

根因三缺口（皆有代码事实）：

| 缺口 | 事实 |
|---|---|
| 默认视野无实值 | `_chat_facts`（server.py:456-515）只含模型/SF/结论/警告/建议/阈值，无 input；冷启动更只有一句"还没有分析报告" |
| 可查目录不明 | input 节可经 `get_report_section` 读（agent_tools.py:358），但没有任何规则把"材料在 input 节"告诉模型 |
| 死胡同无指路牌 | `read_object_config`（agent_tools.py:373）返回 null=继承预设，null 之后无下一步指引 |

同时提示词规则 4（agent_harness.py:137）允许"列出最多 3 个要确认的问题"而无
"数据优先"闸门——数据可答的事实（材料）与真正的意图问题（受力件还是形貌）被打包
成同一条确认。

## 2. 目标 / 非目标

目标：

- G1 冷启动零工具调用即知盘面实值（材料/温度/工艺/对象/盘面）。
- G2 模型对"能查到什么"有完整目录，且目录与报告本体**同源派生**（引擎加节自披露，
  不靠手维护文案）。
- G3 用户侧文本零引擎痕迹：内部机制词不进回复；防火墙=**翻译**而非隐藏（"你怎么
  知道的"要能用打印工坊语言溯源）。
- G4 缺数据自愈：报告缺失/会话失效时模型自己补跑，不把内部错误转述给用户。
- G5 环境变化主动披露：上次分析后预设变了，开场一行提醒（diff 代码算，模型照读）。

非目标（→ §9 ROADMAP）：跨会话用户画像；批量多对象任务模式；打印机状态域；
系统级 push_notification 提醒；心跳保活；audit 词表自动派生。

## 3. 架构总览

三层分离：

```
用户看到的：  "是 PLA，220/65 正合适，不用动温度"        ← 打印工坊语言
agent 视野：  盘面卡 + 输入行 + 可查目录 + 工具面（内部）  ← 知道自己能查什么
底层数据：    引擎报告 / Orca 宿主状态 / G-code（纯 tool） ← 不出现在对话里
```

路由选型（已定）：**事件驱动推送**。`facts_fn` 是纯服务端函数（server.py:768 →
`_tool_get_analysis`），无宿主桥，轮开始不可能"拉"宿主——插件在 lifecycle 事件时
把"环境卡"推给服务端缓存，facts 注入。冷启动零调用即达（缓存命中），新鲜度由事件
保证；被拒的 B 案（卡片缓存进会话+失效机制）正是事件模型免掉的东西。

## 4. 插件侧：事件订阅与卡片推送（stratum_orca.py）

- `StratumPanel` 实现 `on_lifecycle_event`，只筛卡相关事件：预设 2、对象 5、盘 4、
  项目 open/new/close。切片/设备/上传任务事件不订阅。
- **合并窗** ~500ms：arrange/载入会突发大量对象事件，攒一波刷新一次（合并窗逻辑
  拆纯函数可测）。
- 卡组装（UI 线程，与 `_print_context` 同纪律）拆成**注入依赖的纯函数**
  `_assemble_env_card(plater, bundle)`：
  - 对象摘要：现 `_print_context`（stratum_orca.py:1223）的对象清单 + 选中态；
  - 工艺实值 ~10 键：`get_effective_config()` 优先，`preset_bundle()` 读侧兜底
    （读侧已有先例：stratum_orca.py:978、1498）——材料、喷嘴/热床温度、层高、
    喷嘴径、壁数、填充密度/图案、速度、风扇；
  - 耗材**槽位列表**（`preset_bundle().filaments` 复数；多材料 3MF 按槽分析，
    只带槽 1 会瞎）；
  - 当前盘号 + 每盘对象数概览（plate 模块现成）；
  - 组装时顺读一次 `slice_state`：卡带"切片中/空闲"**状态词**（不带进度数字，
    进度属于 UI 不属于 grounding）。
- 推送 `POST /api/env_card`（127.0.0.1，`X-Stratum-UI` 头，沿用现有纪律）：
  fire-and-forget，溢出可丢——卡片是幂等全量刷新，丢了由下一个事件或引导推送自愈。
- 插件启动补一次**引导推送**（挂现有 `_probe_when_ready` 钩子，plater 就绪后）。
- **实现期验证点**（不阻塞本 spec）：`ScriptPluginCapabilityBase` 是否把 lifecycle
  分发到 `on_lifecycle_event`（PythonPluginBase 契约含它，API_VERSION 6）；若不
  转发，调整注册路径，结论回填本节。

## 5. 服务端：卡片缓存与事实块重构（server.py）

- 全局单例卡片缓存 `{card, pushed_at, event}`（单 plater，不分会话）。
  `pushed_at` 只作元数据，**不进 facts**（时间差换算违反数字逐字纪律；新鲜度用
  触发事件名披露）。
- 新端点 `POST /api/env_card`：校验头、整体替换缓存、返回 ok。
- **无卡自愈**：服务端发现缓存空时，经现有面板桥命令通道向插件发一次"刷新并推送"
  （复用 tool 通道消息，不引入心跳）。
- `_chat_facts` 新布局（值一律 `json.dumps` 拼写 → audit 白名单依构造生效）：

```
模型: <上次分析对象>
盘面(实时): 材料 PLA，喷嘴 220，热床 65，层高 0.16，壁 2，填充 15 gyroid，速度 50，
  风扇 100（对象 3 选中 1，盘 1/2，切片中）
环境已变: 喷嘴温度 220→210   ← 仅当卡与报告 input 分歧时代码算出；无分歧无此行
输入(上次分析实收): …        ← 有报告才有；与盘面行来源标明
可查分节: input(材料/温度/工艺实值)、phase_a(几何/悬垂/桥接)、…   ← §6 派生
<现有行：SF / 结论 / 警告 / 建议 / G-code 调优 / 参考阈值>
```

- 降级梯：缓存无卡 → facts 注明"盘面卡未上线"，prompt 退回 `get_print_context`
  现取（同步轻读，A 路径保留）；standalone 服务（无插件）天然走此梯。
- 分歧 diff **在代码里算**：比较卡工艺键与报告 input 对应键，仅输出变化的
  "键 a→b" 行；模型不做比较运算。卡工艺键 ↔ 报告 input 键的映射表与 §6
  REPORT_SECTIONS 同处声明、同测试锚（见 §9）。

## 6. 报告侧单一源（agent_tools.py）

- 顶部定义 `REPORT_SECTIONS = {name: 领域语言释义}` 一份：
  - `get_report_section` 的 enum 从它派生；
  - facts 目录行 import 同一份：报告**实有**顶层键 ∩ 目录表逐项列出；报告有、
    目录表没有的键归入"另有未编目分节"（引擎加节自动浮出，防腐化）；
  - drift-guard 测试钉死 `enum == REPORT_SECTIONS.keys()`。
- `read_object_config` 描述与返回 note 加指路牌：null=继承预设，预设解析后的实值
  看事实块"盘面/输入"行或 `get_report_section(input)`。
- **工具描述改"何时用我"口吻**（路由表语义）：如 `get_report_section` →
  "要查材料/温度/工艺实值或报告细节时用"。注意：五个 v0.9 工具描述与 codex 文本轨
  byte-parity 被测试钉死（agent_tools.py:273-275 注释、test_agent.py §2）——改
  措辞是**有意的解冻**，同一提交内更新双侧与 parity 测试期望，冻结纪律本身保留。

## 7. prompt 规则（agent_harness.py:124-159 与 server.py:387-424 孪生同步）

1. **数据优先**：事实块/工具可答的（材料、温度、参数现值）不得列为确认问题；
   确认问题仅限使用意图类（受力还是形貌、装配要求等）。
2. **词汇防火墙=翻译**：内部机制词（引擎、报告、分节、schema、事实块、键、null、
   工具名）不进回复；被问"你怎么知道的"时用打印语言溯源（"看了你当前的预设"）。
3. **自愈**：工具返回"还没有报告/会话失效"类错误 → 先自己调 run_analysis 补跑
   （每轮 1 次上限既有）；重跑用一句人话预告（"我先算一下"）。Orca 侧确实没选
   模型时才用一句话告诉用户缺什么，不转述内部错误原文。
4. **双源新鲜度**：问"现在/当前"引盘面(实时)行，问"上次分析/结果"引输入行；
   "环境已变"行存在且影响结论时，如实说明并提议重跑。
5. **冷启动**：无报告且有盘面卡时，盘面/材料/工艺问题直接答，不必跑分析。

audit 扩展：内部术语**只计数不剥离**的封闭词表遥测（事实块/分节/schema 等），
随 `stripped` 一起上报，观察泄漏率后再决定是否硬化。

## 8. 测试与验收

server（test_agent.py / test_smoke.py）：
- facts 冷启动（有卡/无卡）与热启动锚；目录派生锚（删一节 → 行变；未编目键浮出）；
- `enum == REPORT_SECTIONS.keys()` drift guard；
- 两处孪生 prompt 含五条规则的锚；parity 测试期望更新；
- audit 术语计数行为；`/api/env_card` 端点（头校验/整体替换）；
- 环境已变行：卡与 input 构造分歧 → 行出现；无分歧 → 无行。

插件（test_chain.py）：
- `_assemble_env_card` 注入假 plater/bundle 的纯函数单测（十键/槽位/盘概览/
  slice_state 状态词）；
- 合并窗纯函数单测。

端到端验收判据（事故回放）：同一场景问"材料是什么/是不是 PLA"——模型零确认
问题、直接答 PLA；冷启动（新会话、无报告）同样零调用直接答。

版本与文档：v0.12.0 / UI 0.43.0，changelog 记"agent ambient grounding"。

## 9. 风险与开放问题

- lifecycle 分发路径（§4 验证点）——实现首日 spike，结论回填。
- `get_effective_config` 多喷嘴/多槽语义（按槽?按当前挤出机?）——对照
  API_REFERENCE §3 实现，卡内键名如实标注槽位。
- 事件风暴极端情形（大项目载入）——合并窗 + 可丢推送已兜底；首版观察日志。
- 双源分歧的键名映射（卡工艺键 ↔ 报告 input 键）需一张显式映射表，随
  REPORT_SECTIONS 同处声明、同测试锚（编码对称：改一端必 grep 另一端）。

## 10. ROADMAP 去向（本仓 ROADMAP.md 记录）

跨会话用户偏好画像；批量多对象任务模式（run_analysis 预算放宽 + 任务队列）；
PrinterConnection 域开放后环境卡扩打印机状态；上传/任务 lifecycle 事件消费
（切片完成 → 自动挂 G-code 会话，与 L145 gcode 伴随融合）。
