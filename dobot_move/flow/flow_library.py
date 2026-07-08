"""Versioned storage and selection helpers for editable robot flows."""

from __future__ import annotations

import copy
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from ..config.config_manager import get_grasp_flow_file


FLOW_SCHEMA_VERSION = 3
LEGACY_FLOW_ID = "flow-1"
SUPPORTED_CAMERA_TYPES = {"D435i", "D405"}

# Default role → flow_id mapping for the three fixed production flows.
DEFAULT_FLOW_ROLES: dict[str, str] = {
    "low_hook": "flow-low-hook",
    "high_hook": "flow-high-hook",
    "error_recovery": "flow-error-recovery",
}

# Display names for the three fixed role flows (used during migration
# when a role flow is missing and must be created).
ROLE_FLOW_NAMES: dict[str, str] = {
    "flow-low-hook": "低钩子提钩",
    "flow-high-hook": "高钩子提钩",
    "flow-error-recovery": "错误回钩",
}


def required_camera_types(modules: list[dict[str, Any]]) -> set[str]:
    required: set[str] = set()
    for module in modules:
        module_type = module.get("type")
        params = module.get("params") or {}
        if module_type == "camera":
            required.add(str(params.get("camera_type", "D435i")))
        elif module_type == "visual_servo":
            required.add("D405")
    return required & SUPPORTED_CAMERA_TYPES


class FlowLibrary:
    def __init__(self, payload: dict[str, Any], path: Path | str | None = None):
        self.path = Path(path or get_grasp_flow_file())
        # Auto-migrate pre-v3 payloads in-memory so callers that bypass
        # ``load()`` (e.g. RuntimePublication._read_drafts with
        # ``migrate=False``, or callers constructing from a published
        # snapshot) can still read legacy v2 data without writing to
        # disk. ``load()`` performs migration + save separately; here we
        # only normalize in-memory.
        if isinstance(payload, dict) and int(payload.get("schema_version", 0)) < FLOW_SCHEMA_VERSION:
            payload = FlowLibrary._migrate_to_v3(payload)
        self.payload = self._normalize_payload(payload)

    @classmethod
    def from_modules(
        cls,
        modules: list[dict[str, Any]],
        path: Path | str | None = None,
    ) -> "FlowLibrary":
        return cls(cls._legacy_payload(modules), path)

    @classmethod
    def load(
        cls,
        path: Path | str | None = None,
        default_modules: list[dict[str, Any]] | None = None,
        migrate: bool = True,
    ) -> "FlowLibrary":
        flow_path = Path(path or get_grasp_flow_file())
        if flow_path.exists():
            with open(flow_path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
        else:
            raw = copy.deepcopy(default_modules or [])

        migrated = isinstance(raw, list)
        if migrated:
            raw = cls._legacy_payload(raw)
        # Schema v2 → v3 auto-migration: ensure flow_roles and the three
        # fixed role flows exist while preserving user modules data.
        schema_migrated = False
        if migrate and isinstance(raw, dict):
            if int(raw.get("schema_version", 0)) < FLOW_SCHEMA_VERSION:
                raw = cls._migrate_to_v3(raw)
                schema_migrated = True
        library = cls(raw, flow_path)
        if migrate and (migrated or schema_migrated or not flow_path.exists()):
            library.save()
        return library

    @staticmethod
    def _migrate_to_v3(payload: dict[str, Any]) -> dict[str, Any]:
        """Migrate a pre-v3 payload to schema_version=3.

        - Adds the ``flow_roles`` mapping (default three-role mapping if
          missing or partial).
        - Ensures the three fixed role flows (flow-low-hook /
          flow-high-hook / flow-error-recovery) exist; creates empty
          modules flows for any that are missing.
        - Preserves existing flows and their modules data verbatim.
        - Repairs ``main_flow_id`` / ``last_edited_flow_id`` if they no
          longer point to existing flows.
        """
        if not isinstance(payload, dict):
            raise ValueError("流程库根节点必须是对象")
        payload = copy.deepcopy(payload)
        payload["schema_version"] = FLOW_SCHEMA_VERSION

        flows = payload.get("flows")
        if not isinstance(flows, list):
            flows = []
        payload["flows"] = flows

        existing_ids: set[str] = {
            str(f.get("id", "")).strip()
            for f in flows
            if isinstance(f, dict)
        }

        # flow_roles: keep user mapping, fill in any missing default roles.
        raw_roles = payload.get("flow_roles")
        flow_roles: dict[str, str] = {}
        if isinstance(raw_roles, dict):
            for role, fid in raw_roles.items():
                role_str = str(role).strip()
                fid_str = str(fid).strip()
                if role_str and fid_str:
                    flow_roles[role_str] = fid_str
        for role, fid in DEFAULT_FLOW_ROLES.items():
            flow_roles.setdefault(role, fid)
        payload["flow_roles"] = flow_roles

        # Ensure three fixed role flows exist; create empty ones if missing.
        for role_fid in DEFAULT_FLOW_ROLES.values():
            if role_fid not in existing_ids:
                flows.append(
                    {
                        "id": role_fid,
                        "name": ROLE_FLOW_NAMES.get(role_fid, role_fid),
                        "modules": [],
                    }
                )
                existing_ids.add(role_fid)

        # Repair main_flow_id / last_edited_flow_id if they point to
        # missing flows. Prefer the legacy main flow when still present;
        # otherwise fall back to flow-low-hook, then any first flow.
        main_flow_id = str(payload.get("main_flow_id", "")).strip()
        if main_flow_id not in existing_ids:
            if LEGACY_FLOW_ID in existing_ids:
                main_flow_id = LEGACY_FLOW_ID
            elif DEFAULT_FLOW_ROLES["low_hook"] in existing_ids:
                main_flow_id = DEFAULT_FLOW_ROLES["low_hook"]
            elif flows:
                main_flow_id = str(flows[0].get("id", "")).strip()
            else:
                main_flow_id = DEFAULT_FLOW_ROLES["low_hook"]
        payload["main_flow_id"] = main_flow_id

        last_edited_flow_id = str(payload.get("last_edited_flow_id", "")).strip()
        if last_edited_flow_id not in existing_ids:
            last_edited_flow_id = main_flow_id
        payload["last_edited_flow_id"] = last_edited_flow_id

        return payload

    @staticmethod
    def _legacy_payload(modules: list[dict[str, Any]]) -> dict[str, Any]:
        # Emitted as schema_version=2 so that ``load()`` routes through
        # ``_migrate_to_v3`` to inject ``flow_roles`` and the three fixed
        # role flows alongside the legacy flow.
        return {
            "schema_version": 2,
            "main_flow_id": LEGACY_FLOW_ID,
            "last_edited_flow_id": LEGACY_FLOW_ID,
            "flows": [
                {
                    "id": LEGACY_FLOW_ID,
                    "name": "流程 1",
                    "modules": copy.deepcopy(modules),
                }
            ],
        }

    @staticmethod
    def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("流程库根节点必须是对象")
        if int(payload.get("schema_version", 0)) != FLOW_SCHEMA_VERSION:
            raise ValueError(f"不支持的流程库版本: {payload.get('schema_version')}")
        raw_flows = payload.get("flows")
        if not isinstance(raw_flows, list) or not raw_flows:
            raise ValueError("流程库至少需要一个流程")

        flows = []
        ids: set[str] = set()
        names: set[str] = set()
        for raw_flow in raw_flows:
            if not isinstance(raw_flow, dict):
                raise ValueError("流程记录必须是对象")
            flow_id = str(raw_flow.get("id", "")).strip()
            name = str(raw_flow.get("name", "")).strip()
            modules = raw_flow.get("modules")
            if not flow_id or flow_id in ids:
                raise ValueError("流程 ID 不能为空且必须唯一")
            if not name or name in names:
                raise ValueError("流程名称不能为空且必须唯一")
            if not isinstance(modules, list):
                raise ValueError(f"流程 {name} 的 modules 必须是列表")
            ids.add(flow_id)
            names.add(name)
            flows.append(
                {
                    "id": flow_id,
                    "name": name,
                    "modules": copy.deepcopy(modules),
                }
            )

        main_flow_id = str(payload.get("main_flow_id", "")).strip()
        if main_flow_id not in ids:
            raise ValueError("main_flow_id 必须指向现有流程")
        last_edited_flow_id = str(payload.get("last_edited_flow_id", "")).strip()
        if last_edited_flow_id not in ids:
            last_edited_flow_id = main_flow_id

        # Validate flow_roles mapping (all role → flow_id must point to
        # existing flows). Default the three production roles if absent.
        raw_flow_roles = payload.get("flow_roles")
        flow_roles: dict[str, str] = {}
        if isinstance(raw_flow_roles, dict):
            for role, fid in raw_flow_roles.items():
                role_str = str(role).strip()
                fid_str = str(fid).strip()
                if not role_str or not fid_str:
                    continue
                if fid_str not in ids:
                    raise ValueError(
                        f"flow_roles 角色映射指向不存在的流程: {fid_str}"
                    )
                flow_roles[role_str] = fid_str
        for role, fid in DEFAULT_FLOW_ROLES.items():
            flow_roles.setdefault(role, fid)
        # Verify default role mappings still point to existing flows
        # (a user may have intentionally remapped them, but the target
        # must exist).
        for role, fid in flow_roles.items():
            if fid not in ids:
                raise ValueError(
                    f"flow_roles 角色 {role} 映射的流程不存在: {fid}"
                )

        return {
            "schema_version": FLOW_SCHEMA_VERSION,
            "main_flow_id": main_flow_id,
            "last_edited_flow_id": last_edited_flow_id,
            "flow_roles": flow_roles,
            "flows": flows,
        }

    @property
    def flows(self) -> list[dict[str, Any]]:
        return self.payload["flows"]

    @property
    def flow_roles(self) -> dict[str, str]:
        return self.payload.get("flow_roles", {})

    @property
    def main_flow_id(self) -> str:
        return self.payload["main_flow_id"]

    @property
    def last_edited_flow_id(self) -> str:
        return self.payload["last_edited_flow_id"]

    def get_flow(self, flow_id: str) -> dict[str, Any]:
        for flow in self.flows:
            if flow["id"] == flow_id:
                return flow
        raise KeyError(f"流程不存在: {flow_id}")

    def get_main_flow(self) -> dict[str, Any]:
        return self.get_flow(self.main_flow_id)

    def set_main_flow(self, flow_id: str) -> None:
        self.get_flow(flow_id)
        self.payload["main_flow_id"] = flow_id

    def set_last_edited_flow(self, flow_id: str) -> None:
        self.get_flow(flow_id)
        self.payload["last_edited_flow_id"] = flow_id

    def create_flow(
        self,
        name: str,
        modules: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        normalized_name = self._validate_new_name(name)
        flow = {
            "id": uuid.uuid4().hex,
            "name": normalized_name,
            "modules": copy.deepcopy(modules or []),
        }
        self.flows.append(flow)
        self.payload["last_edited_flow_id"] = flow["id"]
        return flow

    def rename_flow(self, flow_id: str, name: str) -> None:
        # Role flows (flow_id in flow_roles.values()) are locked: their
        # flow_id and role mapping cannot change. The display ``name``
        # field can still be edited in-place through other paths, but
        # rename_flow refuses to touch role flows to prevent accidental
        # role rebinding via the GUI rename dialog.
        if flow_id in self.flow_roles.values():
            raise ValueError("角色流程不可重命名")
        flow = self.get_flow(flow_id)
        normalized_name = self._validate_new_name(name, exclude_id=flow_id)
        flow["name"] = normalized_name

    def duplicate_flow(self, flow_id: str) -> dict[str, Any]:
        source = self.get_flow(flow_id)
        base_name = f"{source['name']} 副本"
        name = base_name
        suffix = 2
        existing_names = {flow["name"] for flow in self.flows}
        while name in existing_names:
            name = f"{base_name} {suffix}"
            suffix += 1
        return self.create_flow(name, source["modules"])

    def delete_flow(self, flow_id: str) -> None:
        # Role flows (flow_id in flow_roles.values()) are protected from
        # deletion to safeguard production continuity.
        if flow_id in self.flow_roles.values():
            raise ValueError("角色流程不可删除")
        if len(self.flows) <= 1:
            raise ValueError("至少需要保留一个流程")
        if flow_id == self.main_flow_id:
            raise ValueError("主流程不能删除，请先选择其他主流程")
        self.get_flow(flow_id)
        self.payload["flows"] = [
            flow for flow in self.flows if flow["id"] != flow_id
        ]
        if self.last_edited_flow_id == flow_id:
            self.payload["last_edited_flow_id"] = self.main_flow_id

    def _validate_new_name(self, name: str, exclude_id: str | None = None) -> str:
        normalized = str(name).strip()
        if not normalized:
            raise ValueError("流程名称不能为空")
        if len(normalized) > 40:
            raise ValueError("流程名称不能超过40个字符")
        for flow in self.flows:
            if flow["id"] != exclude_id and flow["name"] == normalized:
                raise ValueError("流程名称必须唯一")
        return normalized

    def snapshot_modules(self, flow_id: str | None = None) -> list[dict[str, Any]]:
        flow = self.get_flow(flow_id) if flow_id else self.get_main_flow()
        return copy.deepcopy(flow["modules"])

    def save(self) -> None:
        normalized = self._normalize_payload(self.payload)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            shutil.copy2(self.path, self.path.with_suffix(self.path.suffix + ".bak"))
        tmp_path = self.path.with_name(
            f".{self.path.name}.{uuid.uuid4().hex}.tmp"
        )
        try:
            with open(tmp_path, "x", encoding="utf-8") as handle:
                json.dump(normalized, handle, indent=2, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, self.path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
        self.payload = normalized
