# Tasks

- [ ] Task 1: 添加模拟电池模式
  - [ ] 修改battery_monitor.py，添加SimulatedBatteryMonitor类
  - [ ] 模拟数据包括：电压、电流、SOC、温度、状态
  - [ ] 提供connect()方法（始终成功）
  - [ ] 提供read_data()方法（返回模拟数据）
  - [ ] 提供get_data()方法（返回数据字典）

- [ ] Task 2: 修改电池监控初始化逻辑
  - [ ] 修改DeviceInitThread中的电池初始化
  - [ ] 优先尝试CAN总线连接
  - [ ] CAN失败后提示用户，并提供启用模拟模式的选项

- [ ] Task 3: 改善GUI电池错误提示
  - [ ] 修改gui_app.py中电池连接失败的提示
  - [ ] 显示"电池: 未连接（需要CAN适配器）"

# Task Dependencies
- Task 2 depends on Task 1
- Task 3 depends on Task 2
