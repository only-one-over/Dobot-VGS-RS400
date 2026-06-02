# Verification Checklist

- [x] pymodbus 已安装
- [x] modbus_server.py 可启动 Modbus TCP 服务器
- [x] 寄存器 50001-50019 可被外部 Modbus 客户端写入
- [x] 寄存器 50030-50045 可被外部 Modbus 客户端读取
- [x] 写入 50001=1 触发复位动作
- [x] 写入 50001=2 触发回安全位
- [x] 状态寄存器定时从反馈数据更新
- [x] GUI 有 Modbus 通信选项卡
- [x] GUI 可启停 Modbus 服务
- [x] GUI 显示寄存器实时数据
- [x] 所有 .py 文件语法检查通过
