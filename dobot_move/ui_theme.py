#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unified UI theme: Industrial Robotics Dashboard design system.

Design reference: Industrial Robotics Dashboard UI (Community) — Figma
Dark industrial dashboard with card-based layout, icon sidebar, status indicators.
"""

from __future__ import annotations

from qt_compat import QColor, QPalette


# ---------------------------------------------------------------------------
# Colour tokens — Industrial Robotics Dashboard palette
# ---------------------------------------------------------------------------

COLORS = {
    # Background layers
    "bg":           "#0b0f1a",
    "surface":      "#111827",
    "panel":        "#1a2236",
    "card":         "#1e293b",
    "card_hover":   "#243049",
    # Borders & lines
    "line":         "#2a3550",
    "line_light":   "#334155",
    # Text
    "text":         "#e2e8f0",
    "text_secondary": "#94a3b8",
    "text_muted":   "#64748b",
    # Brand / accent
    "primary":      "#3b82f6",
    "primary_dark": "#2563eb",
    "primary_light": "#60a5fa",
    "accent":       "#06b6d4",
    # Semantic
    "success":      "#22c55e",
    "success_bg":   "#064e3b",
    "warning":      "#f59e0b",
    "warning_bg":   "#451a03",
    "danger":       "#ef4444",
    "danger_bg":    "#450a0a",
    "info":         "#38bdf8",
    "info_bg":      "#0c2d48",
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
    "手眼标定":  "\u229E",
    "相机测试":  "\u25C9",
}


# ---------------------------------------------------------------------------
# Global stylesheet — Industrial Robotics Dashboard
# ---------------------------------------------------------------------------

GLOBAL_STYLESHEET = """\
* {
    font-family: "Segoe UI", "Microsoft YaHei UI", Arial, sans-serif;
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

/* GroupBox -> Dashboard Card */
QGroupBox {
    background: #1e293b;
    border: 1px solid #2a3550;
    border-radius: 10px;
    margin-top: 22px;
    font-weight: 700;
    color: #e2e8f0;
    padding: 14px 12px 10px 12px;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 16px;
    padding: 0 10px;
    color: #94a3b8;
    background: #1e293b;
    font-size: 9pt;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

QGroupBox#topStatusPanel {
    background: #111827;
    border: 1px solid #2a3550;
    border-radius: 10px;
    margin-top: 0;
}

QGroupBox#topStatusPanel::title {
    color: #3b82f6;
}

/* Dashboard Card Frame */
QFrame#dashboardCard {
    background: #1e293b;
    border: 1px solid #2a3550;
    border-radius: 10px;
}

QFrame#statusCard {
    background: #1a2236;
    border: 1px solid #2a3550;
    border-radius: 8px;
}

/* Labels */
QLabel {
    color: #e2e8f0;
}

QLabel#cardTitle {
    color: #64748b;
    font-size: 9pt;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

QLabel#cardValue {
    color: #e2e8f0;
    font-size: 16pt;
    font-weight: 700;
}

QLabel#statusBadge {
    color: #e2e8f0;
    font-size: 9pt;
    font-weight: 600;
    padding: 3px 10px;
    border-radius: 12px;
}

/* Input widgets */
QLineEdit,
QDoubleSpinBox,
QComboBox {
    min-height: 34px;
    padding: 6px 12px;
    border: 1px solid #2a3550;
    border-radius: 6px;
    background: #111827;
    color: #e2e8f0;
    selection-background-color: #2563eb;
}

QLineEdit:focus,
QDoubleSpinBox:focus,
QComboBox:focus {
    border-color: #3b82f6;
}

QComboBox::drop-down {
    border: none;
    width: 24px;
}

QComboBox::down-arrow {
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #94a3b8;
}

/* Buttons */
QPushButton {
    min-height: 34px;
    padding: 7px 16px;
    border: 1px solid #2a3550;
    border-radius: 6px;
    background: #1e293b;
    color: #e2e8f0;
    font-weight: 600;
}

QPushButton:hover {
    background: #243049;
    border-color: #3b82f6;
}

QPushButton:pressed {
    background: #1a2236;
    border-color: #2563eb;
}

QPushButton:disabled {
    background: #111827;
    color: #475569;
    border-color: #1e293b;
}

QPushButton[role="primary"] {
    background: #2563eb;
    border-color: #1d4ed8;
    color: #ffffff;
}

QPushButton[role="primary"]:hover {
    background: #1d4ed8;
}

QPushButton[role="primary"]:pressed {
    background: #1e40af;
}

QPushButton[role="connect"] {
    background: #064e3b;
    border-color: #22c55e;
    color: #86efac;
}

QPushButton[role="connect"]:hover {
    background: #065f46;
    border-color: #4ade80;
}

QPushButton[role="warning"] {
    background: #451a03;
    border-color: #f59e0b;
    color: #fcd34d;
}

QPushButton[role="warning"]:hover {
    background: #78350f;
    border-color: #fbbf24;
}

QPushButton[role="danger"] {
    background: #450a0a;
    border-color: #ef4444;
    color: #fca5a5;
}

QPushButton[role="danger"]:hover {
    background: #7f1d1d;
    border-color: #f87171;
}

QPushButton[role="secondary"] {
    background: #1a2236;
    border-color: #2a3550;
    color: #94a3b8;
}

QPushButton[role="secondary"]:hover {
    background: #243049;
    color: #e2e8f0;
}

/* Emergency Stop */
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

/* Sidebar Navigation */
QWidget#sideNav {
    background: #0b0f1a;
    border-right: 1px solid #1e293b;
}

QPushButton#sideNavButton {
    min-height: 44px;
    padding: 8px 14px;
    border: none;
    border-radius: 8px;
    background: transparent;
    color: #64748b;
    font-weight: 600;
    text-align: left;
    font-size: 10pt;
}

QPushButton#sideNavButton:hover {
    background: #1a2236;
    color: #e2e8f0;
}

QPushButton#sideNavButton:checked {
    background: #1e293b;
    color: #3b82f6;
    border-left: 3px solid #3b82f6;
}

/* Tab Widget */
QTabWidget#workspaceTabs::pane {
    background: #111827;
    border: 1px solid #2a3550;
    border-radius: 10px;
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
    color: #64748b;
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

/* Tables */
QTableWidget {
    background: #111827;
    alternate-background-color: #1a2236;
    gridline-color: #1e293b;
    border: 1px solid #2a3550;
    border-radius: 8px;
    color: #e2e8f0;
}

QTableWidget::item {
    padding: 6px;
}

QTableWidget::item:selected {
    background: #1e3a8a;
    color: #e2e8f0;
}

QHeaderView::section {
    background: #1a2236;
    color: #94a3b8;
    padding: 8px;
    border: none;
    border-right: 1px solid #2a3550;
    border-bottom: 1px solid #2a3550;
    font-weight: 700;
    font-size: 9pt;
    text-transform: uppercase;
    letter-spacing: 0.3px;
}

/* Scrollbars */
QScrollBar:vertical,
QScrollBar:horizontal {
    background: transparent;
    border: none;
}

QScrollBar:vertical {
    width: 8px;
}

QScrollBar:horizontal {
    height: 8px;
}

QScrollBar::handle:vertical,
QScrollBar::handle:horizontal {
    background: #334155;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover,
QScrollBar::handle:horizontal:hover {
    background: #475569;
}

QScrollBar::add-line,
QScrollBar::sub-line,
QScrollBar::add-page,
QScrollBar::sub-page {
    width: 0;
    height: 0;
    background: none;
}

/* Status Bar */
QStatusBar {
    background: #0b0f1a;
    border-top: 1px solid #1e293b;
    color: #64748b;
    font-size: 9pt;
}

QMessageBox {
    background: #1e293b;
    color: #e2e8f0;
}
"""


# ---------------------------------------------------------------------------
# Flow-step style constants — Industrial Dashboard
# ---------------------------------------------------------------------------

FLOW_STEP_STYLE = (
    "color: #94a3b8; background-color: #1a2236; padding: 8px 12px; "
    "border: 1px solid #2a3550; border-radius: 6px;"
)

FLOW_STEP_SELECTED_STYLE = (
    "color: #ffffff; background-color: #1e3a8a; padding: 8px 12px; "
    "border: 1px solid #3b82f6; border-radius: 6px; font-weight: 700;"
)

FLOW_STEP_EMPTY_STYLE = (
    "color: #475569; background-color: #111827; padding: 12px; "
    "border: 1px dashed #2a3550; border-radius: 6px;"
)


# ---------------------------------------------------------------------------
# Dashboard card style helpers
# ---------------------------------------------------------------------------

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


def sidebar_icon_style(active: bool = False) -> str:
    """Icon character style for sidebar buttons."""
    if active:
        return "color: #3b82f6; font-size: 16pt; background: transparent; border: none;"
    return "color: #475569; font-size: 16pt; background: transparent; border: none;"


# ---------------------------------------------------------------------------
# Palette helpers
# ---------------------------------------------------------------------------

def build_app_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(COLORS["bg"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(COLORS["surface"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(COLORS["panel"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(COLORS["card"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(COLORS["primary"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(COLORS["card"]))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(COLORS["text"]))
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
        background = "#1a2236"
        border = "#2a3550"
    return (
        f"color: {color}; background-color: {background}; "
        f"border: 1px solid {border}; border-radius: 12px; "
        "padding: 4px 12px; font-weight: 600; font-size: 9pt;"
    )


def apply_status_visual(label, value):
    label.setStyleSheet(status_style(value))


def set_button_role(button, role):
    button.setProperty("role", role)
    button.style().unpolish(button)
    button.style().polish(button)
