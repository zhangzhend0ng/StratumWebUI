# Stratum-WebUI 路线图

> 建立于 2026-08-18，紧随当日 40 分钟对抗迭代会话（server 输入校验 + 请求闸两轮修复，
> 见 `loop-journal.md`）。所有契约证据来自 **引擎 0.21.0 一手源探针**（无参 usage 83 行
> + JSON v2 报告全结构 dump），非文档转述。
>
> 用法：随迭代勾销 `- [ ]`；引用代码处用函数/符号名（行号会漂移）；契约证据表注明
> 版本，引擎升级时**必须重验**再沿用结论。

## 0. 架构红线（所有方向不许破）

1. **零依赖**：Python stdlib + 自含 HTML UI（`index.html` + `report.js` / `stl-preview.js`，经典 script 标签、零构建链，无外部网络资源）。
2. **引擎是唯一事实源**：Python/JS 不复制任何评分/钳制/锁定规则，只渲染引擎 JSON；
   UI 侧编排（多次调用、批量候选）不算复制规则。

## 1. 契约现状证据（引擎 0.21.0，实测于 2026-08-18）

| # | 发现 | 证据 | 含义 |
|---|---|---|---|
| E1 | 报告大量字段未被 UI 消费 | 【2026-08-19 已大部分解决】`phase_c`/`phase_d`/`trust`/`warnings` 面板均已入 UI（会话 2）；仍遗留：sidecar diff/pareto 已入 ⑥ 面板，`findley` 渲染就位但触发条件未知（引擎侧），`--layer-time`/`--explain` flag 未接 | 屈曲/疲劳/分层正是"可打印性风险"工具的核心产出——零引擎改动即可大幅扩容价值 |
| E2 | 参数面已漂移 | 【2026-08-19 已解决】`PATTERNS` 现由引擎 usage 探针运行时解析（`_probe_surface`），7 种硬编码仅作 fallback；README 参数面描述改为动态探针口径 | 静态硬编码契约必漂移；usage 还暴露 `--layer-time` `--strict-tier` `--explain` `--sidecar-json` `--dry-run` 等 UI 未接 flag |
| E3 | lock 面远大于 UI 参数面 | usage 明示 lock 接受 layer_height / load / outer_wall_speed / retraction_length / retraction_speed / wipe / travel_speed 及 **OrcaSlicer 键**（brim_width、support_angle…）；实测 `--lock layer_height` rc=0、`--lock nozzle` rc=1（lock 命名空间=参数名，非 flag 名） | lock 只做类型闸不收紧白名单的既有决策（loop-journal 迭代 1）继续成立；锁 layer_height 等 UI 侧即可做 |
| E4 | 引擎错误信息 doc 漂移 | `--lock` 报错让用户 `run with --help`，但 `--help` 被当模型文件名解析；真正的发现面是**无参 usage** | 已列引擎队压力点 #1 |

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
- [x] b) **CI**（2026-08-19）：`.github/workflows/ci.yml` 三层（syntax 恒跑；
      tests/installer 由 `STRATUM_SDK_URL` secret 门控——引擎不入库，fork 上
      自动跳过）；verify-installer.ps1 补齐退出码判定（原为恒 rc=0 假绿）
- [x] c) **版本兼容策略**（2026-08-18）：报告含 `schema_version`，逐请求精确校验（不支持即 502 fail-loud，
      不静默渲染错版本字段——2026-08-18 已实现于 server.py `schema_supported`）
- 验证：verify-installer 进 CI；引擎版本矩阵冒烟

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

### v1.0 — 方向四：3D 可视化（半数被引擎契约卡住，见 D2）

- [x] a) WebUI 侧可先行（2026-08-19 完成主体）：STL WebGL 预览（自研 ~240 行，零依赖保红线 1；
      包围盒定中心/拖拽旋转/滚轮缩放）+ **方向候选箭头 overlay**（iter 63：④ 表行点击 ↔ 预览
      箭头高亮，readPixels 像素级验证；遗留子项：点击自动旋转对齐——rx*ry Euler 反解 + z-up
      交换为 iter 42 高危区，留专项轮；3MF 几何预览超零依赖红线待评估）
- [ ] b) 风险热图：**需引擎扩 JSON 逐区域/几何定位字段**（现 risks 只有文本
      `key_points`、phase_b 是标量）——依赖引擎队压力点 #3
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
