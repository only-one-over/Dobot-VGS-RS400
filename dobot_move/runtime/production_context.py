# -*- coding: utf-8 -*-
"""PR 3 — Production task context dataclass.

Holds the per-task state that must survive across PAUSED → RUNNING
transitions and 40004 mid-run changes. Created in
:meth:`DobotRuntimeAgent.start_new_task` when 40001=3 starts a new
production task, cleared after the task enters a terminal state.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProductionTaskContext:
    """Per-task production state.

    Attributes
    ----------
    task_id:
        Unique identifier generated at task creation; preserved across
        PAUSED → RUNNING transitions.
    hook_type:
        Latched 40004 value read at task start. Mid-run 40004 changes
        must NOT modify this field.
    primary_flow_id:
        flow_id resolved via ``ProductionFlowRouter.resolve_primary``
        based on ``hook_type``.
    state:
        Mirrors ``DobotRuntimeAgent.production_state`` (stored as a
        string for JSON-friendliness).
    started_at:
        ``time.time()`` at task creation.
    paused_at_step:
        Last known module index when the task was paused; ``None``
        outside PAUSED state.
    failure_code:
        Code set when the task transitions into a failure state.
    failure_kind:
        Category of failure (``"flow"`` / ``"robot"`` / ``"camera"``).
    """

    task_id: str
    hook_type: int
    primary_flow_id: str
    state: str
    started_at: float
    paused_at_step: Optional[int] = None
    failure_code: Optional[str] = None
    failure_kind: Optional[str] = None

    @classmethod
    def create(
        cls,
        *,
        hook_type: int,
        primary_flow_id: str,
        state: str,
    ) -> "ProductionTaskContext":
        """Factory that fills in the auto-generated fields."""
        return cls(
            task_id=uuid.uuid4().hex,
            hook_type=int(hook_type),
            primary_flow_id=str(primary_flow_id),
            state=str(state),
            started_at=time.time(),
        )


__all__ = ["ProductionTaskContext"]
