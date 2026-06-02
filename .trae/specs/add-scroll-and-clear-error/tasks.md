# Tasks

- [x] Task 1: 为各Tab页添加 QScrollArea 包裹
  - [x] SubTask 1.1: 在 gui_app.py 导入中添加 QScrollArea
  - [x] SubTask 1.2: 创建辅助方法 `_wrap_in_scroll(widget)` 将 QWidget 包裹进 QScrollArea
  - [x] SubTask 1.3: 对6个Tab页（主功能、参数设置、运动编辑、电池电量、机器人力控、Modbus通信）的内容widget调用包裹方法
  - [x] SubTask 1.4: 设置 QScrollArea 属性：widgetResizable=True，水平滚动条按需显示

- [x] Task 2: 在 robot_controller.py 中新增 clear_error() 公开方法
  - [x] SubTask 2.1: 添加 `clear_error()` 方法，检查连接状态
  - [x] SubTask 2.2: 调用 `self.dashboard.ClearError()`，等待0.5秒
  - [x] SubTask 2.3: 清除成功后调用 `self.enable_robot()` 重新使能
  - [x] SubTask 2.4: 返回 True/False 表示操作是否成功

- [x] Task 3: 在"主功能"Tab中添加"清除故障"按钮
  - [x] SubTask 3.1: 在主功能Tab的布局中添加"清除故障"按钮（放在碰撞等级设置下方）
  - [x] SubTask 3.2: 绑定按钮点击事件到 `on_clear_error()` 方法
  - [x] SubTask 3.3: 实现 `on_clear_error()` 方法：检查连接 → 调用 `clear_error()` → 状态栏显示结果

# Task Dependencies
- [Task 3] depends on [Task 2] (GUI按钮需要调用 controller 的 clear_error 方法)
