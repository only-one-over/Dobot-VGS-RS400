# Tasks

- [x] Task 1: config_manager 新增 IP 配置函数
  - [x] SubTask 1.1: 在 `config_manager.py` 中添加 `get_robot_ip()` 函数，默认值 "192.168.5.1"
  - [x] SubTask 1.2: 在 `config_manager.py` 中添加 `set_robot_ip(ip)` 函数

- [x] Task 2: gui_app.py 启动时从配置加载 IP
  - [x] SubTask 2.1: 修改 `DobotGUI.__init__` 中 `self.robot_ip` 从 `config_manager.get_robot_ip()` 获取
  - [x] SubTask 2.2: 修改 `self.ip_input = QLineEdit(...)` 使用配置中的 IP 值

- [x] Task 3: 连接成功后持久化 IP
  - [x] SubTask 3.1: 在 `connect_robot()` 方法中，连接成功后调用 `config_manager.set_robot_ip(ip)` 保存 IP

- [x] Task 4: 添加模块插入到选中位置之后
  - [x] SubTask 4.1: 修改 `add_module()` 方法，当 `self.selected_step_index >= 0` 时使用 `insert(selected_step_index + 1, new_module)`，否则使用 `append`

- [x] Task 5: 删除选中的模块
  - [x] SubTask 5.1: 修改 `remove_module()` 方法，当 `self.selected_step_index >= 0` 时删除选中步骤，否则提示先选择
  - [x] SubTask 5.2: 删除后更新 `self.selected_step_index`（删除末尾时前移，否则保持原索引）

# Task Dependencies
- [Task 2] depends on [Task 1]
- [Task 3] depends on [Task 1]
- [Task 4, 5] 无依赖，可并行
