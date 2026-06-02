# Tasks

- [x] Task 1: 修改 VisionSystem 支持序列号指定设备
  - [x] 1.1: VisionSystem.__init__ 增加 serial_number 参数
  - [x] 1.2: 当 serial_number 非空时，通过 rs.config.enable_device(serial_number) 指定设备
  - [x] 1.3: 当 serial_number 为空时，保持现有行为（打开第一个可用设备）

- [x] Task 2: 修改 gui_app.py 相机连接逻辑为双相机同时连接
  - [x] 2.1: 将 self.vision 拆分为 self.vision_d435i 和 self.vision_d405
  - [x] 2.2: 移除 camera_type_combo 下拉框
  - [x] 2.3: 新增 D435i 连接/断开按钮和 D405 连接/断开按钮，各自独立控制
  - [x] 2.4: 新增 D435i 和 D405 各自的连接状态标签
  - [x] 2.5: 实现 connect_d435i / disconnect_d435i / connect_d405 / disconnect_d405 方法
  - [x] 2.6: 连接时自动探测 RealSense 设备序列号，匹配 D435i/D405

- [x] Task 3: 修改 FlowThread 支持双相机选择
  - [x] 3.1: FlowThread.__init__ 接收 vision_d435i 和 vision_d405 参数
  - [x] 3.2: 相机模块根据 camera_type 参数选择对应 VisionSystem 实例
  - [x] 3.3: 选中的相机未连接时报错终止
  - [x] 3.4: 移除临时创建 VisionSystem 的逻辑（不再需要）

- [x] Task 4: 修改所有引用 self.vision 的代码
  - [x] 4.1: 更新 run_grasp_flow 中 FlowThread 的参数传递
  - [x] 4.2: 更新 run_grasping_task 中的相机检查逻辑
  - [x] 4.3: 更新手眼标定保存时的 vision 同步逻辑
  - [x] 4.4: 更新 closeEvent 中的相机关闭逻辑
  - [x] 4.5: 更新 StatusUpdateThread 中的 vision 引用

# Task Dependencies
- [Task 2] depends on [Task 1]
- [Task 3] depends on [Task 2]
- [Task 4] depends on [Task 2, Task 3]
