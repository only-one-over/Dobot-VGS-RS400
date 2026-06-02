# 运行时性能优化 Spec

## Why
项目在运行时存在多个性能瓶颈：骨架化算法无上限迭代导致单帧耗时 100-200ms、Modbus 周期中同步阻塞调用 `get_current_pose()` 导致周期爆炸到 3-9 秒、CameraTestWorker 4 次图像拷贝 + 无帧率控制导致持续 80%+ CPU、实时反馈对话框 1ms sleep 空转浪费 2-5% CPU、ONNX Runtime 模块级导入导致启动额外慢 2-5 秒、点位表全量重建导致 UI 卡顿 50-200ms、`resolve_point` 副作用写磁盘每次额外 5-20ms。这些瓶颈直接影响用户体验和系统稳定性。

## What Changes
- `vision_system.py` — 骨架化添加最大迭代次数保护（max 200 次），防止大 mask 场景无限循环
- `robot_controller.py` — Modbus 周期中 `_update_modbus_status` 改为从缓存 `feed_data` 提取位姿，不再同步阻塞调用 `get_current_pose()`
- `gui_app.py` `CameraTestWorker` — 添加帧率控制（30 FPS）、减少冗余图像拷贝、用 `pyqtSignal` emit 压缩帧数
- `realtime_feedback_dialog.py` — 将 `time.sleep(0.001)` 改为 `time.sleep(0.005)`，降低空转频率从 1000Hz 到 200Hz
- `gui_app.py` + `vision_system.py` — ONNX Runtime 改为延迟导入，仅在首次创建 `VisionSystem` 时加载（**BREAKING**: 需检查 `_missing_deps` 检测逻辑）
- `point_management_mixin.py` — `refresh_points_table` 改为增量更新：只更新变化的行，不清空全量重建
- `config_manager.py` — `resolve_point` 移除副作用 `set_points()` 磁盘写入

## Impact
- Affected specs: `optimize-code-efficiency`（已完成）、`project-comprehensive-optimization`（已完成）
- Affected code:
  - `dobot_move/vision_system.py` — 骨架化迭代保护 + ONNX 延迟导入
  - `dobot_move/robot_controller.py` — Modbus 位姿提取优化
  - `dobot_move/gui_app.py` — CameraTestWorker 帧率控制 + 图像拷贝减少 + ONNX 延迟导入
  - `dobot_move/realtime_feedback_dialog.py` — sleep 间隔调整
  - `dobot_move/gui_mixins/point_management_mixin.py` — 增量 UI 更新
  - `dobot_move/config_manager.py` — `resolve_point` 去副作用

## ADDED Requirements

### Requirement: 骨架化算法最大迭代次数保护
`_skeletonize_mask` 方法 SHALL 添加最大迭代次数限制（200 次），超过限制时使用 `cv2.ximgproc.thinning` 降级方案，防止大 mask 场景无限循环导致单帧耗时 > 100ms。

#### Scenario: 大 mask 骨架化不超时
- **GIVEN** 一个宽 400 像素的掩码区域
- **WHEN** `_skeletonize_mask` 被调用
- **THEN** 最多迭代 200 次后强制退出，使用 thinning 降级方案，总耗时 < 50ms

#### Scenario: 小 mask 骨架化正常完成
- **GIVEN** 一个宽 50 像素的掩码区域
- **WHEN** `_skeletonize_mask` 被调用
- **THEN** 正常迭代完成，不触发降级方案，行为与原代码一致

### Requirement: Modbus 周期从缓存提取位姿
`_update_modbus_status` 方法 SHALL 从已缓存的 `feed_data`（`ToolVectorActual` 字段）中直接提取 TCP 坐标，而非通过 socket 同步阻塞调用 `get_current_pose()`。

#### Scenario: Modbus 周期不因机器人响应慢而膨胀
- **GIVEN** 机器人正在执行运动命令，dashboard socket 响应延迟
- **WHEN** `_update_modbus_status` 被调用（每 200ms）
- **THEN** 直接从 `feed_data` 缓存读取位姿，IModbus 周期保持 200ms 不变

#### Scenario: 反馈数据不可用时优雅降级
- **GIVEN** `feed_data` 为 None（反馈通道未建立）
- **WHEN** `_update_modbus_status` 被调用
- **THEN** 跳过位姿更新，Modbus 寄存器保持上次值，不阻塞

### Requirement: CameraTestWorker 帧率控制与图像拷贝精简
`CameraTestWorker.run()` SHALL 添加帧率限制（最多 30 FPS），并将每帧的图像拷贝从 4 次减少到 2 次以内。

#### Scenario: 帧率不超过 30 FPS
- **GIVEN** `CameraTestWorker` 正在运行
- **WHEN** 帧处理时间 < 33ms
- **THEN** 循环 `time.sleep` 补足至 33ms/帧，实际帧率不超过 30 FPS

#### Scenario: 每帧图像拷贝最多 2 次
- **GIVEN** `CameraTestWorker` 正在运行
- **WHEN** 一帧处理完成
- **THEN** `display_image.copy()` 和 `QImage(...).copy()` 中的 `cvtColor(...).copy()` 被消除，直接在 frame data 上绘制

### Requirement: 实时反馈对话框 sleep 间隔优化
`RealTimeFeedbackDialog._feed_loop` 的 `time.sleep(0.001)` SHALL 改为 `time.sleep(0.005)`，将空转频率从 1000Hz 降低到 200Hz。

#### Scenario: CPU 使用率降低
- **GIVEN** 实时反馈对话框已打开
- **WHEN** 反馈数据以 125Hz 到达
- **THEN** 反馈线程 CPU 使用率从 2-5% 降低到 < 1%

### Requirement: ONNX Runtime 延迟导入
`onnxruntime` SHALL 不在模块级 `import`，改为在 `VisionSystem.__init__()` 中首次创建 `InferenceSession` 时才导入。

#### Scenario: 不使用视觉功能时启动更快
- **GIVEN** 用户只需使用 Modbus 或基础机器人控制功能
- **WHEN** 程序启动
- **THEN** `onnxruntime` 的 CUDA 初始化（~1-3 秒）不触发，启动时间缩短 2-5 秒

### Requirement: 点位表增量更新
`refresh_points_table` SHALL 改为增量更新模式：仅当点位数量变化时才 `setRowCount`，对于已存在的行仅更新数值内容，不重建整个表格。

#### Scenario: 修改单个点位坐标时不重建表格
- **GIVEN** 表格中有 20 个点位
- **WHEN** 用户修改第 3 个点位的坐标
- **THEN** 仅更新第 3 行的 6 个 SpinBox 值，不触发 `setRowCount(0)` + 全量重建，UI 刷新时间从 40ms 降至 < 5ms

### Requirement: resolve_point 移除副作用
`resolve_point()` SHALL 不再在解析完成后调用 `set_points()` 写入磁盘，仅返回解析后的绝对坐标。

#### Scenario: 解析相对坐标无磁盘写入
- **GIVEN** 点位 `p_test` 为相对点位
- **WHEN** 调用 `resolve_point("p_test")`
- **THEN** 仅计算并返回绝对坐标，不触发 JSON 文件写入，调用耗时从 5-20ms 降至 < 1ms
