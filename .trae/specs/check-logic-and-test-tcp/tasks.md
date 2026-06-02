# Tasks

- [x] Task 1: 创建独立TCP连接测试文件夹和脚本
  - [x] 在项目根目录创建tcp_test文件夹
  - [x] 创建test_dashboard_connection.py测试脚本
  - [x] 脚本逐步测试：连接→读取欢迎消息→RequestControl→ClearError→PowerOn→RobotMode→EnableRobot
  - [x] 每一步都打印详细日志，便于排查问题
  - [x] 添加异常处理和超时提示

- [x] Task 2: 修复robot_controller.py连接逻辑
  - [x] connect()方法不再自动调用enable_robot()，只负责连接和RequestControl
  - [x] RequestControl()失败时检查RobotMode判断是否已在TCP模式
  - [x] PowerOn()后轮询RobotMode等待上电完成（替代固定sleep）

- [x] Task 3: 修复gui_app.py中的调用逻辑
  - [x] "使能机器人"按钮：已使能时提示，未连接先连接再使能
  - [x] "下使能机器人"按钮：已下使能时提示，未连接先连接再下使能
  - [x] "运行抓取任务"：确保机器人已连接且已使能

# Task Dependencies
- Task 2 depends on Task 1
- Task 3 depends on Task 2
