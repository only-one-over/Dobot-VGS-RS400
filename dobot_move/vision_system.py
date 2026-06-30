#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
越疆机器人视觉处理模块
"""

import numpy as np
import pyrealsense2 as rs
try:
    import cv2
except ImportError:
    raise ImportError("缺少依赖 opencv-python，请执行: pip install opencv-python")
import os
import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)
from .config_manager import load_config, get_calibration, get_camera_handeye_matrix



from .transform_utils import euler2rot as _euler2rot, pose2matrix as _pose2matrix

try:
    import dobot_core
    DOBOT_CORE_AVAILABLE = True
except ImportError:
    DOBOT_CORE_AVAILABLE = False

from .tracker import BYTETracker, STrack
from .kalman_filter_3d import KalmanFilter3D
from .depth_processor import DepthProcessor


@dataclass
class FramePacket:
    """线程安全的帧数据包，不持有 pyrealsense2 frame 对象"""
    seq: int
    timestamp: float
    color_image: object  # numpy ndarray
    depth_image: object  # numpy ndarray


DEFAULT_PERFORMANCE_CONFIG = {
    "capture_timeout_ms": 300,
    "camera_test_detection_fps": 10,
    "camera_test_display_fps": 10,
    "performance_log_interval_frames": 30,
}


class VisionSystem:
    """视觉系统 - 用于识别物体并计算坐标"""

    def __init__(self, camera_type="D435i", serial_number=None,
                 enable_tracking=True, enable_kalman=True, enable_depth_filter=True):
        self.camera_type = camera_type
        self.serial_number = serial_number
        self.enable_tracking = enable_tracking
        self.enable_kalman = enable_kalman
        self.enable_depth_filter = enable_depth_filter
        config = load_config()
        performance_config = dict(DEFAULT_PERFORMANCE_CONFIG)
        performance_config.update(config.get("performance", {}))
        self.performance_config = performance_config
        self.capture_timeout_ms = int(performance_config.get("capture_timeout_ms", 300))
        self.performance_log_interval_frames = max(
            1,
            int(performance_config.get("performance_log_interval_frames", 30)),
        )
        self._perf_stats = {}
        self.camera_available = False
        self._consecutive_capture_failures = 0
        self._max_consecutive_failures = 5
        self.pipeline = None
        self.profile = None
        self.depth_scale = 0.001
        # 深度范围：优先从配置读取，无配置时使用默认值
        depth_range_config = config.get("camera", {}).get("depth_range", {})
        if camera_type == "D405":
            self.min_depth = float(depth_range_config.get("D405_min_depth", 0.07))
            self.max_depth = float(depth_range_config.get("D405_max_depth", 0.8))
        else:
            self.min_depth = float(depth_range_config.get("D435i_min_depth", 0.5))
            self.max_depth = float(depth_range_config.get("D435i_max_depth", 2.2))
        self.max_camera_z_mm = 500.0
        self.session = None
        self.inference_provider = "未检测"
        self.input_name = None
        self.input_shape = None
        self.class_names = ["hook"]
        self.num_classes = 1
        self.is_seg_model = True
        self.fx, self.fy = None, None
        self.cx, self.cy = None, None
        
        calib_data = get_calibration(camera_type)
        if not calib_data or "tool_base_calib_pose" not in calib_data:
            raise ValueError(f"未找到相机 {camera_type} 的标定数据")
        self.T_cam2gripper = get_camera_handeye_matrix(camera_type)
        logger.info(f"✅ 加载 {camera_type} 手眼标定矩阵 T_hand_eye:")
        logger.debug(np.round(self.T_cam2gripper, 4))
        
        logger.info("正在启动相机...")
        try:
            self.pipeline = rs.pipeline()
            self.config = rs.config()
            if serial_number:
                self.config.enable_device(serial_number)
                logger.info(f"📷 指定设备序列号: {serial_number}")
            self.config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
            self.config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)

            logger.debug("尝试启动相机...")
            self.profile = self.pipeline.start(self.config)
            if camera_type == "D405":
                depth_sensor = self.profile.get_device().first_depth_sensor()
                depth_sensor.set_option(rs.option.enable_auto_exposure, 1)
            device = self.profile.get_device()
            device_name = device.get_info(rs.camera_info.name)
            logger.info(f"📷 检测到相机: {device_name}")
            self.depth_sensor = self.profile.get_device().first_depth_sensor()
            self.depth_scale = self.depth_sensor.get_depth_scale()
            logger.debug(f"深度比例: {self.depth_scale}")

            self.align_to = rs.stream.color
            self.align = rs.align(self.align_to)

            # 获取相机内参
            depth_profile = self.profile.get_stream(rs.stream.depth).as_video_stream_profile()
            self.depth_intrin = depth_profile.get_intrinsics()
            color_profile = self.profile.get_stream(rs.stream.color).as_video_stream_profile()
            self.color_intrin = color_profile.get_intrinsics()

            self.fx, self.fy = self.color_intrin.fx, self.color_intrin.fy
            self.cx, self.cy = self.color_intrin.ppx, self.color_intrin.ppy
            logger.debug(f"✅ 相机内参(彩色): fx={self.fx:.2f}, fy={self.fy:.2f}, cx={self.cx:.2f}, cy={self.cy:.2f}")
            
            self.camera_available = True
            logger.info("✅ 相机初始化成功 (使用彩色相机内参)")
                
        except Exception as e:
            self.pipeline = None
            self.profile = None
            raise RuntimeError(f"相机初始化失败: {e}")
        
        # 实例分割模型初始化
        logger.info("正在加载实例分割模型...")
        self.model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "best.onnx")
        logger.debug(f"模型路径: {self.model_path}, 文件存在: {os.path.exists(self.model_path)}")

        # 创建ONNX Runtime session（优先GPU，回退CPU）
        import onnxruntime as ort
        # 预加载 CUDA/cuDNN DLL（onnxruntime-gpu[cuda,cudnn] 安装到 nvidia/ site-packages 子目录）
        if hasattr(ort, 'preload_dlls'):
            ort.preload_dlls(directory="")
        available_providers = ort.get_available_providers()
        self.inference_provider = "CPU"

        if 'CUDAExecutionProvider' in available_providers:
            self.session = ort.InferenceSession(self.model_path, providers=['CUDAExecutionProvider'])
            active_providers = self.session.get_providers()
            if 'CUDAExecutionProvider' in active_providers:
                self.inference_provider = "GPU (CUDA)"
                logger.info("实例分割模型加载成功（GPU CUDA 模式）")
            else:
                self.inference_provider = "CPU (CUDA回退)"
                logger.warning(
                    f"CUDAExecutionProvider 注册但未激活，已回退 CPU。活跃 providers: {active_providers}\n"
                    "请检查 CUDA 安装和 onnxruntime-gpu 版本兼容性"
                )
        else:
            self.session = ort.InferenceSession(self.model_path, providers=['CPUExecutionProvider'])
            self.inference_provider = "CPU"
            logger.warning(
                f"CUDA 不可用，使用 CPU 推理。当前可用 providers: {available_providers}\n"
                "如需 GPU 加速，请安装: pip uninstall onnxruntime && pip install onnxruntime-gpu"
            )

        # 获取模型输入输出信息
        self.input_name = self.session.get_inputs()[0].name
        self.input_shape = self.session.get_inputs()[0].shape
        logger.debug(f"模型输入: {self.input_name}, 形状: {self.input_shape}")

        self.warmup_onnx()

        output_infos = self.session.get_outputs()
        self.model_format = "yolov8"  # 默认格式
        if len(output_infos) >= 2:
            self.is_seg_model = True
            output_shape = output_infos[0].shape
            if len(output_shape) == 3:
                # YOLO26: [1, N, C] where N < C (e.g. [1, 300, 38])
                # YOLO11: [1, C, N] where C < N (e.g. [1, 37, 8400])
                dim1, dim2 = output_shape[1], output_shape[2]
                if dim1 < dim2:
                    # YOLO11 format: [1, C, N]
                    self.num_classes = dim1 - 4 - 32
                else:
                    # YOLO26 format: [1, N, C]
                    self.model_format = "yolo26"
                    self.num_classes = 1  # will be inferred from detections
            logger.debug(f"模型输出: seg模式, num_classes={self.num_classes}, model_format={self.model_format}")
        else:
            self.is_seg_model = False
            output_shape = output_infos[0].shape
            if len(output_shape) == 3:
                dim1, dim2 = output_shape[1], output_shape[2]
                if dim1 < dim2:
                    self.num_classes = dim1 - 4
                else:
                    self.model_format = "yolo26"
                    self.num_classes = 1
            logger.debug(f"模型输出: detect模式, num_classes={self.num_classes}, model_format={self.model_format}")

        if self.enable_tracking:
            self.tracker = BYTETracker(track_thresh=0.5, match_thresh=0.8, track_buffer=30)
            self.tracked_target_id = None
            logger.info("✅ ByteTrack 跟踪器已初始化")
        else:
            self.tracker = None
            self.tracked_target_id = None

        if self.enable_kalman:
            self.kalman_3d = KalmanFilter3D(dt=1.0/30, process_noise=1.0, measurement_noise=5.0)
            logger.info("✅ 3D 卡尔曼滤波器已初始化")
        else:
            self.kalman_3d = None

        if self.enable_depth_filter:
            self.depth_processor = DepthProcessor(
                min_depth=self.min_depth, max_depth=self.max_depth,
                depth_scale=self.depth_scale,
                enable_decimation=False,
                enable_spatial=True,
                enable_temporal=True,
                enable_hole_filling=True,
            )
            logger.info("✅ RealSense 深度滤波链已初始化")
        else:
            self.depth_processor = None

        self.last_valid_position = None

    def warmup_onnx(self):
        """ONNX session warmup：运行一次 dummy inference 消除 CUDA JIT 延迟"""
        if self.session is None:
            return
        try:
            dummy_input = np.zeros((1, 3, self.input_shape[2], self.input_shape[3]), dtype=np.float32)
            self.session.run(None, {self.input_name: dummy_input})
            logger.info("ONNX warmup 完成 (%s)", self.inference_provider)
        except Exception as e:
            logger.debug("ONNX warmup 跳过: %s", e)

    def _record_performance(self, scope, timings):
        stats = self._perf_stats.setdefault(
            scope,
            {"count": 0, "totals": {}, "last_log": 0.0},
        )
        stats["count"] += 1
        for key, value in timings.items():
            stats["totals"][key] = stats["totals"].get(key, 0.0) + value

        now = time.perf_counter()
        if (
            stats["count"] % self.performance_log_interval_frames != 0
            or now - stats["last_log"] < 3.0
        ):
            return

        count = max(1, stats["count"])
        parts = [
            f"{key}={total / count:.1f}ms"
            for key, total in sorted(stats["totals"].items())
        ]
        logger.info("performance[%s] frames=%s %s", scope, stats["count"], " ".join(parts))
        stats["count"] = 0
        stats["totals"] = {}
        stats["last_log"] = now

    def extract_mask_point_cloud_with_median_compensation(self, depth_image, mask, max_points=20000):
        mask_bool = mask > 127

        if not np.any(mask_bool):
            return np.array([]), {"compensated": False, "median_depth": 0, "valid_points": 0,
                                  "invalid_points": 0, "compensated_points": 0, "total_points_in_mask": 0}

        raw_depth_meters = depth_image.astype(np.float32) * self.depth_scale

        valid_depth_mask = (raw_depth_meters >= self.min_depth) & (raw_depth_meters <= self.max_depth) & (depth_image != 0)
        valid_depth_in_mask = valid_depth_mask & mask_bool

        invalid_depth_in_mask = mask_bool & (~valid_depth_mask)

        valid_points_count = np.sum(valid_depth_in_mask)
        invalid_points_count = np.sum(invalid_depth_in_mask)

        if valid_points_count > 0:
            valid_depths = raw_depth_meters[valid_depth_in_mask]
            median_depth = np.median(valid_depths)

            filled_depth = raw_depth_meters.copy()

            if invalid_points_count > 0:
                filled_depth[invalid_depth_in_mask] = median_depth

            y_coords, x_coords = np.where(mask_bool)

            if len(x_coords) > max_points * 2:
                indices = np.random.choice(len(x_coords), max_points * 2, replace=False)
                x_coords = x_coords[indices]
                y_coords = y_coords[indices]

            depth_values = filled_depth[y_coords, x_coords]

            valid_depth_mask_final = (depth_values >= self.min_depth) & (depth_values <= self.max_depth) & (depth_values > 0)

            if not np.any(valid_depth_mask_final):
                return np.array([]), {"compensated": True, "median_depth": median_depth, "valid_points": 0,
                                      "invalid_points": int(invalid_points_count), "compensated_points": int(np.sum(invalid_depth_in_mask)),
                                      "total_points_in_mask": int(np.sum(mask_bool))}

            x_coords = x_coords[valid_depth_mask_final]
            y_coords = y_coords[valid_depth_mask_final]
            depth_values = depth_values[valid_depth_mask_final]

            if len(x_coords) > max_points:
                indices = np.random.choice(len(x_coords), max_points, replace=False)
                x_coords = x_coords[indices]
                y_coords = y_coords[indices]
                depth_values = depth_values[indices]

            Z = depth_values
            X = (x_coords - self.cx) / self.fx * Z
            Y = (y_coords - self.cy) / self.fy * Z

            points = np.stack([X, Y, Z], axis=1)

            compensation_info = {
                "compensated": True,
                "median_depth": float(median_depth),
                "valid_points": int(valid_points_count),
                "invalid_points": int(invalid_points_count),
                "compensated_points": int(np.sum(invalid_depth_in_mask)),
                "total_points_in_mask": int(np.sum(mask_bool))
            }

            return points, compensation_info
        else:
            return np.array([]), {"compensated": False, "median_depth": 0, "valid_points": 0,
                                  "invalid_points": int(invalid_points_count), "compensated_points": 0,
                                  "total_points_in_mask": int(np.sum(mask_bool))}

    def filter_detections_by_area(self, detections, image_area, min_area_ratio=0.005):
        if len(detections) <= 1:
            return detections
        filtered_detections = []
        min_area = image_area * min_area_ratio
        for det in detections:
            if det['mask'] is not None:
                mask_area = np.sum(det['mask'] > 127)
                if mask_area >= min_area:
                    filtered_detections.append(det)
                else:
                    logger.debug(f"过滤掉面积过小的目标: {mask_area}像素 (小于{min_area:.0f}像素)")
            else:
                x1, y1, x2, y2 = det['bbox']
                bbox_area = (x2 - x1) * (y2 - y1)
                if bbox_area >= min_area:
                    filtered_detections.append(det)
                else:
                    logger.debug(f"过滤掉面积过小的目标(使用bbox): {bbox_area}像素 (小于{min_area:.0f}像素)")
        if len(filtered_detections) != len(detections):
            logger.debug(f"面积过滤: {len(detections)} -> {len(filtered_detections)} 个目标")
        return filtered_detections

    def calculate_object_position(self, depth_frame, color_frame, detections):
        start = time.perf_counter()
        if not detections or len(detections) == 0:
            logger.debug("no detection for position calculation")
            return None

        depth_image = depth_frame if isinstance(depth_frame, np.ndarray) else np.asanyarray(depth_frame.get_data())
        det = detections[0]
        mask = det.get('mask')

        if mask is None:
            logger.debug("position calculation skipped: mask is None")
            return None

        if DOBOT_CORE_AVAILABLE:
            try:
                cpp_start = time.perf_counter()
                cpp_result = dobot_core.depth.calculate_object_position(
                    depth_image,
                    mask,
                    det.get('bbox'),
                    float(self.fx),
                    float(self.fy),
                    float(self.cx),
                    float(self.cy),
                    float(self.depth_scale),
                    float(self.min_depth),
                    float(self.max_depth),
                )
                self._record_performance(
                    "depth_position",
                    {"total": (time.perf_counter() - cpp_start) * 1000.0},
                )
                if cpp_result is None:
                    return None
                result = dict(cpp_result)
                if "camera_coords" in result:
                    result["camera_coords"] = list(result["camera_coords"])
                return self._reject_camera_z_over_limit(result)
            except Exception as e:
                logger.debug("C++ depth position fallback: %s", e)

        mask_bool = mask > 127
        if not np.any(mask_bool):
            logger.debug("position calculation skipped: empty mask")
            return None

        y_coords, x_coords = np.where(mask_bool)
        if len(x_coords) == 0:
            logger.debug("position calculation skipped: no mask pixels")
            return None

        center_x = int(np.mean(x_coords))
        center_y = int(np.mean(y_coords))
        depth_value = depth_image[center_y, center_x]
        depth_meters = float(depth_value) * self.depth_scale
        compensation_info = {
            "compensated": False,
            "median_depth": 0,
            "valid_points": 0,
            "invalid_points": 0,
            "compensated_points": 0,
        }

        if depth_value == 0 or depth_meters < self.min_depth or depth_meters > self.max_depth:
            bbox = det.get('bbox')
            if bbox:
                x1, y1, x2, y2 = [int(v) for v in bbox]
                x1 = max(0, min(x1, depth_image.shape[1] - 1))
                x2 = max(x1 + 1, min(x2, depth_image.shape[1]))
                y1 = max(0, min(y1, depth_image.shape[0] - 1))
                y2 = max(y1 + 1, min(y2, depth_image.shape[0]))
                depth_region = depth_image[y1:y2, x1:x2]
                mask_region = mask_bool[y1:y2, x1:x2]
                valid_depths = depth_region[mask_region].astype(np.float32) * self.depth_scale
            else:
                valid_depths = depth_image[mask_bool].astype(np.float32) * self.depth_scale

            valid_depths = valid_depths[
                (valid_depths >= self.min_depth)
                & (valid_depths <= self.max_depth)
                & (valid_depths > 0)
            ]
            if len(valid_depths) > 0:
                depth_meters = float(np.median(valid_depths))
                compensation_info["median_depth"] = depth_meters
                compensation_info["valid_points"] = int(len(valid_depths))
            else:
                _, compensation_info = self.extract_mask_point_cloud_with_median_compensation(depth_image, mask)
                if compensation_info["compensated"] and compensation_info["median_depth"] > 0:
                    depth_meters = float(compensation_info["median_depth"])
                else:
                    logger.debug("position calculation skipped: no valid depth")
                    return None

        logger.debug(f"📏 计算深度: {depth_meters:.3f}米")

        if depth_meters < self.min_depth or depth_meters > self.max_depth:
            logger.debug(
                "depth out of range: %.3fm (valid %.3f-%.3fm)",
                depth_meters,
                self.min_depth,
                self.max_depth,
            )
            return None

        Z_mm = depth_meters * 1000.0
        X_mm = (center_x - self.cx) * Z_mm / self.fx
        Y_mm = (center_y - self.cy) * Z_mm / self.fy

        logger.debug(f"📍 原始相机坐标: X={X_mm:.2f}, Y={Y_mm:.2f}, Z={Z_mm:.2f} mm")
        self._record_performance(
            "depth_position",
            {"total": (time.perf_counter() - start) * 1000.0},
        )

        return self._reject_camera_z_over_limit({
            'center_x': center_x,
            'center_y': center_y,
            'depth': depth_meters,
            'camera_coords': [X_mm, Y_mm, Z_mm]
        })

    def _reject_camera_z_over_limit(self, result):
        if not result:
            return None
        coords = result.get("camera_coords") if isinstance(result, dict) else None
        if coords is None or len(coords) < 3:
            return result
        try:
            z_mm = float(coords[2])
        except (TypeError, ValueError):
            return result
        max_z_mm = float(getattr(self, "max_camera_z_mm", 500.0))
        if z_mm > max_z_mm:
            logger.debug("camera Z filtered: %.2fmm > %.2fmm", z_mm, max_z_mm)
            return None
        return result

    def convert_to_end_coords(self, camera_coords):
        """
        相机坐标 → 末端坐标
        使用手眼矩阵进行直接转换（相机 → 末端的变换）
        """
        if self.T_cam2gripper is None:
            raise ValueError("手眼标定矩阵未初始化，无法转换坐标")

        # 相机齐次坐标 [Xc,Yc,Zc,1]
        point_cam = np.array([camera_coords[0], camera_coords[1], camera_coords[2], 1.0])
        
        # 直接使用手眼矩阵进行转换（相机 → 末端）
        point_end = self.T_cam2gripper @ point_cam

        logger.debug(f"📍相机坐标: {camera_coords}")
        logger.debug(f"🔄末端坐标: {point_end[:3]}")
        return point_end[:3]

    def convert_to_base_coords(self, end_coords, robot_pose):
        """
        末端坐标 -> 基座坐标 (越疆官方标准 ZYX 旋转顺序)
        """
        # 末端坐标 (毫米)
        point_end = np.array([end_coords[0], end_coords[1], end_coords[2], 1.0])

        # 机器人当前位姿 (毫米, 度)
        x, y, z, rx, ry, rz = robot_pose

        # --- 构造工具到基座的齐次变换矩阵 ---
        T_tool2base = _pose2matrix(x, y, z, rx, ry, rz)

        # 最终基座坐标
        point_base = T_tool2base @ point_end
        
        logger.debug(f"🏠 计算得到基座坐标: {point_base[:3]}")
        
        return point_base[:3]

    def capture_frames(self):
        """
        捕获一帧深度和彩色图像
        """
        if not self.pipeline:
            logger.warning("相机不可用，无法捕获帧")
            self._consecutive_capture_failures += 1
            if self._consecutive_capture_failures >= self._max_consecutive_failures:
                self.camera_available = False
            return None, None
        
        try:
            start = time.perf_counter()
            frames = self.pipeline.wait_for_frames(timeout_ms=self.capture_timeout_ms)
            wait_done = time.perf_counter()
            aligned_frames = self.align.process(frames)
            align_done = time.perf_counter()
            depth_frame = aligned_frames.get_depth_frame()
            color_frame = aligned_frames.get_color_frame()

            if not depth_frame or not color_frame:
                self._consecutive_capture_failures += 1
                if self._consecutive_capture_failures >= self._max_consecutive_failures:
                    self.camera_available = False
                    logger.warning("连续 %d 次捕获帧失败，标记相机不可用", self._consecutive_capture_failures)
                return None, None

            if self.depth_processor is not None:
                depth_frame = self.depth_processor.process_frame(depth_frame)
            filter_done = time.perf_counter()
            self._record_performance(
                "capture",
                {
                    "wait": (wait_done - start) * 1000.0,
                    "align": (align_done - wait_done) * 1000.0,
                    "depth_filter": (filter_done - align_done) * 1000.0,
                    "total": (filter_done - start) * 1000.0,
                },
            )

            self._consecutive_capture_failures = 0

            return depth_frame, color_frame
        except Exception as e:
            self._consecutive_capture_failures += 1
            if self._consecutive_capture_failures >= self._max_consecutive_failures:
                self.camera_available = False
            logger.warning("捕获帧失败: %s", e)
            return None, None

    def capture_numpy_packet(self, seq):
        """采集帧并转为 numpy 副本，返回 FramePacket（线程安全，不持有 pyrealsense2 frame）"""
        depth_frame, color_frame = self.capture_frames()
        if depth_frame is None or color_frame is None:
            return None
        return FramePacket(
            seq=seq,
            timestamp=time.time(),
            color_image=np.asanyarray(color_frame.get_data()).copy(),
            depth_image=np.asanyarray(depth_frame.get_data()).copy(),
        )

    @property
    def is_available(self):
        """相机是否可用（已连接且 pipeline 存在）"""
        return self.camera_available and self.pipeline is not None

    def preprocess_image_yolov8(self, image, target_size=(640, 640)):
        """为YOLOv8模型预处理图像"""
        h, w = image.shape[:2]

        # 计算缩放比例，保持宽高比
        scale = min(target_size[0] / w, target_size[1] / h)
        new_w = int(w * scale)
        new_h = int(h * scale)

        # 调整图像大小
        resized = cv2.resize(image, (new_w, new_h))

        # 创建画布并填充
        canvas = np.full((target_size[1], target_size[0], 3), 114, dtype=np.uint8)
        y_offset = (target_size[1] - new_h) // 2
        x_offset = (target_size[0] - new_w) // 2
        canvas[y_offset:y_offset + new_h, x_offset:x_offset + new_w] = resized

        # 转换为RGB和浮点类型
        rgb_image = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
        input_tensor = rgb_image.astype(np.float32) / 255.0

        # 转换维度顺序: HWC -> NCHW
        input_tensor = np.transpose(input_tensor, (2, 0, 1))
        input_tensor = np.expand_dims(input_tensor, axis=0)

        return input_tensor, (w, h), scale, (x_offset, y_offset), (new_w, new_h)

    @staticmethod
    def _nms_py(boxes, scores, iou_threshold=0.5):
        if len(boxes) == 0:
            return []
        order = scores.argsort()[::-1]
        keep = []
        while order.size > 0:
            i = order[0]
            keep.append(i)
            if order.size == 1:
                break
            xx1 = np.maximum(boxes[i, 0], boxes[order[1:], 0])
            yy1 = np.maximum(boxes[i, 1], boxes[order[1:], 1])
            xx2 = np.minimum(boxes[i, 2], boxes[order[1:], 2])
            yy2 = np.minimum(boxes[i, 3], boxes[order[1:], 3])
            w = np.maximum(0.0, xx2 - xx1)
            h = np.maximum(0.0, yy2 - yy1)
            inter = w * h
            area_i = (boxes[i, 2] - boxes[i, 0]) * (boxes[i, 3] - boxes[i, 1])
            area_j = (boxes[order[1:], 2] - boxes[order[1:], 0]) * (boxes[order[1:], 3] - boxes[order[1:], 1])
            union = area_i + area_j - inter
            iou = inter / union
            inds = np.where(iou <= iou_threshold)[0]
            order = order[inds + 1]
        return keep

    def nms(self, boxes, scores, iou_threshold=0.5):
        if DOBOT_CORE_AVAILABLE:
            try:
                return dobot_core.nms.nms(boxes, scores, iou_threshold)
            except Exception:
                pass
        return self._nms_py(boxes, scores, iou_threshold)

    def _process_mask_py(self, protos, masks_in, bboxes, shape, scale, offset, new_size, threshold=0.5):
        # protos: (32, 160, 160) 原型掩码
        # masks_in: (n, 32) 掩码系数
        # bboxes: (n, 4) 边界框

        # 确保masks_in是二维数组
        if len(masks_in.shape) == 1:
            masks_in = masks_in.reshape(1, -1)

        n = masks_in.shape[0]  # 检测数量
        c, mh, mw = protos.shape

        # 将原型掩码展平为 (c, mh*mw)
        protos_flat = protos.reshape(c, -1)

        # 计算掩码: (n, 32) @ (32, mh*mw) = (n, mh*mw)
        masks = masks_in @ protos_flat

        # 应用sigmoid
        masks = 1 / (1 + np.exp(-masks))

        # 重塑为 (n, mh, mw)
        masks = masks.reshape(n, mh, mw)

        # 将掩码调整到原始图像大小
        masks_resized = []
        orig_h, orig_w = shape

        for i, (mask, bbox) in enumerate(zip(masks, bboxes)):
            x1, y1, x2, y2 = bbox

            # 确保掩码是numpy数组
            if not isinstance(mask, np.ndarray):
                mask = np.array(mask)

            # 将掩码从160x160缩放到640x640（模型输入尺寸）
            mask_640 = cv2.resize(mask, (640, 640))

            # 裁剪出原始图像区域（考虑填充）
            x_offset_mask, y_offset_mask = offset
            new_w, new_h = new_size

            # 裁剪缩放后的图像区域
            mask_cropped = mask_640[y_offset_mask:y_offset_mask + new_h, x_offset_mask:x_offset_mask + new_w]

            # 将裁剪后的掩码缩放到原始图像大小
            if mask_cropped.size > 0:
                mask_orig = cv2.resize(mask_cropped, (orig_w, orig_h))

                # 创建二值掩码
                binary_mask = (mask_orig > threshold).astype(np.uint8) * 255

                # 只保留边界框内的区域
                full_mask = np.zeros((orig_h, orig_w), dtype=np.uint8)

                # 确保坐标在图像范围内
                x1_clipped = max(0, min(orig_w, x1))
                y1_clipped = max(0, min(orig_h, y1))
                x2_clipped = max(0, min(orig_w, x2))
                y2_clipped = max(0, min(orig_h, y2))

                if x2_clipped > x1_clipped and y2_clipped > y1_clipped:
                    mask_region = binary_mask[y1_clipped:y2_clipped, x1_clipped:x2_clipped]
                    if mask_region.size > 0:
                        # 确保区域大小匹配
                        h_region = y2_clipped - y1_clipped
                        w_region = x2_clipped - x1_clipped
                        mask_resized = cv2.resize(mask_region, (w_region, h_region))
                        full_mask[y1_clipped:y2_clipped, x1_clipped:x2_clipped] = mask_resized

                masks_resized.append(full_mask)
            else:
                # 如果裁剪失败，创建空的掩码
                masks_resized.append(np.zeros((orig_h, orig_w), dtype=np.uint8))

        return masks_resized

    def process_mask(self, protos, masks_in, bboxes, shape, scale, offset, new_size, threshold=0.5):
        if DOBOT_CORE_AVAILABLE:
            try:
                return dobot_core.yolo.process_mask(protos, masks_in, bboxes, shape, scale, offset, new_size, threshold)
            except Exception:
                pass
        return self._process_mask_py(protos, masks_in, bboxes, shape, scale, offset, new_size, threshold)

    def _postprocess_yolov8_py(self, outputs, original_size, scale, offset, new_size, conf_threshold=0.25, iou_threshold=0.5):
        detections = []

        logger.debug(f"模型输出数量: {len(outputs)}")
        for i, out in enumerate(outputs):
            logger.debug(f"  输出{i}: 形状={out.shape}, 类型={out.dtype}")

        if len(outputs) < 2:
            proto = None
        else:
            proto = outputs[1]

        # 提取检测结果和原型掩码
        dets = outputs[0]

        # 获取检测结果的维度
        if len(dets.shape) == 3:
            dets = dets[0]  # 移除批次维度，形状 (37, 8400)

            # 转置: (37, 8400) -> (8400, 37)
            dets = dets.transpose(1, 0)

            # 收集所有候选框
            all_boxes = []
            all_scores = []
            all_masks_coeff = []

            for i, det in enumerate(dets):
                # 提取边界框坐标 (cx, cy, w, h) - 在640x640网格上
                cx, cy, w, h = det[0:4]

                # 提取类别分数
                cls_scores = det[4:4 + self.num_classes]

                # 找到最大分数
                max_score = np.max(cls_scores)
                class_id = np.argmax(cls_scores)

                if max_score > conf_threshold:
                    # 转换为原始图像坐标
                    orig_w, orig_h = original_size

                    # 将中心坐标从640x640转换到原始图像
                    cx_orig = (cx - offset[0]) / scale
                    cy_orig = (cy - offset[1]) / scale
                    w_orig = w / scale
                    h_orig = h / scale

                    # 计算边界框角点
                    x1 = int(cx_orig - w_orig / 2)
                    y1 = int(cy_orig - h_orig / 2)
                    x2 = int(cx_orig + w_orig / 2)
                    y2 = int(cy_orig + h_orig / 2)

                    # 确保在图像范围内
                    x1 = max(0, min(orig_w, x1))
                    y1 = max(0, min(orig_h, y1))
                    x2 = max(0, min(orig_w, x2))
                    y2 = max(0, min(orig_h, y2))

                    mask_coeff = det[4 + self.num_classes:4 + self.num_classes + 32] if self.is_seg_model else None

                    all_boxes.append([x1, y1, x2, y2])
                    all_scores.append(max_score)
                    all_masks_coeff.append(mask_coeff)

            # 如果没有检测到任何对象，直接返回
            if len(all_boxes) == 0:
                return detections

            # 应用非极大值抑制
            all_boxes = np.array(all_boxes)
            all_scores = np.array(all_scores)

            keep_indices = self.nms(all_boxes, all_scores, iou_threshold)

            logger.debug(f"NMS前: {len(all_boxes)} 个候选框, NMS后: {len(keep_indices)} 个检测结果")

            # 如果有原型掩码，处理掩码
            if len(keep_indices) > 0 and proto is not None and self.is_seg_model:
                # 获取保留的框和掩码系数
                boxes_nms = all_boxes[keep_indices]
                masks_coeff_nms = np.array([all_masks_coeff[i] for i in keep_indices])

                # 处理原型掩码维度
                if len(proto.shape) == 4:
                    proto = proto[0]  # 移除批次维度，形状变为 (32, 160, 160)

                # 生成精确掩码
                masks_nms = self.process_mask(proto, masks_coeff_nms, boxes_nms,
                                         (original_size[1], original_size[0]), scale, offset, new_size)
            else:
                masks_nms = []

            # 创建最终的检测结果
            for i, idx in enumerate(keep_indices):
                x1, y1, x2, y2 = all_boxes[idx]
                score = all_scores[idx]

                # 获取对应的掩码（如果有）
                mask = masks_nms[i] if i < len(masks_nms) else None

                # 检查掩码是否有效
                if mask is not None and np.sum(mask) == 0:
                    # 创建一个简单的矩形掩码作为备选
                    mask = np.zeros((original_size[1], original_size[0]), dtype=np.uint8)
                    mask[y1:y2, x1:x2] = 255

                detections.append({
                    'bbox': (int(x1), int(y1), int(x2), int(y2)),
                    'score': float(score),
                    'class_id': 0,
                    'class_name': 'hook',
                    'mask': mask
                })

        if len(detections) > 1:
            image_area = original_size[0] * original_size[1]
            detections = self.filter_detections_by_area(detections, image_area)

        return detections

    def _postprocess_yolo26_py(self, outputs, original_size, scale, offset, new_size, conf_threshold=0.25, iou_threshold=0.5):
        """YOLO26 end-to-end 后处理，输出格式 [1, 300, 38]"""
        detections = []
        proto = None

        if len(outputs) >= 2:
            proto = outputs[1]

        dets = outputs[0]

        if len(dets.shape) == 3:
            dets = dets[0]  # [300, 38]

        all_boxes = []
        all_scores = []
        all_masks_coeff = []

        for i in range(dets.shape[0]):
            det = dets[i]

            # YOLO26 format: x1,y1,x2,y2 + 1 score + 1 class_id + 32 mask_coeff
            x1_raw, y1_raw, x2_raw, y2_raw = det[0:4]
            score = det[4]
            class_id = int(det[5])

            if score < conf_threshold:
                continue

            # Convert from 640x640 to original image coordinates
            orig_w, orig_h = original_size
            x1_orig = (x1_raw - offset[0]) / scale
            y1_orig = (y1_raw - offset[1]) / scale
            x2_orig = (x2_raw - offset[0]) / scale
            y2_orig = (y2_raw - offset[1]) / scale

            x1 = int(max(0, min(orig_w, x1_orig)))
            y1 = int(max(0, min(orig_h, y1_orig)))
            x2 = int(max(0, min(orig_w, x2_orig)))
            y2 = int(max(0, min(orig_h, y2_orig)))

            mask_coeff = det[6:6 + 32] if self.is_seg_model else None

            all_boxes.append([x1, y1, x2, y2])
            all_scores.append(score)
            all_masks_coeff.append(mask_coeff)

        # No NMS needed for YOLO26 (end-to-end model)

        # Process masks
        if len(all_boxes) > 0 and proto is not None and self.is_seg_model:
            boxes_arr = np.array(all_boxes)
            masks_coeff_arr = np.array(all_masks_coeff)

            if len(proto.shape) == 4:
                proto = proto[0]  # [32, 160, 160]

            masks = self.process_mask(proto, masks_coeff_arr, boxes_arr,
                                      (original_size[1], original_size[0]), scale, offset, new_size)
        else:
            masks = []

        # Build detection results
        for i in range(len(all_boxes)):
            x1, y1, x2, y2 = all_boxes[i]
            score = all_scores[i]
            mask = masks[i] if i < len(masks) else None

            if mask is not None and np.sum(mask) == 0:
                mask = np.zeros((original_size[1], original_size[0]), dtype=np.uint8)
                mask[y1:y2, x1:x2] = 255

            detections.append({
                'bbox': (int(x1), int(y1), int(x2), int(y2)),
                'score': float(score),
                'mask': mask,
                'class_id': 0,
                'class_name': self.class_names[0] if self.class_names else 'object',
            })

        return detections

    def postprocess_yolov8(self, outputs, original_size, scale, offset, new_size, conf_threshold=0.25, iou_threshold=0.5):
        if self.model_format == "yolo26":
            if DOBOT_CORE_AVAILABLE:
                try:
                    result = dobot_core.yolo.postprocess_yolo26(outputs, original_size, scale, offset, new_size, self.num_classes, conf_threshold)
                    if isinstance(result, dict) and "detections" in result:
                        return result["detections"]
                    return result
                except Exception as e:
                    logger.debug("C++ YOLO26 postprocess fallback: %s", e)
            return self._postprocess_yolo26_py(outputs, original_size, scale, offset, new_size, conf_threshold, iou_threshold)
        else:
            if DOBOT_CORE_AVAILABLE:
                try:
                    return dobot_core.yolo.postprocess_yolov8(outputs, original_size, scale, offset, new_size, self.num_classes, conf_threshold, iou_threshold)
                except Exception as e:
                    logger.debug("C++ YOLOv8 postprocess fallback: %s", e)
            return self._postprocess_yolov8_py(outputs, original_size, scale, offset, new_size, conf_threshold, iou_threshold)

    def run_detection(self, image):
        """Run instance segmentation and record lightweight timing."""
        if self.session is None:
            return None

        try:
            start = time.perf_counter()
            input_tensor, original_size, scale, offset, new_size = self.preprocess_image_yolov8(image)
            preprocess_done = time.perf_counter()

            outputs = self.session.run(None, {self.input_name: input_tensor})
            inference_done = time.perf_counter()

            detections = self.postprocess_yolov8(outputs, original_size, scale, offset, new_size)
            postprocess_done = time.perf_counter()

            if detections is not None:
                logger.debug("detected %s target(s)", len(detections))

            self._record_performance(
                "detection",
                {
                    "preprocess": (preprocess_done - start) * 1000.0,
                    "inference": (inference_done - preprocess_done) * 1000.0,
                    "postprocess": (postprocess_done - inference_done) * 1000.0,
                    "total": (postprocess_done - start) * 1000.0,
                },
            )
            return detections

        except Exception as e:
            logger.error(f"检测出错: {e}")
            return None

    def run_detection_tracked(self, color_image):
        if self.tracker is None:
            return self.run_detection(color_image)

        detections = self.run_detection(color_image)
        if detections is None:
            detections = []

        det_list = []
        for det in detections:
            det_list.append({
                'bbox': det['bbox'],
                'score': det['score'],
                'mask': det.get('mask'),
                'class_id': det.get('class_id', 0),
            })

        img_size = (color_image.shape[1], color_image.shape[0])
        try:
            tracked_tracks = self.tracker.update(det_list, img_size)
        except Exception:
            logger.exception("目标跟踪更新失败，重置跟踪器并使用当前帧检测结果兜底")
            try:
                self.tracker.reset()
            except Exception:
                logger.exception("目标跟踪器重置失败")
            if detections:
                return max(detections, key=lambda det: float(det.get('score', det.get('confidence', 0.0)) or 0.0))
            return None

        target = self._select_target(tracked_tracks)
        return target

    def _select_target(self, tracks):
        if not tracks:
            if self.tracked_target_id is not None and self.kalman_3d is not None and self.kalman_3d.initialized:
                predicted = self.kalman_3d.predict()
                self.last_valid_position = predicted
                return {
                    'predicted': True,
                    'camera_coords': predicted.tolist(),
                    'confidence': self.kalman_3d.get_confidence(),
                }
            return None

        if self.tracked_target_id is not None:
            for t in tracks:
                if t.track_id == self.tracked_target_id:
                    return {
                        'predicted': False,
                        'track_id': t.track_id,
                        'bbox': tuple(t.bbox.astype(int)),
                        'score': t.score,
                        'mask': t.mask,
                        'class_id': t.class_id,
                        'class_name': 'hook',
                    }

        best = max(tracks, key=lambda t: t.score)
        self.tracked_target_id = best.track_id
        return {
            'predicted': False,
            'track_id': best.track_id,
            'bbox': tuple(best.bbox.astype(int)),
            'score': best.score,
            'mask': best.mask,
            'class_id': best.class_id,
            'class_name': 'hook',
        }

    def calculate_object_position_smoothed(self, depth_frame, color_frame, target):
        if target is None:
            return None
        detection_score = float(target.get('score', target.get('confidence', 0.0)) or 0.0)

        if target.get('predicted'):
            return self._reject_camera_z_over_limit({
                'camera_coords': target['camera_coords'],
                'smoothed': True,
                'confidence': target.get('confidence', 0.0),
                'source': 'kalman_predict',
            })

        detections_for_calc = [{
            'bbox': target['bbox'],
            'score': target['score'],
            'mask': target.get('mask'),
            'class_id': target.get('class_id', 0),
            'class_name': target.get('class_name', 'hook'),
        }]

        raw_result = self.calculate_object_position(depth_frame, color_frame, detections_for_calc)

        if raw_result is None:
            if self.kalman_3d is not None and self.kalman_3d.initialized:
                predicted = self.kalman_3d.predict()
                return self._reject_camera_z_over_limit({
                    'camera_coords': predicted.tolist(),
                    'smoothed': True,
                    'confidence': self.kalman_3d.get_confidence(),
                    'source': 'kalman_predict',
                })
            return None

        if self.kalman_3d is not None:
            observed = raw_result['camera_coords']
            smoothed = self.kalman_3d.update(observed)
            result = dict(raw_result)
            result['camera_coords'] = smoothed.tolist()
            result['smoothed'] = True
            result['confidence'] = detection_score
            result['detection_score'] = detection_score
            result['tracking_confidence'] = self.kalman_3d.get_confidence()
            result['source'] = 'kalman_smoothed'
            result['raw_coords'] = observed
            return self._reject_camera_z_over_limit(result)

        raw_result['smoothed'] = False
        raw_result['confidence'] = detection_score if detection_score > 0 else 1.0
        raw_result['detection_score'] = detection_score
        raw_result['tracking_confidence'] = 0.0
        raw_result['source'] = 'direct'
        return self._reject_camera_z_over_limit(raw_result)

    def reset_tracking(self):
        if self.tracker is not None:
            self.tracker.reset()
        if self.kalman_3d is not None:
            self.kalman_3d.reset()
        self.tracked_target_id = None
        self.last_valid_position = None

    def close(self):
        """
        关闭相机
        """
        if self.camera_available and self.pipeline:
            try:
                self.pipeline.stop()
                logger.info("✅ 相机已关闭")
            except Exception as e:
                logger.error(f"❌ 关闭相机失败: {e}")
            self.camera_available = False
            self.pipeline = None
