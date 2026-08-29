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
- [ ] **挂账（未接，含原因）**：`--gcode-in/out`+`--gcode-vm-floor/m-hot/p-hi`
      应力调优工作流（最重：G-code 上传+成对 flag+`<out>.tune.json` 审计渲染，
      本轮裁决挂账）；`--vtk` ParaView 导出（④ 已有热图，用户面窄）；
      `--phase-a` 仅几何模式（`--fast` 已覆盖快扫；phase-a 会让 ④ 大半面板
      空转，需成套空态处理）；`--drucker-prager`（引擎 no-op 兼容位）、
      `--report`（文本通道）、`--optimize`（`--compare-profiles` 子集）= 非缺口

验证：`tests/test_smoke.py` 103/103（T74-T83 新增，全部真引擎 round-trip 为准）；
`report_render_check.js` 53 项（v0.8.1 新块 20 项，形状取自 2026-08-29 真跑探针）；
`browser_render_check.js` 全绿；GUI 冒烟截图 `gui-test-screenshots/v081-*.png`
（开关行/③b 新行/诊断面板/估算校准，无头 Chrome CDP 管线）。UI 0.8.1。

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

## 5. 过程约定

- **时间盒对抗迭代**：按 `~/.zcode/skills/adversarial-development-loop` 执行，
  每轮落 `loop-journal.md`；2026-08-18 会话实证 40 分钟可完成 2 轮
  independent-REFUTE（2 blocker 修复 + 套件 0→12）
- **ENUMERATE 契约面作为每轮前置**：本项目最大的坑是"以为的契约 ≠ 引擎当前版本的
  契约"——当日两处现状描述被证伪（lock 命名空间、usage 发现面）均由一手源探针抓出
- **测试随行**：smoke 套件随功能扩容；GUI 冒烟用 browser-use 补手动截图轮
  （`gui-test-screenshots/`）
- **引擎升级时**：先重验第 1 节证据表（usage 枚举、报告结构、lock 面），再动工
