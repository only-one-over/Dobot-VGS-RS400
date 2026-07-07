"""Small read-only widgets used by the Runtime engineering console."""

from __future__ import annotations

from collections import deque

from ..ui.qt_compat import QColor, QPainter, QPen, Qt, QWidget


class ErrorTrendPlot(QWidget):
    def __init__(self, title: str, *, x_mode: str, parent=None):
        super().__init__(parent)
        self.title = str(title)
        self.x_mode = str(x_mode)
        self.samples = deque(maxlen=100)
        self.setMinimumHeight(150)

    def add_sample(self, timestamp: float, iteration: int, error_mm: float):
        self.samples.append((float(timestamp), int(iteration), float(error_mm)))
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0b0f1a"))
        painter.setPen(QColor("#cbd5e1"))
        painter.drawText(10, 20, self.title)

        left, top = 42, 30
        right, bottom = max(left + 1, self.width() - 10), max(top + 1, self.height() - 24)
        painter.setPen(QPen(QColor("#334155"), 1))
        painter.drawLine(left, top, left, bottom)
        painter.drawLine(left, bottom, right, bottom)
        if len(self.samples) < 2:
            painter.setPen(QColor("#64748b"))
            painter.drawText(left + 10, top + 30, "等待视觉伺服数据")
            return

        x_values = [
            sample[0] if self.x_mode == "time" else sample[1]
            for sample in self.samples
        ]
        y_values = [sample[2] for sample in self.samples]
        x_min, x_max = min(x_values), max(x_values)
        y_max = max(1.0, max(y_values))
        x_span = max(1e-6, x_max - x_min)

        points = []
        for x_value, y_value in zip(x_values, y_values):
            x = left + (x_value - x_min) / x_span * (right - left)
            y = bottom - max(0.0, y_value) / y_max * (bottom - top)
            points.append((int(x), int(y)))
        painter.setPen(QPen(QColor("#22c55e"), 2))
        for start, end in zip(points, points[1:]):
            painter.drawLine(start[0], start[1], end[0], end[1])
        painter.setPen(QColor("#94a3b8"))
        painter.drawText(4, top + 5, f"{y_max:.1f}")
        painter.drawText(8, bottom + 16, "0")
