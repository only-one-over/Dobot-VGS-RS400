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

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Union


class FailureKind(str, Enum):
    """Typed failure classification for FlowResult.

    Inherits from ``str`` so that ``FailureKind.CAMERA == "camera"`` remains
    ``True`` for backward compatibility with existing string comparisons and
    so the runtime can log/persist the value without import cycles.
    """

    VISION_PROCESS = "vision_process"
    ROBOT = "robot"
    CAMERA = "camera"
    FLOW = "flow"
    PROTOCOL = "protocol"


# Backward-compatible string aliases. Because ``FailureKind`` inherits from
# ``str``, ``FAILURE_KIND_CAMERA == "camera"`` and
# ``FAILURE_KIND_CAMERA == FailureKind.CAMERA`` both remain ``True``.
FAILURE_KIND_VISION_PROCESS = FailureKind.VISION_PROCESS
FAILURE_KIND_ROBOT = FailureKind.ROBOT
FAILURE_KIND_CAMERA = FailureKind.CAMERA
FAILURE_KIND_FLOW = FailureKind.FLOW
FAILURE_KIND_PROTOCOL = FailureKind.PROTOCOL


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
        A :class:`FailureKind` value classifying the failure. On success a
        ``FailureKind.FLOW`` placeholder is stored (success callers should
        consult :attr:`success` rather than :attr:`failure_kind`).
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
    failure_kind: FailureKind
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
            failure_kind=FailureKind.FLOW,
            recoverable=False,
        )

    @classmethod
    def failure(
        cls,
        code: str,
        message: str,
        failure_kind: Union[FailureKind, str],
        *,
        failed_module_index: Optional[int] = None,
        failed_module_name: Optional[str] = None,
        recoverable: bool = False,
    ) -> "FlowResult":
        """Build a failure result with the given fields.

        ``failure_kind`` accepts either a :class:`FailureKind` member or a
        plain ``str`` (matched by value) for backward compatibility with
        existing callers that still pass string literals. Unknown string
        values fall back to :attr:`FailureKind.FLOW` with a warning log.
        """
        if isinstance(failure_kind, FailureKind):
            kind = failure_kind
        else:
            try:
                kind = FailureKind(str(failure_kind))
            except ValueError:
                logging.getLogger(__name__).warning(
                    "Unknown failure_kind=%r; falling back to FailureKind.FLOW",
                    failure_kind,
                )
                kind = FailureKind.FLOW
        return cls(
            success=False,
            code=str(code),
            message=str(message),
            failure_kind=kind,
            failed_module_index=failed_module_index,
            failed_module_name=failed_module_name,
            recoverable=bool(recoverable),
        )


__all__ = [
    "FlowResult",
    "FailureKind",
    "FAILURE_KIND_VISION_PROCESS",
    "FAILURE_KIND_ROBOT",
    "FAILURE_KIND_CAMERA",
    "FAILURE_KIND_FLOW",
    "FAILURE_KIND_PROTOCOL",
]
