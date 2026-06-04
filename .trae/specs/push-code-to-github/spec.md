# 提交代码更新到 GitHub Spec

## Why
本地有大量未提交的代码变更（YOLO26 适配、GUI 架构重构、ConfigService 等），需要整理提交并推送到 GitHub 仓库。

## What Changes
- 暂存所有相关代码文件（排除 .trae/、config.json、临时测试文件）
- 创建语义化 commit
- 推送到 origin/main

## Impact
- Affected repo: https://github.com/only-one-over/Dobot-VGS-RS400

## ADDED Requirements

### Requirement: 代码提交并推送
系统 SHALL 将所有代码变更整理为语义化 commit 并推送到 GitHub。

#### Scenario: 提交成功
- **WHEN** 执行 git add + commit + push
- **THEN** GitHub 仓库包含最新代码
