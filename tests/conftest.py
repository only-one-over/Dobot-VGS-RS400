"""Shared test fixtures."""
import sys
import os

# Ensure dobot_move package is importable
_project_root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.abspath(_project_root))
