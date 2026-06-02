# 检查项目逻辑并创建TCP连接测试 Spec

## Why
当前项目存在连接逻辑问题：DobotController在__init__时不连接，但GUI在初始化时就创建了DobotController实例，导致is_connected=False。当用户点击"使能机器人"时，会先调用connect()，而connect()中会自动调用enable_robot()，然后enable_robot()又会被再次调用，造成重复使能。同时RequestControl()只在机器人未上电或下使能时才允许切换，如果机器人已经使能则RequestControl()会失败。需要创建独立的TCP连接测试脚本来验证通信是否正常。

## What Changes
- 分析并修复项目中的连接逻辑问题
- 创建独立的TCP连接测试文件夹和脚本

## Impact
- 受影响的功能：机器人连接和使能流程
- 受影响的代码：
  - `dobot_move/robot_controller.py` - 连接和使能逻辑
  - `dobot_move/gui_app.py` - GUI调用逻辑

## ADDED Requirements

### Requirement: 独立TCP连接测试脚本
创建一个独立的测试脚本，用于验证TCP连接是否正常

#### Scenario: 测试TCP连接
- **WHEN** 运行测试脚本
- **THEN** 脚本逐步测试：连接→读取欢迎消息→RequestControl→ClearError→PowerOn→RobotMode→EnableRobot

### Requirement: 修复连接逻辑
connect()中自动调用enable_robot()会导致重复使能问题

#### Scenario: 正确的连接流程
- **WHEN** 用户点击"使能机器人"按钮
- **THEN** connect()只负责连接和RequestControl，enable_robot()由用户手动触发

## MODIFIED Requirements

### Requirement: RequestControl调用时机
RequestControl只在机器人未上电或下使能时才允许调用，如果机器人已经使能则不应该调用

#### Scenario: 机器人已使能时连接
- **WHEN** 机器人已经处于使能状态
- **THEN** 跳过RequestControl，直接使用TCP指令
