# Tasks

- [x] Task 1: 修改 config_manager.py — 默认点位改为 d435i / d405
  - [x] SubTask 1.1: `_DEFAULT_POINTS` 从 `p_d435i`/`p_u405`/`p_n405` 改为 `d435i`/`d405` 两个

- [x] Task 2: 修改 gui_app.py — 删除夹爪 UI + 夹爪模块 + 点位名更新
  - [x] SubTask 2.1: 删除夹爪控制 UI（gripper_group: 开/关按钮、位置标签）
  - [x] SubTask 2.2: 删除夹爪模块参数编辑器（gripper_params: 动作/力度/速度）
  - [x] SubTask 2.3: 模块拼接工具中移除"夹爪开合"选项
  - [x] SubTask 2.4: FlowThread 移除 gripper 模块类型处理
  - [x] SubTask 2.5: FlowThread.__init__ 移除 gripper 参数
  - [x] SubTask 2.6: 删除 self.gripper / self.gripper_thread 初始化
  - [x] SubTask 2.7: _on_device_initFinished 移除 gripper 参数和赋值
  - [x] SubTask 2.8: FlowThread 中 D405 识别更新点位名改为 `d405`
  - [x] SubTask 2.9: D435iLowFpsWorker 中更新点位名改为 `d435i`
  - [x] SubTask 2.10: 添加 D435i 低帧率识别 UI 控件到视觉选项卡

- [x] Task 3: 修改 robot_control_mixin.py — 删除夹爪方法和监控
  - [x] SubTask 3.1: 删除 `gripper_open` 方法
  - [x] SubTask 3.2: 删除 `gripper_close` 方法
  - [x] SubTask 3.3: 删除 `update_gripper_position` 方法
  - [x] SubTask 3.4: `start_monitor_threads` 移除夹爪监控线程
  - [x] SubTask 3.5: `stop_monitor_threads` 移除夹爪线程停止

- [x] Task 4: 修改 workers.py — 删除夹爪初始化
  - [x] SubTask 4.1: DeviceInitThread 移除夹爪连接逻辑
  - [x] SubTask 4.2: DeviceInitThread.init_finished 信号改为只传 battery
  - [x] SubTask 4.3: run() 方法末尾 emit 只传 battery

- [x] Task 5: 修改 visual_servo_controller.py — 点位名更新
  - [x] SubTask 5.1: `p_d435i` 改为 `d435i`

- [x] Task 6: 修改 vision_mixin.py — 添加 D435i 低帧率 UI 控件引用
  - [x] SubTask 6.1: 确认低帧率识别方法引用的 UI 控件名与 gui_app.py 中创建的一致

- [x] Task 7: 更新 config.json — 点位结构
  - [x] SubTask 7.1: 将 p_d435i/p_u405/p_n405 替换为 d435i/d405

- [x] Task 8: 更新说明文档
  - [x] SubTask 8.1: README.md 更新（移除夹爪相关描述、更新点位说明、添加低帧率识别说明）
  - [x] SubTask 8.2: PORTING_GUIDE.md 更新（移除夹爪相关内容）

# Task Dependencies
- [Task 2] depends on [Task 1] (点位名变更)
- [Task 3] depends on [Task 2] (robot_control_mixin 中的夹爪方法被 gui_app 引用)
- [Task 4] depends on [Task 2] (workers 的 init_finished 信号被 gui_app 消费)
- [Task 5] depends on [Task 1]
- [Task 6] depends on [Task 2] (UI 控件在 gui_app 中创建)
- [Task 7] depends on [Task 1]
- [Task 8] depends on [Task 1, 2, 3, 4, 5, 6, 7]
