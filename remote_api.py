#!/usr/bin/env python3
"""Compatibility launcher for ``python remote_api.py``."""

from dobot_move.remote_api.app import main


if __name__ == "__main__":
    raise SystemExit(main())
