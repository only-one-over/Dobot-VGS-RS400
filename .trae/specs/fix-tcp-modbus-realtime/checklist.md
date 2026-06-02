# Verification Checklist

- [x] `send_data()` 重试超过10次抛出 ConnectionError
- [x] `reConnect()` 重试超过10次抛出 ConnectionError
- [x] `_feed_loop()` 异常不导致线程崩溃
- [x] `_feed_error_count` 超过100次自动停止
- [x] Modbus 周期使用 Event.wait(0.2) 严格控制
- [x] `_modbus_cycle_count` 每轮递增
- [x] GUI Modbus 选项卡显示周期计数值
- [x] GUI Modbus 选项卡显示每轮耗时
- [x] 寄存器表格 200ms 刷新
- [x] 状态面板实时更新
- [x] 所有 .py 文件语法检查通过