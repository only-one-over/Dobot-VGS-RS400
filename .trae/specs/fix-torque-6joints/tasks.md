# Tasks

- [x] Task 1: 扩展关节力矩Label从4个到6个
  - [x] SubTask 1.1: 在"机器人力控"Tab中添加 torque_joint5_label 和 torque_joint6_label
  - [x] SubTask 1.2: 调整布局为3行2列（J1-J2, J3-J4, J5-J6）

- [x] Task 2: 修复数据更新逻辑
  - [x] SubTask 2.1: 将 `ActualJointTorque` 改为 `IActual`
  - [x] SubTask 2.2: 更新6个关节Label（从检查 len>=4 改为 len>=6）
  - [x] SubTask 2.3: 添加 J5 和 J6 的 setText 调用

# Task Dependencies
- [Task 2] depends on [Task 1] (需要先创建Label才能更新)
