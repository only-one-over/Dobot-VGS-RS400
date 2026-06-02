# 编写项目说明文档 Spec

## Why
项目缺少完整的 README.md 说明文档，新用户无法快速了解项目功能、安装环境、配置步骤和使用方法。需要编写一份结构化的项目文档，涵盖环境安装、硬件连接、配置说明、运行方式及架构概览。

## What Changes
- 新增 `README.md` 项目说明文档（中文）
- 更新 `PORTING_GUIDE.md`，补充 C++ 核心模块相关内容

## Impact
- Affected code: 无代码变更，仅文档
- Affected docs: `README.md`（新增）、`PORTING_GUIDE.md`（更新）

## ADDED Requirements

### Requirement: README.md 项目说明文档
系统 SHALL 提供完整的 `README.md` 文档，包含以下章节：

1. **项目简介**：项目名称、功能概述（越疆 CR5 机械臂 + 双相机视觉 + 力控抓取）、核心特性
2. **系统架构**：模块关系图（文字描述）、核心模块列表及职责
3. **硬件要求**：机械臂型号、相机型号、夹爪、力传感器、网络连接
4. **环境安装**：Python 版本、pip 依赖安装、C++ 核心模块编译（可选）、验证安装
5. **配置说明**：config.json 配置项说明（机器人 IP、拍照位置、手眼标定参数）、相机序列号配置、夹爪串口配置
6. **运行方式**：启动 GUI 程序、首次使用流程（连接→使能→标定→抓取）
7. **模块说明**：各 Python 模块的简要说明
8. **C++ 加速模块**：dobot_core 模块说明、编译方式、回退机制
9. **常见问题**：常见错误及解决方案

#### Scenario: 新用户按照文档完成环境搭建
- **WHEN** 新用户按照 README.md 的"环境安装"章节操作
- **THEN** 能够成功安装所有依赖并启动 GUI 程序

### Requirement: 更新 PORTING_GUIDE.md
`PORTING_GUIDE.md` SHALL 补充 C++ 核心模块（dobot_core）的移植说明，包括模块结构、编译依赖、API 接口。

#### Scenario: 开发者参考 PORTING_GUIDE.md 移植 C++ 模块
- **WHEN** 开发者阅读更新后的 PORTING_GUIDE.md
- **THEN** 能够理解 dobot_core 模块的结构和 API，并成功在其他平台编译

## MODIFIED Requirements
无

## REMOVED Requirements
无
