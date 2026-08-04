"""Read-only vision diagnostics executed by the hardware-owning Runtime."""

from __future__ import annotations

import base64
import copy
import time
from typing import Any

import cv2
import numpy as np


def _encode_image(image: np.ndarray, extension: str, params=None) -> str:
    ok, encoded = cv2.imencode(extension, image, params or [])
    if not ok:
        raise RuntimeError(f"failed to encode {extension} image")
    return base64.b64encode(encoded.tobytes()).decode("ascii")


def _json_value(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def performance_snapshot(vision) -> dict[str, Any]:
    result = {}
    for scope, stats in copy.deepcopy(getattr(vision, "_perf_stats", {})).items():
        count = max(0, int(stats.get("count", 0)))
        totals = stats.get("totals", {})
        result[scope] = {
            "count": count,
            "average_ms": {
                key: (float(value) / count if count else 0.0)
                for key, value in totals.items()
            },
        }
    return result


def capture_vision_snapshot(
    vision,
    controller,
    *,
    camera_type: str,
    include_color: bool = True,
    include_depth: bool = False,
    include_mask: bool = True,
    run_detection: bool = True,
) -> dict[str, Any]:
    started = time.perf_counter()
    packet = vision.capture_numpy_packet(int(time.time() * 1000))
    capture_done = time.perf_counter()
    if packet is None:
        raise RuntimeError(f"{camera_type} did not return a frame")

    color = packet.color_image
    depth = packet.depth_image
    target = None
    position = None
    if run_detection:
        # 快照是一次性请求，必须每帧都跑完整检测；不能走 run_detection_tracked
        # （内部有 yolo_every_n 跳帧逻辑会把快照当作视频流的一帧计数）。
        # 这里直接用 run_detection 取 score 最高的检测，且不调 tracker.update，
        # 避免影响并发的连续视频流跟踪状态。
        detections = vision.run_detection(color)
        if detections:
            best_det = max(
                detections,
                key=lambda d: float(d.get("score", d.get("confidence", 0.0)) or 0.0),
            )
            target = {
                "bbox": best_det["bbox"],
                "score": best_det["score"],
                "mask": best_det.get("mask"),
                "class_id": best_det.get("class_id", 0),
                "class_name": best_det.get("class_name", "hook"),
                "predicted": False,
            }
        else:
            target = None
    inference_done = time.perf_counter()
    if target is not None:
        position = vision.calculate_object_position_smoothed(
            depth,
            color,
            target,
        )
    position_done = time.perf_counter()

    camera_coords = None
    raw_camera_coords = None
    end_coords = None
    base_coords = None
    robot_pose = None
    transform_error = ""
    if position:
        camera_coords = position.get("camera_coords")
        raw_camera_coords = position.get("raw_coords", camera_coords)
        try:
            end_coords = vision.convert_to_end_coords(camera_coords)
            robot_pose = controller.get_current_pose_fast(
                max_age=1.0,
                fallback=False,
            )
            if robot_pose:
                base_coords = vision.convert_to_base_coords(end_coords, robot_pose)
        except Exception as exc:
            transform_error = str(exc)
    transform_done = time.perf_counter()

    annotated = color.copy()
    mask = target.get("mask") if target else None
    if mask is not None:
        mask_array = np.asarray(mask)
        if mask_array.shape[:2] != annotated.shape[:2]:
            mask_array = cv2.resize(
                mask_array.astype(np.uint8),
                (annotated.shape[1], annotated.shape[0]),
                interpolation=cv2.INTER_NEAREST,
            )
        mask_bool = mask_array > 0
        overlay = annotated.copy()
        overlay[mask_bool] = (0, 200, 255)
        annotated = cv2.addWeighted(annotated, 0.7, overlay, 0.3, 0)
    if target and target.get("bbox") is not None:
        x1, y1, x2, y2 = [int(value) for value in target["bbox"]]
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)

    valid_depth = depth[depth > 0]
    result = {
        "camera_type": camera_type,
        "camera_ok": True,  # 走到这里说明 packet 非 None（None 会抛 RuntimeError）
        "inference_ok": (not run_detection) or (target is not None),
        "frame": {
            "width": int(color.shape[1]),
            "height": int(color.shape[0]),
            "timestamp": float(packet.timestamp),
        },
        "detection": (
            {
                "bbox": _json_value(target.get("bbox")),
                "track_id": _json_value(target.get("track_id")),
                "score": float(
                    target.get("score", target.get("confidence", 0.0)) or 0.0
                ),
                "class_id": _json_value(target.get("class_id")),
                "predicted": bool(target.get("predicted", False)),
                "mask_area_px": (
                    int(np.count_nonzero(np.asarray(mask) > 0))
                    if mask is not None
                    else 0
                ),
            }
            if target
            else None
        ),
        "coordinates": {
            "camera_mm": _json_value(camera_coords),
            "raw_camera_mm": _json_value(raw_camera_coords),
            "end_mm": _json_value(end_coords),
            "base_mm": _json_value(base_coords),
            "robot_pose": _json_value(robot_pose),
            "source": position.get("source") if position else None,
            "confidence": (
                float(position.get("confidence", 0.0)) if position else 0.0
            ),
            "transform_error": transform_error,
        },
        "calibration": {
            "camera_to_gripper": _json_value(
                getattr(vision, "T_cam2flange", None)
            ),
        },
        "depth": {
            "valid_pixels": int(valid_depth.size),
            "min_raw": int(valid_depth.min()) if valid_depth.size else None,
            "max_raw": int(valid_depth.max()) if valid_depth.size else None,
            "scale_m": float(getattr(vision, "depth_scale", 0.0)),
        },
        "timings_ms": {
            "capture": (capture_done - started) * 1000.0,
            "inference": (inference_done - capture_done) * 1000.0,
            "position": (position_done - inference_done) * 1000.0,
            "transform": (transform_done - position_done) * 1000.0,
            "total": (transform_done - started) * 1000.0,
        },
        "performance": performance_snapshot(vision),
        "provider": str(getattr(vision, "inference_provider", "")),
        "model_path": str(getattr(vision, "model_path", "")),
    }
    if include_color:
        result["color_jpeg_base64"] = _encode_image(
            annotated,
            ".jpg",
            [cv2.IMWRITE_JPEG_QUALITY, 85],
        )
    if include_depth:
        result["depth_png_base64"] = _encode_image(depth, ".png")
        if valid_depth.size:
            lower, upper = np.percentile(valid_depth, [2, 98])
            if upper <= lower:
                upper = lower + 1.0
            normalized_depth = np.clip(
                (depth.astype(np.float32) - lower) * 255.0 / (upper - lower),
                0,
                255,
            ).astype(np.uint8)
            normalized_depth[depth == 0] = 0
            depth_preview = cv2.applyColorMap(
                normalized_depth,
                cv2.COLORMAP_TURBO,
            )
            result["depth_preview_jpeg_base64"] = _encode_image(
                depth_preview,
                ".jpg",
                [cv2.IMWRITE_JPEG_QUALITY, 85],
            )
    if include_mask and mask is not None:
        mask_u8 = (np.asarray(mask) > 0).astype(np.uint8) * 255
        result["mask_png_base64"] = _encode_image(mask_u8, ".png")
    return _json_value(result)
