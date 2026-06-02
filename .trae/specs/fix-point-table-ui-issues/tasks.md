# Tasks

- [x] Task 1: 默认点位行隐藏"相对"和"基准点位"列控件
  - [x] 1.1: 在 refresh_points_table 中，当 is_default=True 时，第7列和第8列不设置 cellWidget（留空）

- [x] Task 2: 调整表格列宽分配
  - [x] 2.1: 名称列设为固定宽度 100px（setSectionResizeMode Fixed + setWidth）
  - [x] 2.2: X/Y/Z/Rx/Ry/Rz 列设为 Stretch 模式
  - [x] 2.3: "相对"列设为固定宽度 60px
  - [x] 2.4: "基准点位"列设为固定宽度 120px

- [x] Task 3: 修复相对点位选取后不触发坐标重算
  - [x] 3.1: 在 _on_point_relative_changed 中，勾选"相对"后立即调用 resolve_point 并更新坐标显示
  - [x] 3.2: 在 _on_point_relative_to_changed 中，选择基准点位后确保坐标立即重算并更新

# Task Dependencies
无依赖
