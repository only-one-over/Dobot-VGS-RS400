# Tasks

- [x] Task 1: 优化 `gui_app.py` — 消除重复代码和提升导入
  - [x] SubTask 1.1: 将 `json` 和 `os` 导入从方法内部提升到文件顶部
  - [x] SubTask 1.2: 将默认抓取流程模块列表提取为模块级常量 `_DEFAULT_GRASP_FLOW_MODULES`，消除 `__init__` 中约 40 行重复定义
  - [x] SubTask 1.3: 将 `from config_manager import set_photo_position` 从 `set_photo_position` 方法内部提升到文件顶部
  - [x] SubTask 1.4: 将 `save_grasp_flow` 和 `load_grasp_flow` 中的 `import json, os` 移除（已在顶部导入）

- [x] Task 2: 合并 `gui_app.py` 中三个相似监控线程为泛型 `MonitorThread`
  - [x] SubTask 2.1: 创建泛型 `MonitorThread` 类，接受数据读取函数、数据信号和错误信号作为参数
  - [x] SubTask 2.2: 删除 `GripperThread`、`BatteryThread`、`TorqueThread` 三个类
  - [x] SubTask 2.3: 更新 `start_monitor_threads` 和 `stop_monitor_threads` 使用新的 `MonitorThread`
  - [x] SubTask 2.4: 更新对应的信号连接逻辑

- [x] Task 3: 优化 `gui_app.py` 中 `view_current_grasp_flow` 的 UI 刷新逻辑
  - [x] SubTask 3.1: 实现 `on_step_clicked` 方法仅更新新旧选中步骤的样式，而非全量重建
  - [x] SubTask 3.2: 仅在模块增删时才全量重建流程显示

- [x] Task 4: 重构 `robot_controller.py` — 消除重复逻辑
  - [x] SubTask 4.1: 将 `from config_manager import get_photo_position` 从 `__init__` 提升到文件顶部
  - [x] SubTask 4.2: 将 `from config_manager import get_target_offset` 从 `move_to_target_position` 提升到文件顶部
  - [x] SubTask 4.3: 提取 `_describe_error_code` 方法，统一 `enable_robot` 和 `disable_robot` 中的错误码描述逻辑
  - [x] SubTask 4.4: 简化 `parse_response_code` 中的冗余逻辑（regex search 和 isdigit 检查重复）

- [x] Task 5: 优化 `vision_system.py` — 工具函数去重和无效代码清理
  - [x] SubTask 5.1: 将 `euler2rot` 和 `pose2matrix` 提取为模块级函数或类方法，删除 `__init__` 和 `convert_to_base_coords` 中的重复定义
  - [x] SubTask 5.2: 删除 `calculate_object_position` 中 `Z_mm = Z_mm` 无效赋值
  - [x] SubTask 5.3: 将 `MockFrame` 类提取为模块级类，避免每次调用 `capture_frames` 时重复创建

- [x] Task 6: 为 `config_manager.py` 添加配置缓存机制
  - [x] SubTask 6.1: 添加模块级 `_config_cache` 和 `_cache_valid` 变量
  - [x] SubTask 6.2: 修改 `load_config` 优先返回缓存数据
  - [x] SubTask 6.3: 修改 `save_config` 在写入后自动更新缓存

- [x] Task 7: 修复 `dobot_api.py` 响应接收问题
  - [x] SubTask 7.1: 修改 `send_command` 中的 `recv` 逻辑，循环接收直到获取完整响应（以换行符为结束标志）

- [x] Task 8: 修正 `test_gui.py` 的 PyQt 版本
  - [x] SubTask 8.1: 将 `PyQt5` 导入替换为 `PyQt6`，将 `exec_()` 替换为 `exec()`

# Task Dependencies
- [Task 2] depends on [Task 1] (先整理导入和常量，再重构线程)
- [Task 3] depends on [Task 1] (先整理代码结构，再优化 UI 刷新)
- [Task 5] depends on nothing (独立模块)
- [Task 6] depends on nothing (独立模块)
- [Task 7] depends on nothing (独立模块)
- [Task 8] depends on nothing (独立模块)
- [Task 4] depends on nothing (独立模块)
