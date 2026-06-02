# Tasks

- [x] Task 1: 修复dobot_api.py - 核心TCP通信问题
  - [x] connect()中读取欢迎消息：欢迎消息可能不以";"结尾，用recv(1024)读取一次即可
  - [x] connect()中连接成功后自动调用RequestControl()
  - [x] RequestControl()失败时检查RobotMode判断是否已在TCP模式
  - [x] send_command()中确保响应读取正确

- [x] Task 2: 删除C++相关文件
  - [x] 删除cpp_core/目录
  - [x] 删除test_tcp_interface.py旧测试脚本

- [x] Task 3: 移除dobot_core引用
  - [x] vision_system.py中移除dobot_core导入和使用，只保留Python实现
  - [x] torque_monitor.py中移除dobot_core导入和使用，只保留Python实现

# Task Dependencies
- Task 2 depends on Task 3
- Task 3 depends on Task 1
