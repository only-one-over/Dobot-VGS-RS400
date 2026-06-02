# Tasks

- [x] Task 1: 创建公共坐标变换工具模块 transform_utils.py
  - [x] 1.1: 在 `c:\Users\ADMIN\Desktop\dobot_move_python\dobot_move\` 下创建 `transform_utils.py`，包含 `euler2rot(rx, ry, rz, degree=True)` 和 `pose2matrix(x, y, z, rx, ry, rz)` 函数（从 config_manager.py 中的实现复制）
  - [x] 1.2: 修改 `config_manager.py`：删除 `_euler2rot` 和 `_pose2matrix` 定义，改为 `from transform_utils import euler2rot as _euler2rot, pose2matrix as _pose2matrix`
  - [x] 1.3: 修改 `vision_system.py`：删除 `_euler2rot_py`、`_euler2rot`、`_pose2matrix_py`、`_pose2matrix` 定义，改为 `from transform_utils import euler2rot as _euler2rot, pose2matrix as _pose2matrix`
  - [x] 1.4: 修改 `hand_eye_calib.py`：删除 `_euler2rot` 和 `_pose2matrix` 定义，改为 `from transform_utils import euler2rot as _euler2rot, pose2matrix as _pose2matrix`

- [x] Task 2: 删除 gui_app.py 中未使用的 vision 属性
  - [x] 2.1: 删除 `@property` 和 `def vision(self)` 方法（约 line 360-362）

- [x] Task 3: 删除 robot_controller.py 中未调用的方法
  - [x] 3.1: 删除 `move_arc` 方法
  - [x] 3.2: 删除 `move_to_target_position` 方法
  - [x] 3.3: 从 robot_controller.py 的 import 中移除 `get_target_offset`

- [x] Task 4: 删除 config_manager.py 中未使用的函数
  - [x] 4.1: 删除 `get_target_offset` 函数
  - [x] 4.2: 删除 `set_target_offset` 函数

# Task Dependencies
- Task 1 独立
- Task 3 依赖 Task 4（先删除 get_target_offset 的调用者，再删除函数定义）
- Task 2 独立
