#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Shared UI style helpers for the PyQt control panel."""

from PyQt6.QtGui import QColor, QPalette


FLOW_STEP_STYLE = (
    "color: #1a237e; background-color: white; padding: 7px 9px; "
    "border: 1px solid #d6e4f0; border-radius: 5px;"
)

FLOW_STEP_SELECTED_STYLE = (
    "color: white; background-color: #1565c0; padding: 7px 9px; "
    "border: 1px solid #0d47a1; border-radius: 5px; font-weight: 700;"
)

FLOW_STEP_EMPTY_STYLE = (
    "color: #475569; background-color: #f8fafc; padding: 10px; "
    "border: 1px dashed #cbd5e1; border-radius: 5px;"
)


def status_style(value):
    text = str(value)
    if "错误" in text or "失败" in text or "报警" in text or "碰撞" in text:
        color = "#b91c1c"
        background = "#fee2e2"
        border = "#fca5a5"
    elif "已连接" in text or "运行" in text or "成功" in text:
        color = "#166534"
        background = "#dcfce7"
        border = "#86efac"
    elif "暂停" in text or "警告" in text:
        color = "#92400e"
        background = "#fef3c7"
        border = "#fcd34d"
    else:
        color = "#475569"
        background = "#f1f5f9"
        border = "#cbd5e1"
    return (
        f"color: {color}; background-color: {background}; "
        f"border: 1px solid {border}; border-radius: 4px; "
        "padding: 4px 8px; font-weight: 600;"
    )


def apply_status_visual(label, value):
    label.setStyleSheet(status_style(value))


def set_button_role(button, role):
    button.setProperty("role", role)


def build_app_palette():
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(240, 248, 255))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(26, 35, 126))
    palette.setColor(QPalette.ColorRole.Button, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(26, 35, 126))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(33, 150, 243))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    return palette


def apply_app_palette(widget):
    widget.setPalette(build_app_palette())


GLOBAL_STYLESHEET = """
* {
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 10pt;
}
QMainWindow {
    background-color: #f0f8ff;
}
QWidget {
    background-color: #f0f8ff;
}
QScrollArea {
    background-color: #f0f8ff;
    border: none;
}
QLineEdit {
    padding: 6px 10px;
    border: 1px solid #42a5f5;
    border-radius: 4px;
    background-color: white;
    color: #1a237e;
}
QLineEdit:hover {
    border-color: #2196f3;
}
QLineEdit:focus {
    border-color: #1976d2;
    outline: none;
}
QTableWidget {
    background-color: white;
    alternate-background-color: #e3f2fd;
    gridline-color: #bbdefb;
    border: 1px solid #42a5f5;
    border-radius: 4px;
    color: #1a237e;
}
QTableWidget::item {
    padding: 4px;
}
QTableWidget::item:selected {
    background-color: #2196f3;
    color: white;
}
QHeaderView::section {
    background-color: #e3f2fd;
    color: #1a237e;
    padding: 6px;
    border: 1px solid #bbdefb;
    font-weight: bold;
}
QScrollBar:vertical {
    background-color: #f0f8ff;
    width: 10px;
    border: none;
}
QScrollBar::handle:vertical {
    background-color: #90caf9;
    min-height: 30px;
    border-radius: 5px;
}
QScrollBar::handle:vertical:hover {
    background-color: #42a5f5;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}
QScrollBar:horizontal {
    background-color: #f0f8ff;
    height: 10px;
    border: none;
}
QScrollBar::handle:horizontal {
    background-color: #90caf9;
    min-width: 30px;
    border-radius: 5px;
}
QScrollBar::handle:horizontal:hover {
    background-color: #42a5f5;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: none;
}
QGroupBox {
    font-weight: bold;
    border: 1px solid #42a5f5;
    border-radius: 8px;
    margin-top: 15px;
    background-color: white;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 15px;
    padding: 0 10px 0 10px;
    color: #1a237e;
    background-color: white;
    border-radius: 4px;
}
QPushButton {
    padding: 8px 16px;
    border: 1px solid #42a5f5;
    border-radius: 6px;
    background-color: white;
    color: #1a237e;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #e3f2fd;
    border-color: #2196f3;
}
QPushButton:pressed {
    background-color: #bbdefb;
    border-color: #1976d2;
}
QPushButton:default {
    background-color: #2196f3;
    color: white;
    border-color: #1976d2;
}
QPushButton:default:hover {
    background-color: #1976d2;
}
QPushButton[role="primary"] {
    background-color: #1565c0;
    color: white;
    border-color: #0d47a1;
    font-weight: 700;
}
QPushButton[role="primary"]:hover {
    background-color: #0d47a1;
}
QPushButton[role="connect"] {
    background-color: #e8f5e9;
    color: #1b5e20;
    border-color: #66bb6a;
    font-weight: 700;
}
QPushButton[role="connect"]:hover {
    background-color: #c8e6c9;
}
QPushButton[role="warning"] {
    background-color: #fff7ed;
    color: #9a3412;
    border-color: #fb923c;
    font-weight: 700;
}
QPushButton[role="warning"]:hover {
    background-color: #fed7aa;
}
QPushButton[role="danger"] {
    background-color: #fee2e2;
    color: #991b1b;
    border-color: #f87171;
    font-weight: 700;
}
QPushButton[role="danger"]:hover {
    background-color: #fecaca;
}
QPushButton[role="secondary"] {
    background-color: #f8fafc;
    color: #334155;
    border-color: #cbd5e1;
}
QPushButton[role="secondary"]:hover {
    background-color: #e2e8f0;
}
QPushButton:disabled {
    background-color: #e5e7eb;
    color: #94a3b8;
    border-color: #cbd5e1;
}
QDoubleSpinBox, QComboBox {
    padding: 8px;
    border: 1px solid #42a5f5;
    border-radius: 4px;
    background-color: white;
    color: #1a237e;
    min-height: 30px;
}
QComboBox QAbstractItemView {
    background-color: white;
    color: #1a237e;
    selection-background-color: #e3f2fd;
    selection-color: #1a237e;
    border: 1px solid #42a5f5;
}
QDoubleSpinBox:hover, QComboBox:hover {
    border-color: #2196f3;
}
QDoubleSpinBox:focus, QComboBox:focus {
    border-color: #1976d2;
    outline: none;
}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    width: 24px;
    height: 15px;
}
QDoubleSpinBox::up-arrow, QDoubleSpinBox::down-arrow {
    width: 10px;
    height: 10px;
}
QLabel {
    color: #1a237e;
}
QTabWidget::pane {
    border: 1px solid #42a5f5;
    border-radius: 8px;
    background-color: white;
}
QTabBar::tab {
    padding: 10px 20px;
    margin-right: 4px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    background-color: #f0f8ff;
    color: #1a237e;
    border: 1px solid #42a5f5;
    border-bottom: none;
}
QTabBar::tab:selected {
    background-color: white;
    border-bottom: 1px solid white;
}
QTabBar::tab:hover {
    background-color: #e3f2fd;
}
QStatusBar {
    background-color: #e3f2fd;
    border-top: 1px solid #42a5f5;
    color: #1a237e;
}
QMessageBox {
    background-color: white;
    border: 1px solid #42a5f5;
    border-radius: 8px;
}
QMessageBox QLabel {
    color: #1a237e;
}
QMessageBox QPushButton {
    min-width: 80px;
}
""".strip()
