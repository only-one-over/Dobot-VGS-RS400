# Tasks

## [x] Task 1: 修复 dobot_api.py TCP 通信阻塞
- **Priority**: P0
- **Depends On**: None

## [x] Task 2: 修复 _feed_loop 异常保护
- **Priority**: P0
- **Depends On**: Task 1

## [x] Task 3: 优化 Modbus 200ms 严格周期
- **Priority**: P0
- **Depends On**: None

## [x] Task 4: GUI Modbus 选项卡增加实时状态
- **Priority**: P0
- **Depends On**: Task 3

# Task Dependencies
- Task 2 depends on Task 1
- Task 4 depends on Task 3