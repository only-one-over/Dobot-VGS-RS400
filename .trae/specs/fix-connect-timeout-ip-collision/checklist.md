# Verification Checklist

- [x] connect() 设置 3 秒超时，网络不通时返回 False
- [x] connect() 验证 RobotMode() 通信成功才返回 True
- [x] GUI 有 IP 地址编辑框，默认 192.168.5.1
- [x] 连接时使用编辑框中的 IP
- [x] GUI 有碰撞检测等级设置（0-5）
- [x] set_collision_level() 调用 SetCollisionLevel
- [x] 所有 .py 文件语法检查通过
