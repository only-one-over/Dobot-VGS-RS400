import os

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dobot_move.ui.config_center_page import ConfigCenterPage
from dobot_move.ui.qt_compat import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_camera_model_fields_show_independent_paths(qapp):
    """配置中心应独立显示 D435i/D405 的模型路径。"""
    page = ConfigCenterPage()
    d435i_path = os.path.abspath("models/d435i.onnx")
    d405_path = os.path.abspath("models/d405.onnx")

    page.update_camera_status("D435i", "connected", d435i_path)
    page.update_camera_status("D405", "connected", d405_path)

    # update_camera_status 用完整路径设置 text 和 toolTip
    assert page.d435i_model_path.text() == d435i_path
    assert page.d435i_model_path.toolTip() == d435i_path
    assert page.d405_model_path.text() == d405_path
    assert page.d405_model_path.toolTip() == d405_path


def test_connected_camera_disables_only_its_connect_btn(qapp):
    """连接中的相机应仅禁用自身的连接按钮，启用断开按钮。"""
    page = ConfigCenterPage()

    page.update_camera_status("D435i", "connected")

    assert page.d435i_connect_btn.isEnabled() is False
    assert page.d435i_disconnect_btn.isEnabled() is True
    # D405 不受影响
    assert page.d405_connect_btn.isEnabled() is True

    page.update_camera_status("D435i", "disconnected")
    assert page.d435i_connect_btn.isEnabled() is True
    assert page.d435i_disconnect_btn.isEnabled() is False
