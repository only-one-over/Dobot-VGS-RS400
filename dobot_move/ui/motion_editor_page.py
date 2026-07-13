"""Motion editor page widget – extracted from DobotMainWindow._build_motion_tab."""

from ..ui.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QGroupBox,
    QGridLayout, QDoubleSpinBox, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QCheckBox,
)
from ..ui.ui_theme import set_button_role, COLORS
from ..flow.flow_step_list import FlowStepList


class MotionEditorPage(QWidget):
    """Grasp-flow editor + module assembly tool, extracted into its own widget."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        """Build the full motion editor layout (identical to the original
        _build_motion_tab body)."""
        page_layout = QVBoxLayout(self)
        page_layout.setSpacing(10)
        page_layout.setContentsMargins(10, 10, 10, 10)

        # ── grasp flow group ──────────────────────────────────────────
        grasp_flow_group = QGroupBox("抓取流程编辑")
        grasp_flow_layout = QVBoxLayout()
        grasp_flow_layout.setSpacing(10)

        flow_select_layout = QHBoxLayout()
        flow_select_layout.setSpacing(8)
        flow_select_layout.addWidget(QLabel("编辑流程:"))
        self.edit_flow_combo = QComboBox()
        flow_select_layout.addWidget(self.edit_flow_combo, 1)
        self.new_flow_btn = QPushButton("新建")
        set_button_role(self.new_flow_btn, "primary")
        flow_select_layout.addWidget(self.new_flow_btn)
        self.rename_flow_btn = QPushButton("重命名")
        set_button_role(self.rename_flow_btn, "secondary")
        flow_select_layout.addWidget(self.rename_flow_btn)
        self.duplicate_flow_btn = QPushButton("复制")
        set_button_role(self.duplicate_flow_btn, "secondary")
        flow_select_layout.addWidget(self.duplicate_flow_btn)
        self.delete_flow_btn = QPushButton("删除")
        set_button_role(self.delete_flow_btn, "danger")
        flow_select_layout.addWidget(self.delete_flow_btn)
        grasp_flow_layout.addLayout(flow_select_layout)

        # flow step list
        self.flow_step_list = FlowStepList()
        grasp_flow_layout.addWidget(self.flow_step_list)

        # current selected step index
        self.selected_step_index = -1

        # ── module assembly group ─────────────────────────────────────
        module_group = QGroupBox("模块拼接工具")
        module_layout = QVBoxLayout()
        module_layout.setSpacing(10)

        # module selection
        module_select_layout = QHBoxLayout()
        module_select_layout.setSpacing(10)
        module_select_layout.addWidget(QLabel("选择模块:"))
        self.module_combo = QComboBox()
        self.module_combo.addItems(["相机识别", "直线运动", "圆弧运动", "相对移动", "连续相对路径", "关节旋转", "视觉伺服", "延时"])
        module_select_layout.addWidget(self.module_combo)

        self.add_module_btn = QPushButton("添加模块")
        set_button_role(self.add_module_btn, "primary")
        self.add_module_btn.setDefault(True)
        module_select_layout.addWidget(self.add_module_btn)

        self.remove_module_btn = QPushButton("移除模块")
        set_button_role(self.remove_module_btn, "danger")
        module_select_layout.addWidget(self.remove_module_btn)

        module_layout.addLayout(module_select_layout)

        # ── parameter editing ─────────────────────────────────────────
        self.param_group = QGroupBox("参数编辑")
        self.param_layout = QGridLayout()
        self.param_layout.setSpacing(10)

        # --- linear motion params ---
        self.linear_params = QWidget()
        linear_layout = QVBoxLayout(self.linear_params)
        linear_layout.setSpacing(10)

        target_layout = QHBoxLayout()
        target_layout.addWidget(QLabel("目标类型:"))
        self.linear_target_combo = QComboBox()
        self.linear_target_combo.addItems(["已保存点位", "相机识别坐标", "初始位置"])
        self.linear_target_combo.setToolTip("已保存点位: 移动到已保存的点位; 相机识别坐标: 移动到相机识别结果; 初始位置: 移动到初始位置")
        target_layout.addWidget(self.linear_target_combo)
        target_layout.addStretch()
        linear_layout.addLayout(target_layout)

        self.linear_point_combo = QComboBox()
        linear_layout.addWidget(self.linear_point_combo)
        self.linear_point_preview = QLabel("")
        self.linear_point_preview.setStyleSheet("color: #86868b; font-size: 11pt;")
        linear_layout.addWidget(self.linear_point_preview)

        speed_layout = QHBoxLayout()
        speed_layout.addWidget(QLabel("速度:"))
        self.linear_speed = QDoubleSpinBox()
        self.linear_speed.setRange(1, 100)
        self.linear_speed.setValue(30)
        speed_layout.addWidget(self.linear_speed)
        speed_layout.addStretch()
        linear_layout.addLayout(speed_layout)

        linear_force_layout = QHBoxLayout()
        self.linear_force_guard_enabled = QCheckBox("启用TCP力停止")
        linear_force_layout.addWidget(self.linear_force_guard_enabled)
        linear_force_layout.addWidget(QLabel("阈值(N):"))
        self.linear_force_threshold = QDoubleSpinBox()
        self.linear_force_threshold.setRange(0.1, 200.0)
        self.linear_force_threshold.setValue(5.0)
        self.linear_force_threshold.setDecimals(1)
        self.linear_force_threshold.setToolTip("当前TCP力相对运动前基线的合力超过该值时停止当前运动并进入下一步")
        linear_force_layout.addWidget(self.linear_force_threshold)
        linear_force_layout.addStretch()
        linear_layout.addLayout(linear_force_layout)

        self.linear_read_current_btn = QPushButton("读取当前位置")
        self.linear_read_current_btn.setMinimumWidth(120)
        linear_layout.addWidget(self.linear_read_current_btn)

        # --- joint rotation params ---
        self.joint_rotation_params = QWidget()
        joint_layout = QGridLayout(self.joint_rotation_params)
        joint_layout.setSpacing(10)

        self.joint_offsets = []
        for i in range(6):
            row = i // 2
            col = (i % 2) * 3
            joint_layout.addWidget(QLabel(f"关节{i+1}偏移:"), row, col * 2)
            spin = QDoubleSpinBox()
            spin.setRange(-360, 360)
            spin.setValue(0)
            self.joint_offsets.append(spin)
            joint_layout.addWidget(spin, row, col * 2 + 1)

        joint_layout.addWidget(QLabel("加速度:"), 3, 0)
        self.joint_accel = QDoubleSpinBox()
        self.joint_accel.setRange(1, 100)
        self.joint_accel.setValue(20)
        joint_layout.addWidget(self.joint_accel, 3, 1)

        joint_layout.addWidget(QLabel("速度:"), 3, 2)
        self.joint_speed = QDoubleSpinBox()
        self.joint_speed.setRange(1, 100)
        self.joint_speed.setValue(50)
        joint_layout.addWidget(self.joint_speed, 3, 3)

        # --- relative move params ---
        self.relative_move_params = QWidget()
        rel_layout = QGridLayout(self.relative_move_params)
        rel_layout.setSpacing(10)

        rel_layout.addWidget(QLabel("坐标系"), 0, 0)
        self.rel_coord_combo = QComboBox()
        self.rel_coord_combo.addItems(["用户", "工具", "关节"])
        rel_layout.addWidget(self.rel_coord_combo, 0, 1)

        rel_layout.addWidget(QLabel("运动方式:"), 0, 2)
        self.rel_motion_combo = QComboBox()
        self.rel_motion_combo.addItems(["直线", "关节"])
        rel_layout.addWidget(self.rel_motion_combo, 0, 3)

        self.rel_offsets = []
        for i, axis in enumerate(["X", "Y", "Z", "Rx", "Ry", "Rz"]):
            row = 1 + i // 3
            col = (i % 3) * 2
            rel_layout.addWidget(QLabel(f"{axis}偏移:"), row, col)
            spin = QDoubleSpinBox()
            spin.setRange(-1000, 1000)
            spin.setDecimals(2)
            spin.setValue(0)
            self.rel_offsets.append(spin)
            rel_layout.addWidget(spin, row, col + 1)

        rel_layout.addWidget(QLabel("速度:"), 3, 0)
        self.rel_speed = QDoubleSpinBox()
        self.rel_speed.setRange(1, 100)
        self.rel_speed.setValue(30)
        self.rel_speed.setDecimals(0)
        rel_layout.addWidget(self.rel_speed, 3, 1)

        rel_layout.addWidget(QLabel("加速度:"), 3, 2)
        self.rel_accel = QDoubleSpinBox()
        self.rel_accel.setRange(1, 100)
        self.rel_accel.setValue(20)
        self.rel_accel.setDecimals(0)
        rel_layout.addWidget(self.rel_accel, 3, 3)

        rel_layout.addWidget(QLabel("CP:"), 3, 4)
        self.rel_cp = QDoubleSpinBox()
        self.rel_cp.setRange(0, 100)
        self.rel_cp.setValue(100)
        self.rel_cp.setDecimals(0)
        rel_layout.addWidget(self.rel_cp, 3, 5)

        self.rel_force_guard_enabled = QCheckBox("启用TCP力停止")
        rel_layout.addWidget(self.rel_force_guard_enabled, 4, 0, 1, 2)
        rel_layout.addWidget(QLabel("阈值(N):"), 4, 2)
        self.rel_force_threshold = QDoubleSpinBox()
        self.rel_force_threshold.setRange(0.1, 200.0)
        self.rel_force_threshold.setValue(5.0)
        self.rel_force_threshold.setDecimals(1)
        self.rel_force_threshold.setToolTip("当前TCP力相对运动前基线的合力超过该值时停止当前运动并进入下一步")
        rel_layout.addWidget(self.rel_force_threshold, 4, 3)

        # --- arc motion params ---
        self.arc_motion_params = QWidget()
        fa_layout = QVBoxLayout(self.arc_motion_params)
        fa_layout.setSpacing(10)

        fa_params_widget = QWidget()
        fa_params_layout = QGridLayout(fa_params_widget)
        fa_params_layout.setSpacing(10)

        fa_params_layout.addWidget(QLabel("圆心上方距离(mm):"), 0, 0)
        self.fa_center_offset_z = QDoubleSpinBox()
        self.fa_center_offset_z.setRange(1, 500)
        self.fa_center_offset_z.setValue(50)
        self.fa_center_offset_z.setDecimals(2)
        fa_params_layout.addWidget(self.fa_center_offset_z, 0, 1)

        fa_params_layout.addWidget(QLabel("圆弧角度(°):"), 0, 2)
        self.fa_sweep_angle = QDoubleSpinBox()
        self.fa_sweep_angle.setRange(1, 360)
        self.fa_sweep_angle.setValue(90)
        self.fa_sweep_angle.setDecimals(2)
        fa_params_layout.addWidget(self.fa_sweep_angle, 0, 3)

        fa_params_layout.addWidget(QLabel("方向:"), 0, 4)
        self.fa_arc_direction = QComboBox()
        self.fa_arc_direction.addItems(["逆时针", "顺时针"])
        self.fa_arc_direction.setCurrentIndex(0)
        fa_params_layout.addWidget(self.fa_arc_direction, 0, 5)

        fa_params_layout.addWidget(QLabel("路点数"), 1, 0)
        self.fa_num_waypoints = QDoubleSpinBox()
        self.fa_num_waypoints.setRange(2, 500)
        self.fa_num_waypoints.setValue(30)
        self.fa_num_waypoints.setDecimals(0)
        fa_params_layout.addWidget(self.fa_num_waypoints, 1, 1)
        fa_params_layout.itemAtPosition(1, 0).widget().hide()
        self.fa_num_waypoints.hide()

        fa_params_layout.addWidget(QLabel("速度:"), 1, 2)
        self.fa_speed = QDoubleSpinBox()
        self.fa_speed.setRange(1, 100)
        self.fa_speed.setValue(20)
        fa_params_layout.addWidget(self.fa_speed, 1, 3)

        self.fa_force_guard_enabled = QCheckBox("启用TCP力停止")
        fa_params_layout.addWidget(self.fa_force_guard_enabled, 2, 0, 1, 2)
        fa_params_layout.addWidget(QLabel("阈值(N):"), 2, 2)
        self.fa_force_threshold = QDoubleSpinBox()
        self.fa_force_threshold.setRange(0.1, 200.0)
        self.fa_force_threshold.setValue(5.0)
        self.fa_force_threshold.setDecimals(1)
        self.fa_force_threshold.setToolTip("当前TCP力相对运动前基线的合力超过该值时停止当前运动并进入下一步")
        fa_params_layout.addWidget(self.fa_force_threshold, 2, 3)

        fa_layout.addWidget(fa_params_widget)

        # --- camera params ---
        self.camera_params = QWidget()
        camera_param_layout = QGridLayout(self.camera_params)
        camera_param_layout.setSpacing(10)

        camera_param_layout.addWidget(QLabel("选择相机:"), 0, 0)
        self.camera_module_combo = QComboBox()
        self.camera_module_combo.addItems(["D435i", "D405"])
        self.camera_module_combo.setCurrentIndex(0)
        camera_param_layout.addWidget(self.camera_module_combo, 0, 1)

        # --- delay params ---
        self.delay_params = QWidget()
        delay_layout = QGridLayout(self.delay_params)
        delay_layout.addWidget(QLabel("等待方式:"), 0, 0)
        self.delay_wait_mode = QComboBox()
        self.delay_wait_mode.addItems(["固定延时", "40001放行或超时"])
        self.delay_wait_mode.setToolTip(
            "等待期间40001=5；上位机写1可提前进入下一步"
        )
        delay_layout.addWidget(self.delay_wait_mode, 0, 1)

        delay_layout.addWidget(QLabel("最长等待(秒):"), 1, 0)
        self.delay_seconds = QDoubleSpinBox()
        self.delay_seconds.setRange(0.1, 3600.0)
        self.delay_seconds.setDecimals(1)
        self.delay_seconds.setSingleStep(0.5)
        self.delay_seconds.setValue(1.0)
        self.delay_seconds.setSuffix(" s")
        delay_layout.addWidget(self.delay_seconds, 1, 1)

        delay_layout.setColumnStretch(2, 1)

        # --- continuous relative path params ---
        self.relative_path_params = QWidget()
        rpath_layout = QVBoxLayout(self.relative_path_params)
        rpath_layout.setSpacing(6)

        # execution mode
        exec_mode_layout = QHBoxLayout()
        rpath_exec_mode_label = QLabel("执行模式:")
        exec_mode_layout.addWidget(rpath_exec_mode_label)
        self.rpath_exec_mode = QComboBox()
        self.rpath_exec_mode.addItems(["stop_each", "queued"])
        self.rpath_exec_mode.setToolTip("stop_each: 每段等待完成; queued: 连续下发后统一等待")
        exec_mode_layout.addWidget(self.rpath_exec_mode)
        exec_mode_layout.addStretch()
        rpath_layout.addLayout(exec_mode_layout)

        # segment table
        self.rpath_seg_table = QTableWidget(0, 15)
        self.rpath_seg_table.setHorizontalHeaderLabels(["启用", "名称", "坐标系", "方式", "X", "Y", "Z", "Rx", "Ry", "Rz", "速度", "加速度", "CP", "段后等待", "备注"])
        rpath_header = self.rpath_seg_table.horizontalHeader()
        rpath_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)   # 启用
        rpath_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # 名称
        rpath_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)   # 坐标系
        rpath_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)   # 方式
        rpath_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)   # X
        rpath_header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)   # Y
        rpath_header.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)   # Z
        rpath_header.setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)   # Rx
        rpath_header.setSectionResizeMode(8, QHeaderView.ResizeMode.Fixed)   # Ry
        rpath_header.setSectionResizeMode(9, QHeaderView.ResizeMode.Fixed)   # Rz
        rpath_header.setSectionResizeMode(10, QHeaderView.ResizeMode.Fixed)  # 速度
        rpath_header.setSectionResizeMode(11, QHeaderView.ResizeMode.Fixed)  # 加速度
        rpath_header.setSectionResizeMode(12, QHeaderView.ResizeMode.Fixed)  # CP
        rpath_header.setSectionResizeMode(13, QHeaderView.ResizeMode.Fixed)  # 段后等待
        rpath_header.setSectionResizeMode(14, QHeaderView.ResizeMode.Stretch)  # 备注
        self.rpath_seg_table.setColumnWidth(0, 60)   # 启用
        self.rpath_seg_table.setColumnWidth(2, 80)   # 坐标系
        self.rpath_seg_table.setColumnWidth(3, 80)   # 方式
        self.rpath_seg_table.setColumnWidth(4, 80)   # X
        self.rpath_seg_table.setColumnWidth(5, 80)   # Y
        self.rpath_seg_table.setColumnWidth(6, 80)   # Z
        self.rpath_seg_table.setColumnWidth(7, 80)   # Rx
        self.rpath_seg_table.setColumnWidth(8, 80)   # Ry
        self.rpath_seg_table.setColumnWidth(9, 80)   # Rz
        self.rpath_seg_table.setColumnWidth(10, 80)  # 速度
        self.rpath_seg_table.setColumnWidth(11, 80)  # 加速度
        self.rpath_seg_table.setColumnWidth(12, 60)  # CP
        self.rpath_seg_table.setColumnWidth(13, 80)  # 段后等待
        self.rpath_seg_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        rpath_layout.addWidget(self.rpath_seg_table)

        # segment operation buttons
        seg_btn_layout = QHBoxLayout()
        btn_add_seg = QPushButton("添加段")
        btn_add_seg.clicked.connect(lambda: self._add_path_template(self.rpath_seg_table, "empty"))
        seg_btn_layout.addWidget(btn_add_seg)

        btn_del_seg = QPushButton("删除段")
        btn_del_seg.clicked.connect(lambda: self._remove_path_segment(self.rpath_seg_table))
        seg_btn_layout.addWidget(btn_del_seg)

        btn_up_seg = QPushButton("上移")
        btn_up_seg.clicked.connect(lambda: self._move_path_segment(self.rpath_seg_table, -1))
        seg_btn_layout.addWidget(btn_up_seg)

        btn_down_seg = QPushButton("下移")
        btn_down_seg.clicked.connect(lambda: self._move_path_segment(self.rpath_seg_table, 1))
        seg_btn_layout.addWidget(btn_down_seg)

        btn_copy_seg = QPushButton("复制段")
        btn_copy_seg.clicked.connect(lambda: self._copy_path_segment(self.rpath_seg_table))
        seg_btn_layout.addWidget(btn_copy_seg)

        btn_apply_global = QPushButton("应用全局")
        btn_apply_global.clicked.connect(lambda: self._apply_global_to_segments(self.rpath_seg_table))
        seg_btn_layout.addWidget(btn_apply_global)

        btn_zero_sel = QPushButton("清零选中")
        btn_zero_sel.clicked.connect(lambda: self._zero_selected_segments(self.rpath_seg_table))
        seg_btn_layout.addWidget(btn_zero_sel)

        seg_btn_layout.addStretch()
        rpath_layout.addLayout(seg_btn_layout)

        # common parameter row for relative path
        common_layout = QGridLayout()
        common_layout.setSpacing(10)

        common_layout.addWidget(QLabel("坐标系:"), 0, 0)
        self.rpath_coord_combo = QComboBox()
        self.rpath_coord_combo.addItems(["用户", "工具", "关节"])
        common_layout.addWidget(self.rpath_coord_combo, 0, 1)

        common_layout.addWidget(QLabel("运动方式:"), 0, 2)
        self.rpath_motion_combo = QComboBox()
        self.rpath_motion_combo.addItems(["直线", "关节"])
        common_layout.addWidget(self.rpath_motion_combo, 0, 3)

        common_layout.addWidget(QLabel("速度:"), 0, 4)
        self.rpath_speed = QDoubleSpinBox()
        self.rpath_speed.setRange(1, 100)
        self.rpath_speed.setValue(30)
        self.rpath_speed.setDecimals(0)
        common_layout.addWidget(self.rpath_speed, 0, 5)

        common_layout.addWidget(QLabel("加速度:"), 1, 0)
        self.rpath_accel = QDoubleSpinBox()
        self.rpath_accel.setRange(1, 100)
        self.rpath_accel.setValue(30)
        self.rpath_accel.setDecimals(0)
        common_layout.addWidget(self.rpath_accel, 1, 1)

        common_layout.addWidget(QLabel("CP:"), 1, 2)
        self.rpath_cp = QDoubleSpinBox()
        self.rpath_cp.setRange(0, 100)
        self.rpath_cp.setValue(0)
        self.rpath_cp.setDecimals(0)
        common_layout.addWidget(self.rpath_cp, 1, 3)

        self.rpath_force_guard_enabled = QCheckBox("启用TCP力停止")
        common_layout.addWidget(self.rpath_force_guard_enabled, 2, 0, 1, 2)
        common_layout.addWidget(QLabel("阈值(N):"), 2, 2)
        self.rpath_force_threshold = QDoubleSpinBox()
        self.rpath_force_threshold.setRange(0.1, 200.0)
        self.rpath_force_threshold.setValue(5.0)
        self.rpath_force_threshold.setDecimals(1)
        self.rpath_force_threshold.setToolTip("当前TCP力相对运动前基线的合力超过该值时停止当前运动并进入下一步")
        common_layout.addWidget(self.rpath_force_threshold, 2, 3)

        rpath_layout.addLayout(common_layout)

        # default: show linear motion params
        self.param_layout.addWidget(self.linear_params, 0, 0)

        self.param_group.setLayout(self.param_layout)
        module_layout.addWidget(self.param_group)

        # update params button
        self.update_param_btn = QPushButton("更新参数")
        set_button_role(self.update_param_btn, "secondary")
        self.update_param_btn.setDefault(True)
        module_layout.addWidget(self.update_param_btn)

        module_group.setLayout(module_layout)
        grasp_flow_layout.addWidget(module_group)

        # ── flow operation buttons ────────────────────────────────────
        flow_ops_layout = QHBoxLayout()
        flow_ops_layout.setSpacing(10)

        self.view_flow_btn = QPushButton("查看当前流程")
        self.view_flow_btn.setMinimumWidth(120)
        set_button_role(self.view_flow_btn, "secondary")
        flow_ops_layout.addWidget(self.view_flow_btn)

        self.save_flow_btn = QPushButton("保存流程")
        set_button_role(self.save_flow_btn, "secondary")
        flow_ops_layout.addWidget(self.save_flow_btn)

        self.publish_flow_btn = QPushButton("发布到 Runtime")
        set_button_role(self.publish_flow_btn, "primary")
        flow_ops_layout.addWidget(self.publish_flow_btn)

        self.load_flow_btn = QPushButton("加载流程")
        set_button_role(self.load_flow_btn, "secondary")
        flow_ops_layout.addWidget(self.load_flow_btn)

        self.run_flow_btn = QPushButton("执行流程")
        set_button_role(self.run_flow_btn, "primary")
        self.run_flow_btn.setDefault(True)
        flow_ops_layout.addWidget(self.run_flow_btn)

        grasp_flow_layout.addLayout(flow_ops_layout)

        editor_pause_layout = QHBoxLayout()
        self.editor_pause_btn = QPushButton("暂停")
        set_button_role(self.editor_pause_btn, "warning")
        self.editor_pause_btn.setEnabled(False)
        editor_pause_layout.addWidget(self.editor_pause_btn)
        self.editor_continue_btn = QPushButton("继续")
        set_button_role(self.editor_continue_btn, "connect")
        self.editor_continue_btn.setEnabled(False)
        editor_pause_layout.addWidget(self.editor_continue_btn)
        grasp_flow_layout.addLayout(editor_pause_layout)

        grasp_flow_group.setLayout(grasp_flow_layout)
        page_layout.addWidget(grasp_flow_group)

    # ── path segment helper methods ───────────────────────────────────

    def _add_path_template(self, table, template):
        row = table.rowCount()
        table.insertRow(row)
        # Column order: 启用, 名称, 坐标系, 方式, X, Y, Z, Rx, Ry, Rz, 速度, 加速度, CP, 段后等待, 备注
        table.setItem(row, 0, QTableWidgetItem("✓"))  # enabled
        if template == "x200":
            table.setItem(row, 1, QTableWidgetItem("X+200"))
            values = [200, 0, 0, 0, 0, 0]
        elif template == "y200":
            table.setItem(row, 1, QTableWidgetItem("Y+200"))
            values = [0, 200, 0, 0, 0, 0]
        elif template == "z200":
            table.setItem(row, 1, QTableWidgetItem("Z+200"))
            values = [0, 0, 200, 0, 0, 0]
        elif template == "zy200":
            table.setItem(row, 1, QTableWidgetItem("ZY平面200"))
            values = [0, 141.4, 141.4, 0, 0, 0]
        else:
            table.setItem(row, 1, QTableWidgetItem(f"段{row+1}"))
            values = [0, 0, 0, 0, 0, 0]
        table.setItem(row, 2, QTableWidgetItem("继承"))  # coord_system
        table.setItem(row, 3, QTableWidgetItem("继承"))  # motion_type
        for col, val in enumerate(values):
            table.setItem(row, 4 + col, QTableWidgetItem(str(val)))
        table.setItem(row, 10, QTableWidgetItem("继承"))  # speed
        table.setItem(row, 11, QTableWidgetItem("继承"))  # acceleration
        table.setItem(row, 12, QTableWidgetItem("继承"))  # cp
        table.setItem(row, 13, QTableWidgetItem("是"))  # wait_after
        table.setItem(row, 14, QTableWidgetItem(""))  # note

    def _remove_path_segment(self, table):
        rows = set(item.row() for item in table.selectedItems())
        for row in sorted(rows, reverse=True):
            table.removeRow(row)

    def _move_path_segment(self, table, direction):
        rows = set(item.row() for item in table.selectedItems())
        if not rows:
            return
        row = min(rows)
        new_row = row + direction
        if new_row < 0 or new_row >= table.rowCount():
            return
        for col in range(table.columnCount()):
            item1 = table.takeItem(row, col)
            item2 = table.takeItem(new_row, col)
            table.setItem(row, col, item2)
            table.setItem(new_row, col, item1)

    def _copy_path_segment(self, table):
        rows = set(item.row() for item in table.selectedItems())
        if not rows:
            return
        for row in sorted(rows):
            new_row = row + 1
            table.insertRow(new_row)
            for col in range(table.columnCount()):
                item = table.item(row, col)
                new_item = QTableWidgetItem(item.text() if item else "")
                table.setItem(new_row, col, new_item)

    def _apply_global_to_segments(self, table):
        """Apply global defaults to selected segments."""
        rows = set(item.row() for item in table.selectedItems())
        for row in rows:
            table.setItem(row, 2, QTableWidgetItem("继承"))  # coord_system
            table.setItem(row, 3, QTableWidgetItem("继承"))  # motion_type
            table.setItem(row, 10, QTableWidgetItem("继承"))  # speed
            table.setItem(row, 11, QTableWidgetItem("继承"))  # acceleration
            table.setItem(row, 12, QTableWidgetItem("继承"))  # cp

    def _zero_selected_segments(self, table):
        """Zero out offsets for selected segments."""
        rows = set(item.row() for item in table.selectedItems())
        for row in rows:
            for col in range(4, 10):  # X, Y, Z, Rx, Ry, Rz columns
                table.setItem(row, col, QTableWidgetItem("0"))