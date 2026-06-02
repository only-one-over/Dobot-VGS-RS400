# Tasks

- [x] Task 1: 在dobot_api.py中添加GetForce指令
  - [x] 添加GetForce(tool=2)方法
  - [x] 支持指定工具坐标系，默认使用2

- [x] Task 2: 在robot_controller.py中添加get_force()方法
  - [x] 添加get_force(tool=2)方法
  - [x] 解析响应格式: ErrorID,{Fx, Fy, Fz, Mx, My, Mz},GetForce(tool);
  - [x] 返回包含Fx, Fy, Fz, Mx, My, Mz的字典

# Task Dependencies
- Task 2 depends on Task 1
