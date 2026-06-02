# Tasks

- [x] Task 1: 修改 config.json 和 config_manager.py 支持点位数据
  - [x] 1.1: config.json 新增 points 字段，包含 3 个默认点位
  - [x] 1.2: config_manager.py 新增 get_points() / set_points() / get_point(name) / set_point(name, data) / add_point(name, data) / delete_point(name) 接口
  - [x] 1.3: config_manager.py 新增 resolve_point(name) 函数，递归解析相对点位为绝对坐标

- [x] Task 2: 修改 GUI 相机连接区域布局
  - [x] 2.1: D435i 状态标签独占一行，连接/断开按钮另起一行并排
  - [x] 2.2: D405 状态标签独占一行，连接/断开按钮另起一行并排

- [x] Task 3: 新增点位编辑 UI
  - [x] 3.1: 在运动编辑选项卡中增加点位列表区域（QTableWidget 显示名称+坐标+是否相对+基准点位）
  - [x] 3.2: 添加"添加点位"按钮和输入对话框
  - [x] 3.3: 添加"删除点位"按钮（默认点位不可删除）
  - [x] 3.4: 添加"编辑点位"功能：双击或选中后编辑坐标值
  - [x] 3.5: 添加相对点位设置：勾选"相对模式"+ 选择基准点位 + 输入偏移量
  - [x] 3.6: 点位变化时自动保存到 config.json

- [x] Task 4: 修改直线运动参数编辑，增加模式切换
  - [x] 4.1: 在直线运动参数区域顶部添加"坐标模式/点位模式"切换按钮（QRadioButton）
  - [x] 4.2: 坐标模式显示现有偏移值输入框（保持不变）
  - [x] 4.3: 点位模式显示点位选择下拉框（QComboBox，列出所有已定义点位）
  - [x] 4.4: 模式切换时保存/恢复各模式参数

- [x] Task 5: 修改力控圆弧参数编辑，增加模式切换
  - [x] 5.1: 在力控圆弧参数区域顶部添加"坐标模式/点位模式"切换
  - [x] 5.2: 坐标模式显示现有圆心坐标输入框（保持不变）
  - [x] 5.3: 点位模式显示点位选择下拉框，选中的点位作为圆心
  - [x] 5.4: 模式切换时保存/恢复各模式参数

- [x] Task 6: 修改 FlowThread 相机识别模块更新点位
  - [x] 6.1: D435i 识别后，将结果写入全局点位 p_d435i
  - [x] 6.2: D405 识别后，柄端写入 p_u405，钩尖写入 p_n405
  - [x] 6.3: 点位更新后保存到 config.json

- [x] Task 7: 修改 FlowThread 运动模块支持点位引用
  - [x] 7.1: 直线运动模块：若参数含 point_name，从点位字典解析坐标作为目标
  - [x] 7.2: 力控圆弧模块：若参数含 point_name，从点位字典解析坐标作为圆心
  - [x] 7.3: 相对点位自动递归解析为绝对坐标
  - [x] 7.4: 点位不存在时报错终止

- [x] Task 8: 修改 add_module 和 update_module_params 支持新模式
  - [x] 8.1: 直线运动模块新增时，params 包含 mode("coords"/"point") 和 point_name 字段
  - [x] 8.2: 力控圆弧模块新增时，params 包含 mode 和 point_name 字段
  - [x] 8.3: update_module_params 根据当前模式读取对应参数
  - [x] 8.4: on_step_clicked 加载模块参数时恢复模式切换状态

# Task Dependencies
- [Task 2] depends on nothing (independent)
- [Task 3] depends on [Task 1]
- [Task 4] depends on [Task 1]
- [Task 5] depends on [Task 1]
- [Task 6] depends on [Task 1]
- [Task 7] depends on [Task 1, Task 6]
- [Task 8] depends on [Task 4, Task 5]
