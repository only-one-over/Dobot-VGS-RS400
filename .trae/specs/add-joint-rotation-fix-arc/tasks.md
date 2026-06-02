# Tasks

- [x] Task 1: 在dobot_api.py中添加MovC圆弧运动方法
  - [x] 添加MovC(middle_x, middle_y, middle_z, middle_rx, middle_ry, middle_rz, x, y, z, rx, ry, rz)方法
  - [x] 确保命令格式符合TCP文档: MovC(pose={x,y,z,rx,ry,rz}, pose2={mx,my,mz,mrx,mry,mrz})

- [x] Task 2: 在robot_controller.py中添加新方法
  - [x] 添加move_arc()方法支持圆弧运动
  - [x] 添加move_joint_relative()方法支持关节角度偏移运动(RelJointMovJ)
  - [x] 扩展move_to_point()方法支持MovC类型

- [x] Task 3: 在gui_app.py运动编辑面板中添加关节旋转模块
  - [x] 在module_combo中添加"关节旋转"选项
  - [x] 创建joint_rotation_params参数编辑面板（6个关节偏移角度 + 速度）
  - [x] 在add_module()中添加关节旋转模块的创建逻辑
  - [x] 在on_module_combo_changed()中添加关节旋转参数面板切换
  - [x] 在update_module_params()中添加关节旋转参数更新逻辑
  - [x] 在view_current_grasp_flow()中显示关节旋转模块信息
  - [x] 在run_grasp_flow()中添加关节旋转模块执行逻辑

- [x] Task 4: 修复圆弧运动逻辑
  - [x] 修复run_grasp_flow()中MovC的中间点计算逻辑
  - [x] 修复run_grasp_flow()中MovC的目标点计算逻辑
  - [x] 确保圆弧运动正确使用相机识别的物体坐标

# Task Dependencies
- 无未完成任务
