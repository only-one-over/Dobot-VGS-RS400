# Verification Checkli1st

- [ ] dobot\_api.py 已替换为参考版本的完整API（含 DobotApiDashboard + DobotApiFeedBack）
- [ ] files/ 目录下的 alarmController.json、alarmServo.json、alarmController.py、alarmServo.py 已复制
- [ ] robot\_controller.py 中 MovJ/MovL/MovC 调用已增加 coordinateMode=0 参数
- [ ] robot\_controller.py 已集成 DobotApiFeedBack 替代 RealTimeFeedback 和 TorqueMonitor
- [ ] realtime\_feedback\_dialog.py 已改用 DobotApiFeedBack 获取数据
- [ ] gui\_app.py 已移除 RealTimeFeedback 和 TorqueMonitor 的直接引用
- [ ] realtime\_feedback.py 已删除
- [ ] torque\_monitor.py 已删除
- [ ] build\_cpp.py 已删除
- [ ] build\_app.py 已删除
- [ ] tcp\_test/ 目录已删除
- [ ] dist/ 目录已删除
- [ ] grasp\_flow\.json 已删除
- [ ] 所有剩余.py文件import无误（无引用已删除模块）

