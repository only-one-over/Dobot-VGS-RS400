# 获取当前位置直接修改拍照位 Spec

## Why
当前"获取位置"按钮仅弹窗显示当前位置，用户需要手动将数值复制到拍照位置输入框中。应支持一键将当前位姿填入拍照位置输入框，简化操作流程。

## What Changes
- 修改 `get_current_position` 方法，获取当前位置后不仅弹窗显示，还将值填入拍照位置的 6 个输入框
- 在拍照位置设置区域添加"从当前位置获取"按钮，方便用户直接从当前位姿更新拍照位置

## Impact
- Affected code: `gui_app.py`（get_current_position 方法 + 拍照位置 UI 区域）

## ADDED Requirements
### Requirement: 获取当前位置可更新拍照位置
用户获取当前位置后，可选择将当前位姿直接填入拍照位置输入框。

#### Scenario: 获取位置后填入拍照位置
- **WHEN** 用户点击"获取位置"按钮并成功获取当前位姿
- **THEN** 弹窗询问是否将当前位置设为拍照位置，确认后自动填入拍照位置的 6 个输入框

#### Scenario: 拍照位置区域直接获取
- **WHEN** 用户在拍照位置设置区域点击"从当前位置获取"按钮
- **THEN** 当前位姿自动填入拍照位置的 6 个输入框

## MODIFIED Requirements
无

## REMOVED Requirements
无
