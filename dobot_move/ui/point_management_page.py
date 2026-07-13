"""Point management page widget extracted from gui_app.py."""

from ..ui.qt_compat import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QTableWidget,
    QPushButton,
    QHeaderView,
)
from ..ui.ui_theme import set_button_role


class PointManagementPage(QWidget):
    """Point management tab: point table + edit controls."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        """Build the point management page layout."""
        point_mgmt_group = QGroupBox("点位管理")
        point_mgmt_layout = QVBoxLayout()
        point_mgmt_layout.setSpacing(10)

        self.points_table = QTableWidget()
        self.points_table.setColumnCount(9)
        self.points_table.setHorizontalHeaderLabels(
            ["名称", "X", "Y", "Z", "Rx", "Ry", "Rz", "相对", "基准点位"]
        )
        header = self.points_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.points_table.setColumnWidth(0, 100)
        for col in range(1, 7):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)
        self.points_table.setColumnWidth(7, 60)
        header.setSectionResizeMode(8, QHeaderView.ResizeMode.Fixed)
        self.points_table.setColumnWidth(8, 120)
        self.points_table.setAlternatingRowColors(True)
        self.points_table.verticalHeader().setVisible(False)
        self.points_table.verticalHeader().setDefaultSectionSize(56)
        self.points_table.setMinimumHeight(300)
        point_mgmt_layout.addWidget(self.points_table)

        point_btn_layout = QHBoxLayout()
        point_btn_layout.setSpacing(10)

        self.add_point_btn = QPushButton("添加点位")
        set_button_role(self.add_point_btn, "primary")
        point_btn_layout.addWidget(self.add_point_btn)

        self.delete_point_btn = QPushButton("删除点位")
        set_button_role(self.delete_point_btn, "danger")
        point_btn_layout.addWidget(self.delete_point_btn)

        self.edit_point_btn = QPushButton("修改点位")
        set_button_role(self.edit_point_btn, "secondary")
        point_btn_layout.addWidget(self.edit_point_btn)

        self.save_point_btn = QPushButton("保存修改")
        set_button_role(self.save_point_btn, "secondary")
        self.save_point_btn.setEnabled(False)
        point_btn_layout.addWidget(self.save_point_btn)

        self.cancel_point_btn = QPushButton("取消修改")
        set_button_role(self.cancel_point_btn, "secondary")
        self.cancel_point_btn.setEnabled(False)
        point_btn_layout.addWidget(self.cancel_point_btn)

        self.read_point_btn = QPushButton("读取当前点位")
        set_button_role(self.read_point_btn, "secondary")
        self.read_point_btn.setMinimumWidth(120)
        self.read_point_btn.setEnabled(False)
        point_btn_layout.addWidget(self.read_point_btn)

        self.refresh_points_btn = QPushButton("刷新点位")
        set_button_role(self.refresh_points_btn, "secondary")
        point_btn_layout.addWidget(self.refresh_points_btn)

        self.move_to_point_btn = QPushButton("运动到此点")
        set_button_role(self.move_to_point_btn, "secondary")
        self.move_to_point_btn.setEnabled(False)
        point_btn_layout.addWidget(self.move_to_point_btn)

        point_btn_layout.addStretch()
        point_mgmt_layout.addLayout(point_btn_layout)

        point_mgmt_group.setLayout(point_mgmt_layout)

        page_layout = QVBoxLayout(self)
        page_layout.setSpacing(10)
        page_layout.setContentsMargins(10, 10, 10, 10)
        page_layout.addWidget(point_mgmt_group)