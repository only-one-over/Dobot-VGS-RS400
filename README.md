# Dobot-VGS-RS400

Vision-Guided System for Dobot CR Series Robots with Intel RealSense D400 Depth Cameras

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-green.svg)]()
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

基于 Python + PyQt6 的越疆 CR 系列机械臂视觉定位控制系统。集成双 RealSense 深度相机（D435i + D405）、YOLO 实例分割、ByteTrack 目标跟踪、3D 卡尔曼滤波、手眼标定、视觉伺服和力控圆弧，实现从目标识别到精准定位的全自动化流程。

## Table of Contents

- [Features](#features)
- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Usage](#usage)
- [Configuration](#configuration)
- [C++ Acceleration](#c-acceleration)
- [FAQ](#faq)
- [License](#license)

## Features

- 🎯 **Dual-Camera Collaboration** — D435i coarse positioning + D405 fine recognition (mask geometric center)
- 🔄 **Real-Time Tracking** — D435i low-fps (5fps) continuous recognition, real-time target position update
- 🧠 **YOLO Instance Segmentation** — YOLO11s-seg + ByteTrack multi-object tracking + 3D Kalman filter
- 📐 **Hand-Eye Calibration** — Independent calibration for D435i/D405 dual cameras
- 🎮 **Visual Servoing** — Iterative approach with adaptive gain, 2mm convergence threshold
- 💪 **Force-Controlled Arc** — ArcTrajectoryPlanner + ForceFeedbackMonitor + ForceArcController
- 🔌 **Modbus TCP** — Bidirectional communication, PC as Master/Server
- ⚡ **C++ Acceleration** — Optional dobot_core pybind11 module for 5-20x speedup with Python fallback

## Quick Start

### Prerequisites

- Python 3.10+ (3.12 recommended)
- Intel RealSense SDK 2.0
- CMake 3.15+ & C++17 compiler (optional, for C++ acceleration)

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/only-one-over/Dobot-VGS-RS400.git
cd Dobot-VGS-RS400

# 2. Create virtual environment & install dependencies
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux
source .venv/bin/activate
pip install -r requirements.txt

# 3. (Optional) Build C++ acceleration module
pip install pybind11 cmake
python build_cpp.py
```

### Verify Installation

```bash
python -c "import PyQt6, numpy, cv2, pyrealsense2, onnxruntime; print('All dependencies OK')"

# Optional: verify C++ module
python -c "import dobot_core; print('C++ module OK:', dir(dobot_core))"
```

## Architecture

```
┌─────────────────────────────────────────────────┐
│                   GUI (PyQt6)                    │
│           DobotMainWindow + 7 Mixins             │
├─────────┬──────────┬──────────┬─────────────────┤
│  Robot   │  Vision   │  Force   │   Modbus        │
│ Control  │  System   │  Arc     │   Comm          │
├─────────┼──────────┼──────────┼─────────────────┤
│DobotApi │VisionSys │ForceArc  │ ModbusServer    │
│Dashboard│ +Tracker │+FBMonitor│ ModbusClient    │
│Feedback │ +Kalman3D│+ArcPlanner│                │
├─────────┴──────────┴──────────┴─────────────────┤
│          dobot_core (C++ pybind11, optional)      │
│     transforms / nms / yolo (post-processing)     │
└─────────────────────────────────────────────────┘
```

### Core Modules

| Module | File | Description |
|--------|------|-------------|
| Main GUI | `gui_app.py` | PyQt6 main window with 7 Mixins |
| Robot Controller | `robot_controller.py` | Motion control, state management |
| Communication | `dobot_api.py` | TCP/IP Dashboard (29999) + Feedback (30004) |
| Vision System | `vision_system.py` | YOLO inference, object detection, 3D positioning |
| Object Tracking | `tracker.py` | ByteTrack multi-object tracking |
| 3D Filter | `kalman_filter_3d.py` | 6-state 3D Kalman filter |
| Depth Processing | `depth_processor.py` | 4-level RealSense depth filter chain |
| Hand-Eye Calibration | `hand_eye_calib.py` | Calibration matrix management |
| Coordinate Transform | `transform_utils.py` | euler2rot / pose2matrix |
| Visual Servo | `visual_servo_controller.py` | Iterative visual servo control |
| Force Arc | `force_arc_controller.py` | Force + arc trajectory combined control |
| Force Feedback | `force_feedback_monitor.py` | Force sensor monitoring thread |
| Arc Planner | `arc_trajectory_planner.py` | Arc waypoint generation |
| Battery Monitor | `battery_monitor.py` | CAN bus battery monitoring |
| Modbus Server | `modbus_server.py` | Modbus TCP Server |
| Modbus Client | `modbus_client.py` | Modbus TCP Client (cart) |
| Config Manager | `config_manager.py` | JSON config read/write |
| Workers | `workers.py` | Device init, status update threads |
| C++ Core | `cpp_core/` | pybind11 acceleration module |

### Hardware Requirements

| Device | Model | Notes |
|--------|-------|-------|
| Robot Arm | Dobot CR5 / CR10 / CRA series | TCP/IP protocol control |
| Mid-range Camera | Intel RealSense D435i | Coarse positioning, depth 0.5-2.2m |
| Close-range Camera | Intel RealSense D405 | Fine recognition, depth 0.07-0.8m |
| Force Sensor | Built-in 6-axis force sensor | Dobot FT series |
| Network | Ethernet | Robot IP default 192.168.1.50 |

## Usage

### Launch the Application

```bash
cd dobot_move
python gui_app.py
```

### First-Time Setup

1. **Connect Robot** — Enter robot IP in GUI, click "Connect"
2. **Enable Robot** — After connection, click "Enable"
3. **Hand-Eye Calibration** (if recalibration needed):
   - Switch to "Hand-Eye Calibration" tab
   - Enter tool point pose and camera origin pose on calibration board
   - Click "Calculate" to generate calibration matrix
4. **Connect Camera** — Click "Connect Camera", select D435i or D405
5. **Test Vision** — Click "Camera Test" to verify detection
6. **Run Grasp Flow** — Start automated grasp in "Grasp Flow" tab

### D435i Low-FPS Real-Time Recognition

In the Vision tab, D435i low-fps (5fps) continuous recognition is available:

1. Connect D435i camera
2. Click "Start" in the "D435i Low-FPS Recognition" area
3. System continuously detects at 5fps, updating `d435i` point coordinates in real-time
4. GUI displays current camera coords, end-effector coords, base coords
5. Click "Stop" to close recognition

### Grasp Flow

```
Photo Position → D435i Coarse Recognition → Move Above D435i Target
→ Visual Servo Approach → D405 Fine Recognition (Mask Geometric Center)
→ Calculate Target Point → Move to Target Position
→ Force-Controlled Arc (optional) → Lift → Place
```

## Configuration

### config.json

Configuration file located at `dobot_move/config.json`:

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `robot_ip` | string | Robot IP address | `"192.168.1.50"` |
| `photo_position` | float[6] | Photo position (x,y,z,rx,ry,rz) mm/deg | `[900.98, -403.82, 166.76, -83.92, 1.30, -89.06]` |
| `target_offset` | float[3] | Target offset (dx,dy,dz) mm | `[0, 0, 0]` |
| `calibration.D435i` | object | D435i hand-eye calibration params | See below |
| `calibration.D405` | object | D405 hand-eye calibration params | See below |
| `points` | object | Point table | See below |
| `cart_ip` | string | Cart IP address | `"192.168.5.2"` |
| `cart_port` | int | Cart Modbus port | `502` |
| `modbus_port` | int | Local Modbus server port | `502` |

#### Hand-Eye Calibration

Each camera's calibration data contains two fields:

```json
{
  "tool_base_calib_pose": [x, y, z, rx, ry, rz],
  "cam_base_calib_pose": [x, y, z, rx, ry, rz]
}
```

- `tool_base_calib_pose`: Tool point pose on calibration board relative to base
- `cam_base_calib_pose`: Camera origin pose relative to base

The system calculates the hand-eye matrix: `T_cam2gripper = inv(T_tool2base) @ T_cam2base`

#### Point Table

```json
{
  "d435i": {
    "coords": [x, y, z, rx, ry, rz],
    "is_relative": false,
    "relative_to": null,
    "offset": [0, 0, 0, 0, 0, 0],
    "is_default": true
  }
}
```

| Field | Description |
|-------|-------------|
| `coords` | Absolute coordinates (mm, deg) |
| `is_relative` | Whether this is a relative point |
| `relative_to` | Reference point name (for relative points) |
| `offset` | Relative offset |
| `is_default` | System default point (cannot be deleted) |

Two default points: `d435i` (D435i recognition target center) and `d405` (D405 recognition target center), automatically updated by the vision system.

## C++ Acceleration

### Module Structure

```
cpp_core/
├── CMakeLists.txt
├── include/dobot_core/
│   ├── transforms.h
│   ├── nms.h
│   └── yolo.h
└── src/
    ├── pybind_module.cpp
    ├── transforms.cpp
    ├── nms.cpp
    └── yolo.cpp
```

### API

```python
import dobot_core

# Coordinate transforms
R = dobot_core.transforms.euler2rot(rx, ry, rz, degree=True)  # → 3x3 numpy array
T = dobot_core.transforms.pose2matrix(x, y, z, rx, ry, rz)    # → 4x4 numpy array
p = dobot_core.transforms.transform_point(matrix, point)       # → 3D numpy array

# NMS
keep = dobot_core.nms.nms(boxes, scores, iou_threshold=0.5)   # → list[int]

# YOLOv8 post-processing
dets = dobot_core.yolo.postprocess_yolov8(outputs, original_size, scale,
       offset, new_size, num_classes, conf_threshold, iou_threshold)
masks = dobot_core.yolo.process_mask(protos, masks_in, bboxes, shape,
        scale, offset, new_size, threshold)
```

### Fallback

When `dobot_core` is unavailable (not compiled or unsupported platform), the program automatically falls back to pure Python implementation. No functionality is affected.

### Build

```bash
pip install pybind11 cmake
python build_cpp.py
```

## FAQ

### Missing dependency opencv-python
```bash
pip install opencv-python
```

### Camera connection failed
- Confirm RealSense camera is connected via USB
- Confirm Intel RealSense SDK 2.0 is installed
- Check `pyrealsense2` version matches SDK version
- Specify serial number when using multiple cameras

### Robot connection failed
- Confirm robot and PC are on the same network segment
- Check `robot_ip` in `config.json`
- Confirm robot is powered on and network is reachable (`ping 192.168.1.50`)

### C++ module build failed
- Confirm CMake 3.15+ and C++17 compiler are installed
- Windows requires Visual Studio Build Tools
- Not building C++ module does not affect usage — program falls back to Python

### YOLO model detection is poor
- Confirm `best.onnx` model file exists in `dobot_move/` directory
- Check lighting conditions, avoid strong reflections
- If changing detection target, retrain model and replace `best.onnx`
- Note: new model's class count and mask coefficient dimensions must match hardcoded values (1 class, 32 mask_coeff)

### Hand-eye calibration accuracy is insufficient
- Confirm tool point pose on calibration board is recorded accurately
- Check Euler angle convention (this project uses ZYX rotation order)
- Recommend multiple calibrations and averaging
- Calibration error should be < 5mm

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
