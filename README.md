# Stratum WebUI — 工艺参数调参台

本地 Web UI，给 [Stratum](https://github.com/Stratum)（FDM 可打印性分析引擎）调
切片工艺参数。**零依赖**：Python 标准库 server + 自含 HTML（零构建链，JS 拆为 index.html 内联主脚本 + report.js / stl-preview.js 两个经典 `<script src>` 模块）。

当前对接 **引擎 0.24.0 / JSON 报告 schema v3**（v0.8.0 起，v0.8.1 全契约面补齐）；
参数面由引擎 `--schema` 机器可读输出驱动（旧引擎自动回退 usage 正则探针）。

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

**接口契约**：UI 与引擎之间是 Stratum 的 **JSON 报告**（`--json`，schema v3；v2
兼容渲染）+ `--schema` 参数面 + CLI 白名单
flag。引擎（C++）是唯一事实源——评分、安全系数、锁定/钳制规则全部在引擎侧计算，
Python/JS 不复制任何规则，只渲染引擎输出的 JSON。

## 快速开始

```bash
# 1. 准备引擎二进制（三选一）
#    a) 从 Stratum SDK 发布物复制：stratum-sdk-0.24.0/bin/stratum.exe → bin/
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

简单模式默认只提供「快速预设」按钮；逐参数微调需打开高级模式。12 项参数：

| 滑杆 | CLI flag | 范围 | 单位 |
|---|---|---|---|
| 壁数 | `--walls` | 1-20 | — |
| 填充率 | `--infill` | 0-100 | % |
| 填充图案 | `--pattern` | `--schema` 自动同步（回退 7 种） | — |
| 材料 | `--material` | `--schema` 自动同步（回退 PLA/PETG/ABS/CUSTOM） | — |
| 喷嘴直径 | `--nozzle` | 0.1-2.0 | mm |
| 喷嘴温度 | `--nozzle-temp` | 150-350 | °C |
| 热床温度 | `--bed-temp` | 0-200 | °C |
| 打印速度 | `--speed` | 1-1000 | mm/s |
| 冷却风扇 | `--cooling` | 0-100 | % |
| 层高 | `--layer-height` | 0.01-5.0 | mm |
| 层间强度比 Z/XY | `--z-ratio` | 0.1-2.0（不设=随材料） | — |
| 填充角（CLT） | `--fill-angle` | 0-360 | ° |

「环境与载荷」面板（③b，未触碰不发送）：`--load`（白名单防引擎静默回退）、`--force`、
`--service-time`、`--service-temp`、`--ambient-temp`、`--humidity`、`--anneal-hours`、
`--fatigue-cycles`，以及 v0.8 新增 `--layer-time`、`--axis`（扭转轴）、`--machine`
（机器型号，含「自动(3MF 识别)」）、`--validate`（输入校验档位）、「修复网格朝向」
（`--repair-orientation`）——域以引擎 `--schema` 为准。v0.8.1 再加：

- `--precond`（预条件子，自动档不发送；ic0 失败自动回退 Jacobi 在 ④ Phase B
  诊断披露）、`--voxel-vote`（三轴投票体素化，破网格救急，约 3× 体素化开销）；
- `--prony-duration`（粘弹性载荷时长，回显 `requested_prony_duration_s`）；
- **发送值通道（诚实语义）**：`--retraction-length/-speed`、`--travel-speed`、
  `--wipe` —— 这些值**引擎不回显**在报告 `input` 块（只进 Orca 建议/外观通道 +
  设值即钉住该维），行悬停说明「UI 无法核实」；旧版仅可锁定，v0.8.1 起可调；
- **估算校准**：`--cal-time`/`--cal-mass`（实测打印时长/耗材克数，数字直输，
  0=不发送）→ 引擎在顶层 `calibration` 块披露时间/质量校准因子（applied/reason/
  measured/predicted/notes 全量），⑤ 候选行悬停显示「已校准估算」。

① 面板分析按钮旁的运行开关（v0.8.1 全套）：方向优化（`--optimize-orient`）、
快速预览（`--fast`）、外观评估（`--appearance`，④「外观评估」面板）、流变诊断
（`--rheology`，④「流变诊断」面板）、估算误差剖析（`--est-error-profile`，④
分维度误差表）、分辨率校验（`--resolution-check`，2 倍网格重跑，Phase B 详情
披露位移/应力偏差）、FEM 网格（`--grid` 每次运行可调，留空=服务端默认）。
④ 热图面板另有 bins 旋钮（`--heatmap-bins` 2..64，下次分析生效）。
① 面板还有「外挂基线」（`--base-profile`，flat Orca project_settings JSON：
优先级 CLI > 3MF 值 > 基线 > 默认，填 CAD 裸 3MF/STL 的参数空位；服务端做
尺寸/JSON 形状预检后落私有临时盘，键面合法性由引擎裁定）。

「锁定」勾选 → 引擎 `--lock`（参数钉在现值，搜索域坍缩/写回跳过）。除滑杆行外，
③ 面板下方还有一层「可锁定（CLI 直控）」复选框（retraction 族 / wipe / travel_speed
及引擎完整 Orca 键面，清单来自 `--schema` lockable 表自动同步）。

① 面板分析按钮旁还有「方向优化」（`--optimize-orient`）与「快速预览」
（`--fast`，FEM 网格封顶 12³，报告 `fast_mode:true` 披露预览级精度）两个开关。

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

### 引擎 0.24 接入（v0.8，2026-08-28）

- **schema v3 契约**：报告 `schema_version` 闸接受 2/3；5 个不确定度字段按 v3 规则
  渲染（plain=标量、`*_envelope` 孪生显示 "(lo–hi)" 区间带，两代报告都兼容）。
- **真实进度**：引擎 `--progress-json`（stderr NDJSON，阶段边界估算）→ 服务端
  增量解析 → `GET /api/progress` → 分析中按钮旁显示「分析中 42% · fem」
  （无进度时回退纯秒表；批量维持组合计数）。
- **3D 风险热图**：引擎 `--heatmap-json` 的稀疏 bins³ 网格（FEM von Mises +
  Phase A 风险区域聚合）→ ④「风险热图」面板：3D 热图视图（体素立方体替换网格
  视图，jet 色图）/ von Mises 与风险分两种着色源 / 渐变图例；STL 预览不可用时
  仍显示图例与说明。
- **输入校验**：③b 校验档位 select（minimal/standard/strict/paranoid）+
  「修复网格朝向」开关（`--repair-orientation`）。strict/paranoid 拒绝时引擎写
  `status:"validation_refused"` 标记，服务端转结构化 422，④ 内联渲染 findings
  （致命/提示徽章 + 拓扑审计数字）。
- **机器限制**：③b 机器型号 select（A250/A350/Artisan/J1/U1/A1/A1mini/P1P/P1S/
  X1/X1C，「自动」= 3MF printer_model 识别不发 flag）；④「机器限制」面板显示
  识别结果、固件速度上限/层高带与逐项钳制（from → to）。
- **④ 网格拓扑审计**：`mesh_topology` 全量披露（边界边/非流形/退化边/焊合视角
  χ/修复面数/不可定向部件 + validation findings）。
- **一键预设升级**：4 个 preset 现在连层高一起设（安全 0.16 / 均衡 0.2 /
  高速 0.28 / 外观 0.12）；z_ratio/fill_angle 有意不预设（前者随材料、后者 0=不旋转）。
- **求解器诊断与字段面扩容**（2026-08-19 会话 8，iter 67-75）：④ 面板新增 Phase B
  求解器诊断（CG 收敛提示；未收敛/网格部件合并警示以「Phase B:」前缀进入警示列表）、
  屈服单元行；建议项带优先级徽章 `[P n]` 与权衡文案；候选表体积/SF 格悬停显示
  材料·耗材·实体与 SF 来源（引擎原始串）；支撑体积不可用时表下显式声明。
  预览解析对非有限顶点与畸形 facet 防御性整块丢弃（`dropped` 计数体现在降级文案中），
  数值渲染 helper 对非数值引擎值显示「—」而非 NaN。

### 引擎 0.24 全契约面补齐（v0.8.1，2026-08-29）

以 `--schema` + `--help` + 全 flag 真跑报告为一手源做逐项 diff 盘点（缺口表见
ROADMAP v0.8.1），补齐全部「引擎有、UI 未接」项：

- **渲染面补齐**（报告早已带回、此前未消费）：④ 顶部「⚡ 预览级结果」标签
  （`input.fast_mode`）；多喷嘴 3MF 的 `filament_slots` 逐槽材料 + 引擎注记
  （② 面板，分析只按 slot-1 材料进行）；`input_overrides` 参数回退清单；
  `printability` 量化行（悬垂%/桥接/表面/底面接触）；Phase B 的 ZZ-SPR 离散
  误差、Tsai-Wu SF、网格质量、预条件子（含回退计数）；Phase C 的热-速闭环
  （超温建议速度+引擎理由原文）与含填充有效键合；Phase D 的跳过理由、疲劳
  寿命估算、Weibull R/Pf/尺寸因子/σ_eff；建议项置信度与建议值下估算 SF/应力；
  ⑤ 候选行悬停校准/策略/验证维（同名陷阱：顶层 `calibrated` 是 SF 外推含义，
  cal-time/mass 校准在 `estimate.calibrated`）；机器限制层高带未知（0/0）不再
  显示「0–0 mm」。
- **诊断相开关**（① 行，块缺省整体隐藏）：外观评估 `--appearance`、流变诊断
  `--rheology`、估算误差剖析 `--est-error-profile`（elastic/process 组语义
  分列、-1 哨兵显示为「—」、引擎注释原文）、分辨率校验 `--resolution-check`。
- **鲁棒性开关**（③b）：`--voxel-vote`、`--precond`（自动档不发 flag）。
- **发送值通道**（③b，诚实语义）：retraction/travel/wipe（见上节）。
- **旋钮**：`--prony-duration`、`--heatmap-bins`（④ 热图面板）、每次运行
  `--grid`（① 行，域 4..128 服务端预检 400）。
- **估算校准**：`--cal-time/--cal-mass` + ④「估算校准」面板（见上节）。
- **外挂基线**：`--base-profile`（① 面板 JSON 文件上传，见上节）。
- **分析产物下载**（④ 行）：`--generate-supports`（支撑结构网格 STL）与
  `--stress-modifier`（P95 应力热区体素 STL，切片器 modifier mesh）；各跑一次
  完整引擎分析后回传下载，kind 白名单。
- **仅写回 Orca 建议**（⑤ 行）：`--apply-orca` 模式——只把底边/支撑/PA/焊接
  写进新 3MF，不做结构优化写回；该通道引擎不产 sidecar 审计（0.24.0 实测），
  下载即产物；3MF+writable 闸与 `--strict-tier` 复用。
- 未接（挂账见 ROADMAP）：`--gcode-in/out` 应力调优工作流、`--vtk` 导出、
  `--phase-a` 仅几何模式（`--fast` 已覆盖快扫需求）。

## 首跑向导（v0.4a）

启动时找不到 stratum.exe 不再退出：浏览器打开后 ① 面板出现向导，粘贴
stratum.exe 完整路径 → 服务端 usage 探针校验（防误指普通 exe）→ 持久化到
`~/.stratum-webui.json`（重启自动生效；解析顺序 env > bin/ > 配置 > PATH）。
不接受 UNC 网络路径（`\server\share\...`）——本地工具不从网络执行引擎二进制。

## 已知边界（v0.8.1）

- **retraction / travel_speed / wipe 为「发送值」语义**：引擎 0.24 的这几个值
  flag **不回显**在报告 `input` 块（只影响 Orca 建议/外观通道 + 写回，设值即
  钉住）。v0.8.1 起 ③b 可直接调值（旧版仅可锁定），UI 在行悬停与面板脚注明确
  「引擎不回显、UI 无法核实」——实际效果看写回审计；若未来引擎补了回显，此
  通道应升级为常规回显状态机（T78 钉住了该契约，升级时会响亮失败）。
- **热图叠加需 STL 预览**：3MF 网格提取超出零依赖红线，3MF 输入时 ④ 热图面板只显示
  图例与统计，不渲染 3D 体素视图。
- **`--apply-orca` 无 sidecar 审计**：引擎该通道不产审计 JSON（0.24.0 实测），
  仅写回 Orca 建议的下载没有写回明细；需要审计用 `--optimize-3mf` 写回（dry-run
  预览同理）。
- 无云端；仅 127.0.0.1 本机。
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
- 前端可达的 CLI flag 是**白名单**：参数 flag + 环境与载荷 flag（`--load`/`--machine`/
  `--axis`/`--validate`/`--precond` 枚举服务端白名单，防引擎静默回退/拒绝；`--fast`/
  `--repair-orientation`/`--voxel-vote`/`--wipe` 为布尔白名单）+ `--lock` +
  `--optimize-3mf <profile>` / `--apply-orca`（含 `--sidecar-json`/`--dry-run`/
  `--strict-tier`）+ `--progress-json`/`--heatmap-json`/`--heatmap-bins`/
  `--appearance`/`--rheology`/`--est-error-profile`/`--resolution-check`/
  `--generate-supports`/`--stress-modifier`（增值通道，部分旧引擎自动剥离重试）+
  `--grid`（4..128 预检）+ `--base-profile`（服务端 JSON 形状预检 + 256 KB 上限
  后落私有临时盘，只传路径给引擎，键面由引擎裁定）。
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

## 测试（v0.8 后）

`python tests/test_smoke.py`（需 `bin/stratum.exe`）：103 检查，含三层渲染验证——
T56 node 桩解析器检查（stl_nan_check.js）、T57 真 helpers 注入渲染检查
（report_render_check.js，含 numEnv v2/v3 双形态契约与 v0.8.1 全部新块），
T58 无头 Chrome CDP 端到端
（browser_render_check.js，渲染面、错误路径、真实引擎全管线、像素级 readPixels
预览与热图、批量流、写回流、A/B 对比、会话恢复、strict 校验拒绝、真实进度轮询；
无 Chrome 时响亮 SKIP）。取消流的慢钩子验证为一次性（见 loop-journal iter 92：
钩子下无成功路径）。v0.8.1 新增 T74-T83：新渲染字段真引擎契约钉住、appearance/
rheology/est-error/resolution-check 相位 round-trip 与 absent-not-null、voxel-vote/
precond 白名单、retraction/travel/wipe 无回显契约、per-run grid 与 heatmap-bins
域校验、calibration 校准块、base-profile 预检与应用、导出产物魔法数、apply-orca
写回闸。
