# Tasks

- [x] Task 1: 默认点位改用 QTableWidgetItem 纯文本显示
  - [x] 1.1: 在 refresh_points_table 中，当 is_default=True 时，坐标列使用 QTableWidgetItem 显示格式化数值（保留2位小数），不创建 QDoubleSpinBox
  - [x] 1.2: 默认点位的"相对"和"基准点位"列保持空白（已有逻辑，确认不变）

- [x] Task 2: 自定义点位 QDoubleSpinBox 紧凑样式修复
  - [x] 2.1: 为自定义点位的 QDoubleSpinBox 设置紧凑样式（减小 padding、font-size、border），确保不超出单元格
  - [x] 2.2: 将表格行高从 48px 增大到 56px
  - [x] 2.3: 设置 verticalHeader.setDefaultSectionSize(56) 与 setRowHeight 一致

- [x] Task 3: 运动编辑点位模式添加坐标预览
  - [x] 3.1: 在 linear_point_combo 下方添加 linear_point_preview QLabel，选定点位后显示坐标
  - [x] 3.2: 在 fa_point_combo 下方添加 fa_point_preview QLabel，选定点位后显示坐标
  - [x] 3.3: 连接 linear_point_combo.currentTextChanged 信号，选定点位后调用 resolve_point 并更新预览标签
  - [x] 3.4: 连接 fa_point_combo.currentTextChanged 信号，选定点位后调用 resolve_point 并更新预览标签

- [x] Task 4: 确保 combo 刷新时机正确
  - [x] 4.1: 在 _on_add_point 和 _on_delete_point 中确认 refresh_points_table 被调用（已有，验证）
  - [x] 4.2: 在 _on_linear_mode_changed 切换到点位模式时，主动调用 _refresh_point_combos 确保列表最新
  - [x] 4.3: 在 _on_fa_mode_changed 切换到点位模式时，主动调用 _refresh_point_combos 确保列表最新

# Task Dependencies
- Task 3 依赖 Task 1（resolve_point 需要正确返回默认点位坐标）
- Task 4 独立
