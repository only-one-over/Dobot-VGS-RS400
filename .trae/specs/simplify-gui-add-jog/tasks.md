# Tasks

- [x] Task 1: 删除"参数设置"Tab中的"运行速度设置"QGroupBox
  - [x] SubTask 1.1: 删除 speed_group QGroupBox 及其内部控件（speed_spinbox, set_speed_btn）
  - [x] SubTask 1.2: 删除 set_speed() 方法
  - [x] SubTask 1.3: 删除相关的实例变量引用（self.speed_spinbox, self.set_speed_btn）

- [x] Task 2: 精简"机器人力控"Tab
  - [x] SubTask 2.1: 删除"力矩历史数据"QGroupBox（torque_chart_widget 等）
  - [x] SubTask 2.2: 删除"力矩异常预警"QGroupBox（torque_alert_label 等）
  - [x] SubTask 2.3: 删除 update_torque_data 中与历史数据和预警相关的代码

- [x] Task 3: 在 robot_controller.py 中新增点动方法
  - [x] SubTask 3.1: 添加 move_jog(axis_id, coordtype=1) 方法，调用 dashboard.MoveJog()
  - [x] SubTask 3.2: 添加 stop_jog() 方法，调用 dashboard.MoveJog("")

- [x] Task 4: 新增"点动控制"Tab
  - [x] SubTask 4.1: 创建"点动控制"Tab页面widget
  - [x] SubTask 4.2: 添加"关节轴控制"QGroupBox，包含J1-J4正反向按钮（按下开始/松开停止）
  - [x] SubTask 4.3: 添加"坐标轴控制"QGroupBox，包含X/Y/Z/Rx/Ry/Rz正反向按钮
  - [x] SubTask 4.4: 添加坐标类型选择（用户坐标/工具坐标）
  - [x] SubTask 4.5: 实现按钮按下/松开事件绑定（pressed→move_jog, released→stop_jog）
  - [x] SubTask 4.6: 将新Tab添加到 tab_widget 并用 _wrap_in_scroll 包裹

# Task Dependencies
- [Task 4] depends on [Task 3] (GUI点动按钮需要调用 controller 的 move_jog/stop_jog 方法)
