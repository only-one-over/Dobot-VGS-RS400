# Tasks

- [x] Task 1: 直线运动坐标模式重构——UI 改为目标坐标输入 + 读取当前位置按钮
  - [x] 1.1: 将 linear_offset_widget 中的标签从"偏移值 X/Y/Z/Rx/Ry/Rz"改为"目标 X/Y/Z/Rx/Ry/Rz"
  - [x] 1.2: 将 offset_x/y/z/rx/ry/rz 变量重命名为 target_x/y/z/rx/ry/rz（对应 self.target_x 等）
  - [x] 1.3: 在目标坐标输入区域添加"读取当前位置"按钮，点击后调用 controller.get_current_pose() 并填入6个坐标输入框
  - [x] 1.4: 更新 add_module 中直线运动模块的初始参数：将 "offset": [0,0,0] 改为 "target_coords": [0,0,0,0,0,0]
  - [x] 1.5: 更新 update_module_params 中直线运动坐标模式的参数读取：从 self.target_x/y/z/rx/ry/rz 读取，写入 target_coords
  - [x] 1.6: 更新 on_step_clicked 中直线运动坐标模式的参数回填：从 target_coords 读取填入 self.target_x/y/z/rx/ry/rz

- [x] Task 2: 直线运动 FlowThread 执行逻辑重构
  - [x] 2.1: 修改 FlowThread 中直线运动坐标模式分支：不再使用 base_coords + offset 计算，直接使用 module['params']['target_coords'] 作为目标位姿
  - [x] 2.2: 点位模式分支保持不变（已有 resolve_point 逻辑）

- [x] Task 3: 圆弧运动增加点位/坐标模式切换
  - [x] 3.1: 在 arc_params 创建处，将 arc_layout 从 QGridLayout 改为 QVBoxLayout，顶部添加模式切换行（QRadioButton "坐标模式"/"点位模式"）
  - [x] 3.2: 添加 self.arc_mode = "coords"、self.arc_coords_radio、self.arc_point_radio
  - [x] 3.3: 添加 self.arc_point_combo（QComboBox，默认隐藏）和 self.arc_point_preview（QLabel，默认隐藏）
  - [x] 3.4: 将原有的半径/速度输入放入一个 arc_coords_widget 子容器中
  - [x] 3.5: 连接 arc_coords_radio.toggled 到 _on_arc_mode_changed 方法
  - [x] 3.6: 实现 _on_arc_mode_changed：坐标模式显示半径/速度，隐藏 combo/preview；点位模式隐藏半径/速度，显示 combo/preview 并调用 _refresh_point_combos
  - [x] 3.7: 连接 arc_point_combo.currentTextChanged 到 _on_arc_point_selected 方法
  - [x] 3.8: 实现 _on_arc_point_selected：调用 resolve_point 并更新 arc_point_preview

- [x] Task 4: 圆弧运动 FlowThread 执行逻辑 + 参数保存/回填
  - [x] 4.1: 更新 add_module 中圆弧运动模块初始参数：增加 "mode": "coords", "point_name": ""
  - [x] 4.2: 更新 update_module_params 中圆弧运动分支：根据 arc_mode 保存 mode 和 point_name
  - [x] 4.3: 更新 on_step_clicked 中圆弧运动分支：根据 mode 回填 arc_coords_radio/arc_point_radio 和 arc_point_combo
  - [x] 4.4: 修改 FlowThread 中圆弧运动 MovC 分支：支持 mode="point" 时从 resolve_point 获取终点坐标

- [x] Task 5: 清理冗余代码
  - [x] 5.1: 从 gui_app.py 导入语句中移除 QSlider
  - [x] 5.2: 从 gui_app.py 导入语句中移除 QIcon

# Task Dependencies
- Task 2 依赖 Task 1（UI 变量重命名后 FlowThread 才能正确引用）
- Task 4 依赖 Task 3（UI 控件创建后才能实现参数保存/回填）
- Task 5 独立
