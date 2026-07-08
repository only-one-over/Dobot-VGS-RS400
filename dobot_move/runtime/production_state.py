# -*- coding: utf-8 -*-
"""PR 3 — Production state machine enumeration and Modbus status mapping.

Defines :class:`ProductionState` (the runtime production state machine
states) and :data:`MODBUS_STATUS_MAP` (the mapping from a
:class:`ProductionState` to the value written into Modbus holding
register 40001).

Runtime components must remain Qt-free; this module intentionally
depends only on the Python standard library so it can be imported by
``runtime_agent.py`` without pulling in PySide6/PyQt6.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict


class ProductionState(str, Enum):
    """Production state machine states.

    Inheriting from ``str`` keeps the values JSON-serializable and
    friendly for log messages and IPC payloads.
    """

    MANUAL_OFFLINE = "manual_offline"
    IDLE = "idle"
    STANDBY = "standby"
    RUNNING = "running"
    PAUSED = "paused"
    HOLDING_HOOK = "holding_hook"
    RESETTING = "resetting"
    ERROR_RECOVERY = "error_recovery"
    FLOW_ERROR = "flow_error"
    ROBOT_ERROR = "robot_error"
    CAMERA_ERROR = "camera_error"


# Mapping from a :class:`ProductionState` to the value written into
# Modbus holding register 40001. Only states with a defined PLC-facing
# status code appear here. States without an explicit PLC signal
# (``MANUAL_OFFLINE`` / ``RESETTING`` / ``ERROR_RECOVERY``) are
# intentionally absent — callers must handle the ``KeyError`` or
# skip the 40001 update for those states.
MODBUS_STATUS_MAP: Dict[ProductionState, int] = {
    ProductionState.IDLE: 0,
    ProductionState.STANDBY: 2,
    ProductionState.RUNNING: 4,
    ProductionState.PAUSED: 0,
    ProductionState.HOLDING_HOOK: 5,
    ProductionState.FLOW_ERROR: 110,
    ProductionState.ROBOT_ERROR: 111,
    ProductionState.CAMERA_ERROR: 112,
}


# States considered "ERROR" for the ResetStrategy path selection.
ERROR_STATES = frozenset(
    {
        ProductionState.FLOW_ERROR,
        ProductionState.ROBOT_ERROR,
        ProductionState.CAMERA_ERROR,
    }
)


__all__ = ["ProductionState", "MODBUS_STATUS_MAP", "ERROR_STATES"]
