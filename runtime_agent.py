#!/usr/bin/env python3
"""Compatibility launcher for ``python runtime_agent.py``."""

from dobot_move.runtime_agent import main


if __name__ == "__main__":
    raise SystemExit(main())
