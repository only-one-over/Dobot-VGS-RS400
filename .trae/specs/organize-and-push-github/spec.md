# 整理项目并推送到 GitHub 仓库 Spec

## Why
项目代码经过多轮迭代（C++ pybind11 模块、视觉系统重构、夹爪移除、点位系统重构等），需要整理代码、更新文档、初始化 Git 仓库并推送到 GitHub 新仓库。

## What Changes
- 更新 README.md：移除过时描述（夹爪、骨架化端点检测等），更新为当前实际功能
- 创建 .gitignore：排除 .venv/、build/、__pycache__/、.pyd、graphify-out/ 等
- 初始化 Git 仓库
- 提交所有代码（conventional commit）
- 创建 GitHub 远程仓库（名称缩写：Dobot-VGS-RS400）
- 推送代码到 GitHub

## Impact
- Affected code: README.md（更新）、.gitignore（新建）
- Affected docs: README.md 需反映当前实际功能状态

## ADDED Requirements

### Requirement: 更新 README.md
系统 SHALL 更新 README.md 以反映当前项目实际状态：
- 移除夹爪控制器相关描述
- 移除骨架化端点检测描述，改为掩码几何中心
- 更新点位系统描述（d435i/d405 两个点位）
- 更新抓取流程描述
- 更新核心模块表（移除夹爪控制器行）

#### Scenario: README 准确反映当前代码
- WHEN 用户阅读 README.md
- THEN 所有描述与当前代码功能一致

### Requirement: 创建 .gitignore
系统 SHALL 创建 .gitignore 文件排除不需要版本控制的文件：
- Python 缓存（__pycache__/、*.pyc）
- 虚拟环境（.venv/）
- 构建产物（build/、Release/、*.pyd）
- IDE 配置（.vscode/）
- graphify 临时文件（graphify-out/、_graphify_*.py）
- pip 本地安装（.pip_packages/）
- 编译中间文件（cpp_core/build/）

#### Scenario: git status 不显示无关文件
- WHEN 执行 git status
- THEN 不显示 .venv/、build/、__pycache__/ 等文件

### Requirement: 初始化 Git 并提交
系统 SHALL 初始化 Git 仓库并创建初始提交。

#### Scenario: 初始提交成功
- WHEN 执行 git init + git add + git commit
- THEN 所有源代码文件被提交，无关文件被排除

### Requirement: 创建 GitHub 仓库并推送
系统 SHALL 创建 GitHub 远程仓库并推送代码。

仓库信息：
- 名称：Dobot-VGS-RS400
- 描述：Dobot Vision-Guided System Based on RealSense D400 Series Binocular Cameras
- 可见性：由用户决定

#### Scenario: 推送成功
- WHEN 执行 gh repo create + git push
- THEN 代码成功推送到 GitHub 远程仓库

## MODIFIED Requirements

### Requirement: README.md 内容准确性
README.md 中所有功能描述 SHALL 与当前代码一致，包括：
- 双相机协同：D435i 粗定位 + D405 精识别（均使用掩码几何中心）
- D435i 低帧率实时识别（5fps）
- 点位系统：d435i + d405 两个默认点位
- 无夹爪控制功能

## REMOVED Requirements

### Requirement: 夹爪控制器描述
**Reason**: 夹爪功能已在上一轮重构中移除
**Migration**: 从 README.md 核心模块表和抓取流程中移除

### Requirement: 骨架化端点检测描述
**Reason**: D405 已从骨架化端点检测改为掩码几何中心
**Migration**: 更新为"掩码几何中心"描述
