# Tasks

- [ ] Task 1: 更新 README.md 反映当前项目实际状态
  - [ ] 1.1: 移除夹爪控制器相关描述（核心模块表、抓取流程、硬件要求、依赖）
  - [ ] 1.2: 移除骨架化端点检测描述，改为掩码几何中心
  - [ ] 1.3: 更新点位系统描述（d435i/d405 两个点位）
  - [ ] 1.4: 更新抓取流程描述（移除夹爪闭合步骤）
  - [ ] 1.5: 更新核心模块表（移除 gripper_controller.py 行）
  - [ ] 1.6: 更新双相机协同描述（均使用掩码几何中心）
  - [ ] 1.7: 移除 minimalmodbus/pyserial 依赖描述

- [ ] Task 2: 创建 .gitignore 文件
  - [ ] 2.1: 添加 Python 缓存排除规则
  - [ ] 2.2: 添加虚拟环境排除规则
  - [ ] 2.3: 添加构建产物排除规则
  - [ ] 2.4: 添加 IDE 配置排除规则
  - [ ] 2.5: 添加 graphify 临时文件排除规则
  - [ ] 2.6: 添加 pip 本地安装排除规则
  - [ ] 2.7: 添加编译中间文件排除规则

- [ ] Task 3: 初始化 Git 仓库并创建初始提交
  - [ ] 3.1: git init
  - [ ] 3.2: git add 所有文件
  - [ ] 3.3: git commit（conventional commit message）

- [ ] Task 4: 创建 GitHub 远程仓库并推送
  - [ ] 4.1: gh auth login（如需登录）
  - [ ] 4.2: gh repo create Dobot-VGS-RS400
  - [ ] 4.3: git remote add origin
  - [ ] 4.4: git push -u origin main

# Task Dependencies
- [Task 2] depends on [Task 1]（先更新文档再提交）
- [Task 3] depends on [Task 1, Task 2]（先完成文档更新和 .gitignore 再提交）
- [Task 4] depends on [Task 3]（先有本地提交再推送）
