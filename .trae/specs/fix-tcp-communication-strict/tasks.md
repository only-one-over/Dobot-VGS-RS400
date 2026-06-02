# Tasks

- [x] Task 1: 修复DobotApiDashboard.connect() - 消费欢迎消息
  - [x] 连接成功后，先recv()读取机器人发送的欢迎消息
  - [x] 打印欢迎消息内容用于调试
  - [x] 将socket超时从5秒增加到15秒（PowerOn需要约10秒）

- [x] Task 2: 修复DobotApiDashboard.send_command() - 响应格式处理
  - [x] 确保响应以分号";"结尾才算完整
  - [x] 正确处理响应格式: ErrorID,{value},Command();

- [x] Task 3: 修复DobotApiDashboard.EnableRobot() - 参数格式
  - [x] 无参数时发送EnableRobot()而不是EnableRobot(0.0,0.0,0.0,0.0,0)
  - [x] 有参数时才发送对应参数

- [x] Task 4: 修复robot_controller.py - 添加RequestControl()
  - [x] 连接成功后先调用RequestControl()切换TCP模式
  - [x] 确保使能流程: RequestControl() -> ClearError() -> PowerOn() -> EnableRobot()

- [x] Task 5: 修复torque_monitor.py - 力控数据字节偏移
  - [x] 根据TCP文档修正: ActualTCPForce从字节576开始
  - [x] Fx = bytes[576:584], Fy = bytes[584:592], Fz = bytes[592:600]
  - [x] 同时读取Mx, My, Mz扭矩值
  - [x] 读取6个关节扭矩(MActual)从字节1120开始

- [x] Task 6: 修复gui_app.py - 力控标签更新
  - [x] update_torque_data()方法同时更新力控选项卡中的关节力矩标签
  - [x] 从实时反馈数据中读取关节扭矩(MActual)并显示

# Task Dependencies
- Task 2 depends on Task 1
- Task 4 depends on Task 1, Task 2, Task 3
- Task 6 depends on Task 5
