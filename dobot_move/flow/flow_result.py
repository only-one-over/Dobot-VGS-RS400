# -*- coding: utf-8 -*-
"""PR 4 — Structured flow execution result.

Replaces the boolean return value of :meth:`FlowExecutor.run` with a
dataclass that carries enough context for the runtime's recovery policy
to decide whether an error-recovery hook should be dispatched.

Runtime components must remain Qt-free; this module intentionally
depends only on the Python standard library so it can be imported by
``runtime_agent.py`` without pulling in PySide6/PyQt6.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# Recognised failure_kind values. Kept as plain strings (not an Enum) so
# the runtime can log/persist them without import cycles.
FAILURE_KIND_VISION_PROCESS = "vision_process"
FAILURE_KIND_ROBOT = "robot"
FAILURE_KIND_CAMERA = "camera"
FAILURE_KIND_FLOW = "flow"
FAILURE_KIND_PROTOCOL = "protocol"


@dataclass
class FlowResult:
    """Structured result of a single :meth:`FlowExecutor.run` invocation.

    Attributes
    ----------
    success:
        ``True`` when the flow ran to completion without failures.
    code:
        Short machine-readable code (e.g. ``"OK"``, ``"TARGET_LOST"``,
        ``"ROBOT_DISCONNECTED"``).
    message:
        Human-readable detail; empty on success.
    failure_kind:
        One of ``"vision_process"`` / ``"robot"`` / ``"camera"`` /
        ``"flow"`` / ``"protocol"``. Empty string on success.
    failed_module_index:
        0-based index of the module whose execution failed; ``None`` if
        the failure was not tied to a specific module or on success.
    failed_module_name:
        Name of the failed module; ``None`` on success.
    recoverable:
        ``True`` when the runtime's RecoveryPolicy may dispatch the
        error-recovery hook. Always ``False`` on success.
    """

    success: bool
    code: str
    message: str
    failure_kind: str
    failed_module_index: Optional[int] = None
    failed_module_name: Optional[str] = None
    recoverable: bool = False

    @classmethod
    def success_result(cls) -> "FlowResult":
        """Build a canonical success result."""
        return cls(
            success=True,
            code="OK",
            message="",
            failure_kind="",
            recoverable=False,
        )

    @classmethod
    def failure(
        cls,
        code: str,
        message: str,
        failure_kind: str,
        *,
        failed_module_index: Optional[int] = None,
        failed_module_name: Optional[str] = None,
        recoverable: bool = False,
    ) -> "FlowResult":
        """Build a failure result with the given fields."""
        return cls(
            success=False,
            code=str(code),
            message=str(message),
            failure_kind=str(failure_kind),
            failed_module_index=failed_module_index,
            failed_module_name=failed_module_name,
            recoverable=bool(recoverable),
        )


__all__ = [
    "FlowResult",
    "FAILURE_KIND_VISION_PROCESS",
    "FAILURE_KIND_ROBOT",
    "FAILURE_KIND_CAMERA",
    "FAILURE_KIND_FLOW",
    "FAILURE_KIND_PROTOCOL",
]
