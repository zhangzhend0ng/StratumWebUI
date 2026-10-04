# Stratum-WebUI 路线图

> 建立于 2026-08-18，紧随当日 40 分钟对抗迭代会话（server 输入校验 + 请求闸两轮修复，
> 见 `loop-journal.md`）。契约证据来自 **引擎一手源探针**（`--schema` 机器可读输出、
> 无参 usage、JSON 报告全结构 dump），非文档转述。
>
> 用法：随迭代勾销 `- [ ]`；引用代码处用函数/符号名（行号会漂移）；契约证据表注明
> 版本，引擎升级时**必须重验**再沿用结论。0.24.0 重验记录见 v0.8 节。

## 0. 架构红线（所有方向不许破）

1. **零依赖**：Python stdlib + 自含 HTML UI（`index.html` + `report.js` / `stl-preview.js`，经典 script 标签、零构建链，无外部网络资源）。样式内联于 `index.html` 单 `<style>`（UI v3 起含设计令牌体系与旧令牌别名——JS 内联 `var()` 引用依赖别名存在，勿删）；后续若需本地静态资源（同目录文件、仍无 CDN/构建链）允许，但须同步 `server.py UI_STATIC` 白名单与 `packaging/StratumWebUI.spec` datas。
2. **引擎是唯一事实源**：Python/JS 不复制任何评分/钳制/锁定规则，只渲染引擎 JSON；
   UI 侧编排（多次调用、批量候选）不算复制规则。

## 1. 契约现状证据（【v0.8 已按引擎 0.24.0 重验，2026-08-28】）

| # | 发现 | 证据 | 含义 |
|---|---|---|---|
| E1 | 报告大量字段未被 UI 消费 | 【2026-08-19 已解决 + 0.24 新面已接】v0.8 接入 `machine_limits`/`mesh_topology`/热图/`fast_mode`/`input.layer_height_mm` 等新块；仍未消费：`est_error_profile`（需 `--est-error-profile`）、gcode 调优通道 | 核心产出均已入 UI |
| E2 | 参数面漂移 | 【0.24 重验】`--schema`（0.22+）成为一手源：12 pattern 值（含 legacy 拼写）、4 材料、11 机型、4 校验档；server 优先 `--schema` JSON，usage 正则降为旧引擎回退（`probe_schema`） | 结构化契约终结了正则解析时代 |
| E3 | lock 面远大于 UI 参数面 | 【0.24 重验】`lockable_parameters` 现含完整 Orca 键面（brim_width、pressure_advance…）；`layer_height` 已升级为滑杆（v0.8），从 lock-only 退役 | lock 复选框仍为类型闸不收紧白名单 |
| E4 | 引擎错误信息 doc 漂移 | 【0.24 未变】无参 usage 仍是发现面；`--schema` 出现后 UI 主路径已不依赖错误文本 | — |
| E5 | 【v0.8 新】schema v2→v3 破坏性变更 | 5 个不确定度字段 plain 名变标量、区间移入 `*_envelope` 孪生（`docs/schema/report-v3.md`）；`status:"validation_refused"/"cancelled"` 标记替换报告文件；`--force` 默认 10→100 N | 消费者 keyed on v2 会静默拿错类型——schema 闸 + numEnv 双形态是硬防线 |

## 2. 方向与里程碑（推荐序；决策点 D1 可能调整 2/3 顺序）

### v0.2 — 方向一：吃透现有契约（零引擎依赖，价值已实证）

- [x] a) **④ 分析结果面板扩容**（2026-08-19 会话 2-7）：屈曲 SF 与 buckling_warning、疲劳寿命与
      infinite-life 判定、分层/剥离/剪切风险、老化 SF、材料与模块 trust 徽章、
      `warnings` 列表（证据 E1）
- [x] b) **参数面自动同步**（2026-08-19 `_probe_surface`）：启动时无参跑引擎解析 usage 的 pattern/material 枚举
      （一手源对齐），硬编码仅作 fallback，检测到漂移时在 UI 打告警（证据 E2）
- [x] c) **接入既有增值 flag**（sidecar/strict-tier/dry-run 2026-08-19；`--explain` 2026-08-19 iter 62——探针实证其只富化 console 的 grounding 行、JSON 逐字节不变，故纯 argv 接入；`--layer-time` 未接：域 0.1..120 但报告 `input` 不回显（fixture 上无任何 JSON diff），盲接违反「UI 只渲染引擎 JSON」红线，转引擎压力点 #6）：
      `--explain`（每条建议的可信来源引用）、`--sidecar-json`（写回审计：到底写进
      3MF 了什么，当前导出是黑盒）、`--strict-tier`（写回可信层闸）、`--dry-run`
- [x] d) **lock 面扩展**（2026-08-19 `extra_locks` 探针 + ③ 面板复选行）：暴露 layer_height 等锁定（证据 E3；README「已知边界」中
      层高的*锁定*层面可解除，直调仍需引擎 flag）
- [x] e) **清 loop-journal backlog**（GRID/PORT 校验、会话上限 FIFO、res-stress 空值均已落，见 loop-journal 各迭代）：GRID/PORT 启动校验、会话上限/LRU、
      `res-stress` 空值 "— MPa" 显示
- 验证：`tests/test_smoke.py` 随项扩容 + GUI 冒烟；量级：a+b+e ≈ 1–2 个对抗迭代会话

### v0.3 — 方向二：调参工作流深化

- [x] a) **异步与取消**（2026-08-18 会话 3）：/api/cancel 杀引擎进程 + 前端
      AbortController；排队中取消复检；批量间 sticky 取消标志
- [x] b) **会话内历史**（2026-08-18 会话 3）：server 留存 10 次 + A/B 差值表
- [x] c) **用户自定义候选**（2026-08-18 会话 3）：/api/batch 全量前置校验+
      顺序执行（≤8 组合）
- 风险：并发引擎调用的 CPU/内存——需限并发队列；验证 = 并发回归测试

### v0.4 — 方向三：分发与上手（产品化；若定位对外产品则**前插到 v0.3 前**，见 D1）

- [x] a) **首跑向导**（2026-08-18 会话 3）：serve anyway + usage 探针校验 +
      config 持久化 + 表面重探（2026-08-19 追加：UNC 网络路径拒绝）
- [~] b) **CI**（2026-08-19 建，同日公开库关闭）：曾为 `.github/workflows/ci.yml`
      三层（syntax 恒跑；tests/installer 由 `STRATUM_SDK_URL` secret 门控）；
      公开化时按决策移除 workflow，本地回归 = `python tests/test_smoke.py` +
      `node tests/browser_render_check.js`；verify-installer.ps1 保留真实退出码判定
- [x] c) **版本兼容策略**（2026-08-18）：报告含 `schema_version`，逐请求精确校验（不支持即 502 fail-loud，
      不静默渲染错版本字段——2026-08-18 已实现于 server.py `schema_supported`）
- 验证：本地 smoke + browser E2E；引擎版本矩阵冒烟

### v0.5 — 方向三 b：UI 交互优化（2026-08-19，对抗审查修订版 v2）

- [x] a) **简单/高级双模式**：`body.mode-simple` 隐藏 ②③b⑤⑥⑦/历史/控制台，
      localStorage `stratum-ui-mode` 持久化，默认简单
- [x] b) **Toast 通知**：body 级 `#toasts`（err 常驻 / ok-info 5s）；只收编瞬态
      消息（分析完成/取消/下载），持久状态留 inline；顺带修 compare 错误误写
      `#export-msg`（简单模式不可见）的 bug
- [x] c) **调参 baseline 状态机**：`state.baseline` 在面板构建/新上传时记录、
      **引擎回显时刷新**（3MF 基线=内嵌切片配置，非引擎默认）；dirty 行 ● 高亮；
      行级 ↺ 与「重置全部」走 baseline；搜索框过滤含 extra-locks
- [x] d) **分析耗时秒表**：纯客户端（单次分析无服务端进度端点，轮询=伪进度），
      清理挂 analyze `finally`
- [x] e) **引擎枚举着色 + checkbox 历史**：`res-load` 颜色只映射引擎
      `load_adequacy` 枚举（无 UI 自造阈值，红线 2）；历史 checkbox 选择，
      保留 seq 排序与 ≤2 语义
- [x] f) **键盘**：Ctrl/Cmd+Enter 分析、Esc 取消（复用按钮 cancel handler，
      不双接线）；输入框聚焦时忽略
- 验证：`tests/browser_render_check.js` 21/21（8 项断言随 toast/checkbox 同步
  改造）+ `tests/test_smoke.py` 76/76

### v0.6 — UI v3 商业化视觉（2026-08-19，对抗审查修订版 v2）

- [x] a) **设计令牌体系**（单 `<style>` 内）：surface 分层 / 4px 间距网格 /
      圆角·阴影阶梯 / 靛蓝渐变 accent / `prefers-reduced-motion` 降级；
      **旧令牌（--panel/--panel2/--cyan…）保留为别名**——JS 内联 `var()` 引用
      零改动（对抗审查 blocker：抽离 styles.css 需改 server.py 白名单 + spec
      datas，零收益，弃）
- [x] b) **布局重构**：sticky 毛玻璃顶栏（`@supports` 降级不透明）+ 分段控件
      模式切换；上传区拖放卡片（drop 经 DataTransfer 写回 `#model-file` 并派发
      change，测试注入路径不变）；③+③b 同面板双 `<details>` 折叠分组
      （env 组整体 `advanced-only`）；④ 顶部 4 张 KPI 卡片（复用 `res-*` ID，
      report.js 零改动）；空状态统一卡片
- [x] c) **微交互**：按钮 hover/按压/focus 光环、primary 渐变；toast 入场
      动画；分析中按钮 spinner（**不确定态，无伪进度**——与 v0.5 d 的
      "无进度端点不做假进度"决策一致，弃骨架屏）；dirty 行 accent 左竖条；
      表格行 hover
- [x] d) 修复顺带发现：`buildExtraLocks` 空清单时隐藏 parentNode 在 v3 折叠
      分组下会连 ③ 一起塌掉（改为只藏自身行）
- [x] e) **实时分析**（auto mode，默认开，localStorage `stratum-ui-auto`
      持久化，③ 区开关钮）：参数/环境/锁定/方向变化后 800ms 防抖自动重跑。
      并发纪律：运行中重入被 `state.running` 闸住（手动优先，被挡的 auto
      排队到 finally 后补跑，新参数不丢）；批量运行期间挂起（`batchRunning`）；
      手动运行启动即吞掉待触发的 auto；auto 成功/取消不弹 toast（错误仍弹）。
      已知取舍：每次 auto 都真实跑引擎并计入运行历史（server 侧无
      no-history 通道，未加）。回显同步（setParamValue/syncEnvFromReport）
      不经 markChanged，无自触发回路
- 验证：`tests/browser_render_check.js` 21/21 + `tests/report_render_check.js`
  21/21；顺带修测试自身竞态——restore 步骤 reload 后 `clearToasts()` 会清掉
  它正在等待的恢复分析 toast（Page.reload 本就重置 DOM，该清理多余）；
  截图 `gui-test-screenshots/v3-*.png`（简单/高级/运行态/窄屏）

### v0.7 — 新手 0 参数：一键预设（2026-08-25）

- [x] a) **快速预设**：简单模式默认只显示 4 个一键预设按钮（安全/均衡/高速/外观，
      复用引擎 `PROFILES` 语义），9 项参数滑杆整体移入高级模式（③ details 加
      `advanced-only`；DOM 保留，browser E2E 的 `[data-param=walls]` 查询不受
      影响）。预设表服务端定义（`PRESETS`，server.py 紧跟 PARAM_META），经
      `/api/params` 新增 `presets` 字段下发，**无新端点**——点击 = 逐参数写滑杆 +
      置 dirty + 立即一次 `analyze(false)`（analyze 启动即吞掉待触发的 auto 定时，
      杜绝双跑）。`presets_for()` 做枚举漂移兜底：select 值不在实时枚举（引擎离线
      回退）时回退该参数 default，数值越界同理；输入表不被改动（返回深拷贝）
- [x] b) **运行态纪律**：预设按钮随会话启用（`applySession`）/ 运行中禁用（analyze
      start→finally 恢复）/ 会话失效（unknown token 路径）一并禁用；无 token 点击
      err toast，运行中点按 info toast（`state.running` 闸）
- 验证：test_smoke T59（presets 形状 / PROFILES 序 / 值域）/ T60（safe 预设
  analyze 全链路回显 walls=5 等）/ T61（presets_for 漂移兜底 + 无副作用）；
  browser E2E 新增预设 3 项（4 按钮渲染且启用、简单模式滑杆隐藏而预设面板可见、
  点击「安全」→ walls=5 并重分析）；README 记 0 参数流程

### v0.8 — 引擎 0.24.0 全量接入（2026-08-28，三迭代会话）

> 起点状态：`bin/stratum.exe` 已被 sync 到 0.24.0，但 schema 闸仍是 `(2,)`——
> 每次分析 502，WebUI 实际处于不可用状态（E5）。本节即"解阻塞 + 全量接入"。

- [x] a) **解阻塞（iter 1）**：`SUPPORTED_SCHEMA=(2,3)`；`status:"validation_refused"`
      /`"cancelled"` 标记在 rc!=0 路径优先识别（`load_report_marker`/`send_marker_response`，
      结构化 422）；`numEnv/fmtUnit` v2 对象与 v3 标量+孪生双形态；`cp-lh` 改用
      `input.layer_height_mm` 回显（候选 diff 抓取降为旧引擎回退）；`--schema` 探针
      （`probe_schema`，usage 正则降为回退）；`engine_version` 优先 schema `version`
      字段（修复 VERSION.txt 0.21 文本 vs 0.24 二进制漂移）；fixture `report-v3.json`
      重生成（旧 v2 `report.json` 保留作双形态渲染回归样本）；UI 0.8.0
- [x] b) **参数面扩容（iter 2）**：滑杆 += layer_height/z_ratio/fill_angle（域来自
      `--schema` value_flags，`_apply_schema_domains` 覆盖层）；③b += layer-time/
      扭转轴/机器型号（含自动档）/校验档位/修复朝向；① += 快速预览 `--fast`；
      `validated_env` 扩 select 白名单（machine/axis/validate，防静默回退/引擎 400）
      与 bool 白名单；预设表加 layer_height（0.16/0.2/0.28/0.12；z_ratio/fill_angle
      有意不预设）；④ 新增 mesh_topology 审计与 machine_limits（identified/source/
      clamps from→to）面板；④ validation_refused 内联 findings 渲染
- [x] c) **进度 + 热图（iter 3）**：`--progress-json` stderr NDJSON → 增量泵线程
      （`_run_proc_with_inflight` 重写：stderr 泵 + Timer 超时，旧 `communicate`
      无法增量读）→ `GET /api/progress`（运行代际闸防旧泵覆盖新 run）→ 客户端
      500ms 轮询「分析中 42% · fem」（无进度回退秒表）；`--heatmap-json` → 响应
      `heatmap` 字段（缺失/坏文件 = 降级不阻塞）→ `stlSetHeatmap` 体素立方体渲染
      （着色器加 aColor/uHeat；热图激活时替换网格视图——bins 填充零件内部，叠加
      会被表面遮挡）+ ④ 面板开关/着色源切换/图例；`_FALLBACK_FLAGS` += 两个新通道
      flag（旧引擎剥离重试）
- 验证：`tests/test_smoke.py` 92/92（T62-T73 新增：v3 端到端、状态标记、schema
  探针、新参数回显、机器白名单、validated_env、真引擎 strict 拒绝 422、fast 披露、
  热图透传、进度端点形状、慢钩子中段进度轮询）；`browser_render_check.js` 新增
  v3 fixture 渲染/numEnv 拒绝盒/新滑杆/机器与拓扑面板/真引擎热图像素级断言；
  截图 `gui-test-screenshots/v08-*.png`（热图开/网格视图/简单模式）
- 明确不做（backlog）：`--gcode-in/out` 应力调优、`--apply-orca` 独立写回、
  `--base-profile`、`--precond`、`--voxel-vote`/`--resolution-check` 开关、
  retraction 族滑杆（引擎不回显 input）、预设加 z_ratio（材料相对值）

### v0.8.1 — 引擎 0.24 全契约面补齐（2026-08-29，本节即缺口表 + 完成记录）

> 方法：以 `bin/stratum.exe --schema`（26 value + 8 enum + 21 bool + 11 path +
> 3 number + 76 lockable）、`--help`、全 flag 真跑报告 + 8 个可选块实测为一手源，
> 逐项 diff「引擎有什么 vs UI 接了什么」，产出缺口表后按价值排序逐项补齐。
> 兼容性中立：v0.8 遗留垫片（usage 正则回退、flag 剥离重试、schema v2 闸）不碍事
> 全部保留，不为清理而清理。

缺口表（契约项 / UI 现状 → 处置）：

- [x] **渲染面批量**（报告已带回、UI 未消费）：`input.fast_mode` ④ 预览级标签；
      `filament_slots`+`analysis_material_note`（② 多喷嘴披露）；`input_overrides`
      回退清单；`printability` 量化行；`phase_c.thermal_speed`（热-速闭环）与
      `weld_infill_aware`；`phase_b.resolution_adequacy`(ZZ-SPR)/`tsai_wu_safety_factor`/
      `mesh_quality`/`diagnostics.preconditioner+precond_fallback_count`；
      `phase_d.skipped_reasons`/`fatigue_life_cycles+damage_per_cycle`/
      `weibull_R+Pf+size_factor+sigma_eff_mpa`；建议项 `confidence`+
      `est_safety_factor+est_max_stress`；候选 `policy_applied`+
      `verification_dimensions`+校准悬停（同名陷阱：顶层 `calibrated`=SF 外推
      含义恒 false，cal 校准在 `estimate.calibrated`——GUI 冒烟抓出，T 渲染检查
      钉住）；机器限制层高带 0/0 未知不再渲染（2026-08-29 完成）
- [x] **`--appearance` + `--rheology`**：① 开关 → ④「外观评估」「流变诊断」面板
      （引擎评估串 verbatim，absent-not-null 整块隐藏）；body 级开关，批量同
      orient 的整批开关模式（T75 round-trip + 缺省断言）
- [x] **`--est-error-profile` + `--resolution-check`**：① 开关 → ④ 误差表
      （elastic/process 组分列、`-1` 哨兵显示「—」、`process_dims_note` 原文）+
      Phase B 校验行（粗/细网格 delta、capped、收敛态）（T76）
- [x] **`--voxel-vote` + `--precond`**：③b 行（bool + select 自动档不发 flag；
      precond 枚举来自 `--schema` enum_flags 探针 `_enum_values`）（T77）
- [x] **retraction/travel/wipe 发送值通道**：③b 行，诚实语义（行悬停 + 面板脚注
      明示「引擎不回显、设值即钉住」；T78 钉住 no-echo 契约——引擎将来补回显时
      该断言失败，提醒升级为常规回显状态机）
- [x] **`--prony-duration` + `--heatmap-bins` + 每次运行 `--grid`**：③b（有回显）
      / ④ 热图面板 bins 旋钮（2..64）/ ① 网格直输（4..128 服务端 400 预检；
      批量同 grid 整批开关）（T79）
- [x] **`--cal-time`/`--cal-mass`**：③b 数字直输（0=不发送 `zeroUnset`；range
      滑杆 step 吸附会发 1201/16——GUI 冒烟抓出后改直输）→ ④「估算校准」面板
      （applied/reason/factors/measured/predicted/notes）+ ⑤ 候选悬停（T80）
- [x] **`--base-profile`**：① 面板 JSON 文件上传 → 客户端读文本随 body 发送 →
      服务端预检（非空/256KB/JSON 对象）落私有临时盘 → 传路径；STL/裸 3MF 上
      walls/layer_height 等空位被填充；键面合法性引擎裁定（T81）
- [x] **导出族 `--generate-supports` + `--stress-modifier`**：④ 下载按钮行 →
      `POST /api/export-artifact`（kind 白名单，整跑一次引擎分析后回传 STL；
      空支撑也导出空实体——引擎语义）（T82）
- [x] **`--apply-orca` 写回模式**：⑤「仅写回 Orca 建议」→ `/api/export` body
      `mode:"orca"`；3MF+writable 闸、`--strict-tier` 复用；引擎该通道不产
      sidecar（0.24.0 实测），UI 文案如实标注（T83）
- [~] **挂账（未接，含原因）**：~~`--gcode-in/out`+`--gcode-vm-floor/m-hot/p-hi`
      应力调优工作流~~【v0.25.0 已闭环（2026-10-03）：附件会话+成对 flag+tune.json
      审计渲染+调优产物下载，见 v0.25.0 节】；`--vtk` ParaView 导出（④ 已有热图，
      用户面窄）；`--phase-a` 仅几何模式（`--fast` 已覆盖快扫；phase-a 会让 ④ 大半
      面板空转，需成套空态处理）；`--drucker-prager`（引擎 no-op 兼容位）、
      `--report`（文本通道）、`--optimize`（`--compare-profiles` 子集）= 非缺口

验证：`tests/test_smoke.py` 103/103（T74-T83 新增，全部真引擎 round-trip 为准）；
`report_render_check.js` 53 项（v0.8.1 新块 20 项，形状取自 2026-08-29 真跑探针）；
`browser_render_check.js` 全绿；GUI 冒烟截图 `gui-test-screenshots/v081-*.png`
（开关行/③b 新行/诊断面板/估算校准，无头 Chrome CDP 管线）。UI 0.8.1。

### v0.9 — 产品化 P0：建议一键应用 + ④ verdict-first 分层（2026-08-29）

> 方法：设计空间 5 候选各自独立 REFUTE 后收敛（本轮共 4 份对抗报告 + 1 份自我证伪）。
> 判决：**S 服务端映射**（REJECT-as-designed→修正采纳：applyable 必须是响应顶层兄弟键——
> `session["last_report"]` 按引用存储、`/api/report` 直接 dumps，注入 report 树会污染下载工件；
> 逐项 applicable:false+reason 而非静默丢弃；滑杆 step 预吸附对齐控件语义）；
> **W 暂存确认单**（REJECT→staging 降为属性：常驻确认单会被 auto renderReport 摧毁/陈旧且全仓无
> 代际闸——checkbox 与 items 同生命周期即天然免陈旧）；**R 结论卡重组**（REJECT 弃：SF/判定行
> 被 KPI 覆盖面核查 disproves——Tsai-Wu/塑性/残余/老化/Findley 等 13 类无 KPI 代理，折叠即信息丢失；
> 「N 条紧急」计数是 UI 自造分级触红线 2 判例 v0.5e）；**N 虚拟对比**（self-refuted 弃：
> per-item est_safety_factor 全 null，组合效果未验证=假乐观）。

- [x] a) **服务端 `applyable`**（`applyable_suggestions`，响应顶层键）：v1 白名单=仅实证 identity 键
      （nozzle_diameter/print_speed/cooling_fan，0.24.0 真实样本恒等 PARAM_META，零换算）；
      wall_count→walls / infill_pct→infill（单位空间 % vs 分数 fixture 不可判）/ infill_pattern→pattern /
      material 全部**挂账待真实样本**——无实证换算=发明引擎契约。判定规则（控件语义非引擎规则）：
      action∈{increase,decrease}、值≠当前、range 域校验、step 预吸附、同 ui_key 首个 applicable 胜出
      （引擎序=优先级序，UI 永不重排）；构建 never-raise（heatmap 同款纪律），v2 形状容忍
- [x] b) **勾选 + 单 CTA**（`applyCheckedSuggestions`）：checkbox 与 rec item 同生命周期；守卫
      token/running/**batchRunning**；客户端按 meta 复核（控件=最终事实）；写滑杆+dirty（不
      scheduleAuto，单次 analyze(false) 吞 pending auto）；toast 列出生效值（简单模式滑杆隐藏时可感知）；
      `.rec-apply` disabled 生命周期与 preset 按钮三点对齐（analyze start/catch/finally）。
      **前置修复**：applyPreset 补 batchRunning 闸（同语义兄弟，analyze 本体无此闸）
- [x] c) **回显 reconcile**：`state.lastApplied` 记写入值，analyze 成功后比对引擎 echo
      （APPLY_ECHO_KEYS 与 report.js 字面映射同源扩表），不一致 info toast「引擎按域调整为 X」——
      事后诚实披露替代预判钳制（预判=复制引擎钳制规则，触红线 2）
- [x] d) **④ verdict-first 分层**：solver internals（CG/网格/ZZ-SPR/mesh_quality/预条件子/
      resolution_check + Hill48 屈服指数/WLF/结晶度/键合）→ 两个 advanced-only 折叠 details
      （每帧反向复位，absent-not-null）；**全部 SF/判定行/热-速闭环留主区**（R 对抗的证据即边界）
- [x] e) **引擎结论前置**：`phase_b.assessment` verbatim 显示于 KPI 下（v3 实证「✅ 安全 — 结构强度充足」；
      两 fixture 的 warnings 均为 [] 且 priority 域仅 {2}——任何「N 条紧急」计数都是 UI 发明，不做）
- 验证：`tests/test_smoke.py` 105/105（T84 构建器敌意矩阵 14 case + never-raise；T85 真引擎
  round-trip：顶层键/report 树不被污染/逐项配对）；`report_render_check.js` 68 项（internals 位移
  ~13 处 + §24 渲染契约：CTA 计数/勾选配对/不可应用原因/无 applyable 向后兼容/盒子反向复位）；
  `browser_render_check.js` 39 项（真引擎 e2e 断言 applyable 顶层 + CTA 渲染）；截图
  `gui-test-screenshots/v09-*.png`（简单模式结论行+CTA / 高级折叠展开 / 应用后 dirty+toast，
  真引擎 STL 全流程；一次性脚本用后即删）
- 挂账（backlog）：~~改名键白名单扩表（需真实 rec 样本）~~【v0.9.1 闭环：引擎 0.25.0 对齐——
  recommendations 原生键即 walls/infill/pattern（wall_count/infill_pct/infill_pattern 仅
  process_optimization 空间），infill 单位=percent（fraction 仅 input 回显）；真实样本已交付
  `test_data/webui-alignment-2026-09/report-walls-infill-suggestions.json`，白名单=PARAM_META
  数值滑杆全量（select 仍挂账待 change 样本），回显比对扩 walls/infill（percent↔fraction 换算）；
  我方样本"零样本"根因=grid_res=4 触发实心件抑制（分辨率伪影，非能力缺失）——小件/薄壁建议
  提升 `--grid`≥16（默认已 16）】；`overall_band`
  契约缺口（UI 不自造分数色带，需引擎出枚举）；applyable 兜底规则与 presets_for 分叉已成文（本节 a）

### v0.9.1 — 引擎 0.25.0 对齐闭环（2026-09-02，调研驱动）

> 背景：`docs/parameter-research-2026-09.md` 调研（30+ 行业来源 + 聚合物物理文献）→ 差异项回提
> 引擎团队（`docs/engine-feedback-prompt.md`）→ 引擎回复 `C:\build\Stratum\docs\webui-alignment-response-2026-09.md`。
> 本迭代落地回复中"WebUI 侧无需等引擎"的 3 项（附录 C）。

- [x] a) **applyable 白名单扩表**（`applyable_suggestions` 注释+文案；PARAM_META 数值滑杆全量，
      walls/infill 原生键解锁；wall_count 等 process_optimization 键仍拒绝）；前端
      `APPLY_ECHO_KEYS` 扩 walls/infill（infill 回显 fraction→percent 换算，`reconcileApplied`
      支持 [echoKey, factor] 形态）；引擎交付真实样本复制为 fixture
      （`test_data/webui-alignment-2026-09/report-walls-infill-suggestions.json`）
- [x] b) **风扇建议降级展示**（report.js）：cooling_fan 建议且 `phase_c.residual_safety_factor`
      > 100 时附「此项建议对强度的收益可能有限」提示（引擎 warping 分支自述无文献源，
      iter 244；低残余应力场景降幅未门控，0.26 `motivation` 字段前 UI 侧如实披露）
- [x] c) **--grid 验证**：默认已 16（`GRID`，`STRATUM_UI_GRID` env 可覆写），满足引擎
      "小件/薄壁建议提升 --grid≥16" 建议，无代码改动；我方样本 grid_res=4 为 fixture 显式指定
- 验证：`tests/test_smoke.py` 106/106（T84 敌意矩阵扩 3 case：walls/infill 原生键解锁 +
  percent 吸附 + 引擎交付样本全链路；T86 新样本 projection 断言）；`report_render_check.js`
  69 项（24d 文案同步 + 24g 风扇降级提示三态：高 SF 出现/缺 SF 不出现/非风扇参数不出现）；
  `browser_render_check.js` 39 项无回归（T58 真引擎 e2e 通过）

### v0.10.0 — 产品化三阶段（易用性 × 视觉 × 信任，2026-09-02）

> 背景：`docs/productization-prompt-2026-09.md`（基于 v0.9.1 现状的产品化路线，三原则：
> 30 秒首价值 / 渐进披露 / 可行动性）。Phase 1-3 一次会话完成，UI_VERSION → 0.10.0。

- [x] **Phase 1 易用性闭环**
  - 空状态产品化：④「三步得到强度结论」引导卡（3 步 + 3 条能力亮点），首次成功渲染后隐藏
    （renderReport 起手置 none）
  - verdict-first 三卡（`#summary-cards`）：结论卡（引擎 assessment verbatim + SF 色带）/
    风险卡（warnings 前 3 条）/ 建议卡（「应用可行建议 (N)」CTA 前置；引擎无 assessment
    时不编造）；原 KPI 行降为次级
  - 术语解释层：静态 `TERM_INFO` 词汇表（Hill48/Weibull/层间强度 Z-XY/分层/热应力）挂在
    动态 hint 行 title；静态 label（安全系数/载荷判定/最大应力/屈曲/疲劳/Weibull/壁数/
    填充率/层高）在 index.html 带 title——只做静态文案映射，不碰引擎输出
  - 错误可行动化：`renderAnalyzeError`（report.js）——422 validation_refused →
    「校验档位改回 standard 并重跑」按钮；错误文本含 网格/分辨率/部件 →
    「提高网格精度（--grid ×2）并重跑」按钮；成功渲染自动清除。注意 CSS display:none
    默认的元素要置 `style.display="block"`（置 "" 会回落隐藏，已踩坑修复）
  - 移动端：640px 上传拖拽区大卡片化 + 单列 summary/empty 卡；420px KPI 单列
- [x] **Phase 2 视觉产品化**
  - 品牌首屏：header 字标渐变（`.hero-mark`）+ 副标改「强度分析工作台」
  - SF 色带：`sf-low/mid/high`（<1 红 / 1–3 琥珀 / >3 绿）纯展示映射——引擎无 SF 时
    `className="v"` 不上色不猜测；verdict 卡内条形 band（宽 = SF/6 封顶）
  - 候选档位对比条形图（`#cand-bars`）：纯 CSS 相对宽度（SF/时间/材料对 feasible 组内
    归一化），引擎排序不动，feasible<2 不渲染
  - 微交互：建议应用后参数行 `.flash` 高亮 1.4s；KPI `.skeleton` 脉冲 + `#run-progress`
    进度条接 NDJSON /api/progress（pct 驱动宽度）；全部受 prefers-reduced-motion 抑制
- [x] **Phase 3 引导与信任**
  - 首次 3 步引导条（`#first-guide`，localStorage `ui.guide-done` 可关闭、reload 后不再出现）
  - 参数行人话解释：`PARAM_HINT`（12 参数，数据源 parameter-research §2 共识，悬停 title）
  - warnings 卡可点开（`#warnings-card` 徽章 N 条 → click 展开；open 态存 dataset、
    跨渲染保留；summary 风险卡展示前 3 条作默认视图）
  - 引擎附录 C 落地：`phase_b.diagnostics.part_visibility_warning` 存在 → 建议卡
    「提高网格精度（--grid ×2）并重跑」按钮（与 1.4 错误卡同款动作）
- 验证：smoke **106/106**；`report_render_check.js` **95 项**（+26：三卡/SF 色带两态/
  warnings 开合/术语 title/cand-bars 归一化/错误卡三按钮/空态隐藏）；`browser_render_check.js`
  **46 项**（+7：真页面三卡/色带/静态+动态术语/参数 hint/warnings 开合/引导条出现-关闭-
  reload 记忆）；截图 `gui-test-screenshots/product-p1/p2/p3-*.png` ×7
  （`tests/product_shots.js` 可复跑）

### v0.11.0 — 亮色专业主题视觉重做（2026-09-03，独立对抗审查 APPROVE 后实现）

> 背景：v0.10.0 产品化后观感仍偏"工程控制台"（深底 + 双色渐变铺满 + 11-13px 密排 +
> 全站 uppercase 微标签）。方向经用户确认改走**亮色专业 SaaS**（Stripe/Notion 式）。
> 实现前派独立对抗子 agent 证伪方案（REFUTE）：抓出 2 实错（WebGL lit 判定是
> **三通道曼哈顿和**非每通道差——空画布会假绿；`#summary-cards:empty`/`#cand-bars:empty`
> 是承重隐藏规则，report.js 从不写其内联 display）+ 6 处遗漏（warm 分类器第二道 WebGL
> 门、rgba 字面量同步清单、favicon 与徽标同源、非 var 硬编码色清扫、全站去 uppercase
> 枚举不全、clear color 注释已失真），全部修订入实现。

- [x] **亮色 token 全量重设**（`:root`，变量名全保留只改值——JS 内联 var() 为承重引用）：
  浅灰底 `#f4f6fa`/白卡/`#f3f6fb` 下沉面/边框 `#d9dfeb`；单靛蓝 `#4f46e5` 收敛
  （渐变仅留字标与状态色淡阶）；语义色按 **WCAG AA ≥4.5:1（12px 对 #fff）核算选定**
  （text 15.6 / muted 5.8 / green 5.5 / amber 5.0 / red 4.8 / violet 5.7 / accent 6.3；
  核算表见 `docs/reviews/visual-v011-2026-09-03.md`）；新增 line-strong / soft-chip 对 /
  console 深色 token
- [x] **排版与密度**：全站去 uppercase（panel h2 / details summary / table th /
  sum-card h3 等扫净）、字号阶梯重建（panel h2 13→14.5、表格 12.5→13、KPI 22→24、
  header 17→18）；等宽字体收敛到数值/表格/控制台（.sub/.tag/.cb-name 出列）；
  圆角/阴影/间距微放大
- [x] **组件现代化**：主按钮/预设/CTA/引导圆点双色斜渐变 → 单色靛蓝（hover 提亮 +
  克制阴影）；卡片扁平化 + verdict 三卡顶部语义色条（soft 淡阶渐变）；slider thumb
  白心单色；sf-band/对比条/进度改浅色同色相渐变；`:focus-visible` 全覆盖 +
  细滚动条/::selection
- [x] **深色视口与终端的显式例外**：STL 预览视口（WebGL clear color rgb(22,28,41)）与
  引擎控制台/导出预览**保持深色**（CAD/切片惯例；clear color 被 browser e2e 曼哈顿和
  测试 pin 死，stl-preview.js 注释改写为显式契约说明）；导出预览改用 --console-* token
- 验证：smoke **106/106**；`report_render_check.js` **95 项**；`browser_render_check.js`
  **46 项**（含 WebGL 两道门：lit>2% 曼哈顿和 + warm 分类器）全绿；截图
  `gui-test-screenshots/product-*.png` ×7 重拍为亮色（`tests/product_shots.js` 复跑）
- 自检报告 `docs/reviews/visual-v011-2026-09-03.md`（harness 逐条 + 对比度核算表 +
  对抗审查修订记录）；改动面：index.html `<style>` 整体重写 + 静态内联样式点 +
  stl-preview.js 注释 + server.py UI_VERSION

### v0.12.0 — 交互对齐：对齐充分验证的 UX 模式（2026-09-23）

> 背景：用户反馈"还是难用"。诊断结论：v0.10/0.11 修的是皮肤（主题/文案/引导），
> 信息架构仍在镜像引擎管线（①-⑦ 编号 = 引擎数据流顺序）。本轮对齐权威交互模式
> （Nielsen 启发式 / NNG progressive disclosure / Hick 分块 / Material switch /
> "what changed" 反馈），只动 chrome 层（标题/分组/开关/反馈），不碰引擎契约渲染。

- [x] **A 任务化命名 + CLI 术语降层**（Nielsen #4 match real world）：去 ①-⑦ 管线
  编号；面板重命名（模型 / 当前参数 / 调参 / 环境与载荷 / 分析结果 / 档位对比 /
  可信度 / 切片软件建议（Orca））；`--lock`、`--orca-suggest` 等 flag 从标题层降到
  title 悬停；README/注释/一条 server.py stderr 同步（编码对称清扫全部位点）
- [x] **B 上传区动作分层**（NNG progressive disclosure）：主行动只剩
  分析/优化对比/下载报告；6 个诊断开关 + 网格收进「分析选项」折叠组，
  summary 带「已开 N 项」徽章（折叠态自描述，Nielsen #1）
- [x] **C 滑杆心智分组**（Hick/Miller 分块）：12 滑杆按 结构强度/材料与温度/速度与冷却
  三组渲染；分组头携带全组 search 串（搜索时空组自动隐藏，零额外逻辑）；
  schema 漂移新增参数落入「其他」组，永不丢失
- [x] **D 运行增量徽章**（"what changed" 模式）：结论卡显示 SF/评分较上次运行的
  ▲▼ 胶囊（双侧均为有限数才渲染——首跑/缺字段/envelope 无 nominal 不显示，
  假绿/两态哨兵纪律）；与运行历史 #seq 对应
- [x] **E 模式开关控件**（Material switch 解剖）：「高级模式：开/关」文字按钮 →
  checkbox 开关（label 高级选项，键盘/焦点语义免费）；MODE_KEY 持久化不变
- [x] **F 存量 grid blowout 修复**（新守卫抓出）：`.ui-kpis` 1fr 轨 min-content
  （24px 等宽字体的不可断包络值 "(0.04–0.07)"）×4 ≈ 1075px > 右栏可用 ~890px，
  整页横向滚动。修法：`.grid > div { min-width: 0 }` + `repeat(4, minmax(0,1fr))`
- 验证：smoke **106/106**；`report_render_check.js` **95 项**；`browser_render_check.js`
  **46 项**全绿；新增 `tests/ux_alignment_check.js` **23 项**（E1 开关三态+持久化 /
  E2 标题断言 / E3 折叠组+徽章 / E4 分组+搜索联动 / E5 真引擎双跑增量徽章两态 /
  E6 横向溢出守卫 + KPI 无乱码）；截图 `v012_advanced_groups_delta.png` /
  `v012_simple_mode.png`；视觉核验（CDP 截图 + 模型审阅）确认开关/去编号/分组/增量
  四项生效、无破版

### v0.13.0 — 任务流式重排：方案 A 双轨制（2026-09-23）

> 背景：v0.12 对齐了交互模式后，根因层欠账仍是"IA 镜像引擎而非任务"。本轮按用户批准的
> 方案 A（双轨制）：简单模式改成真正的单列任务流，高级模式保留仪表盘 + 三处手术式升级。
> 方案 B（两模式同一新骨架的全局重构）明确为本轮非目标。重排前做了硬约束盘点
> （report.js 写入 id 全集 / 位置敏感 CSS / 布局顺序敏感测试断言），全部 id 未动。

- [x] **简单模式 = 单列任务流**：`body.mode-simple .grid` 单列 + 左栏限宽 760px 居中；
  DOM 顺序天然是 模型→预设→结果（advanced-only 隐藏后），纯 CSS 无节点移动；
  `.simple-only` 反向类（高级模式隐藏流式 chrome）
- [x] **步骤条** `#flow-steps`（简单模式常驻）：上传模型→选预设→看结论，
  done/active 态由 applySession / analyze 成功 / 运行态钩子驱动；首访教育条不自动退场
  （dismissal 是用户的选择，写 ui.guide-done 的只有关闭按钮——曾实现自动退场后因语义
  更差而撤回，见 browser 套件 guide 断言）
- [x] **档位对比开放给简单模式并上移**：panel 移到「分析结果」之后；四预设对比条形图
  直接回答新手第一问"选哪个预设"；捕获/批量/写回工具包进内层 .advanced-only
- [x] **悬浮状态条** `#sticky-verdict`：结果面板顶部 sticky，滚动调参时 SF/评分/▲▼ 常驻；
  运行中显示"分析中"（startRunIndicator/stopRunIndicator 钩子，错误/取消路径不留残态）；
  值镜像 #res-sf/#res-overall（class+text 复用，无二次阈值推导），增量芯片从结论卡克隆
- [x] **改动计数** `#dirty-chip`：分析按钮旁"已改 N 项"（N=state.dirty 键数，即与上传
  基线的差异）；span 而非 button（E3 套件钉死主行动行恰好 3 个 button）；点击/回车=立即
  分析；挂在 updateRowState + resetAllTuning + resetTuningState（全部 dirty 突变位点）
- 验证：smoke **106/106**；`report_render_check.js` **95**；`browser_render_check.js`
  **46** 全绿（面板移动零回归）；`ux_alignment_check.js` 扩到 **26 项**（E7 单列流+面板
  顺序+档位对比可见+步骤条两态 / E8 悬浮条 sticky+运行态切换 / E9 计数胶囊出现-重置消失）
  全绿；截图 `v013_simple_flow.png` / `v013_advanced_sticky.png` + product 系列重拍，
  视觉核验通过（含滚动中悬浮条实测截图）

### v0.18.0 — 简单模式"结论优先、明细退后"：明细墙折叠 + 告警不变式 + 步骤条诚实化（2026-09-29）

> 背景：用户诉求"简单模式一定是很简单的"。实测（beam STL，UI 0.17）简单模式结果区是
> 一面 16 行引擎明细墙（Tsai-Wu/Hill48/热-速闭环中英长文…），页面 3035px≈3.4 屏，
> 且安全相关信号（屈曲警示 λ=86、SF=0.88<1）埋在第 2 屏。独立 REFUTE 一轮（REJECT：
> 1 blocker + 3 major 全部采纳修订）后才动工。
> 契约枚举（BLOCKER 前置）：引擎 0.26 真跑证实 `phase_d.buckling_warning`（引擎亲笔
> 结构化告警字符串）与 `phase_d.fracture_risk_detected`（结构化布尔）存在——告警不变式
> 可不碰"UI 不另行打分"红线实现；顶层 `warnings[]` 与 phase_a 几何风险（S 级严重度）
> 已有折叠区之外的卡承载。
> 明确不做（对抗裁决砍/撤）：自动滚屏（与 v0.13 sticky-verdict 职能重叠）；对比表数值
> 取整（71.812937 vs 71.814511 取整后不可区分——两态哨兵反面）；guide/步骤条互斥
> （代码注释记录在案的"strip=WHERE/guide=WHAT"取舍）；machine-limits/heatmap 补
> advanced-only（考古 v0.8.0 引入、意图不可考——改收进折叠，两模式可见性由折叠统一）。

- [x] **明细墙折叠**：`#structural-summary`/`#printability-line`/`#phase-b-detail`/
  `#phase-c-detail`/`#phase-d-detail`/`#orient-detail`/`#machine-limits-box`/
  `#heatmap-box` 八容器加 `.detail-wall`（DOM 位置与 id 不动，report.js 写入不受影响——
  延续 v0.13"纯 CSS、无节点移动"）；`#detail-fold-toggle` 单钮翻 `body.detail-open`，
  高级模式按钮隐藏、墙面全可见（现状零变化）；`#phase-b-assessment`（引擎结论行）
  保持折叠区外、verdict-first 不动摇；跨分析保留展开态（同 risk-card 用户所有权先例）
- [x] **结构化告警不变式**（折叠不许埋安全信号）：`#pd-warn-promoted` 镜像容器
  （summary-cards 之后），report.js 渲染 phase_d 时同值回显屈曲/断裂告警原文——
  每次渲染先清空（无告警报告不得残留旧警报）；`fracture_risk_detected===true` 且
  assessment 真值才镜像（防渲染 "null"）；fatigue 永不镜像（无结构化判别子，恒真=噪声）；
  镜像 CSS 默认隐藏 + `body.mode-simple` 才显示（正向门控——buildSnapshotDoc 不拷
  body class，反向门控会把镜像漏进导出快照）
- [x] **步骤条诚实化**（原 `2: hasReport ? "done"` 为假绿）：`state.presetApplied`
  仅由 applyPreset 守卫通过后置位（选择动作语义——分析失败也算选过）、resetTuningState
  复位；未选预设的报告 → step2 显示 skip 态（– + 中性 title「未选预设——按当前参数
  分析」，对引擎默认与手调参数两种来源都为真）；boot 补 updateFlowSteps 调用
- [x] **空面板瘦身**：`body.no-report` 门挂「面板原始态」（empty-guide 可见），而非
  hasReport——resetTuningState 保留上一模型结果（既有会话语义），按 hasReport 隐藏
  KPI 会造成半清场（REFUTE major）；首跑前隐藏全 "—" KPI 行与 15 列空对比表 +
  折叠钮，高级模式不受影响
- [x] **E3 既红修复**（v0.17 遗留，非本轮引入）：e7e53c3 给主行动行加了第 4 个按钮
  （下载 HTML 快照）但 E3 仍钉 3 个——套件自 v0.17 起带红运行；按立法本意（钉死行构成、
  dirty-chip 保持 span）更新为 4 按钮构成
- 验证：smoke **118/118**；`report_render_check.js` **136**（原 130 + §25 镜像 6 项：
  原文回显/双通道 pd-warn 类/fatigue 不镜像/null 守卫/清空义务）；`ux_alignment_check.js`
  **40 项**全绿（新增 E10a boot 原始态 + E10b 折叠/镜像/高级对照 + E10c S3 skip 态；
  E7:320 假绿命名更正）；`browser_render_check.js` 全绿；截图
  `v018_simple_folded.png` / `v018_after_results_folded.png`（折叠+镜像+skip 条带）/
  `v018_after_results_expanded.png`（展开态：墙回归 + 屈曲警示琥珀高亮）
- 遗留 backlog：档位对比 15 列原始表收起（本想做"并入折叠"，执行时确认跨面板隐藏
  语义不成立——表属 cand-panel 不属引擎明细墙，且面板本身已是滚动可达的次级内容；
  候选方案：面板内 details）；resetTuningState 半清场（上模型后旧结论卡残留，既有
  行为，本轮未扩大）；引导条重设计（用户决策点，未拍板不动）

### v0.19.0 — 档位对比面板收尾：原始表入面板折叠 + 有效数字去噪（2026-09-30）

> 轮 B（v0.18 backlog 收尾）：简单模式页高 2378px 距 ≤2200 验收线的缺口 ≈ 对比表。
> independent-REFUTE 一轮（VERDICT: REJECT——2 blocker + 2 minor 全采纳后实现）：
> blocker#1 折叠出口枚举漏格（#cand-bars 是条件渲染，`feas.length>=2` 门 + `:empty`
> CSS——「有候选但可行 <2」shape 下折叠表在折叠区外零出口，违反
> `fold-must-not-bury-unchanneled-warnings` → 自动展开谓词改为
> `!cands.length || 可行数<2`，只自动展开从不已动收起）；blocker#2 页高预算自算
> 不闭合 + 绝对页高跨机器硬 pin 会假红（→ 收高手段在方案内闭合，验收只走
> 1440×900 同口径实测）；minor：快照导出只克隆 summary-cards 面板（cand-panel
> 根本不进快照——数据流模型更正）；minor：真实数据下 infill/speed 格本就渲染
> "15"/"120"（JS 数字无尾零），fmtSig 的实际可见变化仅在评分格。

- [x] **原始表入面板折叠**：`<details id="cand-raw-fold">` 包住 15 列原始表
  （summary「原始对比表」，双语进 LANG_EN），置于 `#cand-bars` 之后——刻意不并入
  「引擎完整明细」（跨面板隐藏语义不成立，iter95 裁决）；默认两模式一致收起；
  元素本地 open 状态（不用 body class：快照导出不克隆此面板，applyMode
  「切换只动 CSS 可见性」不变式不破）；`#cand-bars` 保持折叠区外作为出口
- [x] **数值去噪**：report.js `fmtSig(x)` 6 位有效数字（`toPrecision(6)` + parseFloat
  去尾零；非 number 原样透传——iter76 防 throw 约定），应用于候选表 8 个数值格
  （infill/速度/五项评分/quality）。出处：实测噪声形态（report-v3.json
  70.712937/15.0/120.0）+ ROADMAP v0.18 反例对 71.812937/71.814511 第 4 位小数
  分叉——6 位保留 71.8129/71.8145 区分度。不碰：EstSF（既有 Math.round）、
  EstTime/EstMat（既有 toFixed(1) 设计）、tooltips
- [x] **页高预算闭合**（REFUTE blocker#2）：折叠（-160px）+ bars hint 缩一行
  （-20px）+ cand-bars/track/fold 局部 CSS 收紧（-30px）→ beam STL 简单模式实测
  **2197px**（验收 ≤2200，v0.18 基线 2378px；1440×900 同口径，
  `v019_simple_beam_folded.png` / `v019_simple_beam_fullpage.png`）；折叠收起、
  bars 渲染、屈曲镜像浮出三状态探针实测在案
- [x] **顺路 bugfix**（§26 测试首次踩到该分支暴露）：`!cands.length` 的「无候选」行
  原用 `el("td",…).parentNode` 惯用语——未挂载节点 parentNode=null，真浏览器
  `appendChild(null)` 必 throw，缺 process_optimization 的报告渲染中途崩溃；
  且该 td 未设 colSpan=15。改用 note/caveat 行同款模式
- 验证：smoke **118/118**；render_check **142**（原 136 + §26 六项：twin 对
  区分度/infill 去噪/收起负向守卫/可行<2 自动展开/无候选自动展开/fmtSig 守卫——
  旧 report.js 上 4 项结构性必红已 stash 实证）；ux **43**（原 40 + E11 三项：
  details 包裹/bars 折叠外/出口不变式 openState===(bars 空)）；browser **65**
  （+4：出口不变式、fmtSig tripwire——首次跑曾遇一次未复现的 stale-file FAIL、
  去噪无 ≥5 位小数、summary 可点击开合）
- 遗留 backlog：页高验收仍是本机口径实测（无跨机器 pin，字体/DPI 漂移会移动数值）；
  EstSF 的 Math.round 呈现（3.19→3）与 fmtSig 口径不一致，待真实 SF 需求再议；
  ux 套件 fixture 的候选可行性形状若变（<2 可行），E11 出口不变式断言自动适配

### v0.20.0 — i18n 收口：EN 模式残留中文清零（2026-09-30）

> 用户反馈「切到英文模式还有些中文」。静态词典覆盖检查（新 `tests/i18n_coverage_check.js`：
> 提取 LANG_EN/LANG_WORDS 后对 index.html 静态文本/属性 + 三个 JS 的全部字符串字面量
> 重放 trText 管线，注释剥离 + 有意保留 allowlist）实测改前 **280 条**翻译后仍含中文。

- [x] **词典补全**：LANG_EN 精确键 +LANG_WORDS 词级片段共 ~180 条——ENV_META 标签/hint、
  PARAM_HINT 12 条（与 current-params 标题措辞漂移的变体单独键控）、LOAD_LABELS 枚举、
  PARAM_GROUP 组头、写回审计/批量表头、toast/状态词、TERM_INFO 术语卡、stl-preview
  预览错误、server 下发预设 desc（拼接进 title → 只能词级）、报表组合行片段
  （CG/网格/离散误差/相 C 内部/相 D 判定/老化/热-速闭环/拓扑/外观/流变/校准等）
- [x] **死键移植**：只存在于 LANG_EN 精确表的组合串片段（「结论： 」「原因： 」「已校准估算
  （…）」「。standard 档仅披露不拒绝。」等）永不命中 → 移入词级；thrown Error 带
  `Error: ` 前缀使精确键失效 → 词级兜底（上传失败/写回失败等一族）
- [x] **trTextKeepWs**：文本节点普遍带缩进/尾随空白（`<h2>当前参数 <span>` →
  "当前参数 "），精确键永不命中；修剪核心精确命中优先于词级循环（词级含新加全角
  标点条目后恒扰动字符串——首版「先试 trText 再补 core」的门槛使 core 重试不可达，
  browser sweep DIAG 字符码实测定位）；splice 保留原空白，__zh 无损恢复不受影响
- [x] **_langAttrs expando 重收养**：boot 后被 app 重写的属性（日志按钮 title 在
  /api/status 回填路径后缀）因 `__zh_title` 已存在被永久跳过 → 值变化时重新收养
  （en 值则清快照，restoreZh 不回写英文）
- [x] **document.title**：`<title>` 在 `<head>`，translateDom 的 body walker 永远够不到
  → applyLang 显式翻译/恢复
- [x] **引擎原语渠道 skip 对齐**（设计红线「引擎输出保留中文」的实现补全，非本次回归）：
  report.js 多处引擎撰写的 prose 渲染进了未打 skip 的节点（fracture/buckling assessment、
  skipped_reasons、ts.rationale、wi.disclosure、cal.reason/notes、process_dims_note、
  c.note、trust 徽章、analysis_material_note）→ label 保持可译 + prose 包 skip span
  （textContent 拼接逐一不变，render_check 142 断言全绿佐证）；w1（CG 未收敛——纯
  静态 UI 文案、零引擎内容）反向去 skip 进词典
- [x] **词级单字收敛**：裸「无」词级条目误伤引擎 prose（「无需」→「none需」，browser
  sweep 实证）→ 收回为精确键；「开/关」用「方向优化 开」「→ 关」等键控形式避免
  「开裂」类误替换
- [x] **配套**：全角标点→半角（词级表末位，chrome 行不再以 CJK 标点收尾）；快照导出
  `lang` 属性跟随捕获时 UI 语言；`UI_VERSION` 0.20.0
- 验证：静态覆盖检查 **FAIL 0**（有意保留 10 条逐一注释：lang-toggle 自指、skip 节点
  内 UI 前缀等）；新增 `tests/browser_en_check.js`（CDP 真实页面 EN 启动 + 真实样本
  report 渲染 + DOM 全量清扫 + skip 红线正对照 + zh 往返 + 组合片段探针）**11 PASS**；
  既有回归全绿：smoke **118/118**、render_check **142**、ux、browser E2E
- 遗留 backlog：server.py 错误消息中英混排（服务层输出，与引擎控制台同层保留中文）；
  引擎 prose 在非 skip 节点的词级误译是既有已接受行为（本次未扩大）；静态检查器按
  字面量粒度，新拼接模式靠 browser_en_check 兜底

### v0.21.0 — 视觉同一性收口：字号/控件高度/圆角三套刻度 + 边界对齐（2026-09-30）

> 用户反馈「整体 UI 的同一性没有做的很好，大小，高低，边界对齐」。审计实证：v0.11 虽建了
> spacing/radius token，但字号散落 **13 档**（10.5–24px 含 0.5px 步进）、按钮 padding
> 4 种、控件高度 24–41px 混杂；简单模式输入列 760px 居中与全宽结果列形成两条左边线，
> 「调参」面板外壳在简单模式漏隐藏留空壳，header 因 margin/padding 不对称距视口边缘 4px。

- [x] **类型刻度 13→7**：新 token `--fs-xs/sm/md/lg/xl/2xl/kpi`
      （11/12/13/14/15/18/24px），全量替换硬编码字号；9/21/24/30px 为图形 glyph 刻意豁免；
      图标字号与文本字号在 token 注释中划界
- [x] **控件高度三档制**：`--ctl-h 32px`（全部 button/input number·text/select/搜索框，
      flex 垂直居中）、`--ctl-h-hero 40px`（简单模式预设卡）、`--ctl-h-chip 28px`
      （header 徽章/语言 pill，避免压过 25px 标题行）；`.p-reset`/`.toast-x` 裸图标钮
      `height:auto` 豁免；透明 file-input 覆盖层（inset:0）不受高度锁
- [x] **圆角归 token**：新 `--r-xs 6px`（console pre/内联微输入框）；preset 9px、
      rec-apply/sum-cta 硬编码 8px、画布 10px、进度条/条形图/滑轨 2–5px 一律归
      `var(--r-*)`/999px 胶囊；圆角不变量=「token | 999 | 50% | 0」
- [x] **边界对齐三修**：header 改全出血（负 margin=body padding，内容 20px 线与面板对齐）；
      简单模式「调参/环境与载荷」外壳面板补 `advanced-only`（不再渲染空壳卡）
- [x] **简单模式面板同宽（v0.21 r2，用户复核反馈）**：v0.13「限宽 760px 任务流」与全宽
      结果列叠加产生一页两种卡宽，先改左对齐（r1）仍不满足「堆叠卡片至少同宽」→ 撤销
      760px 上限，全部面板全宽统一；beam 页高实测 2128px ≤ 2200px 预算线（v0.19 基线）
- [x] **连带真 bug（假绿暴露）**：`#dirty-chip` CSS `display:none` + JS 置 `""` 回落 none
      ——徽章实际从不渲染，E9 只断言内联样式故全绿；改 JS 置 `inline-flex`
- [x] **防回归**：新增 `tests/ui_consistency_check.js`（静态解析 style 块：C1 字号白名单/
      C2 圆角白名单/C3 token 存在且无 .5px/C4 控件高度契约）——行为 E2E 不盯样式，
      硬编码 13.5px 可无声回潮，此文件是绊线
- 配套：快照模板 10px 圆角归 token（快照内联整页 style，var 随整页样式落盘可解析）；
  solver 折叠区 margin-top 6px 与兄弟区块 8px 对齐；`UI_VERSION` 0.21.0
- 验证：consistency check **21 PASS**；render_check/ux_alignment E2E 回归见
  output.verification.md

### v0.22.0 — 简单模式「一屏一答」：去重 / 信号一致 / 单一主行动（2026-09-30）

> 用户复核 v0.21 后判定「简单模式还是不够简单清晰」。对照 v021_simple_fullpage.png
> 实证清点：同一安全系数出现在 sticky 条+结论卡+KPI 行 3 处、结论文字 2 处、
> 「应用建议」按钮 2 个；⚠ 信息散布在「N 条提示」卡+「N 条几何风险」卡+结论区
> 风险预览卡 3 处；三步引导在首访横幅+步骤条+空态卡出现 3 遍；绿色 ✅ 结论卡
> 与游离的橙色屈曲警示行色彩打架。

- [x] **引导三重→一重**：删 v0.10 首访横幅（first-guide + ui.guide-done 生命周期）与
      v0.13 持久步骤条（flow-steps + updateFlowSteps 诚实三态）——三步内容只保留
      结果面板空态卡（#empty-guide，情境化：结论将出现在哪里就在哪里教）
- [x] **结论 hero（每数字一次）**：summary 三卡 → 两卡（结论 hero + 建议）。hero =
      引擎亲笔结论 verbatim + SF 刻度条 + 人话解读；**卡色取最坏信号**（结论 emoji ×
      phase_d 屈曲/断裂结构化告警 × SF<1，仍是引擎数字的显示映射、无 UI 侧打分）；
      屈曲/断裂镜像横幅**移入卡容器内、贴合 hero 下沿**（渲染时节点搬家，负 margin
      闭合网格缝隙）——绿卡旁的橙线从"孤线"变成 hero 的"但注意"注脚
- [x] **单一主行动**：建议卡 = 「应用全部建议并重新分析 (N)」+「将调整：填充率
      15→25%…」摘要行（标签查自服务端滑杆行 .lbl，客户端仍不持有引擎键名知识；
      简单模式无需勾选仪式）；高级模式保留按勾选应用 CTA（双按钮 CSS 门控）
- [x] **风险一个入口**：warnings 卡 + risk 卡 + 结论区风险预览卡 → 一张「风险与提示」
      合并卡（合计计数 + 「最高 SN」标题行，体内双列表分节）；保留 v0.14 语义：
      用户开关跨分析保留、未点击时 ⚠️/❌ 展开 ✅ 折叠；两流皆空则整卡隐藏
- [x] **数字进折叠**：KPI 行（评分/载荷判定/最大应力）+ 参数建议明细 + 引擎判定行
      （phase-b-assessment，v0.18 时是唯一的上方结论行，hero 落地后成重复）统一挂
      detail-wall；折叠条更名「全部数值与引擎明细」；sticky SF 条简单模式平时隐藏、
      仅分析中现身作运行反馈（高级模式两列滑杆工作流不变）
- [x] **行动行瘦身**：优化对比 / 下载报告 JSON 归高级模式；简单模式主行动行 =
      分析 + 下载 HTML 快照（可分享产物）
- [x] **连带修复（vm 假绿防线）**：worst-of 着色初版读 #pd-warn-promoted 的
      textContent——vm stub 不折叠子文本会假绿，改读引擎 payload（与镜像写入同条件）；
      横幅搬家在 vm 无 removeChild 的 stub 上跳过（位置属装饰，内容渲染与位置无关）
- [x] **防回归**：report_render 142 断言重写（两卡结构/合并卡计数·标题·门控/双 CTA/
      将调整行）；ux_alignment E7/E10 重写（sticky 简单模式隐/运行现、KPI+建议明细
      进折叠、行动行 2 钮、横幅位于 hero 之下）；browser_render 增「横幅入容器」
      「单一引导面」断言；i18n 拼装串补 word pairs（coverage 按字面量、运行时按整
      节点——CDP EN 扫描抓住缺口后补齐）
- 配套：beam 页高 2128→1819px（v0.19 预算线 2200px）；`UI_VERSION` 0.22.0；
  截图 gui-test-screenshots/v022_{simple,advanced}_fullpage.png
- 验证：smoke 118/118；report_render 142/142；ux_alignment 45/45（真引擎 E2E）；
  browser_render all green（真引擎 E2E）；ui_consistency 21/21；i18n FAIL 0；
  browser_en ALL PASS

### v0.23.0 — G-code 伴随工具：gcode-diff 双文件对比 + 单文件评分（2026-09-30）

> 集成兄弟仓库 `C:\build\Gcode-diff`（纯 Rust G-code 对比/评分引擎，3.5 万行/550 测试）
> 为第三条输入流。此前 G-code 在本 UI 是"拒绝面"（.gcode.3mf 上传即拒）。选型：
> **CLI 子进程 + 版本化 JSON**（与 stratum.exe 调用模式同构、零新依赖保红线 1），
> 不 import 其 crate、不走其 C ABI。对抗审查（requirements-gap correction pass）
> 先行打穿三个假设——dist 现成品**落后源码**（空文件评分假绿 100 分，改用仓内
> 0.27.0 构建重打包）；score 模式 `dimensions_scored==0` 无条件 rc=2 且文件已落盘
> （fail-closed 合法态，非工具失败）；diff 模式 rc=2 仅在显式 `--fail-on*`（本 UI
> 永不传 → 成功恒 rc=0）。

- [x] **分发与探测**：`bin/gcode-diff/` 子目录（exe + 自带 stratum_shared.dll，
      与 bin/stratum.exe 的 DLL 解析隔离——未来 SDK 版本错配最坏封顶为工具自身
      rc=1，不波及引擎）；`resolve_gcode_diff_binary()` 照 resolve_binary
      （env STRATUM_GCODE_DIFF_BIN → bin/gcode-diff/ → PATH）；缺失=面板整体隐藏
      （/api/status `gcode_diff_available` 披露，降级不阻断）；build.ps1 `bin\*`
      拷贝补 `-Recurse`（子目录内容否则丢失）+ 伴随缺失仅警告
- [x] **服务端三端点**（纯编排、argv 全常量 flag）：
      `POST /api/gcode-diff`（A/B 两 session、schema 闸 `gcode-diff-report/v1`
      fail-loud、console 取 **stderr** —— 一行摘要在彼处，与 stratum.exe 的
      stdout 相反）；`POST /api/gcode-score`（结构闸、rc∈{0,2} 皆成功、
      `--no-overhang-viz` 免 4.5MB plotly）；`GET /api/gcode-report`（自包含
      HTML 深链，RFC 5987 双头）。上传白名单 +gcode/+gco，session 增 `kind`，
      analyze/batch kind 闸拒绝 G-code 误入几何引擎
- [x] **报告显示名**：上传以 `<run_hex>-<原basename>` 拷贝入 WORK_DIR 再送 argv
      （报告 file_a/file_b 显示真实文件名而非 token 乱码；basename 上传时已拒
      控制字符 + 上游 h_escape 注入测试覆盖）
- [x] **前端**：左列「G-code 工具」面板（评分=简单模式入口"这份 G-code 打几分"；
      对比+轻量几何=advanced-only）；右列 **panel 级互斥**（gcode 结果换整个
      结果列，下次模型分析换回）；HTML 快照仅限模型结果（gcode 的完整产物 =
      深链自包含报告，title 注明 diff 报告恒中文/score 恒英文——引擎产物语言
      原样，v0.15 纪律）
- [x] **渲染两函数**（report.js 只声明约定）：renderGcodeDiff（结论 hero/层差异
      KPI/全局指标差异表/几何卡【available:false 整块隐藏，absent-not-null】/
      physics 标量摘要/slicer_issues severity 着色）；renderGcodeScore
      （**dimensions_scored==0 → 「整体不可评估」卡**——两态哨兵：overall_score
      的 0.0 兼表"未评估"，判定键必须是 dimensions_scored；**dimension.score
      null → "—" 绝不渲染 0**）；引擎文本 verbatim + data-i18n-skip
- 验证：smoke **127/127**（T93-T98：kind 上传/400 引导/两文件 diff schema+
      names+console/评分/void rc=2 透传/HTML 深链/模型 token kind 闸；exe 缺失
      响亮 SKIP；T96b 坏实现翻红-回绿闭环）；report_render **153 项**（argv 路径
      不上屏、null 两态、available:false 整块隐藏、未知 verdict token 中性渲染）；
      browser E2E +3（status gate 放行/列交换/深链/void 卡）；i18n FAIL 0
      （+60 词条）；ui_consistency 全绿；截图 v023_gcode_{diff_advanced,score_simple}.png
- 明确不做：多参考诊断（3+ 文件 UI）；--structure FEM diff（fem_delta/structure
      恒 null 按 absent 隐藏）；3D 点云可视化；physics_delta.layers[] 逐层明细
      （只渲染标量，JSON 原样透传——不在服务端裁剪引擎输出）；进度轮询（秒级
      运行，秒表即可）；--fail-on*/--profile/--machine 暴露（后续版本）

### v0.24.0 — 换模即清场：会话切换滞后状态清扫 + 运行期换模竞态（2026-10-03）

> 背景：v0.18 时被判「既有会话语义」保留的 resetTuningState 半清场（backlog 挂了
> 五个版本），在 v0.22 hero 重设计后升级为真问题——上传新模型后，旧模型的绿色
> 「✅ 安全」hero 继续顶着新模型显示（分析失败/取消时无限期）。枚举又抓出两个
> 同族缺陷：state.history 不随会话清空 → 新模型首轮渲染拿旧模型 run 当 prev 出
> **跨模型 ▲▼ delta 胶囊**；A 运行中上传 B 时 analyze(B) 被 running 闸**静默丢弃**
> （非 auto 不排队）且 A 的迟到响应**渲染进 B 的会话**（错报告+错热图+错历史刷新）。
> independent-REFUTE 一轮（VERDICT: REJECT——2 blocker + 2 major + 5 minor）：
> blocker#1 `#pd-warn-promoted` 首渲染后常驻 `#summary-cards` 内，`innerHTML=""`
> 会永久杀死镜像节点（实现期实踩：摘离后 renderReport 的重挂载以它自己的
> lift-out 为前提，节点脱离 document 后 `getElementById` 恒 null——E10b 探针当场
> 爆炸；修法=摘离后送回静态老家，boot 缓存 `pdwStaticHome`）；blocker#2 服务端
> `_batch_cancel` 毒雷——**一手源核查推翻**：analyze 端点起手 discard（server.py
> 「iter 44 refuter-reproduced」注释在案），B 的补跑请求会先清雷，仅客户端闭包
> 捕获 runToken 采纳；major：scheduleAuto 受实时分析开关门控（改专用
> `state.pendingRun` 直连 analyze）；state.lastApplied 不清会伪造「引擎按域调整
> 为 X」toast（补清）；5 minor（cand-raw-fold 与 detail-open 同属用户所有权——
> 不收起；cand-body 恢复 boot 占位行需语言恢复后缓存 `candBodyBootHTML`；
> alerts-card 是 inline display 机制非 :empty；renderHistory 空态「尚无运行。」
> 断言口径；catch 层也要 token 守卫）全部采纳。
> 测试期教训：beam 夹具引擎仅 27-66ms，任何时序窗口都不存在——新增
> `test_data/cube_100.stl`（实心 100mm 立方体）+ suite 服务器 `STRATUM_UI_GRID=24`
>（cube 运行 1.26s、beam 不受影响），换模/取消/竞态窗口全部确定性化。

- [x] **`resetResultsPanel()`**（resetTuningState 起手调用）：empty-guide 恢复显示
      （no-report 门随之回开）→ pdw 镜像 lift-out+清空+送回静态老家 →
      summary-cards 清空（:empty 自隐藏）→ 8 个 KPI 格与 12 个 cp-* 回显格回
      "—"（sf-*/load 色类一并复位）→ fast-mode-tag/filament-note/engine-console/
      analyze-error/validate-refused 隐藏 → alerts-card inline 隐藏 →
      cand-bars 清空 + cand-body 恢复 boot 占位行 → state.history=[]/ab=[] +
      renderHistory/renderAB 重绘空态 → updateStickyVerdict(false) 自隐
- [x] **analyze() 会话绑定**：`runToken` 起手捕获；取消闭包发 runToken（取消它
      代表的那次运行）；then/catch 双层 `state.token !== runToken → return`
      （迟到的旧会话响应——报告/错误卡/toast——全部丢弃；finally 照常恢复按钮）
- [x] **pendingRun 队列**：running 闸挡下的 manual 运行置 `state.pendingRun`
      （不经 scheduleAuto——那受实时分析开关门控，关掉时假队列），finally 优先于
      autoQueued 直接 `analyze(false)`（新会话首跑不再静默蒸发；手动重入/键盘
      Ctrl+Enter 同受益）
- [x] **配套**：resetTuningState += `state.lastApplied=null` + gcode 面板让位
      （`showGcodeResultPanel(false)`——原先只在 analyze 成功路径换回，失败/被丢
      时 gcode 结果滞留）；两处 stale 注释更新（no-report 门控理由重写）
- 验证：smoke **127/127**；render_check **153**；ui_consistency；i18n FAIL 0；
  browser E2E + browser_en 全绿；ux_alignment **50 项**（新增 E12 七断言：
  取消式 pristine 窗口断言 8 容器 + pdw 存活 + 跨模型 delta 不出现 + 新会话
  history 恰 1 行 + 竞态收敛「重置后 cp-walls≠8、终值=2」）。**牙齿实证**：
  sabotage 三处修复点（resetResultsPanel 早退/守卫失效/队列失效）跑 E12——
  六断言全红（delta:true、sawStale:true、finalWalls:"8" 三个 bug 活体在案），
  还原后全绿
- 遗留 backlog：EN 模式下 cand-body 占位行依赖 boot 缓存（语言切换后上传才会
  拿到新语言占位——当前语义正确：捕获时语言）；E12c 的竞态窗口依赖 grid=24
  的 cube 夹具（引擎提速超 10x 需重标定）

### v0.25.0 — G-code 应力调优：--gcode-in/out 全链路（2026-10-03，v0.8.1 最重挂账闭环）

> 契约探针先行（引擎 0.26 一手源）：`--gcode-in/--gcode-out` 成对、`<out>.tune.json`
> sidecar（段/热区计数、coverage_pct、e_drift_pct、p_hi/m_hot/vm_floor_mpa、
> patch_coverage_ratio **-1=不适用哨兵**、alignment+盲区）；**JSON 报告 0 diff**
> （diff 实测）——纯 artifact 通道（heatmap 同族）；mismatch 切片 = coverage 0 +
> console 告警的合法态。independent-REFUTE 一轮（VERDICT: REJECT——4 major + 7 minor
> 全采纳）：fallback 剥**带值 flag** 留孤儿 positional（引擎今日 rc=0 容忍是运气非
> 契约——顺带翻出 `--heatmap-json/-bins` 自 v0.8 起的潜伏同款，一并修=值感知剥离
> `_strip_fallback_flags` + T103 回归钉）；调优产物无清理语义（对照 heatmap/base
> profile 读后即删——改「新 run 删旧产物 + tune.json 读后删」，auto 重跑不再堆积
> MB 级文件）；attach/detach 删文件撞 in-flight 句柄（best-effort + evict 兜底）；
> 现状陈述纠错（`--progress-json` 是裸 flag 非带值先例；`_validated_float` 不存在
> ——新建）；rc==0+sidecar absent（旧引擎剥 flag）也须清产物指针；patch_coverage_ratio
> -1 上屏=裸哨兵（渲染「—」）；tune 卡挂 detail-wall（新手不见不可控卡）；F5 后
> 数值输入不持久而附件还在服务端（数值随 sessionStorage 走 + 响应 `gcode_attached`
> 补 chip）；scheduleAuto 委托选择器/渲染调用点接线点名。
> 明确不做：batch 不带 gcode 通道（快速参数对比定位，逐 combo tune 产物无消费面
> ——server 注入点只在 single analyze，注释成文）。

- [x] **服务端**：`/api/gcode-attach`（raw body、model session 专属、.gcode/.gco
      白名单、控制字符拒绝、覆盖式重附）+ `/api/gcode-detach`（清指针删文件）+
      `GET /api/gcode-tuned`（RFC 5987 双头下载，`<显示名去扩展>.tuned.gcode`）；
      analyze 在 session 有附件时注入成对 flag（产物指针**逐 run 重算**：成功+有
      sidecar=设置，失败/取消/absent=清除——旧产物不冒充本次）；响应顶层
      `gcode_tune`+`gcode_attached`（sibling-key 纪律，同 heatmap/applyable）；
      `_validated_float` 域校验 400；`_FALLBACK_FLAGS` += 5 flag + 值感知剥离
- [x] **前端**：分析选项区 advanced-only 附件行（file input+chip+移除钮）+ 三数值
      （留空=引擎默认，非空才进 body）；attach/detach/数值 change 走 scheduleAuto；
      `renderGcodeTune`（数字 verbatim 无 UI 侧阈值着色——coverage 50%/70% 是引擎
      console 语义；对齐/盲区 prose 带 i18n skip；-1 哨兵渲染「—」；token 在场才有
      下载钮）；resetTuningState 清 UI 附件态（clearGcodeTuneUI——v0.24 交叉点：
      新 session 无附件，chip 不得谎称）+ resetResultsPanel 隐藏审计卡；F5 数值随
      sessionStorage 持久、chip 由响应 presence 补
- 验证：smoke **141/141**（+14：T99 族 4 项 attach 生命周期/域闸 + T100 族 3 项
  调优分析+审计形状+下载双头 + T101 族 3 项数值域界 + T102 族 2 项 detach 断链 +
  T103 族 2 项值感知剥离回归）；render_check **159**（+6 §28：审计 verbatim/
  -1 哨兵/absent 隐藏/无 token 无钮）；browser E2E +2（attach→auto 分析→卡渲染+下载钮、
  detach→卡隐藏）；i18n FAIL 0（+36 词条）；ux/browser_en/consistency 全绿；
  fixture `test_data/gcode-tune-audit.json`（真引擎 sidecar）+ `cube_100.stl`（v0.24）
- 遗留 backlog：调优产物下载在 rc!=0 后按「无本次产物」诚实清除（已实现），但
  旧产物文件本身在 Windows 句柄占用时靠 evict 兜底（best-effort 已文档化）；
  mismatch 切片（coverage 0）用户引导文案（当前靠引擎 console 告警原文）——待
  真实用户样本再议

### v0.26.0 — gcode-diff 机器/热端键暴露 + 调优通道 DOGFOOD（2026-10-03）

> 两轮：**轮 1（DOGFOOD，迭代 99，self-refuted 轻量）**：合成与 beam 几何匹配的
> 切片夹具 `test_data/gcode/beam-slice.gcode`（Cura 风格 `;TYPE:WALL-OUTER/
> WALL-INNER` 标记——引擎二进制 strings 一手探得词表；FILL/SPARSE/Sparse Infill
> 三探均被 excluded_feature 排除，填充段不参与采样是引擎实际行为，如实记录），
> 首次驱动调优活体形状：**candidates 160 / tuned 80 / coverage 50% / E 漂移
> +2.43%**，产物 E 值精确 +10% 改写（3.3131→3.64441 逐行核实）；T105 字节级
> 断言（audit tuned>0 为主证、下载产物≠输入为辅证——引擎 tuned=0 时也会规范化
> 重排格式，字节差异单用不成两态判别，注释如实降级）。
> **轮 2（迭代 100，independent-REFUTE：VERDICT REQUEST CHANGES——2 blocker +
> 3 major 全采纳）**：blocker#1 白名单来源≠消费者——stratum `--schema` 供枚举、
> gcode-diff.exe 消费（自身无 --schema 且两构件存在 3 天版本错位），fail-loud
> 400 会错杀或放行静默 miss；修=**透传 + 响应回显**（≤32 字符无空白形状闸）。
> blocker#2 argv 生效零可观测面（±--machine 报告字节级相同）；修=响应
> `machine`/`hotend` 回显字段。major：score 侧是死接线（评分机器无关实测）→
> 拒收 400；selects 显隐复用 `(diff && advanced)`；「自动」文案误导 →「不指定
> （不钳制固件限速）」。

- [x] 服务端：`--hotend` 枚举进 `_refresh_select_surfaces`（fallback 6 键）+
      `/api/params` 下发 `hotend_values`；`_gcode_diff` 透传 machine/hotend
      （形状闸 400）+ 响应回显；`_gcode_score` 拒收两键（400 引导切对比模式）
- [x] 前端：G-code 工具面板「机器/热端」双 select（options=探针枚举，选项仅
      便利非闸；显隐=diff+advanced 与 slot B 同一谓词；会话内保留、不进
      localStorage——与 gcodeState 既有语义一致）
- 验证：smoke **146/146**（+4：T106 透传+回显/坏键 400/score 拒收/params
  hotend_values）；browser E2E +1（下拉 populated≥11 且三态显隐）；i18n FAIL 0
  （+8 词条）；render/consistency/ux/browser_en 全绿
- 遗留 backlog：gcode-diff `--profile`（评分阈值配置文件上传通道，重、窄受众，
  挂账）；填充段 excluded_feature 的引擎侧语义（是否漏接 SPARSE 词表——引擎队
  压力点候选）；mismatch 切片用户引导（延续）

### v0.27.0 — 小白闭环四件套：示例模型 / 用途问句预设+材料一问 / 自动调参 / 拿去打印（2026-10-04）

> 背景：产品规划轮定调「小白剩下的不是再减面板，而是三个断点——流程走不到头、
> 唯一必做的决策没人替他做、语言层只翻译了一个数」。本轮落 P0 四件套。
> independent-REFUTE 一轮（VERDICT: REJECT——1 blocker + 8 major + 4 minor 全采纳，
> 详见 loop-journal 迭代 101）；**fixture 探针前置**（真引擎 12 组实测）：beam 族
> 默认参数全部 rank1 ✅（refuter 实测推翻初版 E2E 前提）、建议面每模型 ≤1 条、
> nozzle 0.25 建议反而降 SF——自动调参今日产不出多轮真链，循环停止判定因此抽成
> 纯函数 `autoTuneStepDecision`（report.js §29 合成全 shape）。

- [x] **示例模型**：`sample/beam_100x10x4.stl` 随包分发（spec datas +
      verify 断言）；`POST /api/sample` 走与会话创建同构路径（kind=model
      正常 FIFO）；status `sample_available` 门控双入口——empty-guide 主按钮 +
      「模型」面板常驻链接（REFUTE#4：首渲染隐藏 empty-guide 后入口不死）；
      F5 恢复/换模清场全走既有会话语义，零新状态
- [x] **用途问句 + 材料一问**：PRESETS += `use`（要受力/不确定就选这个/打草稿/
      摆件），presets_for 透传；预设卡 = use 主行 + label·desc 副行（仍是
      `<button class="preset-btn">`——setPresetEnabled 与 C4 契约钉死）；
      STL 族显示材料 select（枚举=--schema 实时面，默认 PLA），答案粘滞并
      在 applyPreset 里**同轮覆盖**预设的 PLA（collectParams 只发 dirty，写行
      先于 analyze）；3MF 隐藏（文件自带材料；预设钉 PLA 为既有文档行为）；
      顺修面板 hint 陈旧「9 项」→10 项
- [x] **自动调参（≤3 轮）**：建议卡第三按钮（simple-only，渲染门=rank≥2 且
      nApplicable>0——verdictRank 与 hero 边色同一显示映射）；驱动器编排
      apply→analyze→再判，停止条件全诚实（已安全/建议耗尽/建议签名不变/轮上限/
      本轮未完成失败或取消/换模静默）；`state.lastReport` 引用哨兵区分轮成与
      轮败；运行中按钮=「第 N/3 轮·点击停止」；生命周期三点位清理（换模
      resetTuningState / unknown-token / stopAutoTune 本身——REFUTE#3 幽灵态）
- [x] **拿去打印出口卡**（#next-step，风险卡之后，simple-only）：可写 3MF →
      档位 select +「下载优化后的 3MF」（复用 export3mf 全审计路径，措辞如实
      「按所选档位优化」——REFUTE#2 假乐观；成功/失败补 toast 修单层可见性）；
      STL/裸 3MF →「照抄进切片软件的参数」折叠卡（值=引擎 input 回显，cp 同源
      键映射）+ 复制按钮（clipboard 回退 execCommand）+ 换 3MF 可写回提示
- 配套：词典 ~60 条（use 整句 + 副行「安全 · 」分隔符词级防误伤「安全系数」）；
      UI_VERSION 0.27.0
- 验证：smoke **152/152**（+T107 族/T108 族）；render_check **182**（+§29：
      verdictRank 10 形态/决策器 8 形态/CTA 三态——real3 自带 λ=86 屈曲警示，
      rank1 对照需剥离 buckling）；ux_alignment **全绿**（+E13-E16 12 项真引擎
      E2E：示例全流程/PETG 回传+预设同轮覆盖/nozzle 0.4→0.25 一轮诚实停止/出口卡
      三变体+高级隐藏）；browser/browser_en/i18n/consistency 全绿；sabotage
      ×2 刀（砍 /api/sample 路由、循环早停+出口卡早退）对应断言全翻红后还原
- 遗留 backlog：exportOrca 简单模式 toast（同族单层修复）；presetApplied 死
      状态；多轮真链 E2E（待引擎建议面扩容）；P1 语言层（人话解读扩面/术语弹卡
      /错误行动化扩展/档位对比摘要行）与 P2 首启（端口占用自动换位）见规划轮

### v0.28.0 — 小白语言层 + 同族小修：屈曲/断裂人话前缀 / KPI+术语「?」弹卡 / 错误行动化扩展 / 档位摘要行（2026-10-04）

> 背景：v0.27 闭环四件套清偿规划轮 P1 语言层 backlog。独立 REFUTE 一轮
> （VERDICT: REJECT——1 blocker + 6 major + 7 minor 全采纳，详见 loop-journal
> 迭代 102）；blocker 推翻「引擎排序第一」措辞前提（candidates 是 preset 枚举
> 无 rank 字段，对照 orient.candidates 有显式 rank），摘要行改述枚举事实。
> 顺修 REFUTE 抓出的既有有害按钮：rc=124 超时文案含「分辨率」会命中网格×2
> 正则——加倍网格让超时更糟，现已按超时类抑制。

- [x] **A1 屈曲/断裂横幅人话前缀**：`#pd-warn-promoted`（简单模式横幅）在引擎
      verbatim 前加一句机制人话（「零件可能被压弯/压塌（屈曲）——引擎原文：…」），
      键于 `pd.buckling_warning` / `fracture_risk_detected===true && fracture_assessment`
      ；字段缺一不加；引擎 prose 仍走 data-i18n-skip span；**墙内（#phase-d-detail）
      保持纯 verbatim**（人话只上横幅）；前缀零严重度用词（REFUTE 核）
- [x] **A2+A3 术语「?」弹卡**：自研零依赖单例弹卡（.term-q 按钮读自身 title——
      悬停与卡同源不漂移；EN 走 MutationObserver 既有 _langAttrs 通道零新跳；
      点外/ESC 关、同开一张、惰性注册 + vm-stub 全守卫）；TERM_INFO 5 位点 +
      KPI 行 4 标签（刻度静态说明进卡，overall_band 缺口不自造档位）；
      renderReport 开头 closeTermPop 防跨渲染孤儿
- [x] **A4 错误行动化扩展**：内存类（bad_alloc/内存/out of memory）→「开快速
      预览并重跑」（--fast 封顶 FEM 体素网格=OOM 分配点）；排队满→一句
      「本次请求未开始」引导（verbatim 已自带稍后/取消指引，不造重复按钮）；
      stderr verbatim 不动
- [x] **A5 档位对比 novice 摘要行**：#cand-bars 门内（≥2 可行）一行只述枚举
      事实「第一个可行档位（引擎枚举序）：safe —— 安全系数 3」（SF 口径=
      表格 Math.round；REFUTE blocker 修正措辞）
- [x] **A6/A7 同族小修**：exportOrca 补成功/失败双 toast（今日唯一触发点在
      高级区=冗余保险，防未来简单模式调用方复活单层缺口）；presetApplied 死
      状态连注释全删（v0.22 删步骤条后零读者，写点两处）
- 配套：LANG_EN 整句 4 + 词级 2（em-dash 分隔符防「安全系数」误伤）；
      INTENTIONAL +3（组合前缀片段，判例同「实时分析：」）；UI_VERSION 0.28.0
- 验证：smoke **152/152**；render_check **195**（原 182+§30 13 条）；ux_alignment
      **全绿**（+E17 8 项真引擎：横幅前缀/摘要行/弹卡四态/孤儿守卫——孤立化
      修正后 sabotage 翻红实证：btn click 的点外关闭路径会掩盖守卫，改直调
      analyze(false)）；browser/browser_en/i18n/consistency 全绿；sabotage ×3 刀
      （砍前缀/砍摘要行/注释 closeTermPop）对应断言全翻红后还原

### v0.29.0 — 首启与分发：端口占用自动换位 + 安装包首启走查 + 页高回收（2026-10-04）

> 背景：v0.27 规划轮 P2 收尾。独立 REFUTE 一轮（VERDICT: REJECT——**实验实证
> 推翻 B1 可达性前提**：win32 上 HTTPServer 默认 SO_REUSEADDR 允许两实例静默
> 共存同一端口，「旧实例未杀」头号场景根本不抛 OSError、浏览器连旧实例；
> 「其他工具占用」报 10013 非 10048——原 fail-loud 分支在发行平台近乎死代码。
> 详见 loop-journal 迭代 103）。

- [x] **B1 端口占用自动换位**：win32 绑定改 `_ExclusiveServer`（SO_EXCLUSIVEADDRUSE
      + 关 REUSEADDR 劫持）让占用真正失败（实测 10048；裸占用者路径 10013 均入
      匹配集）；默认端口路径→`ThreadingHTTPServer((HOST,0))` 无竞换取空闲口 +
      `global PORT` 重绑（banner/浏览器开实际口）+ stderr 醒目披露；显式
      STRATUM_UI_PORT 与非占用类 OSError 维持 fail-loud（REFUTE 裁决：显式=
      确定性契约，三处测试基建轮询固定端口，静默换位=全部挂起）；换位二次失败
      嵌套 try；F2 文案的「由 STRATUM_UI_PORT 指定」从句改为 env 真存在才出现
      （sabotage 实测暴露的谎报缺陷）
- [x] **B2 安装包首启走查**：verify-installer.ps1 追加 `sample_available:true`
      断言（小白示例随包分发全链路）；smoke 端口改每轮动态挑空闲（EXCLUSIVEADDRUSE
      语义下硬编码 8803 会踩上一轮 TIME_WAIT 假失败）；真实跑 build.ps1 全构建
      （0.29.0 Setup.exe）+ verify 全绿（静默装→布局→sha→首启 status→卸载干净）
- [x] **B3 页高复核与回收**：beam 口径简单模式实测 **2376px 超预算 176**（v0.19-
      v0.27 累积债——仅 v0.27 next-step 卡 +138，无人复测；index.html 预算注释
      指向的 output.verification.md 无记录=文档腐化）；回收=条形图简单模式进
      detail-wall（v0.22 分层同款，A5 摘要行迁至 #cand-novice-line 常驻答题，
      高级模式照旧）→ **2118px ≤ 2200**（余量 82px）；E11 出口不变式不动
      （raw 表自动展开逻辑独立于墙）
- 配套：README 端口段/档位段更新；UI_VERSION 0.29.0
- 验证：smoke **157/157**（原 152+T109 族 5：显式撞口 fail-loud/默认撞口换位+
      披露/新口真服务/分类器匹配集/类属性）；render_check **195**（A5 断言随
      容器迁移更新）；ux_alignment 全绿；browser/browser_en/i18n/consistency
      全绿；安装包 verify 全绿；sabotage ×2 刀（分类器恒 False→T109b/c/d 红；
      sample 断言换不可能模式→verify FAIL）翻红后还原

### v1.0 — 方向四：3D 可视化（半数被引擎契约卡住，见 D2）


- [x] a) WebUI 侧可先行（2026-08-19 完成主体）：STL WebGL 预览（自研 ~240 行，零依赖保红线 1；
      包围盒定中心/拖拽旋转/滚轮缩放）+ **方向候选箭头 overlay**（iter 63：④ 表行点击 ↔ 预览
      箭头高亮，readPixels 像素级验证；遗留子项：点击自动旋转对齐——rx*ry Euler 反解 + z-up
      交换为 iter 42 高危区，留专项轮；3MF 几何预览超零依赖红线待评估）
- [x] b) 风险热图：【v0.8 已落地】引擎 0.22+ 提供 `--heatmap-json`（bins³ 聚合），
      压力点解除——3D 体素视图 + 图例见 v0.8 c)
- 争议：内嵌 three.js（破红线 1，inline ~600KB）vs 自研最小 WebGL STL 渲染
  （~200 行，红线可保）——见 D2

## 3. 引擎队压力点（跨队请求，非本仓库工作）

> （公开库版本已移除——引擎探针数据与缺陷细节见内部 loop-journal。）

## 4. 开放决策点（阻塞项排序/技术选型）

- [ ] **D1 分发野心**：个人/内部调参工具 vs 对外安装包产品？
      → 产品化则 v0.4（方向三）前插到 v0.3（方向二）之前
- [ ] **D2 单文件红线**：方向四若启动，允许内嵌 three.js，还是自研最小渲染器保红线？
- [ ] **D3 自动调参停止语义**（v0.27 起）：今日循环停止码（safe/exhausted/
      unchanged/cap）全是 UI 侧从报告推导的哨兵——引擎若提供收敛/稳定信号
      （如「建议面与上轮一致」的一手判定），停止可变一手语义、多轮链路也可
      被 E2E 触达；接入前 UI 哨兵不动（显示映射纪律）。需与引擎队定字段。
- [ ] **D4 SnapmakerOrca 集成路线**：出口卡的「拿去打印」止于下载优化 3MF；
      Orca 侧如何接（预设包导入 / 原生读 stratum 写回键 / 插件）决定
      v0.27 出口卡与写回审计的下一跳，未定前不造 UI 侧转换器。

## 5. 过程约定

- **时间盒对抗迭代**：按 `~/.zcode/skills/adversarial-development-loop` 执行，
  每轮落 `loop-journal.md`；2026-08-18 会话实证 40 分钟可完成 2 轮
  independent-REFUTE（2 blocker 修复 + 套件 0→12）
- **ENUMERATE 契约面作为每轮前置**：本项目最大的坑是"以为的契约 ≠ 引擎当前版本的
  契约"——当日两处现状描述被证伪（lock 命名空间、usage 发现面）均由一手源探针抓出
- **测试随行**：smoke 套件随功能扩容；GUI 冒烟用 browser-use 补手动截图轮
  （`gui-test-screenshots/`）
- **引擎升级时**：先重验第 1 节证据表（usage 枚举、报告结构、lock 面），再动工
