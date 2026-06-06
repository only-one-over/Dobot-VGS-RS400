#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unified UI theme: colours, palette, stylesheet, and style helpers."""

from __future__ import annotations

from qt_compat import QColor, QPalette


# ---------------------------------------------------------------------------
# Colour tokens
# ---------------------------------------------------------------------------

COLORS = {
    "bg": "#0f172a",
    "surface": "#1e293b",
    "panel": "#1e293b",
    "line": "#334155",
    "text": "#e2e8f0",
    "muted": "#94a3b8",
    "primary": "#3b82f6",
    "primary_dark": "#2563eb",
    "success": "#22c55e",
    "warning": "#f59e0b",
    "danger": "#ef4444",
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
    background: #f3f6fb;
    color: #172033;
}

QScrollArea,
QScrollArea > QWidget,
QScrollArea > QWidget > QWidget {
    background: transparent;
    border: none;
}

QGroupBox {
    background: #ffffff;
    border: 1px solid #d6e1ef;
    border-radius: 8px;
    margin-top: 18px;
    font-weight: 700;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 8px;
    color: #172033;
    background: #ffffff;
}

QGroupBox#topStatusPanel {
    background: #ffffff;
    border: 1px solid #d6e1ef;
    border-radius: 8px;
    margin-top: 0;
}

QGroupBox#topStatusPanel::title {
    color: #2563eb;
}

QFrame#dashboardCard {
    background: #ffffff;
    border: 1px solid #d6e1ef;
    border-radius: 8px;
}

QLabel {
    color: #172033;
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
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    background: #ffffff;
    color: #172033;
}

QLineEdit:focus,
QDoubleSpinBox:focus,
QComboBox:focus {
    border-color: #2563eb;
}

QPushButton {
    min-height: 32px;
    padding: 7px 14px;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    background: #ffffff;
    color: #172033;
    font-weight: 600;
}

QPushButton:hover {
    background: #eef4fb;
    border-color: #94a3b8;
}

QPushButton:pressed {
    background: #dbeafe;
}

QPushButton:disabled {
    background: #e5e7eb;
    color: #94a3b8;
    border-color: #d1d5db;
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
    background: #ecfdf5;
    border-color: #86efac;
    color: #166534;
}

QPushButton[role="warning"] {
    background: #fffbeb;
    border-color: #fbbf24;
    color: #92400e;
}

QPushButton[role="danger"] {
    background: #fee2e2;
    border-color: #f87171;
    color: #991b1b;
}

QPushButton[role="secondary"] {
    background: #f8fafc;
    border-color: #cbd5e1;
    color: #334155;
}

QPushButton#emergencyStopButton {
    min-width: 82px;
    min-height: 82px;
    max-width: 82px;
    max-height: 82px;
    border-radius: 41px;
    background: #dc2626;
    border: 4px solid #fecaca;
    color: #ffffff;
    font-size: 13pt;
    font-weight: 900;
}

QPushButton#emergencyStopButton:hover {
    background: #b91c1c;
}

QPushButton#emergencyStopButton[active="true"] {
    background: #f97316;
    border-color: #fed7aa;
}

QTabWidget#workspaceTabs::pane {
    background: #ffffff;
    border: 1px solid #d6e1ef;
    border-radius: 8px;
}

QTabWidget#workspaceTabs QTabBar {
    background: #0f172a;
}

QTabWidget#workspaceTabs QTabBar::tab {
    min-width: 126px;
    min-height: 42px;
    padding: 8px 14px;
    margin: 4px 8px;
    border-radius: 6px;
    background: transparent;
    color: #cbd5e1;
    font-weight: 700;
}

QTabWidget#workspaceTabs QTabBar::tab:selected {
    background: #2563eb;
    color: #ffffff;
}

QTabWidget#workspaceTabs QTabBar::tab:hover {
    background: #1e293b;
    color: #ffffff;
}

QTableWidget {
    background: #ffffff;
    alternate-background-color: #f8fafc;
    gridline-color: #e2e8f0;
    border: 1px solid #d6e1ef;
    border-radius: 6px;
    color: #172033;
}

QTableWidget::item {
    padding: 4px;
}

QTableWidget::item:selected {
    background: #dbeafe;
    color: #1e3a8a;
}

QHeaderView::section {
    background: #eef4fb;
    color: #334155;
    padding: 7px;
    border: none;
    border-right: 1px solid #d6e1ef;
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
    background: #cbd5e1;
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
    background: #ffffff;
    border-top: 1px solid #d6e1ef;
    color: #64748b;
}

QMessageBox {
    background: #ffffff;
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
    "color: #64748b; background-color: #0f172a; padding: 10px; "
    "border: 1px dashed #475569; border-radius: 6px;"
)


# ---------------------------------------------------------------------------
# Palette helpers
# ---------------------------------------------------------------------------

def build_app_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(COLORS["bg"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(COLORS["surface"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(COLORS["panel"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(COLORS["surface"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(COLORS["primary"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
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
