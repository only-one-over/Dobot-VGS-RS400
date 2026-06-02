# D405 实时视觉伺服抓取控制器 Spec

## Why
当前系统 D405 仅做单次识别后开环运动，无法应对目标移动或定位偏差。需要独立的 D405 PBVS（基于位置的视觉伺服）闭环控制器，结合卡尔曼滤波和自适应增益，实现实时抓取闭环控制。

## What Changes
- 新增 `visual_servo_controller.py`：独立的 D405 实时视觉伺服抓取控制器，包含 PBVS 闭环、自适应增益、卡尔曼前馈补偿、安全保护
- 修改 `gui_app.py`：FlowThread 新增 `visual_servo` 模块类型，集成视觉伺服流程

## Impact
- Affected code: `gui_app.py`（FlowThread 新增模块类型）
- 新增文件: `visual_servo_controller.py`

## ADDED Requirements

### Requirement: PBVS 闭环控制器
系统 SHALL 提供 PBVS（基于位置的视觉伺服）闭环控制器，通过 D405 持续反馈目标位置，驱动机器人逼近抓取点。

#### Scenario: 正常收敛
- **WHEN** PBVS 循环运行，位置误差 > 收敛阈值
- **THEN** 每帧计算误差 e = p_target - p_current，执行 MovL(p_current + e × gain)

#### Scenario: 收敛成功
- **WHEN** 位置误差 < 收敛阈值（默认 2mm）
- **THEN** 循环退出，返回成功

#### Scenario: 超时退出
- **WHEN** 循环次数超过最大迭代次数（默认 60）
- **THEN** 循环退出，返回失败

### Requirement: 自适应增益
系统 SHALL 根据位置误差大小自动调整增益和速度。

#### Scenario: 远距离逼近
- **WHEN** 误差 > 50mm
- **THEN** gain=0.6, speed=10%

#### Scenario: 中距离逼近
- **WHEN** 10mm < 误差 <= 50mm
- **THEN** gain=0.4, speed=5%

#### Scenario: 近距离精调
- **WHEN** 误差 <= 10mm
- **THEN** gain=0.2, speed=2%

### Requirement: 卡尔曼前馈补偿
系统 SHALL 利用卡尔曼滤波器的速度估计做前馈补偿，应对目标移动。

#### Scenario: 目标静止
- **WHEN** 卡尔曼速度估计 ≈ 0
- **THEN** 前馈项为 0，退化为标准 PBVS

#### Scenario: 目标移动
- **WHEN** 卡尔曼速度估计 > 0
- **THEN** 指令位置加入 v_target × dt 前馈补偿

### Requirement: 安全保护
系统 SHALL 在每步运动前进行安全检查。

#### Scenario: 步长限制
- **WHEN** 单步计算位移 > max_step_mm（默认 5mm）
- **THEN** 缩减位移到 max_step_mm

#### Scenario: Z 轴下限
- **WHEN** 目标 Z 坐标 < 0
- **THEN** 跳过该步运动

### Requirement: 流程集成
系统 SHALL 在 FlowThread 中支持 `visual_servo` 模块类型。

#### Scenario: 执行视觉伺服
- **WHEN** 流程中遇到 visual_servo 模块
- **THEN** 使用 D405 执行 PBVS 闭环，收敛后更新 p_u405/p_n405 点位

## MODIFIED Requirements
无。

## REMOVED Requirements
无。
