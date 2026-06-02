# Tasks

- [x] Task 1: 删除主功能Tab的速度滑块和系统状态栏的速度Label
  - [x] SubTask 1.1: 删除 speed_slider、speed_value_label、speed_container（主功能Tab L510-521区域）
  - [x] SubTask 1.2: 删除 speed_label 及相关状态更新代码（系统状态栏 L429-430、L1178-1179）
  - [x] SubTask 1.3: 删除 speed_slider.valueChanged 信号连接

- [x] Task 2: 在 robot_controller.py 中添加暂停/继续方法
  - [x] SubTask 2.1: 添加 `pause()` 方法，检查连接后调用 `dashboard.Pause()`
  - [x] SubTask 2.2: 添加 `continue_motion()` 方法，检查连接后调用 `dashboard.Continue()`

- [x] Task 3: 重构 run_grasp_flow 为后台线程执行
  - [x] SubTask 3.1: 将 `run_grasp_flow` 主体逻辑移到 QThread 的 run() 中，保留原方法作为线程启动入口
  - [x] SubTask 3.2: 添加 `self.is_paused` 标志和 `self._flow_running` 标志
  - [x] SubTask 3.3: 在每个模块执行前检查暂停标志，暂停时循环等待（time.sleep(0.1)）

- [x] Task 4: 流程中自动清除报警
  - [x] SubTask 4.1: 在每个模块执行前添加 RobotMode 检查
  - [x] SubTask 4.2: 若 RobotMode==9，调用 `self.controller.clear_error()` 清除报警后继续

- [x] Task 5: 在主功能Tab添加暂停/继续按钮
  - [x] SubTask 5.1: 在 clear_error_btn 下方添加"暂停"按钮，绑定 `on_pause`
  - [x] SubTask 5.2: 在"暂停"按钮旁添加"继续"按钮，绑定 `on_continue`
  - [x] SubTask 5.3: 实现 `on_pause()` 和 `on_continue()` 方法
  - [x] SubTask 5.4: 流程执行时按钮启用，结束后禁用

# Task Dependencies
- [Task 3] depends on [Task 2] (流程中需要调用 pause/continue_motion)
- [Task 4] depends on [Task 3] (在重构后的流程中添加报警检查)
- [Task 5] depends on [Task 3] (暂停/继续按钮需要操作流程状态)
