"""Versioned publication of GUI drafts for the hardware-owning Runtime."""

from __future__ import annotations

import copy
import json
import os
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..config import config_manager
from ..flow.flow_library import FlowLibrary


PUBLICATION_SCHEMA_VERSION = 1


class PublicationError(ValueError):
    pass


class RuntimePublicationStore:
    """Keep editable files separate from the last Runtime-approved snapshot."""

    def __init__(
        self,
        path: Path | str,
        *,
        config_path: Path | str | None = None,
        flow_path: Path | str | None = None,
    ):
        self.path = Path(path)
        self.config_path = Path(config_path or config_manager.CONFIG_FILE)
        self.flow_path = Path(flow_path or config_manager.get_grasp_flow_file())
        self._lock = threading.RLock()
        self.load_error = ""
        self._active = self._load_existing_or_legacy()

    @staticmethod
    def _validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise PublicationError("publication root must be an object")
        if int(payload.get("schema_version", 0)) != PUBLICATION_SCHEMA_VERSION:
            raise PublicationError("unsupported publication schema")
        revision = str(payload.get("revision", "")).strip()
        config = payload.get("config")
        flow_payload = payload.get("flow_library")
        if not revision:
            raise PublicationError("publication revision is required")
        if not isinstance(config, dict):
            raise PublicationError("published config must be an object")
        library = FlowLibrary(flow_payload, path="published-flow.json")
        return {
            "schema_version": PUBLICATION_SCHEMA_VERSION,
            "revision": revision,
            "published_at": str(payload.get("published_at", "")),
            "config": copy.deepcopy(config),
            "flow_library": copy.deepcopy(library.payload),
        }

    def _read_drafts(self) -> tuple[dict[str, Any], FlowLibrary]:
        try:
            with open(self.config_path, "r", encoding="utf-8") as handle:
                config = json.load(handle)
        except Exception as exc:
            raise PublicationError(f"cannot read config draft: {exc}") from exc
        if not isinstance(config, dict):
            raise PublicationError("config draft root must be an object")
        try:
            library = FlowLibrary.load(self.flow_path, migrate=False)
        except Exception as exc:
            raise PublicationError(f"cannot read flow draft: {exc}") from exc
        return config, library

    def _legacy_snapshot(self) -> dict[str, Any]:
        config, library = self._read_drafts()
        return {
            "schema_version": PUBLICATION_SCHEMA_VERSION,
            "revision": "legacy-draft",
            "published_at": "",
            "config": copy.deepcopy(config),
            "flow_library": copy.deepcopy(library.payload),
        }

    def _load_existing_or_legacy(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._legacy_snapshot()
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                return self._validate_payload(json.load(handle))
        except Exception as exc:
            self.load_error = f"cannot load Runtime publication: {exc}"
            return self._legacy_snapshot()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._active)

    def status(self) -> dict[str, Any]:
        snapshot = self.snapshot()
        library = FlowLibrary(snapshot["flow_library"], path="published-flow.json")
        main_flow = library.get_main_flow()
        return {
            "revision": snapshot["revision"],
            "published_at": snapshot["published_at"],
            "main_flow_id": main_flow["id"],
            "main_flow_name": main_flow["name"],
        }

    def publish_drafts(
        self,
        validator: Callable[[dict[str, Any], FlowLibrary], list[str]] | None = None,
    ) -> dict[str, Any]:
        config, library = self._read_drafts()
        errors = list(validator(config, library) if validator else [])
        if errors:
            raise PublicationError("; ".join(str(item) for item in errors))
        now = datetime.now(timezone.utc)
        payload = {
            "schema_version": PUBLICATION_SCHEMA_VERSION,
            "revision": (
                now.strftime("%Y%m%dT%H%M%S.%fZ")
                + "-"
                + uuid.uuid4().hex[:8]
            ),
            "published_at": now.isoformat(),
            "config": copy.deepcopy(config),
            "flow_library": copy.deepcopy(library.payload),
        }
        normalized = self._validate_payload(payload)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            shutil.copy2(self.path, self.path.with_suffix(self.path.suffix + ".bak"))
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with open(temporary, "x", encoding="utf-8") as handle:
                json.dump(normalized, handle, indent=2, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
        with self._lock:
            self._active = normalized
        return self.snapshot()

    def reload_published(self) -> dict[str, Any]:
        if not self.path.exists():
            raise PublicationError("no published Runtime snapshot exists")
        with open(self.path, "r", encoding="utf-8") as handle:
            payload = self._validate_payload(json.load(handle))
        with self._lock:
            self._active = payload
        return self.snapshot()
