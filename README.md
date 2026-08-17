# Stratum WebUI — 工艺参数调参台

本地 Web UI，给 [Stratum](https://github.com/Stratum)（FDM 可打印性分析引擎）调
切片工艺参数。**零依赖**：Python 标准库 server + 自含单文件 HTML。

## 架构

```
Stratum-WebUI                 ← 独立仓库，只消费 Stratum 的发布物
├── server.py                 ← Python stdlib ThreadingHTTPServer (127.0.0.1)
├── index.html                ← 自含单文件（零外部资源，JS 只渲染 JSON）
└── bin/stratum.exe           ← SDK CLI 副本（或 STRATUM_BIN 指定）
     │
     └── subprocess ──► stratum.exe <model> --phase-c --json report.json
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
2. **② 当前参数** — 引擎实际使用的参数（来自 JSON 报告 `input` 块）
3. **③ 调参** — 滑杆改参数 + 「锁定」勾选（对应引擎 `--lock` 语义）
4. **④ 分析结果** — 几何风险、安全系数、参数建议、引擎推荐行
5. **⑤ 候选档位对比** — safe/balanced/fast/appearance 对比表（Goal/EstTime/EstMat/EstSF）
6. **写回下载** — 仅 `.3mf` 输入可用：跑 `--optimize-3mf <profile>` 下载新 3MF

## 可调参数（滑杆 ↔ CLI flag）

| 滑杆 | CLI flag | 范围 | 单位 |
|---|---|---|---|
| 壁数 | `--walls` | 1-20 | — |
| 填充率 | `--infill` | 0-100 | % |
| 填充图案 | `--pattern` | 7 种 | — |
| 材料 | `--material` | PLA/PETG/ABS/CUSTOM | — |
| 喷嘴直径 | `--nozzle` | 0.1-2.0 | mm |
| 喷嘴温度 | `--nozzle-temp` | 150-350 | °C |
| 热床温度 | `--bed-temp` | 0-200 | °C |
| 打印速度 | `--speed` | 1-1000 | mm/s |
| 冷却风扇 | `--cooling` | 0-100 | % |

「锁定」勾选 → 引擎 `--lock`（参数钉在现值，搜索域坍缩/写回跳过）。

## 已知边界（v0.1）

- **层高（layer_height）不可直接调**：CLI 无 `--layer-height` flag。层高通过
  safe/balanced/fast/appearance 档位候选体现（对比表 diff 中可见）。若需要直调，
  属引擎侧独立决策（`--layer-height` flag 或 C API `stratum_config_set_layer_height`
  via ctypes）。
- **retraction / wipe / travel_speed** 等 Orca 建议域参数不进本页（无 JSON 当前值来源）。
- 无 3D 风险/应力热图查看器；无云端；仅 127.0.0.1 本机。

## 安全模型

- 仅绑定 `127.0.0.1`；`subprocess` 用列表参数（**无 shell**，参数值不可能注入命令）。
- 前端可达的 CLI flag 是**白名单**：上述参数 flag + `--lock` + `--optimize-3mf <profile>`。
- 上传模型存私有临时目录，进程退出时清理；模型文件永不被执行。

## 开发

```bash
# 冒烟（起服务后另开终端）
python server.py &
curl http://127.0.0.1:8765/api/status
curl -F "" ...   # 或直接用浏览器上传 test_data/beam_10x2x2.stl
```

环境变量：`STRATUM_BIN`（二进制路径）、`STRATUM_UI_PORT`（默认 8765）、
`STRATUM_UI_GRID`（FEM 网格，默认 16）。
