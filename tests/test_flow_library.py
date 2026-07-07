import json
import shutil
import uuid
from pathlib import Path

import pytest

from dobot_move.flow.flow_library import FlowLibrary, required_camera_types


@pytest.fixture
def flow_path():
    directory = Path.cwd() / f".flow_library_test_{uuid.uuid4().hex}"
    directory.mkdir()
    try:
        yield directory / "flows.json"
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def test_legacy_list_is_migrated_and_backed_up(flow_path):
    legacy = [{"type": "move", "name": "旧步骤", "params": {}}]
    flow_path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")

    library = FlowLibrary.load(flow_path)

    assert library.main_flow_id == "flow-1"
    assert library.get_main_flow()["name"] == "流程 1"
    assert library.snapshot_modules() == legacy
    assert flow_path.with_suffix(".json.bak").exists()
    saved = json.loads(flow_path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == 2


def test_flow_crud_and_main_flow_rules(flow_path):
    library = FlowLibrary.load(
        flow_path,
        default_modules=[{"type": "delay", "params": {"duration_s": 1}}],
    )
    first_id = library.main_flow_id
    second = library.create_flow("流程 2", [{"type": "camera", "params": {"camera_type": "D405"}}])
    library.rename_flow(second["id"], "精定位")
    duplicate = library.duplicate_flow(second["id"])

    with pytest.raises(ValueError, match="主流程不能删除"):
        library.delete_flow(first_id)

    library.set_main_flow(second["id"])
    library.delete_flow(first_id)
    library.save()
    reloaded = FlowLibrary.load(flow_path)

    assert reloaded.main_flow_id == second["id"]
    assert reloaded.get_main_flow()["name"] == "精定位"
    assert duplicate["name"] == "精定位 副本"


def test_flow_names_must_be_nonempty_and_unique(flow_path):
    library = FlowLibrary.load(flow_path, default_modules=[])
    library.create_flow("流程 2")

    with pytest.raises(ValueError, match="不能为空"):
        library.create_flow(" ")
    with pytest.raises(ValueError, match="必须唯一"):
        library.create_flow("流程 2")


def test_snapshot_is_isolated_from_later_edits(flow_path):
    library = FlowLibrary.load(
        flow_path,
        default_modules=[{"type": "delay", "params": {"duration_s": 1}}],
    )

    snapshot = library.snapshot_modules()
    library.get_main_flow()["modules"][0]["params"]["duration_s"] = 9

    assert snapshot[0]["params"]["duration_s"] == 1


def test_required_cameras_follow_flow_modules():
    modules = [
        {"type": "camera", "params": {"camera_type": "D435i"}},
        {"type": "visual_servo", "params": {}},
        {"type": "camera", "params": {"camera_type": "unknown"}},
    ]

    assert required_camera_types(modules) == {"D435i", "D405"}
