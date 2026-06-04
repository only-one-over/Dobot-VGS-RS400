# Roadmap

## Current State

- Python/PyQt6 desktop app for Dobot robot control is present.
- Dual-camera vision flow supports D435i and D405 roles.
- YOLO/ONNX Runtime, tracking, depth processing, hand-eye calibration, visual servoing, force arc control, Modbus, and battery monitoring are represented in modules.
- Optional `dobot_core` C++ acceleration exists and is documented in `docs/cpp_acceleration.md`.
- Existing docs include README, porting guide, C++ acceleration notes, and UI/thread optimization notes.
- Project-level Codex rules and architecture/workflow/UI/roadmap docs have now been added.

## Short-Term Tasks

- Fix or recover mojibake-corrupted Chinese text in source comments, labels, and existing docs.
- Move `test_yolo26_bbox.py` into `tests/` after documenting its expected inputs and fixtures.
- Add targeted py_compile or smoke-test command to a script under `scripts/`.
- Document required hardware state before any manual robot/camera validation.
- Add a `README.md` section pointing to `docs/architecture.md`, `docs/ui_spec.md`, and `docs/dev_workflow.md`.

## Medium-Term Tasks

- Extract more UI construction from `gui_app.py` into dedicated widgets/panels.
- Split `FlowThread` behavior into testable grasp-flow module handlers.
- Introduce a config schema version and migration path for `dobot_move/config.json`.
- Add unit tests for point resolution, calibration matrix generation, pose parsing, and C++/Python fallback contracts.
- Add logging and status normalization so UI state colors do not depend on exact localized strings.
- Confirm PyInstaller packaging and document bundled model/DLL/native-extension requirements.

## Long-Term Tasks

- Define a plugin-like grasp-flow module registry for new motion/vision/force steps.
- Add simulation or dry-run mode for flow validation without live robot motion.
- Add structured telemetry for latency, detection confidence, robot state, and flow outcomes.
- Add hardware-in-the-loop validation checklist for release builds.
- Consider packaging the Python project with `pyproject.toml` once module layout and dependencies stabilize.

## Technical Debt

- `gui_app.py` remains too large and owns too many UI construction details.
- Some worker logic mixes orchestration, safety checks, and business rules in one thread class.
- Runtime config writes are spread across UI and flow paths.
- Encoding corruption makes maintenance risky and reduces operator readability.
- Tests are not yet organized under `tests/`.
- Build outputs and local environment artifacts are present in the working tree and should stay out of normal source changes.

## Priority Suggestions

1. Encoding recovery and UTF-8 policy enforcement.
2. Test folder organization plus basic non-hardware regression checks.
3. Config write centralization and schema versioning.
4. UI extraction from `gui_app.py`.
5. Flow execution service extraction.
6. Packaging and release checklist.
