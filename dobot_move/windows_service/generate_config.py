"""CLI used by PowerShell deployment scripts to generate WinSW XML."""

from __future__ import annotations

import argparse
from pathlib import Path

from .service_config import (
    build_runtime_service_xml,
    build_watchdog_service_xml,
)


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--python-exe", type=Path, required=True)
    parser.add_argument("--token-path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "DobotRuntimeService.xml").write_text(
        build_runtime_service_xml(
            args.project_root,
            args.python_exe,
            args.token_path,
        ),
        encoding="utf-8",
    )
    (args.output_dir / "DobotRuntimeWatchdog.xml").write_text(
        build_watchdog_service_xml(
            args.project_root,
            args.python_exe,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
