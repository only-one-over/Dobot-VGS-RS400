#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Flow step list widget with drag-and-drop reordering and status icons."""

from ..ui.qt_compat import (
    QByteArray,
    QColor,
    QDrag,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMimeData,
    QPainter,
    QPixmap,
    Qt,
    QVBoxLayout,
    QWidget,
    pyqtSignal,
)

from ..ui.ui_theme import FLOW_STEP_STYLE, FLOW_STEP_SELECTED_STYLE, FLOW_STEP_EMPTY_STYLE


# Status constants
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

# Status display config
_STATUS_CONFIG = {
    STATUS_PENDING:   {"icon": "⏳", "color": "#86909c", "bg": "#f7f9fb", "border": "#dde2e9"},
    STATUS_RUNNING:   {"icon": "▶", "color": "#1664FF", "bg": "#f3f7ff", "border": "#1664FF"},
    STATUS_COMPLETED: {"icon": "✓", "color": "#189959", "bg": "#e2f5eb", "border": "#2a814b"},
    STATUS_FAILED:    {"icon": "✗", "color": "#c43138", "bg": "#feeced", "border": "#d7312a"},
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
        self._empty_label: QLabel | None = None

        self.setAcceptDrops(True)
        self.setObjectName("flow_step_list")
        self.setStyleSheet("#flow_step_list { border: 1px solid #dde2e9; border-radius: 6px; }")

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
        # Clear existing step items
        for item in self._items:
            self._layout.removeWidget(item)
            item.setParent(None)
        self._items.clear()

        # Clear previous empty label if present
        if self._empty_label is not None:
            self._layout.removeWidget(self._empty_label)
            self._empty_label.setParent(None)
            self._empty_label = None

        if not self._modules:
            self._empty_label = QLabel("抓取流程为空")
            self._empty_label.setStyleSheet(FLOW_STEP_EMPTY_STYLE)
            self._layout.addWidget(self._empty_label)
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
        params = module.get('params', {})
        force_guard = params.get("force_guard") or {}
        force_text = ""
        if force_guard.get("enabled"):
            force_text = f", TCP力停: {float(force_guard.get('threshold_n', 0)):.1f}N"
        if module['type'] == "move":
            if params.get('motion_type') == "MovL":
                point_name = params.get('point_name', '')
                text += f" (直线运动, 点位: {point_name}, 速度: {params['speed']}%{force_text})"
        elif module['type'] in ("arc_motion", "force_arc"):
            p = params
            offset = p.get('center_offset_z', p.get('radius', 50))
            sweep = p.get('sweep_angle', abs(float(p.get('end_angle', 90)) - float(p.get('start_angle', 0))))
            direction = "顺时针" if p.get('arc_direction') == 'cw' else "逆时针"
            text += f" (圆弧运动, 上方距离: {offset}mm, 角度: {sweep}°, 方向: {direction}{force_text})"
        elif module['type'] == "relative_move":
            p = params
            coord = {"user": "用户", "tool": "工具", "joint": "关节"}.get(p.get("coord_system", "user"), "用户")
            motion = {"linear": "直线", "joint": "关节"}.get(p.get("motion_type", "linear"), "直线")
            text += f" (相对移动, 坐标系: {coord}, 方式: {motion}, 偏移: {p.get('offsets', [0]*6)}, 速度: {p.get('speed', 30)}%{force_text})"
        elif module['type'] == "relative_path":
            text += f" (连续相对路径{force_text})"
        elif module['type'] == "joint_move":
            offsets = params.get('offsets', [0]*6)
            text += f" (关节旋转, 偏移: {offsets}, 速度: {params['speed']}%)"
        elif module['type'] == "visual_servo":
            p = params
            text += f" (视觉伺服, 目标: {p.get('target_type', 'grasp_point')}, 阈值: {p.get('converge_threshold', 2.0)}mm)"
        elif module['type'] == "delay":
            duration_s = float(params.get('duration_s', 1.0))
            if params.get("wait_mode", "time") == "modbus_or_timeout":
                text += f" (最长等待: {duration_s:.1f}秒, 40001=1提前通过)"
            else:
                text += f" (延时: {duration_s:.1f}秒)"
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
