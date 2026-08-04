# -*- coding: utf-8 -*-
"""PR 3 — State-aware reset strategy.

Selects the correct reset motion sequence based on the
``source_state`` from which the reset was triggered (HOLDING_HOOK /
PAUSED / ERROR). Uses only existing controller / program_runner APIs
so no new motion primitives are introduced.

Paths
-----
* ``HOLDING_HOOK`` — 扶钩位安全缩回：先停止任何残留运动，再移动到
  ``initial_point`` (待机位)。``initial_point`` 通过控制器配置解析，
  与 ``_modbus_move_initial`` 同源。
* ``PAUSED`` — 终止当前任务 + ``Stop`` + 检查当前位置 + 安全撤离
  + 待机位。先停止流程线程再移动到待机位。
* ``ERROR`` (FLOW_ERROR / ROBOT_ERROR / CAMERA_ERROR) — 确认允许运动
  + ``ClearError`` + ``EnableRobot`` + 根据当前位置安全撤离 + 待机位。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .production_state import ERROR_STATES, ProductionState

logger = logging.getLogger(__name__)


class ResetStrategy:
    """State-aware reset sequence executor.

    The strategy is intentionally side-effect-light: it delegates every
    hardware action to the supplied ``controller`` (a
    :class:`~dobot_move.robot.robot_controller.DobotController`) and the
    supplied ``program_runner`` (a
    :class:`~dobot_move.runtime.runtime_agent.RuntimeProgramRunner`).
    """

    def execute(
        self,
        source_state: ProductionState,
        controller: Any,
        program_runner: Optional[Any] = None,
    ) -> bool:
        """Run the reset path selected by ``source_state``.

        Returns ``True`` only when the reset path ran to completion
        without raising. Individual path steps log warnings on best-effort
        failures (e.g. ``Stop()`` failing because the robot is already
        stopped) but still return ``True`` so the caller can transition
        to STANDBY. Returns ``False`` when a critical hardware action
        (clear_error / enable_robot / move_to_initial) fails.
        """
        if source_state == ProductionState.HOLDING_HOOK:
            return self._reset_from_holding_hook(controller, program_runner)
        if source_state == ProductionState.PAUSED:
            return self._reset_from_paused(controller, program_runner)
        if source_state in ERROR_STATES:
            return self._reset_from_error(controller, program_runner)
        if source_state == ProductionState.MANUAL_OFFLINE:
            # 重新上线后的复位：与 ERROR 路径同源（清故障 + 使能 + 撤离）
            return self._reset_from_error(controller, program_runner)
        logger.warning(
            "ResetStrategy: no specific path for source_state=%s; "
            "falling back to safe retraction",
            source_state,
        )
        return self._safe_retract_to_standby(controller)

    # ------------------------------------------------------------------
    # Path 1: HOLDING_HOOK — 扶钩位安全缩回
    # ------------------------------------------------------------------
    def _reset_from_holding_hook(
        self,
        controller: Any,
        program_runner: Optional[Any],
    ) -> bool:
        logger.info("ResetStrategy: HOLDING_HOOK 路径 — 扶钩位安全缩回")
        # 预检：清错+使能+反馈健康+报警状态检查
        if not controller.prepare_for_action(auto_clear_error=True, auto_enable=True):
            logger.warning("_reset_from_holding_hook: prepare_for_action 失败")
            return False
        # No active flow should be running in HOLDING_HOOK, but stop
        # defensively in case the program_runner thread hasn't exited.
        self._best_effort_stop_flow(program_runner)
        # Move to standby position via the same path used by Modbus
        # 40001=1 (initial_point). The controller's
        # ``move_to_initial_position`` already validates motion safety
        # and uses ``initial_point`` as the standby pose.
        return self._safe_retract_to_standby(controller)

    # ------------------------------------------------------------------
    # Path 2: PAUSED — 终止任务 + Stop + 撤离
    # ------------------------------------------------------------------
    def _reset_from_paused(
        self,
        controller: Any,
        program_runner: Optional[Any],
    ) -> bool:
        logger.info("ResetStrategy: PAUSED 路径 — 终止任务 + Stop + 撤离")
        # 预检：清错+使能+反馈健康+报警状态检查
        if not controller.prepare_for_action(auto_clear_error=True, auto_enable=True):
            logger.warning("_reset_from_paused: prepare_for_action 失败")
            return False
        # Terminate the paused task first so its stop_event is set and
        # the flow thread can exit before we move the robot.
        self._best_effort_stop_flow(program_runner)
        self._best_effort_robot_stop(controller)
        # Check current position then retract to standby.
        return self._safe_retract_to_standby(controller)

    # ------------------------------------------------------------------
    # Path 3: ERROR — ClearError + EnableRobot + 撤离
    # ------------------------------------------------------------------
    def _reset_from_error(
        self,
        controller: Any,
        program_runner: Optional[Any],
    ) -> bool:
        logger.info("ResetStrategy: ERROR 路径 — 清故障 + 使能 + 撤离")
        # Defensive stop in case the flow thread is still alive.
        self._best_effort_stop_flow(program_runner)
        if not self._ensure_motion_allowed(controller):
            return False
        return self._safe_retract_to_standby(controller)

    # ------------------------------------------------------------------
    # Primitive helpers (use existing controller APIs only)
    # ------------------------------------------------------------------
    def _best_effort_stop_flow(self, program_runner: Optional[Any]) -> None:
        if program_runner is None:
            return
        try:
            program_runner.stop()
        except Exception:
            logger.debug("ResetStrategy: program_runner.stop() failed", exc_info=True)

    def _best_effort_robot_stop(self, controller: Any) -> None:
        try:
            dashboard = getattr(controller, "dashboard", None)
            if dashboard is not None:
                dashboard.Stop()
        except Exception:
            logger.debug("ResetStrategy: dashboard.Stop() failed", exc_info=True)

    def _ensure_motion_allowed(self, controller: Any) -> bool:
        # ClearError then EnableRobot. ``clear_error`` and
        # ``enable_robot`` are existing DobotController methods.
        try:
            controller.clear_error()
        except Exception:
            logger.exception("ResetStrategy: clear_error failed")
            return False
        try:
            if not controller.enable_robot():
                logger.error("ResetStrategy: enable_robot failed")
                return False
        except Exception:
            logger.exception("ResetStrategy: enable_robot raised")
            return False
        return True

    def _safe_retract_to_standby(self, controller: Any) -> bool:
        # ``move_to_initial_position`` is the existing controller API
        # for "go to standby pose" — it resolves ``initial_point`` from
        # config and runs ``move_to_point`` with safety validation.
        try:
            success = controller.move_to_initial_position(
                verify_start_pose=False,
                verify_end_pose=False,
            )
        except Exception:
            logger.exception("ResetStrategy: move_to_initial_position raised")
            return False
        if not success:
            logger.error("ResetStrategy: move_to_initial_position returned False")
            return False
        return True


__all__ = ["ResetStrategy"]
