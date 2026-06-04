# Architecture

## Project Overview

This project is a Dobot vision-guided robot control application. It provides a PyQt6 desktop UI for connecting to a Dobot robot, operating dual RealSense cameras, detecting targets with YOLO/ONNX Runtime, converting camera detections into robot coordinates, editing grasp-flow modules, and executing motion/force-control workflows.

The repository also includes an optional C++/pybind11 module named `dobot_core` for hot vision paths such as YOLO post-processing, depth position calculation, non-maximum suppression, and coordinate transforms. The Python application should continue to work when the native module is not built.

## Directory Structure

```text
.
├── dobot_move/                  # Main Python package and PyQt6 application
│   ├── gui_app.py               # Main window, tabs, lifecycle, worker wiring
│   ├── main_control_panel.py    # Extracted main control panel widget
│   ├── gui_mixins/              # UI behavior mixins by feature area
│   ├── workers.py               # QThread workers for init, monitoring, flows, camera tests
│   ├── robot_controller.py      # Dobot motion/state orchestration
│   ├── dobot_api.py             # Dobot Dashboard/Feedback socket API wrappers
│   ├── vision_system.py         # RealSense, ONNX inference, tracking, 3D position
│   ├── config_manager.py        # Runtime JSON config service and point/calibration access
│   ├── ui_theme.py              # Shared PyQt palette and stylesheet helpers
│   └── config.json              # Runtime config, calibration, points, performance knobs
├── cpp_core/                    # Optional C++17 pybind11 acceleration module
├── docs/                        # Project documentation
├── build_cpp.py                 # Native extension build helper
├── requirements.txt             # Python dependencies
├── test_yolo26_bbox.py          # Current root-level vision regression test/script
└── DobotControl.spec            # PyInstaller packaging spec
```

## Module Responsibilities

- `gui_app.py`: owns the `QApplication` entrypoint, `DobotMainWindow`, tab composition, UI lifecycle, status refresh, and signal wiring.
- `main_control_panel.py`: provides the primary control widget for robot connection, camera connection, grasp execution, collision level, pause/resume, and error clearing.
- `gui_mixins/`: separates feature behavior for robot control, vision, Modbus, point management, force arc, grasp flow, and jog control.
- `workers.py`: runs slow or repeated work outside the UI thread, including device initialization, feedback monitoring, flow execution, camera test display, and D435i low-FPS recognition.
- `robot_controller.py`: coordinates Dobot Dashboard/Feedback APIs, motion commands, safety state, Modbus integration, force monitor state, and pose parsing.
- `vision_system.py`: owns camera startup, RealSense frame capture, ONNX model loading, YOLO post-processing, tracking, depth processing, smoothing, and coordinate conversion.
- `config_manager.py`: centralizes reads/writes for `dobot_move/config.json`, including robot/cart IPs, Modbus port, calibration, points, and hand-eye matrices.
- `cpp_core/`: mirrors selected Python vision math in native code for performance. It must preserve input/output contracts used by `vision_system.py`.

## Data Flow

1. User operates the PyQt6 UI in `DobotMainWindow`.
2. UI events call feature mixins or `MainControlPanel` signals.
3. Robot operations flow through `DobotController`, then into `DobotApiDashboard` and `DobotApiFeedBack`.
4. Camera operations create `VisionSystem` instances for D435i and/or D405.
5. `VisionSystem` captures RealSense frames, runs ONNX inference, tracks targets, estimates depth, and converts camera coordinates through hand-eye calibration.
6. Detected base coordinates update default points such as `d435i` and `d405` through `config_manager.py`.
7. `FlowThread` executes configured modules from `grasp_flow_modules.json`, resolving points and coordinating robot motion, vision detection, visual servoing, and force-control operations.
8. UI updates are returned through Qt signals to keep the main thread responsive.

## Dependencies

- Runtime Python dependencies are listed in `requirements.txt`.
- RealSense operation requires Intel RealSense SDK and compatible D435i/D405 devices.
- ONNX inference expects a model file at `dobot_move/best.onnx` according to `vision_system.py`.
- Robot control expects reachable Dobot Dashboard and Feedback ports; defaults in docs mention Dashboard `29999` and Feedback `30004`.
- Modbus defaults are stored in `config.json`, with typical TCP port `502`.
- C++ acceleration depends on CMake, a C++17 compiler, pybind11, and Python ABI compatibility.

## Extension Points

- Add new grasp-flow module types in `workers.FlowThread` and corresponding UI editing behavior in grasp-flow mixins.
- Add new point/config fields through `config_manager.py` with migration/default handling.
- Add camera-specific detection behavior by extending `VisionSystem` while preserving D435i/D405 role separation.
- Add C++ acceleration by exposing a compatible pybind11 function and guarding calls with Python fallback behavior.
- Extract additional UI panels from `gui_app.py` into focused widgets under `dobot_move/` or a future UI folder.

## Risk Points

- Robot motion is safety-critical. Incorrect coordinate conversion, calibration, units, or point resolution can cause unsafe motion.
- Existing Chinese text in several files appears mojibake-corrupted. Editing those files can make recovery harder unless encoding is handled carefully.
- `gui_app.py` remains large and still mixes UI composition, lifecycle, status, and some feature wiring.
- `config.json` is both runtime state and persisted configuration; concurrent writes from UI/worker paths can cause stale or lost updates.
- RealSense, ONNX Runtime, CUDA provider availability, Dobot network state, and C++ extension ABI are environment-sensitive.
- Root-level generated/build artifacts such as `build/`, `Release/`, and `.pyd` files can obscure source-only changes.

## Refactoring Suggestions

- Move remaining tab construction from `gui_app.py` into dedicated widgets, keeping `DobotMainWindow` as an assembler.
- Move flow execution logic from `workers.FlowThread` into a service with testable module handlers.
- Add config write debounce or a single save service to avoid direct writes from many UI paths.
- Move root-level `test_yolo26_bbox.py` into `tests/` after confirming expected fixtures and hardware/model assumptions.
- Add a packaging/build document for PyInstaller and native extension compatibility.
- TODO: Define a stable schema version for `config.json` and migration rules.
