# Tasks

## [x] Task 1: 替换 dobot_api.py 为参考版本
- **Priority**: P0
- **Depends On**: None
- **Description**:
  - 复制 `TCP-IP-Python-V4-main/TCP-IP-Python-V4-main/dobot_api.py` 到 `dobot_move/dobot_api.py`，替换当前简化版本
  - 复制 `TCP-IP-Python-V4-main/TCP-IP-Python-V4-main/files/alarmController.json` 到 `dobot_move/files/alarmController.json`
  - 复制 `TCP-IP-Python-V4-main/TCP-IP-Python-V4-main/files/alarmServo.json` 到 `dobot_move/files/alarmServo.json`
  - 复制 `TCP-IP-Python-V4-main/TCP-IP-Python-V4-main/files/alarmController.py` 到 `dobot_move/files/alarmController.py`
  - 复制 `TCP-IP-Python-V4-main/TCP-IP-Python-V4-main/files/alarmServo.py` 到 `dobot_move/files/alarmServo.py`

## [x] Task 2: 更新 robot_controller.py 适配新API
- **Priority**: P0
- **Depends On**: Task 1
- **Description**:
  - 导入 `DobotApiFeedBack` 替代 `RealTimeFeedback` 和 `TorqueMonitor`
  - 在 `__init__` 中创建 `DobotApiFeedBack` 实例连接30004端口
  - 添加 `start_feedback()` 和 `stop_feedback()` 方法管理反馈线程
  - 添加 `get_feed_data()` 方法返回最新解析的反馈数据
  - 适配 `MovJ(x,y,z,rx,ry,rz)` → `MovJ(x,y,z,rx,ry,rz,0)` 增加coordinateMode=0
  - 适配 `MovL(x,y,z,rx,ry,rz)` → `MovL(x,y,z,rx,ry,rz,0)` 增加coordinateMode=0
  - 适配 `MovC(...)` → `MovC(..., 0)` 增加coordinateMode=0  
  - 保持 `RelJointMovJ` 和 `GetForce` 调用不变

## [x] Task 3: 更新 realtime_feedback_dialog.py 使用新API
- **Priority**: P0
- **Depends On**: Task 1
- **Description**:
  - 移除 `from realtime_feedback import RealTimeFeedback`
  - 改为导入 `DobotApiFeedBack`
  - 使用 `DobotApiFeedBack.feedBackData()` 获取numpy结构化数据
  - 适配数据读取方式（从dict格式改为numpy数组字段访问）

## [x] Task 4: 更新 gui_app.py 移除已删除模块引用
- **Priority**: P0
- **Depends On**: Task 2
- **Description**:
  - 移除 `from realtime_feedback import RealTimeFeedback` 导入
  - 移除 `torque_monitor.TorqueMonitor` 相关导入
  - 更新 `DeviceInitThread` 移除 torque_monitor 和 realtime_feedback 初始化
  - 将力矩数据显示改为通过 `robot_controller` 获取
  - 移除 `update_torque_data` 方法（或改为通过controller获取）

## [x] Task 5: 删除多余文件和目录
- **Priority**: P1
- **Depends On**: Task 4
- **Description**:
  - 删除 `dobot_move/realtime_feedback.py`
  - 删除 `dobot_move/torque_monitor.py`
  - 删除 `build_cpp.py`
  - 删除 `build_app.py`
  - 删除 `tcp_test/` 目录
  - 删除 `dist/` 目录
  - 删除 `grasp_flow.json`（空文件）

## [x] Task 6: 验证项目完整性
- **Priority**: P1
- **Depends On**: Task 5
- **Description**:
  - 检查所有Python文件的import语句无误
  - 确认 gui_app.py 可以正常启动（语法检查）
  - 确认 robot_controller.py 逻辑完整

# Task Dependencies
- Task 2 depends on Task 1
- Task 3 depends on Task 1
- Task 4 depends on Task 2
- Task 5 depends on Task 4
- Task 6 depends on Task 5
