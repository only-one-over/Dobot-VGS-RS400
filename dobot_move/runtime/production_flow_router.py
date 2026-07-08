# -*- coding: utf-8 -*-
"""PR 3 — Production flow router.

Resolves a Modbus 40004 ``hook_type`` value to the corresponding
production flow id, using the ``flow_roles`` mapping published by
:class:`~dobot_move.flow.flow_library.FlowLibrary` (PR 2).

This module deliberately holds NO Flow ID literals — the mapping is
sourced from ``flow_roles`` so the user (or migration logic) can
rebind role → flow_id without code changes here.
"""

from __future__ import annotations

from typing import Dict, Mapping


class ProductionFlowRouter:
    """Resolve ``hook_type`` (40004) → ``flow_id`` via ``flow_roles``.

    Parameters
    ----------
    flow_roles:
        ``dict[str, str]`` mapping role names to flow ids. Expected
        keys: ``"low_hook"`` / ``"high_hook"`` / ``"error_recovery"``.
    """

    LOW_HOOK = 0
    HIGH_HOOK = 1

    def __init__(self, flow_roles: Mapping[str, str]):
        # Copy to a plain dict so callers can't mutate our internal
        # state by mutating the source mapping after construction.
        self.flow_roles: Dict[str, str] = dict(flow_roles)

    def resolve_primary(self, hook_type: int) -> str:
        """Resolve the primary production flow id for ``hook_type``.

        Parameters
        ----------
        hook_type:
            ``0`` → low_hook flow; ``1`` → high_hook flow.

        Returns
        -------
        str
            The flow_id from ``flow_roles``.

        Raises
        ------
        ValueError
            If ``hook_type`` is not ``0`` or ``1``, or the corresponding
            role key is missing from ``flow_roles``.
        """
        if hook_type == self.LOW_HOOK:
            role = "low_hook"
        elif hook_type == self.HIGH_HOOK:
            role = "high_hook"
        else:
            raise ValueError(f"Unsupported hook type: {hook_type}")
        try:
            return self.flow_roles[role]
        except KeyError as exc:
            raise ValueError(
                f"flow_roles missing required role '{role}'"
            ) from exc

    def resolve_recovery(self) -> str:
        """Resolve the error-recovery flow id."""
        try:
            return self.flow_roles["error_recovery"]
        except KeyError as exc:
            raise ValueError(
                "flow_roles missing required role 'error_recovery'"
            ) from exc


__all__ = ["ProductionFlowRouter"]
