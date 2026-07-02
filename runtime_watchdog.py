#!/usr/bin/env python3
"""Compatibility launcher for ``python runtime_watchdog.py``."""

from dobot_move.runtime_watchdog import main


if __name__ == "__main__":
    raise SystemExit(main())
