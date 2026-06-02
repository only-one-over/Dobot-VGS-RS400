# Tasks
- [x] Task 1: 在 config_manager.py 中添加小车 IP、小车端口、Modbus 端口的读写函数
  - [x] SubTask 1.1: 添加 get_cart_ip() / set_cart_ip(ip) 函数，默认值 "192.168.5.2"
  - [x] SubTask 1.2: 添加 get_cart_port() / set_cart_port(port) 函数，默认值 502
  - [x] SubTask 1.3: 添加 get_modbus_port() / set_modbus_port(port) 函数，默认值 502
- [x] Task 2: 修改 gui_app.py 中 IP/端口输入框的初始化，从配置读取默认值
  - [x] SubTask 2.1: 导入新增的 config_manager 函数
  - [x] SubTask 2.2: cart_ip_input 初始值改为 get_cart_ip()
  - [x] SubTask 2.3: cart_port_input 初始值改为 str(get_cart_port())
  - [x] SubTask 2.4: modbus_port_input 初始值改为 str(get_modbus_port())
- [x] Task 3: 为所有 IP/端口输入框绑定 editingFinished 信号实现即时保存
  - [x] SubTask 3.1: ip_input.editingFinished 连接保存机器人 IP
  - [x] SubTask 3.2: cart_ip_input.editingFinished 连接保存小车 IP
  - [x] SubTask 3.3: cart_port_input.editingFinished 连接保存小车端口
  - [x] SubTask 3.4: modbus_port_input.editingFinished 连接保存 Modbus 端口
- [x] Task 4: 验证所有 IP/端口修改后重启应用能自动恢复

# Task Dependencies
- Task 2 依赖 Task 1
- Task 3 依赖 Task 1
- Task 4 依赖 Task 2 和 Task 3
