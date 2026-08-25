# Stratum WebUI — 工艺参数调参台

本地 Web UI，给 [Stratum](https://github.com/Stratum)（FDM 可打印性分析引擎）调
切片工艺参数。**零依赖**：Python 标准库 server + 自含 HTML（零构建链，JS 拆为 index.html 内联主脚本 + report.js / stl-preview.js 两个经典 `<script src>` 模块）。

## 架构

```
Stratum-WebUI                 ← 独立仓库，只消费 Stratum 的发布物
├── server.py                 ← Python stdlib ThreadingHTTPServer (127.0.0.1)
├── index.html                ← 主 UI（零外部资源，JS 只渲染 JSON）
├── report.js / stl-preview.js ← UI 拆分模块（报告渲染 / WebGL STL 预览）
└── bin/stratum.exe           ← SDK CLI 副本（或 STRATUM_BIN 指定）
     │
     └── subprocess ──► stratum.exe <model> --phase-c --phase-d --json report.json
```

**接口契约**：UI 与引擎之间是 Stratum 的 **JSON v2 报告**（`--json`）+ CLI 白名单
flag。引擎（C++）是唯一事实源——评分、安全系数、锁定/钳制规则全部在引擎侧计算，
Python/JS 不复制任何规则，只渲染引擎输出的 JSON。

## 快速开始

```bash
# 1. 准备引擎二进制（三选一）
#    a) 从 Stratum SDK 发布物复制：stratum-sdk-0.21.0/bin/stratum.exe → bin/
#    b) 设置环境变量：STRATUM_BIN=C:/path/stratum.exe
#    c) 把 stratum.exe 放进 PATH

# 2. 启动（Python 3.8+，仅标准库）
python server.py
#   -> http://127.0.0.1:8765
```

浏览器打开 `http://127.0.0.1:8765`：

1. **① 上传模型**（STL/OBJ/PLY/3MF/AMF）→ 自动跑一次分析
2. **快速预设**（新手 0 参数入口）— 安全 / 均衡 / 高速 / 外观 一键：自动设置
   全部 9 项打印参数并立即分析；预设由服务端定义（`/api/params` `presets` 字段，
   值随引擎枚举漂移自动兜底）。想手动微调？打开顶栏「高级模式」
3. **② 当前参数** — 引擎实际使用的参数（来自 JSON 报告 `input` 块）
4. **③ 调参**（高级模式）— 滑杆改参数 + 「锁定」勾选（对应引擎 `--lock` 语义）。
   **只发送你动过的参数**：未动参数沿用引擎默认（STL 输入）或 3MF 自带的
   切片配置（Orca 导出 3MF 的 wall/infill/temp 等原样作为基线）；换模型
   上传会重置全部改动与锁定，新模型按自身基线分析
5. **④ 分析结果** — 几何风险、安全系数、参数建议、引擎推荐行；Phase C/D 结构细节
   （Hill48/热应力/层间残余/分层/老化、屈曲/疲劳/断裂/Weibull，含 1e10→∞ 哨兵判别）、
   warnings、⑥ 模块可信度徽章
6. **⑤ 候选档位对比** — safe/balanced/fast/appearance 对比表（Goal/EstTime/EstMat/EstSF）
7. **写回下载** — 仅 `.3mf` 输入可用：`--optimize-3mf <profile>` 下载新 3MF，
   响应附写回审计头（applied/skipped/verified，来自 `--sidecar-json`）；
   「预览写回（dry-run）」跑 `--dry-run` 出引擎审计表不落盘；「严格可信层」
   勾选透传 `--strict-tier`

## 可调参数（滑杆 ↔ CLI flag，高级模式内）

简单模式默认只提供「快速预设」按钮；逐参数微调需打开高级模式。9 项参数：

| 滑杆 | CLI flag | 范围 | 单位 |
|---|---|---|---|
| 壁数 | `--walls` | 1-20 | — |
| 填充率 | `--infill` | 0-100 | % |
| 填充图案 | `--pattern` | 引擎 usage 自动同步（回退 7 种） | — |
| 材料 | `--material` | 引擎 usage 自动同步（回退 PLA/PETG/ABS/CUSTOM） | — |
| 喷嘴直径 | `--nozzle` | 0.1-2.0 | mm |
| 喷嘴温度 | `--nozzle-temp` | 150-350 | °C |
| 热床温度 | `--bed-temp` | 0-200 | °C |
| 打印速度 | `--speed` | 1-1000 | mm/s |
| 冷却风扇 | `--cooling` | 0-100 | % |

「环境与载荷」面板（③b，未触碰不发送）：`--load`（白名单防引擎静默回退）、`--force`、
`--service-time`、`--service-temp`、`--ambient-temp`、`--humidity`、`--anneal-hours`、
`--fatigue-cycles`——域以引擎校验为准（错误文案即一手源）。

「锁定」勾选 → 引擎 `--lock`（参数钉在现值，搜索域坍缩/写回跳过）。除滑杆行外，
③ 面板下方还有一层「可锁定（CLI 直控）」复选框（layer_height / retraction 族 /
wipe / travel_speed 等，清单同样来自 usage 探针自动同步）；载荷类型 select 自带锁定。

## 调参工作流（v0.3）

- **运行历史 + A/B 对比**：每次分析留档（本会话最近 `STRATUM_UI_MAX_HISTORY`（默认 10）次，仅 nominal 值）；
- **方向优化**：① 面板「方向优化」复选框 → 引擎 `--optimize-orient`，④ 面板渲染方向候选表
  （rank/方向向量/代价/Z 高/底面，引擎排序；批量运行为整批开关）；STL 输入时候选方向以
  箭头叠加在 3D 预览上（rank 1 金色、其余灰蓝），点击表行高亮该候选（红色）、再点取消；
- **引擎控制台**：④ 面板折叠显示引擎 stdout 原文（含 Findley 等跳过项理由、`--explain`
  的逐条建议 grounding，JSON 不携带）；
- **报告下载**：① 面板「下载报告 JSON」→ `GET /api/report?download=1`（最近一次成功运行的全量报告）；
- **STL 3D 预览**：① 面板自研 WebGL 预览（零依赖；二进制/ASCII STL、包围盒定中心、拖拽旋转、
  滚轮缩放、>150 万三角抽稀；3MF/其他格式显示占位文案）；
  点击两条历史条目即出 A/B 差值表（Δ 涨绿跌红；null=未评估不参与差值；载荷判定
  枚举行显示转变而非数值）。
- **批量进度**：批量运行期间 `GET /api/history` 恒携带 `batch` 键（`{done,total}`
  跨并发批量求和；null=空闲）——进度计入每个 combo 含失败者（失败组合不进历史，
  不能用历史条目数计进度）。
- **取消**：分析进行中「分析/优化对比」按钮变为「取消」——服务端杀引擎进程 +
  前端 abort（`POST /api/cancel`）。键盘：`Ctrl/Cmd+Enter` 分析、`Esc` 取消
  （复用按钮 cancel handler，运行中重入被 `state.running` 闸住）。
- **交互（v0.5d/v0.6/v0.7）**：简单/高级双模式（顶栏分段控件）；toast 通知（err 常驻、
  ok 5s）；调参 baseline 状态机（行级 ↺ +「重置全部」）；分析耗时秒表（纯客户端，
  无伪进度）；拖放上传（drop 写回同一 file input）；**实时分析 auto 模式**（默认开，
  ③ 区开关、`localStorage` 持久化：参数/环境/锁定/方向变化 800ms 防抖自动重跑；
  运行中手动优先、被挡 auto 排队补跑、批量期间挂起）；设计令牌体系 +
  `prefers-reduced-motion` 降级。**一键预设**（v0.7）：简单模式 0 参数——4 个
  preset 按钮（安全/均衡/高速/外观）一次设置全部参数并立即分析，滑杆移入高级模式。
- **自定义候选批量跑**：⑤ 面板把当前滑杆捕获为自定义候选（≤8 个）→ 批量运行
  （`POST /api/batch`，纯编排多次引擎调用）；全部组合先校验后执行（坏组合 400
  零副作用），单个失败不影响其余。
- **并发保护**：所有重引擎调用（分析/批量/写回/预览）共享并发池
  （`STRATUM_UI_MAX_CONCURRENCY`，默认 2）+ 有界排队（`STRATUM_UI_MAX_QUEUE`，
  默认 8，满则 503）。
- **写回前置校验**：上传时检测 3MF 是否含 `Metadata/*.config` 切片设置——CAD 裸导出的
  3MF 可分析但**不可写回**（`/api/upload` 响应 `writable: false`，UI 禁用写回按钮，
  `/api/export` 直接 400 而非引擎 rc=1 透传；写回**预览不设门**——引擎 dry-run 无需设置）。
- **写回审计细节**：写回下载后 ⑤ 面板展示完整审计（重跑 SF vs 搜索估计、SF 来源、
  逐项写入明细、Pareto 前沿，来自引擎 `--sidecar-json`）。
- **Orca 工艺建议**（⑦ 面板）：分析自动带 `--orca-suggest --explain`，引擎结构化输出
  （decision/display 档、置信度、grounding 模块）直接渲染；`--explain` 的逐条
  trust grounding（kb_module/trust_source）进入引擎控制台（verbatim 折叠区）；
  旧引擎自动去 flag 重试。
- **求解器诊断与字段面扩容**（2026-08-19 会话 8，iter 67-75）：④ 面板新增 Phase B
  求解器诊断（CG 收敛提示；未收敛/网格部件合并警示以「Phase B:」前缀进入警示列表）、
  屈服单元行；建议项带优先级徽章 `[P n]` 与权衡文案；候选表体积/SF 格悬停显示
  材料·耗材·实体与 SF 来源（引擎原始串）；支撑体积不可用时表下显式声明。
  预览解析对非有限顶点与畸形 facet 防御性整块丢弃（`dropped` 计数体现在降级文案中），
  数值渲染 helper 对非数值引擎值显示「—」而非 NaN。

## 首跑向导（v0.4a）

启动时找不到 stratum.exe 不再退出：浏览器打开后 ① 面板出现向导，粘贴
stratum.exe 完整路径 → 服务端 usage 探针校验（防误指普通 exe）→ 持久化到
`~/.stratum-webui.json`（重启自动生效；解析顺序 env > bin/ > 配置 > PATH）。
不接受 UNC 网络路径（`\server\share\...`）——本地工具不从网络执行引擎二进制。

## 已知边界（v0.1）

- **层高（layer_height）不可直接调**：CLI 无 `--layer-height` flag。层高通过
  safe/balanced/fast/appearance 档位候选体现（对比表 diff 中可见）。若需要直调，
  属引擎侧独立决策（`--layer-height` flag 或 C API `stratum_config_set_layer_height`
  via ctypes）。
- **retraction / wipe / travel_speed 等可锁定但不可调**：有锁定复选框（--lock 面），
  但无滑杆（CLI 无对应值 flag；Orca 建议数值只在写回预览/审计中体现）。
- 无 3D 风险/应力热图查看器；无云端；仅 127.0.0.1 本机。
- 刷新页面（F5）会自动恢复上传会话并重新分析（token 存 sessionStorage，
  服务器重启后失效并提示重新上传）。

## 打包分发（Windows 安装包）

`packaging/` 把本仓库打成用户可直接安装的 `Setup.exe`（PyInstaller onedir +
Inno Setup，无 Python 依赖、无网络请求）：

```bash
# 前置：Python 3.8+（仅构建时需要）、bin/stratum.exe 已就位
#       Inno Setup 6（可选）：winget install -e --id JRSoftware.InnoSetup

powershell -ExecutionPolicy Bypass -File packaging/build.ps1
# 产物：
#   dist/StratumWebUI/                    ← 绿色版，双击 StratumWebUI.exe 即用
#   dist/installer/StratumWebUI-Setup-0.1.0.exe  ← 安装包（开始菜单/卸载器）
```

用户侧体验：双击 `Setup.exe` → 安装向导（默认装 Program Files，可选"仅为我
安装"免管理员）→ 开始菜单"Stratum WebUI" → 启动后自动打开浏览器。

实现要点：

- `server.py` 对 PyInstaller frozen 布局做了适配：`index.html` 从
  `_internal/`（`sys._MEIPASS`）读取，`bin/stratum.exe` 相对 exe 所在目录解析；
- 构建工具（PyInstaller `6.22.1`）pin 在 `packaging/requirements-build.txt`，
  由 `build.ps1` 装进独立 `.venv-build`，不污染用户环境也不随产物分发；
- `packaging/ChineseSimplified.isl` 是检入仓库的官方简中翻译（Inno Setup
  安装器不一定带语言包，winget 静默安装完全不带）；
- 应用图标由 `packaging/make_icon.py` 程序化生成（「浮层」设计：渐变层堆 +
  悬浮发光的顶层，隐喻"掀起一层来调参"，Pillow 仅为重生成时的依赖）：
  `stratum-webui.ico` 同时嵌入 exe 与安装器；网页 favicon 与页头 logo 是
  同款 SVG（源文件 `packaging/favicon.svg`，base64 内嵌进 `index.html`）；
  备选方向（光切片/等高线）保留在 `packaging/icon_concepts.py`；
  注意：PyInstaller 的 EXE 缓存不校验 `.ico` 内容（只记路径），改图标后
  需删除 `build/StratumWebUI/` 再构建，否则旧图标会被静默带上；
- 打包后的 exe 保持控制台窗口：日志可见、Ctrl+C 退出、`stratum.exe` 子进程
  不闪窗。frozen 版本号（0.1.0）维护在 `installer.iss` 的 `MyAppVersion`；
- 自动化验证：`powershell -File packaging/verify-installer.ps1` 静默装到
  临时目录 → 布局/接口冒烟 → 静默卸载 → 确认无残留。

发布到 GitHub Releases：把 `dist/installer/StratumWebUI-Setup-<ver>.exe`
（可选附带 `dist/StratumWebUI` 的 zip）作为 Release 资产上传即可。

## 安全模型

- 仅绑定 `127.0.0.1`；`subprocess` 用列表参数（**无 shell**，参数值不可能注入命令）。
- 请求闸（防 DNS rebinding / 跨站 CSRF）：Host 头必须是 `127.0.0.1` / `localhost` /
  `[::1]`；`/api/*` 的 POST 必须带 `X-Stratum-UI: 1` 头（同源 UI 自动携带；网页发起
  的跨站请求带不了自定义头，preflight 会被 501 挡下）。curl 调试时需加：
  `curl -H "X-Stratum-UI: 1" ...`。
- 前端可达的 CLI flag 是**白名单**：参数 flag + 环境与载荷 flag（`--load` 枚举服务端
  白名单，防引擎静默回退）+ `--lock` + `--optimize-3mf <profile>`（含 `--sidecar-json`/
  `--dry-run`/`--strict-tier`）。
- 上传模型存私有临时目录，进程退出时清理；模型文件永不被执行。上传扩展白名单
  stl/3mf/obj/ply/amf（引擎按扩展名选 parser，服务端保留真实扩展）。
- 引擎路径来源（向导持久化/config/PATH 命中）均拒绝 UNC 网络路径（`STRATUM_BIN`
  env 为开发者显式设置，不受此闸）。
- 版本闸：引擎报告 `schema_version` 逐请求校验（本版仅支持 2，不匹配即 502 fail-loud，
  不静默渲染错版本字段；`STRATUM_UI_ALLOW_ANY_SCHEMA=1` 为逃生阀）。

## 开发

```bash
# 冒烟（起服务后另开终端）
python server.py &
curl http://127.0.0.1:8765/api/status
curl -F "" ...   # 或直接用浏览器上传 test_data/beam_100x10x4.stl
```

环境变量：`STRATUM_BIN`（二进制路径）、`STRATUM_UI_PORT`（默认 8765，需 1-65535 整数）、
`STRATUM_UI_GRID`（FEM 网格，默认 16，引擎域 4-128）、`STRATUM_UI_MAX_SESSIONS`
（会话 FIFO 上限，默认 32）、`STRATUM_UI_PHASE_D`（=0 关闭 --phase-d，旧引擎逃生）、
`STRATUM_UI_ALLOW_ANY_SCHEMA`（=1 跳过 schema 闸）、`STRATUM_UI_NO_BROWSER`、
`STRATUM_UI_MAX_CONCURRENCY`（引擎并发，默认 2，1-16）、`STRATUM_UI_MAX_QUEUE`
（排队上限，默认 8，满 503）、`STRATUM_UI_MAX_HISTORY`（会话历史条数，默认 10，
需 2-100 整数）、`STRATUM_UI_ANALYZE_DELAY`（测试钩子：慢 runner）、
`STRATUM_UI_CONFIG`（配置文件路径覆盖，默认 `~/.stratum-webui.json`）
（=1 不自动开浏览器）。非法 PORT/GRID/MAX_SESSIONS 启动即拒（友好报错，非堆栈）。

## 测试（2026-08-19 会话 8 后）

`python tests/test_smoke.py`（需 `bin/stratum.exe`）：76 检查，含三层渲染验证——
T56 node 桩解析器检查（stl_nan_check.js）、T57 真 helpers 注入渲染检查
（report_render_check.js）、T58 无头 Chrome CDP 端到端（browser_render_check.js，
17 断言：渲染面、错误路径、真实引擎全管线、像素级 readPixels 预览、批量流、
写回流、A/B 对比、会话恢复；无 Chrome 时响亮 SKIP）。取消流的慢钩子验证为
一次性（见 loop-journal iter 92：钩子下无成功路径）。
