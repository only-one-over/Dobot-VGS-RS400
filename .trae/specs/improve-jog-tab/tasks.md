# Tasks

- [x] Task 1: 重构"点动控制"Tab布局 — 替换当前布局为模式切换+动态内容
  - [x] SubTask 1.1: 删除当前"关节轴控制"、"坐标轴控制"、"坐标类型选择"的代码
  - [x] SubTask 1.2: 添加模式切换（QComboBox: "坐标模式"/"轴模式"），绑定切换事件
  - [x] SubTask 1.3: 创建坐标模式widget：实时TCP坐标Label + 目标坐标输入框(QDoubleSpinBox x6) + "运动到目标"按钮 + 坐标点动按钮(X/Y/Z/Rx/Ry/Rz) + 坐标类型选择
  - [x] SubTask 1.4: 创建轴模式widget：实时关节角度Label + 目标角度输入框(QDoubleSpinBox x4) + "运动到目标"按钮 + 关节点动按钮(J1-J4)
  - [x] SubTask 1.5: 使用 QStackedWidget 切换坐标/轴模式widget

- [x] Task 2: 添加实时位置更新逻辑
  - [x] SubTask 2.1: 在 _read_torque_from_controller 定时器回调中添加实时坐标/角度更新
  - [x] SubTask 2.2: 从 feed_data 的 ToolVectorActual 读取TCP坐标更新Label
  - [x] SubTask 2.3: 从 feed_data 的 QActual 读取关节角度更新Label

- [x] Task 3: 添加"运动到目标"功能
  - [x] SubTask 3.1: 坐标模式"运动到目标"按钮 — 调用 MovJ(x,y,z,rx,ry,rz,0)
  - [x] SubTask 3.2: 轴模式"运动到目标"按钮 — 调用 MovJ(j1,j2,j3,j4,0,0,1)

# Task Dependencies
- [Task 2] depends on [Task 1] (需要先创建Label才能更新)
- [Task 3] depends on [Task 1] (需要先创建输入框才能读取目标值)
