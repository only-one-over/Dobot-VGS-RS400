#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unified UI theme: colours, palette, stylesheet, and style helpers.

Light modern theme inspired by the Yuanli Design System (源力设计系统) —
clean surfaces, soft shadows, clear hierarchy, and high legibility for
industrial robot operations.
"""

from __future__ import annotations

from ..ui.qt_compat import QColor, QPalette


# ---------------------------------------------------------------------------
# Colour tokens — Yuanli Design System light palette
# ---------------------------------------------------------------------------

COLORS = {
    "bg": "#f7f9fb",
    "surface": "#ffffff",
    "panel": "#fcfdfe",
    "card": "#ffffff",
    "line": "#eceded",
    "border": "#dde2e9",
    "text": "#0c0d0e",
    "muted": "#86909c",
    "primary": "#1664FF",
    "primary_dark": "#0055ff",
    "primary_container": "#f3f7ff",
    "success": "#2a814b",
    "warning": "#bd7e00",
    "danger": "#d7312a",
    "accent_blue": "#387bff",
}

FONT_SIZES = {
    "xs": 9,   # placeholder/disabled text
    "sm": 10,  # titles/secondary text
    "md": 11,  # body text
    "lg": 13,  # emphasized values
    "xl": 18,  # page titles
}

# Sidebar navigation icon characters (Unicode)
NAV_ICONS = {
    "主功能":    "\u2302",
    "运动编辑":  "\u27F3",
    "点位管理":  "\u25CE",
    "Modbus 通信": "\u229E",
    "报警记录":  "\u26A0",
    "相机测试":  "\u25C9",
    "生产监控":  "\u25A0",
    "配置中心":  "\u2699",
    "Runtime 调试": "\u25C8",
    "运动调试":    "\u25B6",
    "命令控制台": "\u25B8",
}


# ---------------------------------------------------------------------------
# Global stylesheet
# ---------------------------------------------------------------------------

GLOBAL_STYLESHEET = """\
* {
    font-family: "PingFang SC", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif;
    font-size: 10pt;
}

QMainWindow,
QWidget#appRoot {
    background: #f7f9fb;
    color: #0c0d0e;
}

QScrollArea,
QScrollArea > QWidget,
QScrollArea > QWidget > QWidget {
    background: transparent;
    border: none;
}

QGroupBox {
    background: #ffffff;
    border: 1px solid #eceded;
    border-radius: 8px;
    margin-top: 20px;
    font-weight: 600;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 16px;
    padding: 0 8px;
    color: #0c0d0e;
    background: #ffffff;
}

QGroupBox#topStatusPanel {
    background: #ffffff;
    border: 1px solid #eceded;
    border-radius: 8px;
    margin-top: 0;
}

QGroupBox#topStatusPanel::title {
    color: #1664FF;
}

QFrame#dashboardCard {
    background: #ffffff;
    border: 1px solid #eceded;
    border-radius: 8px;
}

QLabel {
    color: #0c0d0e;
}

QLabel#cardTitle {
    color: #86909c;
    font-size: 9pt;
    font-weight: 600;
}

QLineEdit,
QDoubleSpinBox,
QComboBox {
    min-height: 32px;
    padding: 6px 10px;
    border: 1px solid #dde2e9;
    border-radius: 4px;
    background: #ffffff;
    color: #0c0d0e;
}

QLineEdit:focus,
QDoubleSpinBox:focus,
QComboBox:focus {
    border-color: #1664FF;
    border: 2px solid #1664FF;
}

QPushButton:focus {
    border-color: #1664FF;
    outline: 1px solid #1664FF;
}

QTableWidget:focus {
    border-color: #1664FF;
}

QListWidget:focus {
    border-color: #1664FF;
}

QComboBox QAbstractItemView {
    background: #ffffff;
    color: #0c0d0e;
    selection-background-color: #1664FF;
    selection-color: #ffffff;
    border: 1px solid #dde2e9;
    padding: 4px 8px;
    outline: none;
}

QPushButton {
    min-height: 32px;
    padding: 7px 14px;
    border: 1px solid #dde2e9;
    border-radius: 4px;
    background: #ffffff;
    color: #0c0d0e;
    font-weight: 600;
}

QPushButton:hover {
    background: #f3f7ff;
    border-color: #c9cdd4;
}

QPushButton:pressed {
    background: #ebf1ff;
}

QPushButton:disabled {
    background: #f7f9fb;
    color: #c9cdd4;
    border-color: #eceded;
}

QPushButton[role="primary"] {
    background: #1664FF;
    border-color: #0055ff;
    color: #ffffff;
}

QPushButton[role="primary"]:hover {
    background: #0055ff;
}

QPushButton[role="primary"]:disabled {
    background: #a0c0ff;
    color: #ffffff;
    border-color: #a0c0ff;
}

QPushButton[role="connect"] {
    background: #e2f5eb;
    border-color: #2a814b;
    color: #189959;
}

QPushButton[role="connect"]:hover {
    background: #d4f0dc;
}

QPushButton[role="connect"]:disabled {
    background: #f7f9fb;
    color: #c9cdd4;
    border-color: #eceded;
}

QPushButton[role="warning"] {
    background: #fdf3de;
    border-color: #bd7e00;
    color: #de9400;
}

QPushButton[role="warning"]:hover {
    background: #ffe8c2;
}

QPushButton[role="warning"]:disabled {
    background: #f7f9fb;
    color: #c9cdd4;
    border-color: #eceded;
}

QPushButton[role="danger"] {
    background: #feeced;
    border-color: #d7312a;
    color: #c43138;
}

QPushButton[role="danger"]:hover {
    background: #fbd0ce;
}

QPushButton[role="danger"]:disabled {
    background: #f7f9fb;
    color: #c9cdd4;
    border-color: #eceded;
}

QPushButton[role="secondary"] {
    background: #f7f9fb;
    border-color: #dde2e9;
    color: #4e5969;
}

QPushButton[role="secondary"]:hover {
    background: #ebf1ff;
    border-color: #c9cdd4;
}

QTabWidget::pane {
    background: #ffffff;
    border: 1px solid #eceded;
    border-radius: 8px;
}

QTabWidget QTabBar {
    background: #f7f9fb;
}

QTabWidget QTabBar::tab {
    padding: 6px 14px;
    margin: 2px 4px;
    border-radius: 6px;
    background: transparent;
    color: #86909c;
    font-weight: 600;
}

QTabWidget QTabBar::tab:selected {
    background: #1664FF;
    color: #ffffff;
}

QTabWidget QTabBar::tab:hover {
    background: #ebf1ff;
    color: #0c0d0e;
}

QTabWidget#workspaceTabs::pane {
    background: #ffffff;
    border: 1px solid #eceded;
    border-radius: 8px;
}

QTabWidget#workspaceTabs QTabBar {
    background: #f7f9fb;
}

QTabWidget#workspaceTabs QTabBar::tab {
    min-width: 126px;
    min-height: 42px;
    padding: 8px 14px;
    margin: 4px 8px;
    border-radius: 8px;
    background: transparent;
    color: #86909c;
    font-weight: 600;
}

QTabWidget#workspaceTabs QTabBar::tab:selected {
    background: #1664FF;
    color: #ffffff;
}

QTabWidget#workspaceTabs QTabBar::tab:hover {
    background: #ebf1ff;
    color: #0c0d0e;
}

QTableWidget {
    background: #ffffff;
    alternate-background-color: #f7f9fb;
    gridline-color: #eceded;
    border: 1px solid #eceded;
    border-radius: 8px;
    color: #0c0d0e;
}

QTableWidget::item {
    padding: 4px;
}

QTableWidget::item:selected {
    background: #1664FF;
    color: #ffffff;
}

QHeaderView::section {
    background: #f7f9fb;
    color: #86909c;
    padding: 7px;
    border: none;
    border-right: 1px solid #eceded;
    border-bottom: 1px solid #eceded;
    font-weight: 600;
}

QScrollBar:vertical,
QScrollBar:horizontal {
    background: transparent;
    border: none;
}

QScrollBar:vertical {
    width: 10px;
}

QScrollBar:horizontal {
    height: 10px;
}

QScrollBar::handle:vertical,
QScrollBar::handle:horizontal {
    background: #c9cdd4;
    border-radius: 5px;
}

QScrollBar::handle:vertical:hover,
QScrollBar::handle:horizontal:hover {
    background: #86909c;
}

QScrollBar::add-line,
QScrollBar::sub-line,
QScrollBar::add-page,
QScrollBar::sub-page {
    width: 0;
    height: 0;
    background: none;
}

QStatusBar {
    background: #ffffff;
    border-top: 1px solid #eceded;
    color: #86909c;
}

QMessageBox {
    background: #ffffff;
}

QWidget#sideNav {
    background: #ffffff;
    border-right: 1px solid #eceded;
}

QPushButton#sideNavButton {
    background: transparent;
    border: none;
    border-left: 3px solid transparent;
    color: #86909c;
    text-align: left;
    padding: 10px 12px;
    font-weight: 600;
    min-height: 36px;
    border-radius: 0;
}

QPushButton#sideNavButton:hover {
    background: rgba(22, 100, 255, 0.08);
    color: #0c0d0e;
}

QPushButton#sideNavButton:checked {
    background: #f3f7ff;
    color: #1664FF;
    border-left: 3px solid #1664FF;
}

QPushButton#sideNavButton:focus {
    outline: none;
    border: none;
    border-left: 3px solid transparent;
}

QPushButton#sideNavButton:checked:focus {
    border-left: 3px solid #1664FF;
}

QFrame#statusCard {
    background: #ffffff;
    border: 1px solid #eceded;
    border-radius: 8px;
}

QCheckBox {
    color: #0c0d0e;
    spacing: 6px;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 2px solid #dde2e9;
    border-radius: 4px;
    background: #ffffff;
}

QCheckBox::indicator:checked {
    background: #1664FF;
    border-color: #1664FF;
}

QTextEdit {
    background: #ffffff;
    color: #0c0d0e;
    border: 1px solid #dde2e9;
    border-radius: 4px;
    padding: 4px;
}
"""


# ---------------------------------------------------------------------------
# Flow-step style constants
# ---------------------------------------------------------------------------

FLOW_STEP_STYLE = (
    "color: #0c0d0e; background-color: #ffffff; padding: 7px 9px; "
    "border: 1px solid #dde2e9; border-radius: 4px;"
)

FLOW_STEP_SELECTED_STYLE = (
    "color: #ffffff; background-color: #1664FF; padding: 7px 9px; "
    "border: 1px solid #0055ff; border-radius: 4px; font-weight: 700;"
)

FLOW_STEP_EMPTY_STYLE = (
    "color: #c9cdd4; background-color: #f7f9fb; padding: 10px; "
    "border: 1px dashed #dde2e9; border-radius: 4px;"
)


# ---------------------------------------------------------------------------
# Palette helpers
# ---------------------------------------------------------------------------

def build_app_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#f7f9fb"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#0c0d0e"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#f7f9fb"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#0c0d0e"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#1664FF"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#0c0d0e"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#0c0d0e"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#0c0d0e"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#c9cdd4"))
    return palette


def apply_app_palette(widget):
    widget.setPalette(build_app_palette())


# ---------------------------------------------------------------------------
# Top-level theme application
# ---------------------------------------------------------------------------

def apply_theme(target) -> None:
    target.setPalette(build_app_palette())
    target.setStyleSheet(GLOBAL_STYLESHEET)


# ---------------------------------------------------------------------------
# Status / role helpers
# ---------------------------------------------------------------------------

def status_style(value):
    text = str(value)
    if any(key in text for key in ("错误", "失败", "报警", "碰撞", "error", "failed", "alarm")):
        color = "#c43138"
        background = "#feeced"
        border = "#d7312a"
    elif any(key in text for key in ("已连接", "运行", "成功", "connected", "running", "success")):
        color = "#189959"
        background = "#e2f5eb"
        border = "#2a814b"
    elif any(key in text for key in ("暂停", "警告", "warning", "paused")):
        color = "#de9400"
        background = "#fdf3de"
        border = "#bd7e00"
    else:
        color = "#4e5969"
        background = "#f7f9fb"
        border = "#dde2e9"
    return (
        f"color: {color}; background-color: {background}; "
        f"border: 1px solid {border}; border-radius: 6px; "
        "padding: 4px 8px; font-weight: 600;"
    )


def apply_status_visual(label, value):
    label.setStyleSheet(status_style(value))


def set_button_role(button, role):
    button.setProperty("role", role)
    button.style().unpolish(button)
    button.style().polish(button)


def card_style(accent_color: str = "") -> str:
    """Return stylesheet for a dashboard card frame, optionally with accent border."""
    base = (
        "QFrame { background: #ffffff; border: 1px solid #eceded; "
        "border-radius: 8px; padding: 12px; }"
    )
    if accent_color:
        base = (
            f"QFrame {{ background: #ffffff; border: 1px solid {accent_color}; "
            f"border-left: 3px solid {accent_color}; border-radius: 8px; padding: 12px; }}"
        )
    return base


def metric_label_style(color: str = "#0c0d0e") -> str:
    """Large metric value label."""
    return (
        f"color: {color}; font-size: 13pt; font-weight: 700; "
        "font-family: 'PingFang SC', 'Microsoft YaHei', monospace; background: transparent; border: none;"
    )


def metric_title_style() -> str:
    """Small uppercase metric title label."""
    return (
        "color: #86909c; font-size: 10pt; font-weight: 600; "
        "text-transform: uppercase; letter-spacing: 0.5px; "
        "background: transparent; border: none;"
    )


def metric_value_style(color: str = "#0c0d0e") -> str:
    """Standard metric value style for overview/summary labels (13pt)."""
    return (
        f"color: {color}; font-size: 13pt; font-weight: 600; "
        "background: transparent; border: none;"
    )


def card_value_color(text: str) -> str:
    """Return the appropriate color for a card value based on its text content."""
    if any(k in text for k in ("已连接", "运行", "成功", "connected", "running")):
        return "#2a814b"
    if any(k in text for k in ("错误", "失败", "报警", "error", "failed")):
        return "#d7312a"
    return "#4e5969"
