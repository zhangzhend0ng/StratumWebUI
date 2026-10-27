# Upstream PR 草案 — plugin-host plater object bindings

> 分支：`plugin-host-bindings`（单提交 6c54c308ec，只含
> `src/slic3r/plugin/host/PluginHostApp.cpp`，+71/-1。**未 push**，本文件为 PR 文案准备。）

## PR 标题

```
feat(plugin-host): plater object bindings for tools
```

## PR 描述

### 动机

插件宿主（`orca.host.plater()`）目前是纯只读面：插件能看到盘上有什么，但无法与盘上
对象闭环。嵌入式分析工具（以 Stratum 可打印性分析面板为第一个消费者）需要三条最小
能力，缺一条就断一个闭环：

1. 知道用户**选中了哪个对象**（而不是只有整个 model）；
2. 把分析结论**写回为对象级参数覆盖**（与用户手动在对象设置里改参数同一语义）；
3. 让插件触发一次**真实重切片**并拿到 G-code 产物（复用 Export G-code 的既有机制，
   而非在插件里另起切片栈）。

### API 面（全部加在 `orca.host.plater()` 上，均为新增）

| 绑定 | 签名 | 语义 |
|------|------|------|
| `selected_object_indices` | `() -> list[int]` | 3D 视图选中对象在 `model.objects()` 中的索引（任一实例被选中即算）；UI 线程调用 |
| `apply_object_config` | `(object_idx: int, values: dict[str,str]) -> list[tuple[str,bool,str]]` | 逐键写对象级覆盖（Orca 键名 + 序列化字符串值）；逐键返回 `(key, ok, error)` 使部分失败可见；任一键成功后 `changed_object()` 刷新 GUI；UI 线程调用 |
| `schedule_plate_gcode_export` | `(output_path: str) -> str` | `schedule_export(path, false)` + `reslice()`——与 Export G-code 菜单同一机制（去掉文件对话框）；异步，调用方轮询产物文件；已有导出任务在跑时抛错拒绝并发；UI 线程调用 |

实现注记：`selected_object_indices` 直接构造 `py::list`——本编译单元不引
`pybind11/stl.h`，返回 `std::vector` 会在运行期报 "Unregistered type"（已在真机复现过）。

### 向后兼容性

- **纯增量**：不改动任何既有绑定的名字、签名与行为；不调用新绑定的插件零影响。
- 三个绑定都是显式调用（无隐式生命周期挂钩），失败路径全部可异常化（越界/空盘/
  并发导出均 `throw`，映射为 Python 异常由插件侧呈现）。
- 无构建系统、无资源、无序列化格式变更；仅一个 `.cpp` 文件。

### 测试证据（真机，integrate/release_2.4.1 构建）

- 绑定存在性：`strings -a build/src/Release/Snapmaker_Orca.dll | grep <符号名>` 三绑定全部在产物中。
- 功能闭环（Stratum 插件 v0.3.0，Windows + WebView2 + 内嵌 CPython 3.12）：
  - `selected_object_indices`：从盘选取→STL 导出→分析全链跑通；
  - `schedule_plate_gcode_export`：真实重切片产出 G-code 并挂载分析（stress-tune 通道生效）；
  - `apply_object_config`：建议参数写入对象级覆盖，GUI 即时刷新。
- 插件侧无头回归：`packaging/orca-plugin/test_chain.py` 连续两跑全绿（服务/引擎侧）。

### 不在范围

- 非选中对象的批量操作、多对象写回、进度回调 API（等有第二个消费者再议）；
- 非 Windows 平台验证（引擎二进制与面板桥目前只在 Windows 验证）。
