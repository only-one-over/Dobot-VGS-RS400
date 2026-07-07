import os

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dobot_move.ui.main_control_panel import MainControlPanel
from dobot_move.ui.qt_compat import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_camera_model_fields_show_independent_paths(qapp):
    panel = MainControlPanel()
    d435i_path = os.path.abspath("models/d435i.onnx")
    d405_path = os.path.abspath("models/d405.onnx")

    panel.set_camera_model_path("D435i", d435i_path)
    panel.set_camera_model_path("D405", d405_path)

    assert panel.d435i_model_path.text() == "d435i.onnx"
    assert panel.d435i_model_path.toolTip() == d435i_path
    assert panel.d405_model_path.text() == "d405.onnx"
    assert panel.d405_model_path.toolTip() == d405_path


def test_connected_camera_disables_only_its_model_selector(qapp):
    panel = MainControlPanel()

    panel.set_camera_model_selection_enabled("D435i", False)

    assert panel.d435i_model_select_btn.isEnabled() is False
    assert panel.d405_model_select_btn.isEnabled() is True

    panel.set_camera_model_selection_enabled("D435i", True)
    assert panel.d435i_model_select_btn.isEnabled() is True
