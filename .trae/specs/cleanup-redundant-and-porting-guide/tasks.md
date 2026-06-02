# Tasks

- [ ] Task 1: 创建公共坐标变换工具模块 transform_utils.py
  - [ ] 1.1: 在 `c:\Users\ADMIN\Desktop\dobot_move_python\dobot_move\` 下创建 `transform_utils.py`，包含 `euler2rot(rx, ry, rz, degree=True)` 和 `pose2matrix(x, y, z, rx, ry, rz)` 函数（从 config_manager.py 中的实现复制）
  - [ ] 1.2: 修改 `config_manager.py`：删除 `_euler2rot` 和 `_pose2matrix` 定义，改为 `from transform_utils import euler2rot as _euler2rot, pose2matrix as _pose2matrix`
  - [ ] 1.3: 修改 `vision_system.py`：删除 `_euler2rot_py`、`_euler2rot`、`_pose2matrix_py`、`_pose2matrix` 定义，改为 `from transform_utils import euler2rot as _euler2rot, pose2matrix as _pose2matrix`
  - [ ] 1.4: 修改 `hand_eye_calib.py`：删除 `_euler2rot` 和 `_pose2matrix` 定义，改为 `from transform_utils import euler2rot as _euler2rot, pose2matrix as _pose2matrix`

- [ ] Task 2: 删除 gui_app.py 中未使用的 vision 属性
  - [ ] 2.1: 删除 `@property` 和 `def vision(self)` 方法（约 line 360-362）

- [ ] Task 3: 删除 robot_controller.py 中未调用的方法
  - [ ] 3.1: 删除 `move_arc` 方法（约 line 763-850）
  - [ ] 3.2: 删除 `move_to_target_position` 方法（约 line 928-970）
  - [ ] 3.3: 从 robot_controller.py 的 import 中移除 `get_target_offset`（line 16）

- [ ] Task 4: 删除 config_manager.py 中未使用的函数
  - [ ] 4.1: 删除 `get_target_offset` 函数（约 line 65-76）
  - [ ] 4.2: 删除 `set_target_offset` 函数（约 line 71-76）

- [ ] Task 5: 创建设备移植方案文档 PORTING_GUIDE.md
  - [ ] 5.1: 在 `c:\Users\ADMIN\Desktop\dobot_move_python\` 下创建 `PORTING_GUIDE.md`，包含以下章节：
    - 概述：项目架构和模块依赖关系
    - 硬件接口适配：替换机器人控制器（TCP/IP 协议适配、端口配置、指令格式映射）
    - 通信协议替换：Modbus TCP Server/Client 适配新设备
    - 视觉系统配置：RealSense 相机选型、深度范围、分辨率、标定流程
    - 手眼标定：标定流程、矩阵格式、如何为新设备计算标定矩阵
    - 点位管理系统：点位数据格式、相对点位解析、如何迁移已有点位
    - 力控圆弧：力反馈接口适配、力控参数调整
    - 配置文件：config.json 格式说明、需要修改的配置项
    - 移植检查清单：逐步验证清单

# Task Dependencies
- Task 1 独立（公共模块提取）
- Task 3 依赖 Task 4（先删除 get_target_offset 的调用者，再删除函数定义）
- Task 5 独立
