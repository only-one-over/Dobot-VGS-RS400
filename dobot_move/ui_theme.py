#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unified UI theme: colours, palette, stylesheet, and style helpers."""

from __future__ import annotations

from qt_compat import QColor, QPalette


# ---------------------------------------------------------------------------
# Colour tokens
# ---------------------------------------------------------------------------

COLORS = {
    "bg": "#0b0f1a",
    "surface": "#111827",
    "panel": "#1a2236",
    "card": "#1e293b",
    "line": "#2a3550",
    "border": "#334155",
    "text": "#e2e8f0",
    "muted": "#94a3b8",
    "primary": "#3b82f6",
    "primary_dark": "#2563eb",
    "success": "#22c55e",
    "warning": "#f59e0b",
    "danger": "#ef4444",
    "accent_blue": "#93c5fd",
}

# Sidebar navigation icon characters (Unicode)
NAV_ICONS = {
    "主功能":    "\u2302",
    "运动编辑":  "\u27F3",
    "点位管理":  "\u25CE",
    "电池电量":  "\u26A1",
    "机器人力控": "\u2388",
    "Modbus 通信": "\u229E",
    "报警记录":  "\u26A0",
    "点动控制":  "\u2725",
    "手眼标定":  "\u25A3",
    "相机测试":  "\u25C9",
}


# ---------------------------------------------------------------------------
# Global stylesheet (inlined from style.qss)
# ---------------------------------------------------------------------------

GLOBAL_STYLESHEET = """\
* {
    font-family: "Microsoft YaHei UI", "Segoe UI", Arial, sans-serif;
    font-size: 10pt;
}

QMainWindow,
QWidget#appRoot {
    background: #0b0f1a;
    color: #e2e8f0;
}

QScrollArea,
QScrollArea > QWidget,
QScrollArea > QWidget > QWidget {
    background: transparent;
    border: none;
}

QGroupBox {
    background: #1e293b;
    border: 1px solid #2a3550;
    border-radius: 8px;
    margin-top: 18px;
    font-weight: 700;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 8px;
    color: #e2e8f0;
    background: #1e293b;
}

QGroupBox#topStatusPanel {
    background: #1e293b;
    border: 1px solid #2a3550;
    border-radius: 8px;
    margin-top: 0;
}

QGroupBox#topStatusPanel::title {
    color: #3b82f6;
}

QFrame#dashboardCard {
    background: #1e293b;
    border: 1px solid #2a3550;
    border-radius: 8px;
}

QLabel {
    color: #e2e8f0;
}

QLabel#cardTitle {
    color: #64748b;
    font-size: 9pt;
    font-weight: 700;
}

QLineEdit,
QDoubleSpinBox,
QComboBox {
    min-height: 32px;
    padding: 6px 10px;
    border: 1px solid #334155;
    border-radius: 6px;
    background: #111827;
    color: #e2e8f0;
}

QLineEdit:focus,
QDoubleSpinBox:focus,
QComboBox:focus {
    border-color: #3b82f6;
}

QPushButton {
    min-height: 32px;
    padding: 7px 14px;
    border: 1px solid #334155;
    border-radius: 6px;
    background: #1e293b;
    color: #e2e8f0;
    font-weight: 600;
}

QPushButton:hover {
    background: #1a2236;
    border-color: #475569;
}

QPushButton:pressed {
    background: #1e3a8a;
}

QPushButton:disabled {
    background: #1a2236;
    color: #64748b;
    border-color: #2a3550;
}

QPushButton[role="primary"] {
    background: #2563eb;
    border-color: #1d4ed8;
    color: #ffffff;
}

QPushButton[role="primary"]:hover {
    background: #1d4ed8;
}

QPushButton[role="connect"] {
    background: #064e3b;
    border-color: #22c55e;
    color: #86efac;
}

QPushButton[role="warning"] {
    background: #451a03;
    border-color: #f59e0b;
    color: #fcd34d;
}

QPushButton[role="danger"] {
    background: #450a0a;
    border-color: #ef4444;
    color: #fca5a5;
}

QPushButton[role="secondary"] {
    background: #1a2236;
    border-color: #334155;
    color: #94a3b8;
}

QPushButton#emergencyStopButton {
    min-width: 82px;
    min-height: 82px;
    max-width: 82px;
    max-height: 82px;
    border-radius: 41px;
    background: #dc2626;
    border: 4px solid #7f1d1d;
    color: #ffffff;
    font-size: 13pt;
    font-weight: 900;
}

QPushButton#emergencyStopButton:hover {
    background: #b91c1c;
}

QPushButton#emergencyStopButton[active="true"] {
    background: #f97316;
    border-color: #9a3412;
}

QTabWidget#workspaceTabs::pane {
    background: #1e293b;
    border: 1px solid #2a3550;
    border-radius: 8px;
}

QTabWidget#workspaceTabs QTabBar {
    background: #0b0f1a;
}

QTabWidget#workspaceTabs QTabBar::tab {
    min-width: 126px;
    min-height: 42px;
    padding: 8px 14px;
    margin: 4px 8px;
    border-radius: 6px;
    background: transparent;
    color: #94a3b8;
    font-weight: 700;
}

QTabWidget#workspaceTabs QTabBar::tab:selected {
    background: #2563eb;
    color: #ffffff;
}

QTabWidget#workspaceTabs QTabBar::tab:hover {
    background: #1a2236;
    color: #e2e8f0;
}

QTableWidget {
    background: #1e293b;
    alternate-background-color: #111827;
    gridline-color: #2a3550;
    border: 1px solid #2a3550;
    border-radius: 6px;
    color: #e2e8f0;
}

QTableWidget::item {
    padding: 4px;
}

QTableWidget::item:selected {
    background: #1e3a8a;
    color: #93c5fd;
}

QHeaderView::section {
    background: #1a2236;
    color: #94a3b8;
    padding: 7px;
    border: none;
    border-right: 1px solid #2a3550;
    font-weight: 700;
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
    background: #475569;
    border-radius: 5px;
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
    background: #1e293b;
    border-top: 1px solid #2a3550;
    color: #64748b;
}

QMessageBox {
    background: #1e293b;
}

QWidget#sideNav {
    background: #0b0f1a;
    border-right: 1px solid #1e293b;
}

QPushButton#sideNavButton {
    background: transparent;
    border: none;
    border-left: 3px solid transparent;
    color: #94a3b8;
    text-align: left;
    padding: 10px 12px;
    font-weight: 600;
    min-height: 36px;
}

QPushButton#sideNavButton:hover {
    background: #1a2236;
    color: #e2e8f0;
}

QPushButton#sideNavButton:checked {
    background: #111827;
    color: #3b82f6;
    border-left: 3px solid #3b82f6;
}

QFrame#statusCard {
    background: #1e293b;
    border: 1px solid #2a3550;
    border-radius: 10px;
}
"""


# ---------------------------------------------------------------------------
# Flow-step style constants
# ---------------------------------------------------------------------------

FLOW_STEP_STYLE = (
    "color: #e2e8f0; background-color: #1e293b; padding: 7px 9px; "
    "border: 1px solid #475569; border-radius: 6px;"
)

FLOW_STEP_SELECTED_STYLE = (
    "color: #ffffff; background-color: #3b82f6; padding: 7px 9px; "
    "border: 1px solid #2563eb; border-radius: 6px; font-weight: 700;"
)

FLOW_STEP_EMPTY_STYLE = (
    "color: #64748b; background-color: #0b0f1a; padding: 10px; "
    "border: 1px dashed #475569; border-radius: 6px;"
)


# ---------------------------------------------------------------------------
# Palette helpers
# ---------------------------------------------------------------------------

def build_app_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#0b0f1a"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#e2e8f0"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#111827"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#1a2236"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#1e293b"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#e2e8f0"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#3b82f6"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#e2e8f0"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#1e293b"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#e2e8f0"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#64748b"))
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
        color = "#fca5a5"
        background = "#450a0a"
        border = "#ef4444"
    elif any(key in text for key in ("已连接", "运行", "成功", "connected", "running", "success")):
        color = "#86efac"
        background = "#064e3b"
        border = "#22c55e"
    elif any(key in text for key in ("暂停", "警告", "warning", "paused")):
        color = "#fcd34d"
        background = "#451a03"
        border = "#f59e0b"
    else:
        color = "#94a3b8"
        background = "#1e293b"
        border = "#475569"
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
        "QFrame { background: #1e293b; border: 1px solid #2a3550; "
        "border-radius: 10px; padding: 12px; }"
    )
    if accent_color:
        base = (
            f"QFrame {{ background: #1e293b; border: 1px solid {accent_color}; "
            f"border-left: 3px solid {accent_color}; border-radius: 10px; padding: 12px; }}"
        )
    return base


def metric_label_style(color: str = "#e2e8f0") -> str:
    """Large metric value label."""
    return (
        f"color: {color}; font-size: 18pt; font-weight: 700; "
        "font-family: 'Segoe UI', monospace; background: transparent; border: none;"
    )


def metric_title_style() -> str:
    """Small uppercase metric title label."""
    return (
        "color: #64748b; font-size: 8pt; font-weight: 700; "
        "text-transform: uppercase; letter-spacing: 0.5px; "
        "background: transparent; border: none;"
    )
