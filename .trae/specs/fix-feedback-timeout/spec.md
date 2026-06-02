# 修复实时反馈超时问题 Spec

## Overview
- **Summary**: 用户反馈连接时实时反馈超时，需要添加端口30004的测试和更好的错误处理
- **Purpose**: 解决实时反馈端口连接失败导致连接被拒绝的问题
- **Target Users**: Dobot机器人用户

## Goals
- 添加端口30004的预测试
- 增加反馈连接超时处理
- 添加反馈连接失败时的重试机制
- 如果反馈连接失败，给出明确的错误提示

## Non-Goals (Out of Scope)
- 修改机器人固件设置

## Background & Context
当前问题：
- Dashboard端口29999连接成功
- RobotMode和GetAngle验证通过
- 但实时反馈端口30004连接超时

可能原因：
- 机器人未启用反馈端口30004
- 防火墙阻止了端口30004
- 网络延迟导致反馈数据接收慢

## Functional Requirements
- **FR-1**: 在连接前测试端口30004是否可达
- **FR-2**: 增加反馈连接超时时间
- **FR-3**: 添加反馈连接失败时的重试机制
- **FR-4**: 如果反馈无法连接，允许跳过反馈继续连接（可选）

## Acceptance Criteria

### AC-1: 端口30004测试
- **Given**: 用户点击连接按钮
- **When**: 端口30004不可达
- **Then**: 显示警告"反馈端口30004不可达，部分功能可能受限"
- **Verification**: programmatic

### AC-2: 反馈连接重试
- **Given**: 用户点击连接按钮
- **When**: 反馈连接失败
- **Then**: 自动重试3次后再失败
- **Verification**: programmatic

### AC-3: 可选跳过反馈
- **Given**: 反馈端口无法连接
- **When**: 用户选择继续
- **Then**: 跳过反馈继续连接机器人
- **Verification**: human-judgment
