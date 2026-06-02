# Verification Checklist

* [x] enable\_robot() 设置 socket 超时 2 秒，超时返回 False

* [x] disable\_robot() 设置 socket 超时 2 秒

* [x] connect() 不再自动调用 enable\_robot()

* [x] gui\_app 新增"连接机器人"按钮可见可点击

* [x] 未连接时点击使能弹窗"机器人未连接"

* [x] 使能/下使能/连接在后台线程执行，UI 不卡死

* [x] 所有 .py 文件语法检查通过

