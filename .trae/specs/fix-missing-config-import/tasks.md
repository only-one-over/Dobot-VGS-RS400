# Tasks
- [x] Task 1: 在 gui_app.py 第 26 行添加缺失的 config_manager 导入
  - [x] SubTask 1.1: 将 `from config_manager import set_photo_position as config_set_photo_position` 修改为 `from config_manager import set_photo_position as config_set_photo_position, get_robot_ip, set_robot_ip as config_set_robot_ip`
- [x] Task 2: 验证 gui_app.py 可正常启动（无 NameError）

# Task Dependencies
- Task 2 依赖 Task 1
