# 修复相机测试选项卡不显示画面和坐标 Spec

## Why
相机测试选项卡点击"开始测试"后，QTimer 回调在主线程中执行耗时的视觉处理（100-300ms），阻塞 GUI 事件循环导致 UI 不刷新；同时 QImage 引用 numpy 数组内存，数组被 GC 后画面变空白。

## What Changes
- 修改 `gui_app.py`：将 `_camera_test_tick()` 中的视觉处理移到后台线程，通过信号传递结果到主线程更新 UI；修复 QImage 内存引用问题

## Impact
- Affected code: `gui_app.py`（`_camera_test_tick` 重构 + 新增 Worker + 信号）

## ADDED Requirements

### Requirement: 后台线程处理视觉数据
系统 SHALL 在后台线程中执行相机采集和检测，通过信号将结果传递到主线程更新 UI。

#### Scenario: 正常刷新
- **WHEN** QTimer 触发
- **THEN** 在后台线程中执行 capture_frames + run_detection_tracked + calculate_object_position_smoothed，完成后通过 pyqtSignal 将结果发送到主线程更新 QLabel

#### Scenario: 处理中跳过
- **WHEN** 上一次视觉处理尚未完成时 QTimer 再次触发
- **THEN** 跳过本次处理，避免积压

### Requirement: QImage 内存安全
系统 SHALL 确保 QImage 持有图像数据的独立副本，不依赖 numpy 数组的内存引用。

#### Scenario: 图像显示
- **WHEN** 后台线程完成一帧处理
- **THEN** 将 numpy 数组转换为 QImage 时使用 `.copy()` 确保数据独立

## MODIFIED Requirements
无。

## REMOVED Requirements
无。
