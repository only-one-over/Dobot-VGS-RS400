# C++ Acceleration Guide

This project can accelerate the hottest vision paths with the `dobot_core`
pybind11 module:

- YOLO segmentation post-processing: bbox parsing, NMS, mask generation.
- Depth position calculation: mask centroid, depth fallback, camera coordinates.
- Coordinate transforms: Euler/matrix helpers already exposed by `dobot_core`.

If `dobot_core` cannot be imported, the Python implementation is used
automatically. The app should keep working, but vision latency will be higher.

## Build Requirements

- CMake 3.15 or newer
- A C++17 compiler
- Python development headers matching the Python used to run the app
- `pybind11`

On Windows, use the same Python environment that runs the GUI whenever possible.

## Build Commands

From the repository root:

```powershell
cmake -S cpp_core -B cpp_core/build
cmake --build cpp_core/build --config Release
```

The built extension is written to the repository root by `cpp_core/CMakeLists.txt`.
After building, the root directory should contain a platform-specific extension
such as `dobot_core.pyd`.

## Verify That C++ Is Enabled

Run this from the repository root with the app's Python:

```powershell
python - <<'PY'
import dobot_core
print("dobot_core loaded:", dobot_core.__doc__)
print("has yolo:", hasattr(dobot_core, "yolo"))
print("has depth:", hasattr(dobot_core, "depth"))
print("has transforms:", hasattr(dobot_core, "transforms"))
PY
```

The GUI imports `dobot_core` in `dobot_move/vision_system.py`. When import
succeeds, these paths are attempted first:

- `dobot_core.yolo.postprocess_yolov8`
- `dobot_core.yolo.postprocess_yolo26`
- `dobot_core.yolo.process_mask`
- `dobot_core.depth.calculate_object_position`

If a C++ call raises an exception, the code logs a debug fallback message and
uses the Python implementation for that operation.

## Depth Position Contract

`dobot_core.depth.calculate_object_position(...)` expects:

```python
calculate_object_position(
    depth_image,   # uint16 HxW RealSense depth image
    mask,          # uint8 HxW segmentation mask, valid pixels > 127
    bbox,          # (x1, y1, x2, y2) or None
    fx, fy, cx, cy,
    depth_scale,
    min_depth,
    max_depth,
)
```

It returns either `None` or:

```python
{
    "center_x": int,
    "center_y": int,
    "depth": float,                 # meters
    "camera_coords": (x, y, z),      # millimeters
}
```

The center point is the segmentation mask centroid, not the bbox center. If the
center depth is invalid, the C++ path computes the median valid depth inside the
bbox-limited mask region.

## Performance Verification

Run camera recognition and inspect these logs:

- `performance[detection]`
- `performance[depth_position]`
- `performance[camera_test_worker]`
- `performance[d435i_low_fps_worker]`

Expected improvements should appear mainly in:

- `postprocess` time inside `performance[detection]`
- `total` time inside `performance[depth_position]`
- worker `total` time when detections are present

## Fallback Test

To confirm Python fallback still works, temporarily rename the built extension
outside the app process, for example:

```powershell
Rename-Item .\dobot_core*.pyd dobot_core.disabled.pyd
```

Then start the app. It should still run, but the C++ acceleration paths will not
be available. Rename the file back after testing.

## Troubleshooting

- `ModuleNotFoundError: dobot_core`: build output is missing or not in the
  repository root / Python path.
- `ImportError` about Python DLL or ABI: rebuild with the same Python used to
  run the GUI.
- `pybind11_DIR` not found: install `pybind11` in the active Python environment
  or pass its CMake directory explicitly.
- C++ call falls back silently at info level: enable debug logging to see the
  specific fallback reason.
