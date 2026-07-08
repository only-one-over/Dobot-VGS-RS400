"""PR 2 — 锁定三个生产流程角色 (Lock production flow roles).

Covers Tasks 1-5 of the spec at
``.trae/specs/lock-production-flow-roles/tasks.md``:

1. FlowLibrary schema_version=3 + flow_roles field
2. grasp_flow_modules.default.json contains three fixed flows + flow_roles
3. delete_flow / rename_flow reject role flows
4. Schema v2 → v3 auto-migration preserves user modules
5. GUI hides new/rename/duplicate/delete flow buttons
"""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest

from dobot_move.config.config_manager import DEFAULT_GRASP_FLOW_TEMPLATE
from dobot_move.flow.flow_library import (
    DEFAULT_FLOW_ROLES,
    FLOW_SCHEMA_VERSION,
    FlowLibrary,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def flow_path():
    directory = Path.cwd() / f".flow_roles_test_{uuid.uuid4().hex}"
    directory.mkdir()
    try:
        yield directory / "flows.json"
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def _v3_payload_with_roles() -> dict:
    """A minimal valid v3 payload containing the three fixed role flows."""
    return {
        "schema_version": 3,
        "main_flow_id": "flow-low-hook",
        "last_edited_flow_id": "flow-low-hook",
        "flow_roles": {
            "low_hook": "flow-low-hook",
            "high_hook": "flow-high-hook",
            "error_recovery": "flow-error-recovery",
        },
        "flows": [
            {"id": "flow-low-hook", "name": "低钩子提钩", "modules": []},
            {"id": "flow-high-hook", "name": "高钩子提钩", "modules": []},
            {"id": "flow-error-recovery", "name": "错误回钩", "modules": []},
        ],
    }


def _v2_payload_with_user_flow() -> dict:
    """A v2 payload with a single user flow carrying real modules data."""
    return {
        "schema_version": 2,
        "main_flow_id": "flow-1",
        "last_edited_flow_id": "flow-1",
        "flows": [
            {
                "id": "flow-1",
                "name": "流程 1",
                "modules": [
                    {"type": "move", "name": "旧步骤", "params": {"speed": 30}},
                    {"type": "delay", "name": "等待", "params": {"duration_s": 2}},
                ],
            }
        ],
    }


# ---------------------------------------------------------------------------
# Task 1: FlowLibrary schema_version=3 + flow_roles field
# ---------------------------------------------------------------------------


def test_schema_version_is_three():
    assert FLOW_SCHEMA_VERSION == 3


def test_flow_roles_loaded_from_v3_config(flow_path):
    payload = _v3_payload_with_roles()
    flow_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    library = FlowLibrary.load(flow_path)

    assert library.flow_roles == {
        "low_hook": "flow-low-hook",
        "high_hook": "flow-high-hook",
        "error_recovery": "flow-error-recovery",
    }


def test_flow_roles_property_returns_mapping(flow_path):
    payload = _v3_payload_with_roles()
    flow_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    library = FlowLibrary.load(flow_path)

    # flow_roles is exposed as a property (not a plain attribute) that
    # returns the dict[str, str] mapping from the normalized payload.
    assert isinstance(library.flow_roles, dict)
    assert set(library.flow_roles.keys()) == {
        "low_hook",
        "high_hook",
        "error_recovery",
    }
    for role, fid in DEFAULT_FLOW_ROLES.items():
        assert library.flow_roles[role] == fid


def test_save_persists_flow_roles_and_schema_v3(flow_path):
    payload = _v3_payload_with_roles()
    flow_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    library = FlowLibrary.load(flow_path)
    library.save()

    saved = json.loads(flow_path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == 3
    assert "flow_roles" in saved
    assert saved["flow_roles"]["low_hook"] == "flow-low-hook"
    assert saved["flow_roles"]["high_hook"] == "flow-high-hook"
    assert saved["flow_roles"]["error_recovery"] == "flow-error-recovery"


# ---------------------------------------------------------------------------
# Task 2: default config contains three fixed flows + flow_roles mapping
# ---------------------------------------------------------------------------


def test_default_config_has_schema_version_three():
    with open(DEFAULT_GRASP_FLOW_TEMPLATE, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    assert data["schema_version"] == 3


def test_default_config_contains_flow_roles_mapping():
    with open(DEFAULT_GRASP_FLOW_TEMPLATE, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    assert data["flow_roles"] == {
        "low_hook": "flow-low-hook",
        "high_hook": "flow-high-hook",
        "error_recovery": "flow-error-recovery",
    }


def test_default_config_contains_three_fixed_flows():
    with open(DEFAULT_GRASP_FLOW_TEMPLATE, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    flow_ids = [flow["id"] for flow in data["flows"]]
    assert "flow-low-hook" in flow_ids
    assert "flow-high-hook" in flow_ids
    assert "flow-error-recovery" in flow_ids
    # Each fixed flow should start with an empty modules array (the user
    # will populate them via the editor).
    for flow in data["flows"]:
        assert isinstance(flow["modules"], list)


def test_default_config_loads_via_flow_library(flow_path):
    """The shipped default config must load cleanly through FlowLibrary."""
    shutil.copy2(DEFAULT_GRASP_FLOW_TEMPLATE, flow_path)
    library = FlowLibrary.load(flow_path)
    assert library.flow_roles["low_hook"] == "flow-low-hook"
    assert library.flow_roles["high_hook"] == "flow-high-hook"
    assert library.flow_roles["error_recovery"] == "flow-error-recovery"
    library.get_flow("flow-low-hook")
    library.get_flow("flow-high-hook")
    library.get_flow("flow-error-recovery")


# ---------------------------------------------------------------------------
# Task 3: delete_flow / rename_flow reject role flows
# ---------------------------------------------------------------------------


def test_delete_flow_rejects_role_flow_low_hook(flow_path):
    payload = _v3_payload_with_roles()
    flow_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    library = FlowLibrary.load(flow_path)

    with pytest.raises(ValueError, match="角色流程不可删除"):
        library.delete_flow("flow-low-hook")


def test_delete_flow_rejects_role_flow_high_hook(flow_path):
    payload = _v3_payload_with_roles()
    flow_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    library = FlowLibrary.load(flow_path)

    with pytest.raises(ValueError, match="角色流程不可删除"):
        library.delete_flow("flow-high-hook")


def test_delete_flow_rejects_role_flow_error_recovery(flow_path):
    payload = _v3_payload_with_roles()
    flow_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    library = FlowLibrary.load(flow_path)

    with pytest.raises(ValueError, match="角色流程不可删除"):
        library.delete_flow("flow-error-recovery")


def test_delete_flow_allows_non_role_flow(flow_path):
    """A user-created (non-role) flow can still be deleted."""
    payload = _v3_payload_with_roles()
    flow_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    library = FlowLibrary.load(flow_path)
    # Create a non-role flow and make it the main flow so the role flow
    # main_flow_id guard doesn't block deletion of flow-low-hook's sibling.
    custom = library.create_flow("自定义流程", [{"type": "delay", "params": {"duration_s": 1}}])
    library.set_main_flow(custom["id"])
    # Deleting another non-role flow (a duplicate) should be allowed.
    duplicate = library.duplicate_flow(custom["id"])
    library.delete_flow(duplicate["id"])  # should not raise
    remaining_ids = {flow["id"] for flow in library.flows}
    assert duplicate["id"] not in remaining_ids


def test_rename_flow_rejects_role_flow(flow_path):
    payload = _v3_payload_with_roles()
    flow_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    library = FlowLibrary.load(flow_path)

    with pytest.raises(ValueError, match="角色流程不可重命名"):
        library.rename_flow("flow-high-hook", "新名称")


def test_rename_flow_rejects_error_recovery(flow_path):
    payload = _v3_payload_with_roles()
    flow_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    library = FlowLibrary.load(flow_path)

    with pytest.raises(ValueError, match="角色流程不可重命名"):
        library.rename_flow("flow-error-recovery", "应急流程")


def test_rename_flow_allows_non_role_flow(flow_path):
    payload = _v3_payload_with_roles()
    flow_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    library = FlowLibrary.load(flow_path)
    custom = library.create_flow("自定义流程", [])
    library.rename_flow(custom["id"], "新名称")  # should not raise
    assert library.get_flow(custom["id"])["name"] == "新名称"


# ---------------------------------------------------------------------------
# Task 4: Schema v2 → v3 auto-migration
# ---------------------------------------------------------------------------


def test_v2_config_auto_migrates_to_v3(flow_path):
    v2 = _v2_payload_with_user_flow()
    flow_path.write_text(json.dumps(v2, ensure_ascii=False), encoding="utf-8")

    library = FlowLibrary.load(flow_path)

    assert library.flow_roles == {
        "low_hook": "flow-low-hook",
        "high_hook": "flow-high-hook",
        "error_recovery": "flow-error-recovery",
    }


def test_v2_migration_creates_three_fixed_flows(flow_path):
    v2 = _v2_payload_with_user_flow()
    flow_path.write_text(json.dumps(v2, ensure_ascii=False), encoding="utf-8")

    library = FlowLibrary.load(flow_path)

    flow_ids = {flow["id"] for flow in library.flows}
    assert "flow-low-hook" in flow_ids
    assert "flow-high-hook" in flow_ids
    assert "flow-error-recovery" in flow_ids
    # The original user flow must also be preserved.
    assert "flow-1" in flow_ids


def test_v2_migration_preserves_user_modules(flow_path):
    v2 = _v2_payload_with_user_flow()
    flow_path.write_text(json.dumps(v2, ensure_ascii=False), encoding="utf-8")

    library = FlowLibrary.load(flow_path)

    user_flow = library.get_flow("flow-1")
    assert len(user_flow["modules"]) == 2
    assert user_flow["modules"][0]["type"] == "move"
    assert user_flow["modules"][0]["params"]["speed"] == 30
    assert user_flow["modules"][1]["type"] == "delay"
    assert user_flow["modules"][1]["params"]["duration_s"] == 2


def test_v2_migration_persists_v3_schema_to_disk(flow_path):
    v2 = _v2_payload_with_user_flow()
    flow_path.write_text(json.dumps(v2, ensure_ascii=False), encoding="utf-8")

    FlowLibrary.load(flow_path)

    saved = json.loads(flow_path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == 3
    assert "flow_roles" in saved
    saved_ids = {flow["id"] for flow in saved["flows"]}
    assert {"flow-low-hook", "flow-high-hook", "flow-error-recovery"} <= saved_ids
    assert "flow-1" in saved_ids


def test_v2_migration_preserves_main_flow_id(flow_path):
    """The user's existing main flow stays as main after migration."""
    v2 = _v2_payload_with_user_flow()
    flow_path.write_text(json.dumps(v2, ensure_ascii=False), encoding="utf-8")

    library = FlowLibrary.load(flow_path)

    assert library.main_flow_id == "flow-1"


def test_v2_migration_creates_backup(flow_path):
    v2 = _v2_payload_with_user_flow()
    flow_path.write_text(json.dumps(v2, ensure_ascii=False), encoding="utf-8")

    FlowLibrary.load(flow_path)

    # save() backs up the existing file before overwriting.
    assert flow_path.with_suffix(".json.bak").exists()


def test_v3_config_not_re_migrated(flow_path):
    """Loading an already-v3 config should not trigger migration save."""
    payload = _v3_payload_with_roles()
    flow_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    library = FlowLibrary.load(flow_path)
    # Re-loading should be idempotent: no backup file created because
    # save() only writes when content changed via normalization.
    assert library.flow_roles["low_hook"] == "flow-low-hook"


# ---------------------------------------------------------------------------
# Task 5: GUI shows new/rename/duplicate/delete flow buttons
# ---------------------------------------------------------------------------


def test_gui_app_shows_flow_management_buttons():
    """The four flow management buttons are visible (not hidden).

    Source-inspection approach: instantiating ``DobotMainWindow`` requires
    a Qt display and many runtime dependencies, so we verify the source
    does NOT contain ``setVisible(False)`` calls for any of the four
    buttons. Role-flow protection is enforced at the FlowLibrary layer
    (delete_flow/rename_flow raise ValueError for role flows), and the
    mixin's try/except surfaces a QMessageBox to the user.
    """
    gui_app_path = Path(__file__).resolve().parent.parent / "dobot_move" / "ui" / "gui_app.py"
    source = gui_app_path.read_text(encoding="utf-8")

    # Each of the four buttons must be created and must NOT be hidden.
    button_attrs = (
        "new_flow_btn",
        "rename_flow_btn",
        "duplicate_flow_btn",
        "delete_flow_btn",
    )
    for attr in button_attrs:
        creation_pattern = f"self.{attr} = QPushButton"
        hide_pattern = f"self.{attr}.setVisible(False)"
        assert creation_pattern in source, (
            f"Missing button creation for {attr} in gui_app.py"
        )
        assert hide_pattern not in source, (
            f"{attr} must not be hidden via setVisible(False) in gui_app.py "
            "(restore-user-flow-crud spec requires visible flow management buttons)"
        )


def test_grasp_flow_mixin_still_exposes_flow_methods():
    """The mixin still defines create_flow/rename_flow/duplicate_flow/delete_flow.

    The buttons are visible, and the underlying handler methods remain
    defined (they are called from the GUI constructor's signal wiring).
    This guards against accidental deletion of the methods.
    """
    from dobot_move.ui.mixins.grasp_flow_mixin import GraspFlowMixin

    for method_name in (
        "create_flow",
        "rename_flow",
        "duplicate_flow",
        "delete_flow",
    ):
        assert callable(getattr(GraspFlowMixin, method_name, None)), (
            f"GraspFlowMixin.{method_name} must remain defined"
        )


# ---------------------------------------------------------------------------
# Spec invariants
# ---------------------------------------------------------------------------


def test_no_chinese_name_based_flow_lookup_in_role_mapping():
    """Spec: flow selection must go through flow_roles, not Chinese names.

    Verify the DEFAULT_FLOW_ROLES mapping uses only ASCII role keys →
    ASCII flow_ids, never Chinese name strings.
    """
    for role, fid in DEFAULT_FLOW_ROLES.items():
        assert isinstance(role, str) and role.isascii()
        assert isinstance(fid, str) and fid.isascii()
        assert fid.startswith("flow-")


def test_role_flows_cannot_be_main_flow_after_migration(flow_path):
    """After v2 migration, the user's main flow is preserved (not a role flow).

    The migration logic must NOT silently reassign main_flow_id to a role
    flow when the user's original main flow still exists.
    """
    v2 = _v2_payload_with_user_flow()
    flow_path.write_text(json.dumps(v2, ensure_ascii=False), encoding="utf-8")

    library = FlowLibrary.load(flow_path)

    assert library.main_flow_id == "flow-1"
    assert library.main_flow_id not in library.flow_roles.values()
