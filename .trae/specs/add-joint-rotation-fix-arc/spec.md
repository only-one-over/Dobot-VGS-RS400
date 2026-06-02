# Add Joint Rotation & Fix Arc Movement Spec

## Why
1. 运动编辑面板缺少关节角旋转控制选项，用户无法通过GUI直接控制各关节角度偏移
2. 圆弧运动(MovC)逻辑存在缺陷：dobot_api.py缺少MovC方法，圆弧中间点和目标点计算逻辑错误导致运动轨迹不正确

## What Changes
- 在dobot_api.py中添加MovC圆弧运动方法
- 在robot_controller.py中添加move_arc()和move_joint_relative()方法
- 在gui_app.py运动编辑面板中添加"关节旋转"模块选项和参数编辑区域
- 修复run_grasp_flow()中圆弧运动的中间点计算逻辑
- 在move_to_point()中支持MovC运动类型

## Impact
- Affected specs: dobot_api.py, robot_controller.py, gui_app.py
- Affected code: 运动编辑模块拼接、流程执行逻辑

## ADDED Requirements

### Requirement: Joint Angle Rotation Control
系统应允许用户通过GUI添加关节角度偏移运动模块

#### Scenario: 添加关节旋转模块
- **WHEN** 用户在运动编辑面板选择"关节旋转"模块
- **THEN** 显示6个关节的偏移角度输入框和速度设置
- **AND** 添加到抓取流程后生成正确的RelJointMovJ指令

#### Scenario: 执行关节旋转
- **WHEN** 用户执行包含关节旋转的流程
- **THEN** 机器人从当前位置按指定的关节角度偏移进行运动

### Requirement: Fix Arc Movement Logic
圆弧运动应正确计算中间点和目标点，并使用正确的API方法

#### Scenario: 圆弧运动执行
- **WHEN** 用户执行圆弧运动模块
- **THEN** 系统发送正确的MovC指令（包含中间点和目标点）
- **AND** 圆弧半径参数正确影响运动轨迹

## MODIFIED Requirements

### Requirement: Motion Edit Panel
在模块拼接工具的模块选择下拉框中添加"关节旋转"选项，并添加对应的参数编辑面板

### Requirement: Arc Movement Execution
修复run_grasp_flow()中MovC的执行逻辑：
- 中间点应基于相机识别位置和半径计算，使得圆弧真正经过目标点
- 目标点应为相机识别的物体位置

### Requirement: move_to_point Method
扩展move_to_point()方法支持MovC运动类型，接收middle_pose参数并调用正确的API

## REMOVED Requirements
无
