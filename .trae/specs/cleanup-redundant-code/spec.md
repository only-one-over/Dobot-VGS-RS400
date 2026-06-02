# 代码冗余清理 Spec

## Why
项目经过多轮迭代后积累了冗余代码（未使用的属性、方法、重复的工具函数），需要清理以降低维护成本。

## What Changes
- 删除 gui_app.py 中未使用的 `vision` 属性
- 删除 robot_controller.py 中未调用的 `move_arc` 和 `move_to_target_position` 方法
- 将 `_euler2rot` 和 `_pose2matrix` 重复定义提取到公共模块 `transform_utils.py`
- 删除 config_manager.py 中未被外部调用的 `get_target_offset`/`set_target_offset`

## Impact
- Affected code: `gui_app.py`、`robot_controller.py`、`config_manager.py`、`vision_system.py`、`hand_eye_calib.py`
- 新增文件: `transform_utils.py`

## ADDED Requirements

### Requirement: 公共坐标变换工具模块
系统 SHALL 提供公共的 `euler2rot` 和 `pose2matrix` 函数，消除在 config_manager.py、vision_system.py、hand_eye_calib.py 中的重复定义。

#### Scenario: 统一使用公共模块
- **WHEN** 任何模块需要欧拉角转旋转矩阵或位姿转齐次变换矩阵
- **THEN** 从 `transform_utils` 模块导入 `euler2rot` 和 `pose2matrix`，不再各自定义

## MODIFIED Requirements
无。

## REMOVED Requirements

### Requirement: gui_app.py vision 属性
**Reason**: 未被任何代码引用，属于遗留代码
**Migration**: 无需迁移，直接删除

### Requirement: robot_controller.py move_arc 方法
**Reason**: 圆弧运动模块已删除，该方法无调用者
**Migration**: 如需圆弧运动功能，使用 move_to_point(move_type="MovC")

### Requirement: robot_controller.py move_to_target_position 方法
**Reason**: 无任何调用者
**Migration**: 使用 move_to_point 直接指定目标坐标

### Requirement: config_manager.py get_target_offset / set_target_offset
**Reason**: 仅被 move_to_target_position 使用，该方法将被删除
**Migration**: 使用点位管理系统替代偏移量概念
