# -*- coding: utf-8 -*-
"""PR 4 — Recovery policy for production flow failures.

The :class:`RecoveryPolicy` decides whether the runtime's production
state machine may dispatch the error-recovery hook after a primary
flow has failed. The decision is based on:

* the structured :class:`~dobot_move.flow.flow_result.FlowResult` returned
  by :meth:`FlowExecutor.run` (in particular its ``recoverable`` flag
  and ``failure_kind``);
* the live robot controller state — connected, feedback health OK,
  ``RobotMode`` not in ``{9, 11}`` (急停 / 故障), and ``ErrorStatus == 0``.

This module is intentionally Qt-free (standard library only) so the
unattended runtime can import it without pulling in PySide6/PyQt6.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from ..flow.flow_result import FlowResult

logger = logging.getLogger(__name__)


# RobotMode values that indicate the robot is in a hard-fault state and
# must not be trusted with a recovery motion. Mirrors the Dobot CR-series
# feedback protocol:
#   9  = 急停 (emergency stop)
#   11 = 故障 (fault)
ROBOT_MODE_HARD_FAULT = frozenset({9, 11})


class RecoveryPolicy:
    """Decide whether an error-recovery hook may run after a primary failure.

    The policy is conservative: any doubt about robot health, feedback
    freshness, or the primary result's ``recoverable`` flag causes it to
    return ``False`` so the state machine falls straight through to the
    final error state (FLOW_ERROR / CAMERA_ERROR / ROBOT_ERROR).
    """

    def can_recover(
        self,
        result: Optional[FlowResult],
        controller: Any,
    ) -> bool:
        """Return ``True`` only when a recovery hook may be dispatched.

        Parameters
        ----------
        result:
            The :class:`FlowResult` produced by the failed primary flow.
            ``None`` is treated as non-recoverable.
        controller:
            The runtime's robot controller. Must expose
            ``is_connected`` / ``get_feedback_health()`` /
            ``get_motion_safety_state()``.
        """
        if result is None:
            return False
        if not result.recoverable:
            return False
        if controller is None:
            return False
        if not bool(getattr(controller, "is_connected", False)):
            return False

        # Feedback health — disconnected/stale feedback means we cannot
        # trust the robot's current pose, so recovery motion is unsafe.
        try:
            feedback = controller.get_feedback_health()
        except Exception:
            logger.exception("RecoveryPolicy: get_feedback_health raised; rejecting recovery")
            return False
        if not isinstance(feedback, dict) or feedback.get("health") != "ok":
            return False

        # Motion safety state — RobotMode in {9, 11} or any ErrorStatus
        # means the robot itself is in a fault state and must not move.
        try:
            safety = controller.get_motion_safety_state()
        except Exception:
            logger.exception("RecoveryPolicy: get_motion_safety_state raised; rejecting recovery")
            return False
        if safety is None:
            return False
        robot_mode = int(getattr(safety, "robot_mode", 0) or 0)
        if robot_mode in ROBOT_MODE_HARD_FAULT:
            return False
        error_status = int(getattr(safety, "error_status", 0) or 0)
        if error_status != 0:
            return False
        return True


__all__ = ["RecoveryPolicy", "ROBOT_MODE_HARD_FAULT"]
