#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Flow step list widget with drag-and-drop reordering and status icons."""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame
from PyQt6.QtCore import Qt, pyqtSignal, QMimeData, QByteArray
from PyQt6.QtGui import QDrag, QPixmap, QPainter, QColor

from ui_theme import FLOW_STEP_STYLE, FLOW_STEP_SELECTED_STYLE, FLOW_STEP_EMPTY_STYLE


# Status constants
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

# Status display config
_STATUS_CONFIG = {
    STATUS_PENDING:   {"icon": "⏳", "color": "#475569", "bg": "#f8fafc", "border": "#cbd5e1"},
    STATUS_RUNNING:   {"icon": "▶", "color": "#1e40af", "bg": "#dbeafe", "border": "#60a5fa"},
    STATUS_COMPLETED: {"icon": "✓", "color": "#166534", "bg": "#dcfce7", "border": "#86efac"},
    STATUS_FAILED:    {"icon": "✗", "color": "#991b1b", "bg": "#fee2e2", "border": "#fca5a5"},
}

_MIME_TYPE = "application/x-flow-step-index"


class FlowStepItem(QFrame):
    """A single flow step widget with status icon and drag support."""

    def __init__(self, index: int, text: str, status: str = STATUS_PENDING, parent=None):
        super().__init__(parent)
        self._index = index
        self._status = status
        self._selected = False
        self._drag_start_pos = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        self._icon_label = QLabel()
        self._icon_label.setFixedWidth(20)
        layout.addWidget(self._icon_label)

        self._text_label = QLabel(text)
        self._text_label.setWordWrap(True)
        self._text_label.setMinimumHeight(28)
        layout.addWidget(self._text_label, 1)

        self._update_style()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(40)

    @property
    def index(self):
        return self._index

    @index.setter
    def index(self, value):
        self._index = value

    @property
    def status(self):
        return self._status

    @status.setter
    def status(self, value):
        self._status = value
        self._update_style()

    @property
    def selected(self):
        return self._selected

    @selected.setter
    def selected(self, value):
        self._selected = value
        self._update_style()

    def _update_style(self):
        cfg = _STATUS_CONFIG.get(self._status, _STATUS_CONFIG[STATUS_PENDING])
        self._icon_label.setText(cfg["icon"])

        if self._selected:
            self.setStyleSheet(FLOW_STEP_SELECTED_STYLE)
        else:
            style = (
                f"color: {cfg['color']}; background-color: {cfg['bg']}; "
                f"padding: 7px 9px; border: 1px solid {cfg['border']}; border-radius: 5px;"
            )
            self.setStyleSheet(style)

    # --- Drag support ---
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if self._drag_start_pos is None:
            return
        distance = (event.position().toPoint() - self._drag_start_pos).manhattanLength()
        if distance < 10:
            return

        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(_MIME_TYPE, QByteArray(str(self._index).encode()))
        drag.setMimeData(mime)

        # Create drag pixmap
        pixmap = QPixmap(self.size())
        self.render(pixmap)
        drag.setPixmap(pixmap)

        drag.exec(Qt.DropAction.MoveAction)

    def mouseReleaseEvent(self, event):
        self._drag_start_pos = None
        super().mouseReleaseEvent(event)


class FlowStepList(QWidget):
    """List of flow steps with drag-and-drop reordering and status icons."""

    step_clicked = pyqtSignal(int)
    step_reordered = pyqtSignal(list)  # emits the reordered module list

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setSpacing(5)
        self._layout.setContentsMargins(15, 15, 15, 15)
        self._items: list[FlowStepItem] = []
        self._modules: list[dict] = []
        self._selected_index = -1

        self.setAcceptDrops(True)
        self.setObjectName("flow_step_list")
        self.setStyleSheet("#flow_step_list { border: 1px solid #42a5f5; border-radius: 6px; }")

    def set_steps(self, modules: list[dict]):
        """Set the step list from module definitions."""
        self._modules = modules
        self._rebuild()

    def set_step_status(self, index: int, status: str):
        """Update the status icon for a specific step."""
        if 0 <= index < len(self._items):
            self._items[index].status = status

    def set_selected(self, index: int):
        """Select a step by index."""
        old = self._selected_index
        self._selected_index = index
        if 0 <= old < len(self._items):
            self._items[old].selected = False
        if 0 <= index < len(self._items):
            self._items[index].selected = True

    def _rebuild(self):
        """Rebuild all step items from self._modules."""
        # Clear existing
        for item in self._items:
            self._layout.removeWidget(item)
            item.setParent(None)
        self._items.clear()

        if not self._modules:
            empty = QLabel("抓取流程为空")
            empty.setStyleSheet(FLOW_STEP_EMPTY_STYLE)
            self._layout.addWidget(empty)
            return

        for i, module in enumerate(self._modules):
            text = self._build_step_text(i, module)
            item = FlowStepItem(i, text)
            item.mousePressEvent = self._make_click_handler(i, item)
            self._layout.addWidget(item)
            self._items.append(item)

        if 0 <= self._selected_index < len(self._items):
            self._items[self._selected_index].selected = True

    def _build_step_text(self, i: int, module: dict) -> str:
        """Build display text for a step."""
        text = f"{i+1}. {module['name']}"
        if module['type'] == "move":
            if module['params'].get('motion_type') == "MovL":
                point_name = module['params'].get('point_name', '')
                text += f" (直线运动, 点位: {point_name}, 速度: {module['params']['speed']}%)"
        elif module['type'] == "force_arc":
            p = module['params']
            if p.get('center_mode') == 'point':
                text += f" (力控圆弧, 圆心点位: {p.get('center_point_name', '')}, 半径: {p['radius']}mm, {p['start_angle']}°→{p['end_angle']}°, 轴: {p['rotation_axis']}, 增益: {p['correction_gain']})"
                return text
            text += f" (力控圆弧, 圆心: {p['center']}, 半径: {p['radius']}mm, {p['start_angle']}°→{p['end_angle']}°, 轴: {p['rotation_axis']}, 增益: {p['correction_gain']})"
        elif module['type'] == "force_guard_move":
            p = module['params']
            text += f" (力阈值移动, 方向: {p.get('axis', 'Z')}, 距离: {p.get('distance', 0)}mm, 力上限: {p.get('force_limit', 0)}N, 速度: {p.get('speed', 20)}%)"
        elif module['type'] == "joint_move":
            offsets = module['params'].get('offsets', [0]*6)
            text += f" (关节旋转, 偏移: {offsets}, 速度: {module['params']['speed']}%)"
        elif module['type'] == "visual_servo":
            p = module['params']
            text += f" (视觉伺服, 目标: {p.get('target_type', 'grasp_point')}, 阈值: {p.get('converge_threshold', 2.0)}mm)"
        return text

    def _make_click_handler(self, idx: int, item: FlowStepItem):
        def handler(event):
            self.set_selected(idx)
            self.step_clicked.emit(idx)
        return handler

    # --- Drop support ---
    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(_MIME_TYPE):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(_MIME_TYPE):
            event.acceptProposedAction()

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(_MIME_TYPE):
            return

        source_index = int(bytes(event.mimeData().data(_MIME_TYPE)).decode())
        drop_pos = event.position().toPoint()

        # Find target index based on drop position
        target_index = len(self._modules) - 1
        for i, item in enumerate(self._items):
            if drop_pos.y() < item.geometry().center().y():
                target_index = i
                break

        if source_index == target_index:
            return

        # Reorder modules
        module = self._modules.pop(source_index)
        self._modules.insert(target_index, module)

        # Update selected index
        if self._selected_index == source_index:
            self._selected_index = target_index
        elif source_index < self._selected_index <= target_index:
            self._selected_index -= 1
        elif target_index <= self._selected_index < source_index:
            self._selected_index += 1

        self._rebuild()
        self.step_reordered.emit(self._modules)
        event.acceptProposedAction()
