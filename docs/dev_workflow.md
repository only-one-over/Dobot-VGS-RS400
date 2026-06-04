# Development Workflow

## Install Dependencies

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

RealSense work also requires Intel RealSense SDK 2.0 installed outside Python. Native acceleration requires CMake, a C++17 compiler, and pybind11.

## Start the Project

Run the PyQt application:

```powershell
.\.venv\Scripts\activate
python dobot_move\gui_app.py
```

The app expects runtime config at `dobot_move/config.json`. Camera startup expects connected RealSense hardware and the ONNX model at `dobot_move/best.onnx`.

## Run Tests and Checks

Current test coverage is limited. Use targeted checks:

```powershell
python -m py_compile dobot_move\gui_app.py dobot_move\workers.py dobot_move\vision_system.py
python test_yolo26_bbox.py
```

Use `test_yolo26_bbox.py` only after confirming required model/input assumptions. TODO: Move test scripts into `tests/` and document fixtures.

## Build Native Acceleration

Preferred helper:

```powershell
pip install pybind11 cmake
python build_cpp.py
```

Alternative CMake path:

```powershell
cmake -S cpp_core -B cpp_core/build
cmake --build cpp_core/build --config Release
```

Verify:

```powershell
python -c "import dobot_core; print('C++ module OK:', dir(dobot_core))"
```

## Build or Package

The repository contains `DobotControl.spec`, indicating PyInstaller packaging support.

TODO: Confirm the current packaging command, required data files, model files, RealSense DLLs, and C++ extension placement before relying on packaged output.

## Commit Code

Recommended local flow:

```powershell
git status
python -m py_compile <touched-python-files>
git diff
git add <intended-files>
git commit -m "<short change summary>"
```

Do not include generated build directories, local virtual environments, or accidental runtime config changes unless intentionally part of the change.

## Common Troubleshooting

- Missing `pyrealsense2`: install Intel RealSense SDK first, then install Python package matching the local Python/SDK environment.
- `ModuleNotFoundError: dobot_core`: build native extension or rely on Python fallback.
- C++ import ABI error: rebuild with the same Python version used to run the app.
- Camera connection failure: check USB connection, RealSense SDK installation, serial selection, and camera availability in RealSense Viewer.
- Robot connection failure: check robot power, network segment, configured IP in `config.json`, Dashboard port, and TCP/IP mode.
- ONNX Runtime provider failure: CUDA provider may fail and CPU provider may be used; check logs before assuming model failure.
- Modbus failure: check port `502`, firewall, whether another process already owns the port, and cart/server IP settings.
- Garbled Chinese text: preserve UTF-8, avoid editor encodings such as GBK unless intentionally recovering existing text.

## Suggested Project Folders

Created/suggested for future hygiene:

- `tests/`: move focused regression tests here after fixture assumptions are clarified.
- `scripts/`: place repeatable maintenance/build/check scripts here.
- `README.md`: keep setup and operator quick-start current; move deeper engineering detail into `docs/`.
