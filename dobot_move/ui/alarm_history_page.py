from ..ui.qt_compat import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget, QHeaderView
from ..ui.ui_theme import set_button_role


class AlarmHistoryPage(QWidget):
    """Standalone alarm history page extracted from gui_app.py."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        page_layout = QVBoxLayout(self)
        page_layout.setSpacing(10)
        page_layout.setContentsMargins(10, 10, 10, 10)

        ops_layout = QHBoxLayout()
        self.alarm_refresh_btn = QPushButton("刷新报警记录")
        set_button_role(self.alarm_refresh_btn, "secondary")
        self.alarm_refresh_btn.setMinimumWidth(120)
        ops_layout.addWidget(self.alarm_refresh_btn)

        self.alarm_clear_btn = QPushButton("清空本地记录")
        set_button_role(self.alarm_clear_btn, "danger")
        self.alarm_clear_btn.setMinimumWidth(120)
        self.alarm_clear_btn.setEnabled(False)
        ops_layout.addWidget(self.alarm_clear_btn)
        ops_layout.addStretch()
        page_layout.addLayout(ops_layout)

        self.alarm_table = QTableWidget()
        self.alarm_table.setColumnCount(7)
        self.alarm_table.setHorizontalHeaderLabels(["时间", "来源", "代码", "等级", "描述", "处理建议", "原始响应"])
        header = self.alarm_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)  # 时间
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)  # 来源
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)  # 代码
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)  # 等级
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)  # 描述
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)  # 处理建议
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)  # 原始响应
        self.alarm_table.setColumnWidth(0, 150)  # 时间
        self.alarm_table.setColumnWidth(1, 100)  # 来源
        self.alarm_table.setColumnWidth(2, 80)   # 代码
        self.alarm_table.setColumnWidth(3, 60)   # 等级
        self.alarm_table.setColumnWidth(6, 100)  # 原始响应
        self.alarm_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.alarm_table.setAlternatingRowColors(True)
        page_layout.addWidget(self.alarm_table)