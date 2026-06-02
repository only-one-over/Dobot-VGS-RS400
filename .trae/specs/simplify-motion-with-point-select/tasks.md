# Tasks

- [x] Task 1: 直线运动简化为始终选定点位
  - [x] 1.1: 移除直线运动的坐标模式/点位模式切换（删除 linear_coords_radio、linear_point_radio、linear_mode 变量和模式切换布局行）
  - [x] 1.2: linear_point_combo 和 linear_point_preview 改为始终显示（不再 hide）
  - [x] 1.3: 移除 linear_target_widget（6个目标坐标输入框），保留速度输入和"读取当前位置"按钮，将它们直接放入 linear_layout
  - [x] 1.4: "读取当前位置"按钮改为将当前位姿写入点位管理（用名称如 "current_pos"），并自动选中该点位
  - [x] 1.5: 更新 add_module 中直线运动初始参数：移除 target_coords 和 mode，只保留 point_name 和 speed
  - [x] 1.6: 更新 update_module_params 中直线运动分支：只保存 point_name 和 speed
  - [x] 1.7: 更新 on_step_clicked 中直线运动分支：只回填 point_name 到 combo
  - [x] 1.8: 更新 FlowThread 中直线运动分支：统一使用 resolve_point，移除 target_coords 分支
  - [x] 1.9: 更新 view_current_grasp_flow 中直线运动显示：统一显示点位名称

- [x] Task 2: 删除圆弧运动模块
  - [x] 2.1: 从 module_combo.addItems 中移除 "圆弧运动"
  - [x] 2.2: 删除 arc_params 整个 widget 及其所有子控件（arc_coords_radio、arc_point_radio、arc_point_combo、arc_point_preview、arc_coords_widget、arc_radius、arc_speed）
  - [x] 2.3: 删除 _on_arc_mode_changed 和 _on_arc_point_selected 方法
  - [x] 2.4: 从 on_module_combo_changed 中移除 "圆弧运动" 分支
  - [x] 2.5: 从 add_module 中移除 "圆弧运动" 分支
  - [x] 2.6: 从 update_module_params 中移除 "圆弧运动" 分支
  - [x] 2.7: 从 on_step_clicked 中移除 MovC 分支
  - [x] 2.8: 从 FlowThread 中移除 MovC 分支（elif module['params']['motion_type'] == "MovC"）
  - [x] 2.9: 从 view_current_grasp_flow 中移除圆弧运动显示分支
  - [x] 2.10: 从 _DEFAULT_GRASP_FLOW_MODULES 中移除圆弧运动模块
  - [x] 2.11: 从 _refresh_point_combos 中移除 arc_point_combo 刷新逻辑

- [x] Task 3: 力控圆弧圆心增加点位选择
  - [x] 3.1: 在 fa_center_widget 上方添加圆心坐标模式/点位模式切换（fa_center_coords_radio "坐标模式"、fa_center_point_radio "点位模式"）
  - [x] 3.2: 添加 fa_center_mode 变量（"coords" 或 "point"）
  - [x] 3.3: 添加 fa_center_point_combo（QComboBox，默认隐藏）和 fa_center_point_preview（QLabel，默认隐藏）
  - [x] 3.4: 连接 fa_center_coords_radio.toggled 到 _on_fa_center_mode_changed
  - [x] 3.5: 实现 _on_fa_center_mode_changed：坐标模式显示 fa_center_widget，隐藏 combo/preview；点位模式隐藏 fa_center_widget，显示 combo/preview 并刷新
  - [x] 3.6: 连接 fa_center_point_combo.currentTextChanged 到 _on_fa_center_point_selected
  - [x] 3.7: 实现 _on_fa_center_point_selected：调用 resolve_point 并更新 preview
  - [x] 3.8: 更新 add_module 中力控圆弧初始参数：增加 center_mode="coords"、center_point_name=""
  - [x] 3.9: 更新 update_module_params 中力控圆弧分支：根据 fa_center_mode 保存 center_mode 和 center_point_name
  - [x] 3.10: 更新 on_step_clicked 中力控圆弧分支：根据 center_mode 回填 radio 和 combo
  - [x] 3.11: 更新 FlowThread 中力控圆弧分支：支持 center_mode="point" 时从 resolve_point 获取圆心坐标

# Task Dependencies
- Task 2 独立（删除圆弧运动）
- Task 1 和 Task 3 独立
- Task 1 应在 Task 2 之前完成（避免删除时误删共享代码）
