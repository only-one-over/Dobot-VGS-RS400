# Project Rules for Codex

## Project Goal

This repository implements a vision-guided control system for Dobot CR-series robots with Intel RealSense D435i/D405 cameras. The application combines a PyQt6 desktop UI, Dobot TCP/IP control, RealSense depth processing, YOLO/ONNX vision inference, tracking, hand-eye calibration, Modbus communication, force-controlled arc motion, and an optional C++/pybind11 acceleration module.

## Technical Stack

- Language: Python 3.10+; Python 3.12 is currently used by the built extension artifact.
- UI: PyQt6 desktop application.
- Vision: Intel RealSense SDK via `pyrealsense2`, OpenCV, ONNX Runtime, NumPy, SciPy.
- Robot control: Dobot Dashboard and feedback TCP APIs.
- Communication: Modbus TCP via `pymodbus`, serial/CAN support via `minimalmodbus` and `python-can`.
- Native acceleration: C++17, CMake, pybind11, optional `dobot_core` extension.
- Project docs: Markdown under `docs/`.

Use Context7 MCP for current documentation whenever working with a library, framework, SDK, API, CLI tool, or cloud service. This includes PyQt6, RealSense, ONNX Runtime, CMake, pybind11, pymodbus, and Dobot SDK/API references when documentation is needed.

When running shell commands in this project, prefer prefixing commands with `rtk` where it works. For PowerShell built-ins, use `rtk powershell -NoProfile -Command "<command>"`.

## Architecture Principles

- Keep hardware-facing code isolated from UI layout code. UI should call controllers, workers, or services rather than opening sockets or camera pipelines directly.
- Keep long-running robot, camera, and inference operations off the Qt main thread.
- Preserve pure-Python fallback behavior when using `dobot_core`.
- Treat `dobot_move/config.json` as runtime configuration. Avoid broad rewrites or schema changes without migration handling.
- Keep camera-specific behavior explicit for D435i and D405 because depth ranges, hand-eye calibration, and task roles differ.
- Prefer small, focused modules over adding more behavior to `gui_app.py`.

## Code Standards

- Follow the existing Python style: small functions, explicit imports, logging through `logging.getLogger(__name__)`, and PyQt signals for thread/UI handoff.
- Use UTF-8 for new files. Existing Chinese text has visible mojibake in several files; do not worsen it. If editing affected text, preserve intent and note encoding risk.
- Do not block the Qt event loop with `time.sleep()` in UI paths; use `QTimer`, `QThread.msleep()`, or worker threads.
- Validate robot IPs, point names, config values, camera availability, and hardware connection state before executing motion.
- Prefer structured JSON access through `config_manager.py` over ad hoc file reads/writes.
- Keep C++ acceleration APIs compatible with Python fallback contracts.

## Modification Principles

- Read existing files before updating them.
- Do not delete files, move modules, or perform large refactors unless explicitly requested.
- Avoid changing robot motion behavior, calibration math, or hardware communication semantics unless the task requires it.
- Make changes narrowly around the requested behavior and document assumptions with `TODO` where the project state is uncertain.
- Keep generated/build artifacts out of source edits unless the user asks to rebuild or package.

## Testing Principles

- For Python syntax safety, run targeted `python -m py_compile` on touched modules.
- For C++ changes, build through `python build_cpp.py` or the documented CMake path and verify `import dobot_core`.
- For vision changes, test Python fallback and, when available, C++ acceleration paths.
- For UI changes, start the PyQt app only when the environment has the required display/hardware context; otherwise document that manual UI/hardware verification is required.
- Do not run motion, force-control, or robot enable commands as tests without explicit user approval and hardware readiness confirmation.

## Documentation Principles

- Keep `README.md` focused on user setup and quick start.
- Keep architecture details in `docs/architecture.md`.
- Keep UI conventions in `docs/ui_spec.md`.
- Keep repeatable development commands in `docs/dev_workflow.md`.
- Keep priorities and technical debt in `docs/roadmap.md`.
- When adding hardware assumptions, include concrete device names, ports, config keys, and known fallback behavior.

## Security and Safety Principles

- Never commit real robot credentials, private network details beyond documented defaults, API tokens, or proprietary model files unless already intentionally tracked.
- Treat robot movement as safety-critical. Require connection checks, error-state checks, speed limits, and stop paths.
- Avoid exposing Modbus or robot control ports to untrusted networks.
- Avoid logging sensitive production data. Logs may include robot state, pose, and IP addresses.
- Keep dependency installation commands explicit; avoid executing unknown external scripts.

## Forbidden Actions

- Do not delete or overwrite `dobot_move/config.json` without a backup/migration plan.
- Do not silently change calibration defaults, coordinate conventions, Euler order, or unit conventions.
- Do not remove Python fallback paths for `dobot_core`.
- Do not run destructive git commands such as `git reset --hard` or `git checkout --` unless explicitly requested.
- Do not move existing UI files into new folders just to match an ideal structure.
- Do not run live robot motion, gripper, force-control, or Modbus write operations without explicit approval.
