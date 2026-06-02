# 代码检查与删除旧打包文件 Spec

## Why
项目中残留旧的 PyInstaller 打包产物（DobotControl.spec、build/DobotControl/），占用磁盘空间且非项目源码，需要清理。

## What Changes
- 验证所有源码文件语法正确、导入无误
- 删除旧的 PyInstaller 打包产物和构建文件

## Impact
- Affected specs: 无
- Affected code: 无源码变更

## ADDED Requirements

### Requirement: 代码语法检查
系统 SHALL 确保所有 Python 源文件通过语法编译检查。

#### Scenario: 语法编译通过
- **WHEN** 对所有 .py 文件执行 py_compile
- **THEN** 无语法错误，所有文件通过检查

### Requirement: 清理旧打包文件
系统 SHALL 删除所有旧的 PyInstaller 打包产物。

#### Scenario: 删除 spec 文件
- **WHEN** 执行清理
- **THEN** DobotControl.spec 被删除

#### Scenario: 删除 build 目录
- **WHEN** 执行清理
- **THEN** build/DobotControl/ 目录及其所有内容被删除

## REMOVED Requirements

### Requirement: DobotControl.spec 打包配置文件
**Reason**: 旧的打包配置，不再使用
**Migration**: 直接删除

### Requirement: build/DobotControl/ 打包输出目录
**Reason**: 旧的打包产物（含 .exe、.toc、.pyz 等），可重新生成
**Migration**: 直接删除
