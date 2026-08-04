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
import logging
import os
import queue
import threading
import time
from dataclasses import dataclass

from ..config.config_manager import (
    get_calibration,
    get_camera_config,
    get_camera_handeye_matrix,
    load_config,
    resolve_camera_model_path,
)



from ..robot.transform_utils import euler2rot as _euler2rot, pose2matrix as _pose2matrix

logger = logging.getLogger(__name__)
_CUDA_RUNTIME_FAILURE = None
_CUDA_DLL_HANDLES = []
# 预处理 UMat 可用性缓存：None=未检测, True/False=已检测并缓存
_PREPROCESS_USE_UMAT: bool | None = None


def _setup_nvidia_dll_path() -> None:
    """把 nvidia.* 包的 DLL 目录注册到 Windows DLL 搜索路径（仅 Windows）。

    新版 nvidia-cublas/nvidia-cufft 等包（无 cu13 后缀）把 DLL 合并到
    ``nvidia/cu13/bin/x86_64/`` 下，onnxruntime 默认不搜索该路径，导致
    ``import onnxruntime`` 时打印 "Failed to load cublas64_13.dll" 警告，
    虽不影响延迟加载的 CUDA EP 实际工作，但日志噪声大。

    本函数在模块加载时调用一次，使用 ``os.add_dll_directory``（Python 3.8+
    推荐方式，比修改 PATH 环境变量更可靠）注册 DLL 搜索目录，确保后续任何
    ``import onnxruntime`` 或 ``ctypes.CDLL`` 都能找到 nvidia DLL。

    失败时静默（nvidia 包未安装时 ``find_spec`` 返回 None，跳过即可），
    不阻塞模块导入。
    """
    if os.name != "nt":
        return
    try:
        import importlib.util
        from pathlib import Path

        nvidia_pkg_names = (
            "nvidia.cudnn",
            "nvidia.cu13",
            "nvidia.cuda_runtime",
            "nvidia.cublas",
            "nvidia.cufft",
            "nvidia.curand",
            "nvidia.cuda_nvrtc",
            "nvidia.nvjitlink",
        )
        existing_path = os.environ.get("PATH", "")
        added = 0
        for pkg_name in nvidia_pkg_names:
            pkg_spec = importlib.util.find_spec(pkg_name)
            if pkg_spec is None:
                continue
            pkg_locations = list(pkg_spec.submodule_search_locations or [])
            if not pkg_locations:
                continue
            pkg_root = Path(pkg_locations[0])
            for sub in ("bin", "bin/x86_64"):
                cand = pkg_root / sub
                if not cand.is_dir():
                    continue
                cand_str = str(cand.resolve())
                # 优先用 os.add_dll_directory（Python 3.8+ 推荐）
                try:
                    os.add_dll_directory(cand_str)
                    added += 1
                except (OSError, AttributeError):
                    # 回退到 PATH 修改（兼容旧 Python 或异常情况）
                    if cand_str not in existing_path:
                        existing_path = cand_str + os.pathsep + existing_path
        if existing_path != os.environ.get("PATH", ""):
            os.environ["PATH"] = existing_path
        if added:
            logger.debug("已注册 %d 个 nvidia DLL 搜索目录", added)
    except Exception as exc:
        logger.debug("设置 nvidia DLL 搜索路径失败（可忽略）: %s", exc)


# 模块加载时尽早设置 PATH，让后续 import onnxruntime 能找到 nvidia DLL。
_setup_nvidia_dll_path()


def _detect_umat_available() -> bool:
    """检测当前 OpenCV 环境是否可用 UMat（OpenCL/Vulkan 后端）执行 GPU 加速预处理。

    UMat 能把 preprocess_image_yolov8 中的 resize/cvtColor/画布填充搬到 GPU
    执行，降低 CPU 开销。本函数在首次调用 preprocess_image_yolov8 时被调用
    一次，结果缓存到模块级 ``_PREPROCESS_USE_UMAT``，避免重复检测开销。

    检测方式：构造一张 16x16 的零图，依次尝试转 UMat、resize、``.get()``
    转回 ndarray，任一步抛异常即视为 UMat 不可用（返回 False）。
    """
    try:
        test_mat = cv2.UMat(np.zeros((16, 16, 3), np.uint8))
        resized = cv2.resize(test_mat, (8, 8))
        _ = resized.get()
        return True
    except Exception:
        return False


def preload_onnx_runtime_dlls(ort) -> bool:
    """Preload ONNX Runtime dependencies, including a cuDNN 9 Windows sublibrary.

    返回 True 表示 DLL 预加载成功（或非 Windows 平台），False 表示 cuDNN
    Tensor IR 子库加载失败，调用方应跳过 CUDA 分支直接走 CPU。
    """
    if hasattr(ort, "preload_dlls"):
        try:
            ort.preload_dlls(directory="")
        except Exception as exc:
            logger.warning("ort.preload_dlls 调用失败: %s", exc)
    if os.name != "nt":
        return True

    try:
        import ctypes
        import importlib.util
        from pathlib import Path

        # nvidia DLL 目录已由模块级 _setup_nvidia_dll_path() 加入 PATH，
        # 此处无需重复设置。

        spec = importlib.util.find_spec("nvidia.cudnn")
        if spec is None:
            logger.warning("nvidia.cudnn 包未安装，跳过 cuDNN Tensor IR 子库预加载")
            return False
        locations = list(spec.submodule_search_locations or [])
        if not locations:
            logger.warning(
                "nvidia.cudnn 包缺少子模块搜索路径，跳过 cuDNN Tensor IR 子库预加载"
            )
            return False
        tensor_ir_path = (
            Path(locations[0]) / "bin" / "cudnn_engines_tensor_ir64_9.dll"
        )
        if not tensor_ir_path.is_file():
            logger.warning(
                "cuDNN Tensor IR 子库文件不存在: %s", tensor_ir_path,
            )
            return False
        resolved = str(tensor_ir_path.resolve())
        already_loaded = any(
            getattr(handle, "_name", None) == resolved
            for handle in _CUDA_DLL_HANDLES
        )
        if not already_loaded:
            _CUDA_DLL_HANDLES.append(ctypes.CDLL(resolved))
            logger.debug("已预加载 cuDNN Tensor IR 子库: %s", resolved)

        # 新增：检查其他 CUDA 依赖（cudart / cublas / cublasLt / cufft）
        # onnxruntime-gpu CUDA EP 还依赖 cudart64_*.dll、cublas64_*.dll、
        # cublasLt64_*.dll、cufft64_*.dll，缺失任一都会导致 CUDA 退回 CPU。
        #
        # 兼容两种 nvidia 包目录结构：
        # 1. 旧包（带 cu12 后缀，如 nvidia-cublas-cu12）：
        #    nvidia/cublas/bin/cublas64_12.dll
        #    nvidia/cuda_runtime/bin/cudart64_12.dll
        #    nvidia/cufft/bin/cufft64_*.dll
        # 2. 新包（无后缀，如 nvidia-cublas）合并到 nvidia.cu13 命名空间：
        #    nvidia/cu13/bin/x86_64/cublas64_13.dll
        #    nvidia/cu13/bin/x86_64/cudart64_13.dll
        #    nvidia/cu13/bin/x86_64/cufft64_12.dll
        #
        # 每个 DLL 在多个候选包/子目录中查找，命中即视为已就绪。
        _CUDA_DEPS = (
            # (dll_prefix, (候选包名列表), (候选子目录列表))
            ("cudart64", ("nvidia.cuda_runtime", "nvidia.cu13"), ("bin", "bin/x86_64")),
            ("cublas64", ("nvidia.cublas", "nvidia.cu13"), ("bin", "bin/x86_64")),
            ("cublasLt64", ("nvidia.cublas", "nvidia.cu13"), ("bin", "bin/x86_64")),
            ("cufft64", ("nvidia.cufft", "nvidia.cu13"), ("bin", "bin/x86_64")),
        )
        missing = []
        for dll_prefix, pkg_candidates, subdirs in _CUDA_DEPS:
            found = False
            for pkg_name in pkg_candidates:
                if found:
                    break
                pkg_spec = importlib.util.find_spec(pkg_name)
                if pkg_spec is None:
                    continue
                pkg_locations = list(pkg_spec.submodule_search_locations or [])
                if not pkg_locations:
                    continue
                for subdir in subdirs:
                    bin_dir = Path(pkg_locations[0]) / subdir
                    if not bin_dir.is_dir():
                        continue
                    if list(bin_dir.glob(f"{dll_prefix}*.dll")):
                        found = True
                        break
            if not found:
                missing.append(
                    f"{dll_prefix}*.dll "
                    f"(在候选包 {pkg_candidates} 的 {subdirs}/ 目录中均未找到)"
                )

        if missing:
            for m in missing:
                logger.warning(
                    "CUDA 依赖缺失: %s，请运行 "
                    "`pip install --force-reinstall onnxruntime-gpu[cuda,cudnn]`",
                    m,
                )
            return False
        return True
    except Exception as exc:
        logger.warning("预加载 cuDNN Tensor IR 子库失败，将通过真实推理检测: %s", exc)
        return False

try:
    import dobot_core
    DOBOT_CORE_AVAILABLE = True
except ImportError:
    DOBOT_CORE_AVAILABLE = False

from ..vision.tracker import BYTETracker, STrack
from ..vision.kalman_filter_3d import KalmanFilter3D
from ..vision.depth_processor import DepthProcessor


@dataclass
class FramePacket:
    """线程安全的帧数据包，不持有 pyrealsense2 frame 对象"""
    seq: int
    timestamp: float
    color_image: object  # numpy ndarray
    depth_image: object  # numpy ndarray
    capture_time: float = 0.0  # perf_counter 时间戳，记录 wait_for_frames 返回时刻
    frame_timestamp_ms: float = 0.0  # RealSense 原始帧时间戳 (ms)


DEFAULT_PERFORMANCE_CONFIG = {
    "capture_timeout_ms": 300,
    "camera_test_detection_fps": 10,
    "camera_test_display_fps": 10,
    "performance_log_interval_frames": 30,
}


def resolve_max_camera_z_mm(camera_type, config_dict):
    """Resolve the camera Z-axis limit (mm) for filtering detected objects.

    Priority:
    1. Explicit ``camera.max_camera_z_mm`` in config (optional key).
    2. Camera-type defaults matching the depth sensor max_depth:
       - D435i -> 2200.0 mm (max_depth=2.2m)
       - D405  -> 800.0 mm  (max_depth=0.8m)
    3. Safe fallback 2200.0 mm for unknown camera types.
    """
    camera_config = {}
    if isinstance(config_dict, dict):
        camera_config = config_dict.get("camera", {}) or {}
    max_z_cfg = camera_config.get("max_camera_z_mm", None) if isinstance(camera_config, dict) else None
    if max_z_cfg is not None:
        return float(max_z_cfg)
    if camera_type == "D405":
        return 800.0
    # D435i and any unknown camera type fall back to the wider D435i range.
    return 2200.0


class VisionSystem:
    """视觉系统 - 用于识别物体并计算坐标"""

    def __init__(self, camera_type="D435i", serial_number=None,
                 enable_tracking=True, enable_kalman=True, enable_depth_filter=True,
                 model_path=None):
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
        # yolo_every_n: 每 N 帧跑一次完整 YOLO 推理（session.run），其余帧只用 ByteTrack
        # 跟踪预测，用于在流水线模式下提升 inference_fps。从 performance.visual_servo
        # 读取，默认 3（与 config_manager.DEFAULT_VISUAL_SERVO_CONFIG 一致）。
        _vs_cfg = performance_config.get("visual_servo", {}) or {}
        self.yolo_every_n = max(1, int(_vs_cfg.get("yolo_every_n", 3)))
        self._yolo_frame_counter = 0
        self.camera_available = False
        self._consecutive_capture_failures = 0
        self._max_consecutive_failures = 5
        # 相机硬件 fps 测量：记录上一帧 RealSense 时间戳，用于计算相邻帧 diff
        self._last_frame_timestamp_ms = 0.0  # 上一帧的硬件时间戳（ms）
        self._low_camera_fps_count = 0  # 连续低 fps 计数（camera_fps < 25）
        # 诊断帧缓存：弱引用式注入，默认 None 表示未注册。由 runtime 层挂载
        # DiagnosticFrameCache 实例；InferenceWorker 在每帧推理完成后 fan-out 写入，
        # 复用生产推理结果避免重复 session.run。不在此 import diagnostic_frame_cache
        # 模块，避免 vision 层依赖 runtime 层导致循环导入。
        self._diagnostic_cache = None
        self.pipeline = None
        self.profile = None
        self.depth_scale = 0.001
        # 相机配置：enable_align / enable_depth_filter 等开关，缺失时取默认值
        camera_config = get_camera_config()
        self._enable_align = bool(camera_config.get("enable_align", True))
        self._enable_depth_filter = bool(camera_config.get("enable_depth_filter", True))
        if not self._enable_align:
            logger.warning(
                "相机深度对齐已关闭（camera.enable_align=false），"
                "深度未对齐到彩色视角，位置计算可能不准（仅诊断用）"
            )
        if not self._enable_depth_filter:
            logger.warning(
                "深度滤波已关闭（camera.enable_depth_filter=false），"
                "深度噪声可能增加（仅诊断用）"
            )
        # 深度范围：优先从配置读取，无配置时使用默认值
        depth_range_config = config.get("camera", {}).get("depth_range", {})
        if camera_type == "D405":
            self.min_depth = float(depth_range_config.get("D405_min_depth", 0.07))
            self.max_depth = float(depth_range_config.get("D405_max_depth", 0.8))
        else:
            self.min_depth = float(depth_range_config.get("D435i_min_depth", 0.5))
            self.max_depth = float(depth_range_config.get("D435i_max_depth", 2.2))
        # 相机 Z 轴过滤上限（mm）：配置显式值优先，否则按相机类型默认值
        self.max_camera_z_mm = resolve_max_camera_z_mm(camera_type, config)
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
        if not calib_data or "cam_to_flange_pose" not in calib_data:
            raise ValueError(f"未找到相机 {camera_type} 的标定数据")
        self.T_cam2flange = get_camera_handeye_matrix(camera_type)
        logger.info(f"✅ 加载 {camera_type} 手眼标定矩阵 T_hand_eye:")
        logger.debug(np.round(self.T_cam2flange, 4))

        self.model_path = resolve_camera_model_path(camera_type, model_path)
        self._initialize_onnx_model()

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

        if self.enable_tracking:
            self.tracker = BYTETracker(track_thresh=0.5, match_thresh=0.8, track_buffer=30)
            self.tracked_target_id = None
            logger.info("✅ ByteTrack 跟踪器已初始化")
        else:
            self.tracker = None
            self.tracked_target_id = None

        if self.enable_kalman:
            # TODO: 弃用 — kalman_3d 在 Camera Frame 滤波，跨帧比较不一致，
            # D405 路径将逐步迁移到 kalman_3d_base（Base Frame）。保留以兼容。
            self.kalman_3d = KalmanFilter3D(dt=1.0/30, process_noise=1.0, measurement_noise=5.0)
            logger.info("✅ 3D 卡尔曼滤波器已初始化")
        else:
            self.kalman_3d = None

        # Task 6: D405 专用 Base Frame Kalman 滤波器（逐步迁移）
        self.kalman_3d_base = None
        if camera_type == "D405" and self.enable_kalman:
            self.kalman_3d_base = KalmanFilter3D(
                dt=1.0/30, process_noise=1.0, measurement_noise=5.0,
            )
            logger.info("✅ Base Frame 3D 卡尔曼滤波器已初始化 (D405)")

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
        # SubTask 7.3: tracks last kalman predict/update time for variable dt
        self._kalman_last_time = None

    def _kalman_step_dt(self):
        """Return (now, dt) for variable-dt kalman predict/update.

        dt is None on the first call (no prior timestamp). Uses getattr so that
        test fixtures built via object.__new__ without running __init__ still
        work.
        """
        now = time.perf_counter()
        last = getattr(self, "_kalman_last_time", None)
        if last is None:
            dt = None
        else:
            dt = now - last
        return now, dt

    @property
    def kalman_prediction_age(self):
        """Seconds since the last successful Kalman update (0.0 if disabled)."""
        if self.kalman_3d is None:
            return 0.0
        return self.kalman_3d.prediction_age

    @property
    def kalman_miss_count(self):
        """Consecutive gated-out measurements since the last successful update."""
        if self.kalman_3d is None:
            return 0
        return self.kalman_3d.miss_count

    def _initialize_onnx_model(self):
        global _CUDA_RUNTIME_FAILURE
        logger.info("正在为 %s 加载模型: %s", self.camera_type, self.model_path)
        try:
            import onnxruntime as ort

            dll_preload_ok = preload_onnx_runtime_dlls(ort)
            available_providers = ort.get_available_providers()
            self.inference_provider = "CPU"
            using_cuda = False

            if (
                'CUDAExecutionProvider' in available_providers
                and _CUDA_RUNTIME_FAILURE is None
                and dll_preload_ok
            ):
                # 配置 SessionOptions：启用内存模式重用和图优化
                sess_options = ort.SessionOptions()
                sess_options.enable_mem_pattern = True
                sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                sess_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL

                # CUDA EP provider_options：用显存换速度
                # 注意：onnxruntime 要求 provider_options 的值必须是字符串类型
                cuda_provider_options = {
                    # 允许 cuDNN 卷积使用最大工作区显存，提升卷积算子性能
                    "cudnn_conv_use_max_workspace": "1",
                    # 按请求大小扩展显存 arena，避免过度预占用显存
                    "arena_extend_strategy": "kSameAsRequested",
                    # 启用可调算子（TunableOp），自动选择最优 GPU kernel 实现
                    "tunable_op_enable": "1",
                    # 禁用 CUDA Graph 捕获（输入形状动态变化时不宜启用）
                    "enable_cuda_graph": "0",
                }

                try:
                    self.session = ort.InferenceSession(
                        self.model_path,
                        sess_options=sess_options,
                        providers=[
                            ('CUDAExecutionProvider', cuda_provider_options),
                            'CPUExecutionProvider',
                        ],
                    )
                except Exception as cuda_opt_exc:
                    # 旧版 onnxruntime 可能不支持某些 provider_options key，
                    # 回退到不带 provider_options 的简单 providers 列表，保证兼容性
                    logger.warning(
                        "CUDA provider_options 创建失败，回退到默认配置: %s",
                        str(cuda_opt_exc).splitlines()[0][:200],
                    )
                    self.session = ort.InferenceSession(
                        self.model_path,
                        sess_options=sess_options,
                        providers=['CUDAExecutionProvider', 'CPUExecutionProvider'],
                    )
                active_providers = self.session.get_providers()
                if 'CUDAExecutionProvider' in active_providers:
                    using_cuda = True
                    self.inference_provider = "GPU (CUDA)"
                    if hasattr(self.session, "disable_fallback"):
                        self.session.disable_fallback()
                else:
                    self.inference_provider = "CPU (CUDA回退)"
                    logger.warning(
                        "CUDAExecutionProvider 注册但未激活，已回退 CPU。活跃 providers: %s",
                        active_providers,
                    )
            else:
                self.session = ort.InferenceSession(
                    self.model_path,
                    providers=['CPUExecutionProvider'],
                )
                if (
                    not dll_preload_ok
                    and 'CUDAExecutionProvider' in available_providers
                    and _CUDA_RUNTIME_FAILURE is None
                ):
                    self.inference_provider = "CPU (DLL预加载失败)"
                    logger.warning("DLL 预加载失败，跳过 CUDA 直接走 CPU")
                elif _CUDA_RUNTIME_FAILURE is not None:
                    self.inference_provider = "CPU (CUDA运行失败回退)"
                    logger.warning(
                        "本进程已检测到 CUDA 运行环境异常，%s 直接使用 CPU: %s",
                        self.camera_type,
                        _CUDA_RUNTIME_FAILURE,
                    )
                else:
                    self.inference_provider = "CPU"
                    logger.warning(
                        "CUDA 不可用，使用 CPU 推理。当前可用 providers: %s",
                        available_providers,
                    )

            input_infos = self.session.get_inputs()
            if not input_infos or len(input_infos[0].shape) != 4:
                raise ValueError("模型必须具有一个四维 NCHW 输入")
            self.input_name = input_infos[0].name
            self.input_shape = input_infos[0].shape
            height, width = self.input_shape[2], self.input_shape[3]
            if not isinstance(height, int) or height <= 0 or not isinstance(width, int) or width <= 0:
                raise ValueError("模型输入高度和宽度必须是固定正整数")
            logger.debug(f"模型输入: {self.input_name}, 形状: {self.input_shape}")

            try:
                self.warmup_onnx()
            except Exception as cuda_exc:
                if not using_cuda:
                    raise
                error_summary = str(cuda_exc).splitlines()[0][:500]
                _CUDA_RUNTIME_FAILURE = error_summary
                logger.warning(
                    "CUDA 首次推理失败，显式回退 CPU；请检查 CUDA/cuDNN DLL: %s",
                    error_summary,
                )
                logger.debug("CUDA 首次推理完整异常", exc_info=True)
                self._log_cuda_diagnostic()
                self.session = ort.InferenceSession(
                    self.model_path,
                    providers=['CPUExecutionProvider'],
                )
                self.inference_provider = "CPU (CUDA运行失败回退)"
                input_infos = self.session.get_inputs()
                self.input_name = input_infos[0].name
                self.input_shape = input_infos[0].shape
                self.warmup_onnx()
                using_cuda = False

            if using_cuda:
                active_providers = self.session.get_providers()
                if 'CUDAExecutionProvider' in active_providers:
                    logger.info("实例分割模型加载成功（GPU CUDA 模式）")
                else:
                    self.inference_provider = "CPU (CUDA运行时回退)"
                    logger.warning(
                        "CUDA 首次推理后已切换到 CPU。活跃 providers: %s",
                        active_providers,
                    )

            output_infos = self.session.get_outputs()
            if not output_infos or len(output_infos[0].shape) != 3:
                raise ValueError("模型主输出必须是三维 YOLO 检测张量")
            self.model_format = "yolov8"
            output_shape = output_infos[0].shape
            dim1, dim2 = output_shape[1], output_shape[2]
            if not isinstance(dim1, int) or not isinstance(dim2, int):
                raise ValueError("模型输出维度必须是固定整数")

            if len(output_infos) >= 2:
                self.is_seg_model = True
                mask_shape = output_infos[1].shape
                if (
                    len(mask_shape) != 4
                    or not isinstance(mask_shape[1], int)
                    or mask_shape[1] != 32
                ):
                    raise ValueError("实例分割模型掩码输出必须是 [N, 32, H, W]")
                if dim1 < dim2:
                    self.num_classes = dim1 - 4 - 32
                else:
                    self.model_format = "yolo26"
                    self.num_classes = 1
                if self.num_classes <= 0:
                    raise ValueError("分割模型输出中未检测到有效类别")
                logger.debug(
                    "模型输出: seg模式, num_classes=%s, model_format=%s",
                    self.num_classes,
                    self.model_format,
                )
            else:
                self.is_seg_model = False
                if dim1 < dim2:
                    self.num_classes = dim1 - 4
                else:
                    self.model_format = "yolo26"
                    self.num_classes = 1
                if self.num_classes <= 0:
                    raise ValueError("检测模型输出中未检测到有效类别")
                logger.debug(
                    "模型输出: detect模式, num_classes=%s, model_format=%s",
                    self.num_classes,
                    self.model_format,
                )
        except Exception as exc:
            self.session = None
            raise RuntimeError(
                f"{self.camera_type} 模型加载失败 ({self.model_path}): {exc}"
            ) from exc

    def _log_cuda_diagnostic(self):
        """打印 CUDA 依赖诊断信息，便于用户排查 GPU 退回 CPU 的原因。"""
        try:
            import onnxruntime as ort
            import importlib.util
            from pathlib import Path

            providers = ort.get_available_providers()
            logger.warning("=== CUDA 诊断 ===")
            logger.warning("available_providers: %s", providers)

            # 与 preload_onnx_runtime_dlls 一致的 _CUDA_DEPS 检测逻辑，
            # 用于列出具体缺失的 DLL 文件名（如 cudart64_*.dll）。
            _CUDA_DEPS = [
                ("nvidia.cudnn", "cudnn_engines_tensor_ir64_9", "bin"),
                ("nvidia.cuda_runtime", "cudart64", "bin"),
                ("nvidia.cublas", "cublas64", "bin"),
                ("nvidia.cublas", "cublasLt64", "bin"),
                ("nvidia.cufft", "cufft64", "bin"),
            ]

            missing_dlls = []
            for pkg_name, dll_prefix, subdir in _CUDA_DEPS:
                spec = importlib.util.find_spec(pkg_name)
                if spec is None:
                    missing_dlls.append(
                        f"{dll_prefix}*.dll ({pkg_name} 包未安装)"
                    )
                    logger.warning("  %s: 未安装", pkg_name)
                    continue
                logger.warning("  %s: 已安装", pkg_name)
                locations = list(spec.submodule_search_locations or [])
                if not locations:
                    missing_dlls.append(
                        f"{dll_prefix}*.dll ({pkg_name} 包缺少子模块搜索路径)"
                    )
                    continue
                bin_dir = Path(locations[0]) / subdir
                if not bin_dir.is_dir():
                    missing_dlls.append(
                        f"{dll_prefix}*.dll ({pkg_name} 包缺少 {subdir}/ 目录)"
                    )
                    continue
                matches = list(bin_dir.glob(f"{dll_prefix}*.dll"))
                if not matches:
                    missing_dlls.append(
                        f"{dll_prefix}*.dll "
                        f"({pkg_name} 包的 {subdir}/ 目录中无匹配文件)"
                    )

            if missing_dlls:
                logger.warning("缺失 DLL 列表:")
                for m in missing_dlls:
                    logger.warning("  - %s", m)
                logger.warning(
                    "修复命令: pip install --force-reinstall "
                    "onnxruntime-gpu[cuda,cudnn]"
                )
            else:
                logger.warning("所有 CUDA 依赖 DLL 均已就绪")
        except Exception as e:
            logger.warning("CUDA 诊断收集失败: %s", e)

    def warmup_onnx(self):
        """ONNX session warmup：运行一次 dummy inference 消除 CUDA JIT 延迟"""
        if self.session is None:
            return
        dummy_input = np.zeros(
            (1, 3, self.input_shape[2], self.input_shape[3]),
            dtype=np.float32,
        )
        self.session.run(None, {self.input_name: dummy_input})
        logger.info("ONNX warmup 完成 (%s)", self.inference_provider)

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
        # 计算 fps：基于"两次日志输出之间的实际时间"。
        # 首次（last_log == 0.0）尚无前一次输出基准，不算 fps；
        # 从第二次开始用 count / elapsed 计算。
        fps_str = ""
        if stats["last_log"] > 0:
            elapsed = now - stats["last_log"]
            if elapsed > 0:
                fps = count / elapsed
                fps_str = f"fps={fps:.1f} "
        parts = [
            f"{key}={total / count:.1f}"
            if key.endswith("_fps")
            else f"{key}={total / count:.1f}ms"
            for key, total in sorted(stats["totals"].items())
        ]
        logger.info(
            "performance[%s] frames=%s %s%s",
            scope, stats["count"], fps_str, " ".join(parts),
        )
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
        max_z_mm = float(getattr(self, "max_camera_z_mm", 2200.0))
        if z_mm > max_z_mm:
            logger.debug("camera Z filtered: %.2fmm > %.2fmm", z_mm, max_z_mm)
            return None
        return result

    def convert_to_end_coords(self, camera_coords):
        """
        相机坐标 → 末端坐标
        使用手眼矩阵进行直接转换（相机 → 末端的变换）
        """
        if self.T_cam2flange is None:
            raise ValueError("手眼标定矩阵未初始化，无法转换坐标")

        # 相机齐次坐标 [Xc,Yc,Zc,1]
        point_cam = np.array([camera_coords[0], camera_coords[1], camera_coords[2], 1.0])

        # 直接使用手眼矩阵进行转换（相机 → 末端）
        point_end = self.T_cam2flange @ point_cam

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
            # camera.enable_align=false 时跳过深度→彩色对齐（诊断用），
            # 此时 aligned_frames 即原始 frames，深度未对齐到彩色视角。
            if self._enable_align:
                aligned_frames = self.align.process(frames)
            else:
                aligned_frames = frames
            align_done = time.perf_counter()
            depth_frame = aligned_frames.get_depth_frame()
            color_frame = aligned_frames.get_color_frame()

            if not depth_frame or not color_frame:
                self._consecutive_capture_failures += 1
                if self._consecutive_capture_failures >= self._max_consecutive_failures:
                    self.camera_available = False
                    logger.warning("连续 %d 次捕获帧失败，标记相机不可用", self._consecutive_capture_failures)
                return None, None

            # camera.enable_depth_filter=false 时跳过深度滤波链（诊断用）。
            if self._enable_depth_filter and self.depth_processor is not None:
                depth_frame = self.depth_processor.process_frame(depth_frame)
            filter_done = time.perf_counter()

            # 计算相机硬件 fps（基于 RealSense 帧时间戳差）
            # 首帧时 _last_frame_timestamp_ms == 0，跳过 diff 计算，camera_fps 保持 0.0
            camera_fps = 0.0
            try:
                frame_ts_ms = float(depth_frame.get_timestamp())
                if (
                    self._last_frame_timestamp_ms > 0
                    and frame_ts_ms > self._last_frame_timestamp_ms
                ):
                    diff_ms = frame_ts_ms - self._last_frame_timestamp_ms
                    if diff_ms > 0:
                        camera_fps = 1000.0 / diff_ms
                self._last_frame_timestamp_ms = frame_ts_ms
            except Exception:
                pass

            timings = {
                "wait": (wait_done - start) * 1000.0,
                "align": (align_done - wait_done) * 1000.0,
                "depth_filter": (filter_done - align_done) * 1000.0,
                "total": (filter_done - start) * 1000.0,
            }
            if camera_fps > 0:
                timings["camera_fps"] = camera_fps
                # 连续低 fps 告警（camera_fps < 25 视为异常）
                if camera_fps < 25.0:
                    self._low_camera_fps_count += 1
                    if self._low_camera_fps_count >= 3:
                        logger.warning(
                            "相机硬件 fps 连续 %d 次低于 25（当前 %.1f），"
                            "可能受 USB 带宽/分辨率/align 影响",
                            self._low_camera_fps_count, camera_fps,
                        )
                else:
                    self._low_camera_fps_count = 0
            self._record_performance("capture", timings)

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
        # capture_time 前移：wait_for_frames 返回后立即记录，避免 numpy 拷贝耗时引入漂移
        capture_time = time.perf_counter()
        frame_ts_ms = 0.0
        try:
            frame_ts_ms = float(depth_frame.get_timestamp())
        except Exception:
            frame_ts_ms = 0.0
        return FramePacket(
            seq=seq,
            timestamp=time.time(),
            color_image=np.asanyarray(color_frame.get_data()).copy(),
            depth_image=np.asanyarray(depth_frame.get_data()).copy(),
            capture_time=capture_time,
            frame_timestamp_ms=frame_ts_ms,
        )

    @property
    def is_available(self):
        """相机是否可用（已连接且 pipeline 存在）"""
        return self.camera_available and self.pipeline is not None

    def preprocess_image_yolov8(self, image, target_size=(640, 640)):
        """为YOLOv8模型预处理图像"""
        global _PREPROCESS_USE_UMAT
        # 首次调用时检测 UMat 可用性并缓存结果，避免重复检测开销
        if _PREPROCESS_USE_UMAT is None:
            _PREPROCESS_USE_UMAT = _detect_umat_available()
            if not _PREPROCESS_USE_UMAT:
                logger.warning("OpenCV UMat 不可用，预处理将走 CPU 路径（可能影响 GPU 推理吞吐）")
        use_umat = _PREPROCESS_USE_UMAT

        h, w = image.shape[:2]

        # 计算缩放比例，保持宽高比
        scale = min(target_size[0] / w, target_size[1] / h)
        new_w = int(w * scale)
        new_h = int(h * scale)

        y_offset = (target_size[1] - new_h) // 2
        x_offset = (target_size[0] - new_w) // 2

        # resize/画布填充/cvtColor 优先走 UMat（GPU/OpenCL 后端），失败回退 numpy 路径
        rgb_image = None
        if use_umat:
            try:
                # 输入图像转 UMat，resize/cvtColor/画布填充均在 GPU 上执行
                umat_in = cv2.UMat(image)
                umat_resized = cv2.resize(umat_in, (new_w, new_h))
                # 用 copyMakeBorder 在 UMat 上完成 letterbox 画布填充，
                # 等价于 numpy 路径的 np.full 画布 + 切片赋值，但避免 UMat
                # 不支持切片赋值的问题
                top = y_offset
                bottom = target_size[1] - new_h - y_offset
                left = x_offset
                right = target_size[0] - new_w - x_offset
                umat_padded = cv2.copyMakeBorder(
                    umat_resized, top, bottom, left, right,
                    cv2.BORDER_CONSTANT, value=(114, 114, 114),
                )
                umat_rgb = cv2.cvtColor(umat_padded, cv2.COLOR_BGR2RGB)
                # 转回 ndarray，后续 astype/transpose 仍在 CPU 上执行
                rgb_image = umat_rgb.get()
            except Exception as exc:
                logger.warning("UMat 预处理失败，回退 numpy 路径: %s", exc)
                rgb_image = None

        if rgb_image is None:
            # numpy 路径（原逻辑）：resize → np.full 画布 + 切片赋值 → cvtColor
            resized = cv2.resize(image, (new_w, new_h))
            canvas = np.full((target_size[1], target_size[0], 3), 114, dtype=np.uint8)
            canvas[y_offset:y_offset + new_h, x_offset:x_offset + new_w] = resized
            rgb_image = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)

        input_tensor = rgb_image.astype(np.float32) / 255.0

        # 转换维度顺序: HWC -> NCHW
        # transpose 会产生非连续内存视图，ORT 内部需做隐式拷贝，
        # 这里显式转为 C-contiguous 内存布局，消除额外拷贝开销
        input_tensor = np.ascontiguousarray(np.transpose(input_tensor, (2, 0, 1)))
        input_tensor = np.ascontiguousarray(np.expand_dims(input_tensor, axis=0))

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

    def run_detection_tracked(self, color_image, force_inference=False):
        if self.tracker is None:
            # 无跟踪器时无法跳帧（跳帧依赖 ByteTrack 维护目标状态），直接跑完整检测
            return self.run_detection(color_image)

        # yolo_every_n 跳帧：先判断本帧是否需要跑 YOLO 推理，再更新计数器。
        # counter 从 0 开始，第一帧 (counter%N==0) 跑检测，确保初始有目标可跟踪；
        # 之后每 N 帧跑 1 次 session.run，其余帧只用 ByteTrack 预测（_track_only_no_inference）。
        # 跳帧逻辑在 run_detection_tracked 内部处理，InferenceWorker 调用时自动生效。
        yolo_every_n = getattr(self, 'yolo_every_n', 1)
        counter = getattr(self, '_yolo_frame_counter', 0)
        if force_inference:
            # force_inference=True 时强制跑检测，且不递增计数器，不影响后续跳帧节奏
            should_infer = True
        else:
            should_infer = (yolo_every_n <= 1) or (counter % yolo_every_n == 0)
            counter += 1
            self._yolo_frame_counter = counter
        logger.debug(
            "yolo_every_n skip: counter=%d, every_n=%d, infer=%s, force=%s",
            counter, yolo_every_n, should_infer, force_inference,
        )
        if not should_infer:
            return self._track_only_no_inference(color_image)

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

    def _track_only_no_inference(self, color_image):
        """跳帧时仅用 ByteTrack 预测目标位置，不跑 session.run。

        对 tracker 当前维护的 tracked_stracks 逐个调用 predict() 推演 bbox（Kalman
        预测），然后复用 _select_target 选目标。**不调 tracker.update()** —— 因为
        update([], img_size) 会把所有 tracked 目标立即标记为 lost 并清空（见
        BYTETracker.update 的空检测分支），那样跳帧反而会丢失跟踪目标。

        若 tracker 无 tracked_stracks 且无可用 kalman 预测，返回 None（由调用方兜底）。
        """
        try:
            for t in self.tracker.tracked_stracks:
                t.predict()
        except Exception:
            logger.exception("跳帧跟踪预测失败")
            return None
        return self._select_target(self.tracker.tracked_stracks)

    def _select_target(self, tracks):
        if not tracks:
            if self.tracked_target_id is not None and self.kalman_3d is not None and self.kalman_3d.initialized:
                now, dt = self._kalman_step_dt()
                predicted = self.kalman_3d.predict(dt)
                self._kalman_last_time = now
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
                'source': 'prediction',
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
                now, dt = self._kalman_step_dt()
                predicted = self.kalman_3d.predict(dt)
                self._kalman_last_time = now
                return self._reject_camera_z_over_limit({
                    'camera_coords': predicted.tolist(),
                    'smoothed': True,
                    'confidence': self.kalman_3d.get_confidence(),
                    'source': 'prediction',
                })
            return None

        if self.kalman_3d is not None:
            observed = raw_result['camera_coords']
            now, dt = self._kalman_step_dt()
            smoothed = self.kalman_3d.update(observed, dt)
            self._kalman_last_time = now
            result = dict(raw_result)
            result['camera_coords'] = smoothed.tolist()
            result['smoothed'] = True
            result['confidence'] = detection_score
            result['detection_score'] = detection_score
            result['tracking_confidence'] = self.kalman_3d.get_confidence()
            result['source'] = 'smoothed'
            result['raw_coords'] = observed
            return self._reject_camera_z_over_limit(result)

        raw_result['smoothed'] = False
        raw_result['confidence'] = detection_score if detection_score > 0 else 1.0
        raw_result['detection_score'] = detection_score
        raw_result['tracking_confidence'] = 0.0
        raw_result['source'] = 'detection'
        return self._reject_camera_z_over_limit(raw_result)

    def update_base_kalman(self, target_base):
        """同步更新 Base Frame Kalman 滤波器（仅 D405 启用）。

        用 target_base（基座坐标系位置）作为观测更新 kalman_3d_base，
        用于逐步将 D405 滤波从 Camera Frame 迁移到 Base Frame。
        """
        if self.kalman_3d_base is None:
            return
        self.kalman_3d_base.update(np.asarray(target_base)[:3])

    def reset_tracking(self):
        if self.tracker is not None:
            self.tracker.reset()
        if self.kalman_3d is not None:
            self.kalman_3d.reset()
        if self.kalman_3d_base is not None:
            self.kalman_3d_base.reset()
        self.tracked_target_id = None
        self.last_valid_position = None
        self._kalman_last_time = None
        # 重置跳帧计数器，确保 reset 后与 tracker 状态同步（counter=0 时下一帧跑检测）
        self._yolo_frame_counter = 0

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


class InferenceWorker(threading.Thread):
    """从 frame_queue 取帧，跑 preprocess+session.run+postprocess+位置计算，结果放 result_queue。

    与 :class:`CaptureWorker` 解耦，让 GPU 推理无需等帧采集完成，提升 GPU 占用率。

    线程安全说明：``VisionSystem`` 的 ``tracker`` / ``kalman_3d`` / ``last_valid_position``
    等状态在 ``run_detection_tracked`` 与 ``calculate_object_position_smoothed`` 中都会被
    读写。为避免跨线程竞争，本 worker 默认同时执行这两步（preprocess + session.run +
    postprocess + 位置平滑），把所有视觉状态变更收敛在单一线程内；主线程只读取最终
    结果做置信度筛选。这样无需给 VisionSystem 加锁，最小改动且无死锁风险。

    启用 PositionWorker 时（``compute_position=False``）：本 worker 只跑 detection 段，
    把 ``(packet, target, capture_ms)`` 三元组入 intermediate_queue，位置计算交给
    PositionWorker 线程。**注意**：此模式下 ``run_detection_tracked`` 与
    ``calculate_object_position_smoothed`` 会并发访问 ``kalman_3d`` /
    ``_kalman_last_time`` / ``last_valid_position`` 等状态，存在潜在线程安全风险
    （见 :class:`PositionWorker` 文档），仅诊断/实验用，默认禁用。
    """

    def __init__(self, vision_system, frame_queue, result_queue, stop_event, compute_position=True):
        # vision_system: VisionSystem 实例（用于调 run_detection_tracked /
        #   calculate_object_position_smoothed，复用其 preprocess/session.run/postprocess）
        # frame_queue: queue.Queue，CaptureWorker 入 ``(packet, capture_ms)``
        # result_queue: queue.Queue(maxsize=1)，存最新检测结果
        # stop_event: threading.Event
        # compute_position: 是否在本 worker 内调用 calculate_object_position_smoothed。
        #   默认 True 保持原行为。启用 PositionWorker 时传 False，位置计算交给
        #   PositionWorker 线程，本 worker 只把 (packet, target, capture_ms) 入
        #   intermediate_queue（由调用方传入，实际是 result_queue 形参）。
        super().__init__(daemon=True, name="inference-worker")
        self._vision = vision_system
        self._frame_queue = frame_queue
        self._result_queue = result_queue
        self._stop_event = stop_event
        self._compute_position = compute_position
        # 分段计时累计统计（detection / position / total），定期输出后重置
        # 与 VisionSystem._record_performance 行为一致：日志输出后清零，便于分段观察
        self._frame_count = 0
        self._detection_total_ms = 0.0
        self._position_total_ms = 0.0
        self._total_ms = 0.0
        # 复用 vision_system 的 performance_log_interval_frames；缺失时回退默认 30
        self._log_interval = getattr(vision_system, 'performance_log_interval_frames', 30)
        self._last_log_time = time.perf_counter()

    def run(self):
        while not self._stop_event.is_set():
            try:
                frame = self._frame_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                result = self._run_inference(frame)
                # 入 result_queue（maxsize=1），满了丢旧，保证主线程拿到最新结果
                try:
                    self._result_queue.put_nowait(result)
                except queue.Full:
                    try:
                        self._result_queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        self._result_queue.put_nowait(result)
                    except queue.Full:
                        pass
            except Exception as exc:
                logger.warning("InferenceWorker 推理失败: %s", exc)

    def _run_inference(self, frame):
        """复用 vision_system 已有方法跑推理 + 位置计算，返回结果字典。

        加分段计时：detection 段（run_detection_tracked，含 preprocess + session.run
        + postprocess + tracker）和 position 段（calculate_object_position_smoothed）。
        每 ``_log_interval`` 帧输出一次 INFO 日志，定位瓶颈在 detection 还是 position。

        当 ``self._compute_position`` 为 False（启用 PositionWorker 时）：
        只跑 detection 段，返回 (packet, target, capture_ms) 三元组交给
        PositionWorker 线程做位置计算；本 worker 不再访问 kalman_3d 等状态。
        """
        packet, capture_ms = frame
        t0 = time.perf_counter()
        # run_detection_tracked 内部已包含 preprocess + session.run + postprocess + 跟踪器更新；
        # yolo_every_n 跳帧也由其内部处理（每 N 帧只跑 1 次 session.run，其余帧只用
        # ByteTrack 预测），InferenceWorker 无需额外跳帧逻辑。
        target = self._vision.run_detection_tracked(packet.color_image)
        t1 = time.perf_counter()
        if not self._compute_position:
            # 启用 PositionWorker：本 worker 只跑 detection，把 (packet, target, capture_ms)
            # 入 intermediate_queue（即调用方传入的 result_queue 形参），位置计算由
            # PositionWorker 线程执行。分段计时只统计 detection 段。
            detection_ms = (t1 - t0) * 1000.0
            self._frame_count += 1
            self._detection_total_ms += detection_ms
            self._total_ms += detection_ms
            if self._frame_count % self._log_interval == 0:
                now = time.perf_counter()
                elapsed = now - self._last_log_time
                fps = self._frame_count / elapsed if elapsed > 0 else 0.0
                logger.info(
                    "performance[inference_worker] frames=%d fps=%.1f detection=%.1fms total=%.1fms (position offloaded)",
                    self._frame_count,
                    fps,
                    self._detection_total_ms / self._frame_count,
                    self._total_ms / self._frame_count,
                )
                self._frame_count = 0
                self._detection_total_ms = 0.0
                self._total_ms = 0.0
                self._last_log_time = now
            # 返回三元组：PositionWorker 从 intermediate_queue 取这个结构
            return (packet, target, capture_ms)
        # 位置计算也复用现有方法（同时保持 kalman/tracker 状态单线程访问）
        object_position = self._vision.calculate_object_position_smoothed(
            packet.depth_image, packet.color_image, target
        )
        t2 = time.perf_counter()
        detection_ms = (t1 - t0) * 1000.0
        position_ms = (t2 - t1) * 1000.0
        total_ms = (t2 - t0) * 1000.0
        # 累计到统计（与 _record_performance 行为一致：日志输出后清零，便于分段观察）
        self._frame_count += 1
        self._detection_total_ms += detection_ms
        self._position_total_ms += position_ms
        self._total_ms += total_ms
        # 定期日志：在 worker 线程内输出，覆盖 detection / position 两段
        if self._frame_count % self._log_interval == 0:
            now = time.perf_counter()
            elapsed = now - self._last_log_time
            fps = self._frame_count / elapsed if elapsed > 0 else 0.0
            logger.info(
                "performance[inference_worker] frames=%d fps=%.1f detection=%.1fms position=%.1fms total=%.1fms",
                self._frame_count,
                fps,
                self._detection_total_ms / self._frame_count,
                self._position_total_ms / self._frame_count,
                self._total_ms / self._frame_count,
            )
            # 重置累计（与 _record_performance 行为一致）
            self._frame_count = 0
            self._detection_total_ms = 0.0
            self._position_total_ms = 0.0
            self._total_ms = 0.0
            self._last_log_time = now
        # fan-out 到诊断缓存（若已注册）：复用本帧推理结果，避免诊断流重复 session.run。
        # 用 getattr 动态访问，未注册时只多一次属性查询 + None 判断，几乎零开销；
        # 不引入对 diagnostic_frame_cache 模块的 import，避免 vision→runtime 循环导入。
        cache = getattr(self._vision, "_diagnostic_cache", None)
        if cache is not None:
            try:
                # 绘制标注（bbox + mask），与 runtime_vision_debug.capture_vision_snapshot 一致
                annotated = packet.color_image.copy()
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
                # JPEG 编码内联在此，不依赖 runtime_vision_debug（避免 vision 层依赖 runtime 层）
                ok, encoded = cv2.imencode(
                    ".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 85]
                )
                if ok:
                    jpeg_bytes = encoded.tobytes()
                    seq = packet.seq
                    metadata = {
                        "detection": (
                            {
                                "bbox": target.get("bbox"),
                                "track_id": target.get("track_id"),
                                "score": float(target.get("score", 0.0)),
                                "predicted": bool(target.get("predicted", False)),
                            }
                            if target
                            else None
                        ),
                        "coordinates": object_position,
                        "timings_ms": {
                            "detection": detection_ms,
                            "position": position_ms,
                            "total": total_ms,
                        },
                    }
                    cache.update(seq, jpeg_bytes, metadata)
            except Exception as exc:
                # fan-out 失败不能影响主流程，只记 warning 日志
                logger.warning("fan-out 写入诊断缓存失败: %s", exc)
        return {
            "seq": packet.seq,
            "capture_ms": capture_ms,
            "target": target,
            "object_position": object_position,
        }


class PipelinedDetector:
    """封装 CaptureWorker + InferenceWorker，提供流水线检测接口。

    失败时回退到串行模式：``start()`` 返回 False，调用方据 ``is_pipelined``
    属性决定走流水线路径还是原串行路径。

    帧数据流（默认，``position_worker_enabled=False``）：
        CaptureWorker 采集 → frame_queue(maxsize=2，满了丢最旧) →
        InferenceWorker 推理（detection + 位置计算）→ result_queue(maxsize=1，存最新)
        → 主线程取最新结果。

    帧数据流（``position_worker_enabled=True``，实验性）：
        CaptureWorker 采集 → frame_queue(maxsize=2) →
        InferenceWorker 推理（仅 detection）→ intermediate_queue(maxsize=1) →
        PositionWorker 位置计算 → result_queue(maxsize=1) → 主线程取最新结果。
    """

    def __init__(self, capture_worker_factory, vision_system, position_worker_enabled=False):
        # capture_worker_factory: callable(frame_queue) -> CaptureWorker | None
        #   接收 PipelinedDetector 内部创建的 frame_queue，返回一个已配置好帧输出
        #   的 CaptureWorker（或 None 表示创建失败，触发回退串行）。
        # vision_system: VisionSystem 实例
        # position_worker_enabled: 是否启用 PositionWorker 异步化（默认 False）。
        #   True 时 InferenceWorker 只跑 detection，位置计算由独立 PositionWorker 线程执行。
        #   高风险：见 PositionWorker 文档的线程安全说明，仅诊断/实验用。
        self._capture_worker_factory = capture_worker_factory
        self._vision_system = vision_system
        self._position_worker_enabled = bool(position_worker_enabled)
        self._capture_worker = None
        self._inference_worker = None
        self._position_worker = None
        self._frame_queue = None
        self._result_queue = None
        self._intermediate_queue = None  # 启用 PositionWorker 时 InferenceWorker→PositionWorker 的中转队列
        self._stop_event = None
        self._is_pipelined = False

    @property
    def is_pipelined(self) -> bool:
        return self._is_pipelined

    def start(self) -> bool:
        """启动流水线。成功返回 True，失败返回 False（调用方应回退串行）。"""
        try:
            self._frame_queue = queue.Queue(maxsize=2)
            self._result_queue = queue.Queue(maxsize=1)
            self._stop_event = threading.Event()
            capture_worker = self._capture_worker_factory(self._frame_queue)
            if capture_worker is None:
                self.stop()
                return False
            self._capture_worker = capture_worker
            if self._position_worker_enabled:
                # 启用 PositionWorker：InferenceWorker 入 intermediate_queue，
                # PositionWorker 从 intermediate_queue 取后入 result_queue。
                self._intermediate_queue = queue.Queue(maxsize=1)
                self._inference_worker = InferenceWorker(
                    self._vision_system,
                    self._frame_queue,
                    self._intermediate_queue,  # InferenceWorker 的 result_queue 实参指向中转队列
                    self._stop_event,
                    compute_position=False,
                )
                self._position_worker = PositionWorker(
                    self._vision_system,
                    self._intermediate_queue,
                    self._result_queue,
                    self._stop_event,
                )
            else:
                # 默认路径：InferenceWorker 自己做位置计算，直接入 result_queue
                self._inference_worker = InferenceWorker(
                    self._vision_system,
                    self._frame_queue,
                    self._result_queue,
                    self._stop_event,
                )
            self._capture_worker.start()
            self._inference_worker.start()
            if self._position_worker is not None:
                self._position_worker.start()
            self._is_pipelined = True
            return True
        except Exception as exc:
            logger.warning("PipelinedDetector 启动失败，将回退串行模式: %s", exc)
            self.stop()
            return False

    def get_latest_detection(self, timeout=0.0):
        """返回最新检测结果，无新结果返回 None。跳过过期结果。

        先（可选）阻塞 ``timeout`` 等首个结果，再排空队列里所有剩余结果，只保留
        最新一个。``result_queue`` maxsize=1，通常只有 0 或 1 个结果，排空是为了
        健壮处理。
        """
        if self._result_queue is None:
            return None
        latest = None
        if timeout and timeout > 0:
            try:
                latest = self._result_queue.get(timeout=timeout)
            except queue.Empty:
                return None
        # 排空剩余，只保留最新（跳过过期结果）
        try:
            while True:
                latest = self._result_queue.get_nowait()
        except queue.Empty:
            pass
        return latest

    def stop(self):
        """停止所有线程，清理资源。idempotent，可重复调用。"""
        if self._stop_event is not None:
            self._stop_event.set()
        if self._inference_worker is not None and self._inference_worker.is_alive():
            try:
                self._inference_worker.join(timeout=2.0)
            except Exception:
                pass
        if self._position_worker is not None and self._position_worker.is_alive():
            try:
                self._position_worker.join(timeout=2.0)
            except Exception:
                pass
        if self._capture_worker is not None:
            stop_fn = getattr(self._capture_worker, "stop", None)
            if stop_fn is not None:
                try:
                    stop_fn()
                except Exception:
                    pass
            join_fn = getattr(self._capture_worker, "join", None)
            if join_fn is not None and self._capture_worker.is_alive():
                try:
                    join_fn(timeout=1.0)
                except Exception:
                    pass
        self._is_pipelined = False


class PositionWorker(threading.Thread):
    """从 intermediate_queue 取 (packet, target, capture_ms)，跑 calculate_object_position_smoothed，结果放 result_queue。

    与 :class:`InferenceWorker` 解耦，让 GPU 推理（detection 段）不被 CPU 位置计算
    （深度对齐 + mask 点云提取 + Kalman）阻塞，提升 inference_fps。

    帧数据流（启用 ``pipeline.position_worker_enabled`` 时）：
        InferenceWorker（仅 detection）→ intermediate_queue(maxsize=1) →
        PositionWorker（位置计算）→ result_queue(maxsize=1) → 主线程取最新结果。

    线程安全说明（高风险，默认禁用）：
        ``calculate_object_position_smoothed`` 会读写 ``VisionSystem`` 的
        ``kalman_3d``（predict/update）、``_kalman_last_time``、
        ``last_valid_position`` 等状态；同时 ``run_detection_tracked``（在
        InferenceWorker 线程执行）内部的 ``_select_target`` 在无跟踪目标时也会
        读写 ``kalman_3d`` / ``_kalman_last_time`` / ``last_valid_position``。
        启用本 worker 后这两个线程会并发访问这些共享状态，存在潜在竞争。

        未加锁的原因（权衡）：
        - 加 ``threading.Lock`` 会让 detection 段和 position 段重新串行化，失去
          异步收益（与默认串行路径等价但多了线程切换开销）。
        - 加 ``threading.RLock`` 虽不会死锁，但默认路径（InferenceWorker 同线程
          调用两段）会引入无竞争的锁开销，违反"默认路径不变"原则。
        - 因此本 worker 采用"尽力而为"策略：不加锁，仅在注释中标记风险。启用前
          请确认能接受偶发的 kalman 状态竞争（如预测漂移、dt 跳变）。生产环境
          务必保持 ``pipeline.position_worker_enabled=false``。

    默认不启用（``pipeline.position_worker_enabled=false``），由
    :class:`PipelinedDetector` 根据配置决定是否创建本 worker。
    """

    def __init__(self, vision_system, intermediate_queue, result_queue, stop_event):
        # vision_system: VisionSystem 实例
        # intermediate_queue: queue.Queue，InferenceWorker 入 (packet, target, capture_ms)
        # result_queue: queue.Queue(maxsize=1)，存最终结果（含 object_position）
        # stop_event: threading.Event
        super().__init__(daemon=True, name="position-worker")
        self._vision = vision_system
        self._intermediate_queue = intermediate_queue
        self._result_queue = result_queue
        self._stop_event = stop_event

    def run(self):
        while not self._stop_event.is_set():
            try:
                item = self._intermediate_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                packet, target, capture_ms = item
                object_position = self._vision.calculate_object_position_smoothed(
                    packet.depth_image, packet.color_image, target
                )
                result = {
                    "seq": packet.seq,
                    "capture_ms": capture_ms,
                    "target": target,
                    "object_position": object_position,
                }
                # 入 result_queue（maxsize=1），满了丢旧
                try:
                    self._result_queue.put_nowait(result)
                except queue.Full:
                    try:
                        self._result_queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        self._result_queue.put_nowait(result)
                    except queue.Full:
                        pass
            except Exception as exc:
                logger.warning("PositionWorker 位置计算失败: %s", exc)
