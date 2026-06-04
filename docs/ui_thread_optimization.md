# UI and Thread Optimization Notes

本文记录本轮针对 Dobot PyQt6 控制界面的结构、效率和 UI 优化，便于后续继续迭代。

## 已完成

### 1. UI 状态和主题

- 新增 `dobot_move/ui_theme.py`，集中管理状态徽标、流程步骤样式、按钮角色和应用调色板。
- 主界面按钮新增语义角色：
  - `primary`: 运行抓取任务、执行流程
  - `connect`: 连接、使能、继续
  - `warning`: 下使能、暂停
  - `danger`: 清除故障
  - `secondary`: 普通辅助动作
- D435i、D405、低帧率识别状态统一使用共享状态样式。
- 流程步骤列表启用自动换行，并统一普通、选中、空状态样式。

### 2. 线程和生命周期

- 修复 `FlowThread` 调用参数错位问题，移除不存在的 `self.gripper` 传参。
- `FlowThread` 增加 `stop()` 和停止标志，暂停等待和多帧检测中可提前退出。
- 主窗口状态刷新从 `StatusUpdateThread` 改为 `QTimer`，减少一个常驻后台线程。
- 删除废弃的 `StatusUpdateThread`。
- `RobotCmdThread`、`FlowThread`、相机测试 worker、低帧率 worker、设备初始化线程均接入 `deleteLater()`。
- 关闭窗口时会停止状态 timer、相机 worker、低帧率 worker、流程线程和监控线程。

### 3. 低帧率识别效率

- `D435iLowFpsWorker` 不再在后台线程中写 `config.json`。
- 点位保存移动到主线程 `_on_low_fps_result()`。
- 新增节流逻辑：至少间隔 1 秒，或 base 坐标变化超过 1mm，才保存一次 `d435i` 点位。
- 相机测试和低帧率 worker 的帧率等待从 `time.sleep()` 改为 `QThread.msleep()`，停止响应更及时。

## 验证

已通过语法编译检查：

```powershell
python -m py_compile dobot_move\gui_app.py dobot_move\ui_theme.py dobot_move\workers.py dobot_move\gui_mixins\grasp_flow_mixin.py dobot_move\gui_mixins\vision_mixin.py dobot_move\gui_mixins\robot_control_mixin.py
```

## 后续建议

- 将 `gui_app.py` 中剩余的大段全局 stylesheet 迁移到 `ui_theme.py`。
- 将主功能页拆成独立 `MainControlPanel`，主窗口只负责装配。
- 将 `CameraTestWorker`、`D435iLowFpsWorker`、`FlowThread` 迁移到独立 worker 模块。
- 用 `QTableWidget` 或自定义 widget 替代流程步骤纯 `QLabel` 列表，支持拖拽排序和状态图标。
- 对配置写入建立统一 debounce/save 服务，避免多个 UI 路径直接写 `config.json`。
