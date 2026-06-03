# GitHub 风格说明文档重构与仓库界面更新 Spec

## Why
当前 README.md 偏向内部技术文档风格，缺少 GitHub 开源项目常见的视觉元素（徽章、目录、截图占位、贡献指南等），需要重构为面向 GitHub 访客的友好格式，同时更新仓库的 topics 和描述。

## What Changes
- 重构 README.md 为 GitHub 风格（徽章、目录、快速开始、功能展示、架构图、使用指南、FAQ）
- 通过 gh CLI 更新 GitHub 仓库的 description、homepage、topics
- 提交更新并推送到远程

## Impact
- Affected code: README.md（完全重写）
- Affected docs: README.md
- Affected external: GitHub 仓库界面（description, topics）

## ADDED Requirements

### Requirement: GitHub 风格 README.md
README.md SHALL 遵循 GitHub 开源项目常见格式：
- 顶部项目标题 + 一句话描述 + 徽章（Python 版本、License、平台）
- 目录（Table of Contents）
- 功能特性（带 emoji 图标）
- 系统架构图（保留 ASCII 架构图）
- 快速开始（Quick Start）——精简的安装步骤
- 使用指南——详细的操作流程
- 配置说明
- C++ 加速模块
- 常见问题
- 许可证

#### Scenario: GitHub 访客快速了解项目
- WHEN 访客打开仓库首页
- THEN 能在 10 秒内了解项目用途、技术栈、如何安装

### Requirement: 更新 GitHub 仓库界面
通过 gh CLI 更新仓库元信息：
- description: "Vision-Guided System for Dobot CR Series Robots with Intel RealSense D400 Depth Cameras"
- topics: dobot, realsense, yolo, robotic-arm, computer-vision, pyqt6, pybind11, visual-servoing, force-control

#### Scenario: 仓库搜索可发现
- WHEN 用户在 GitHub 搜索 dobot 或 realsense
- THEN 仓库出现在搜索结果中

## MODIFIED Requirements

### Requirement: README.md 结构
README.md 结构从"内部技术文档"改为"GitHub 开源项目风格"：
- 标题 + 徽章 + 一句话描述
- 目录导航
- 功能特性（简洁列表）
- 快速开始（3 步安装）
- 详细使用指南
- 架构/配置/FAQ

## REMOVED Requirements
无
