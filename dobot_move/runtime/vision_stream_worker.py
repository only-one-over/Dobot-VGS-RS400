"""Background diagnostic vision stream worker.

When the production stream is not running, this worker launches a
CaptureWorker + InferenceWorker pipeline (reusing the same parameters as
production via run_detection_tracked with yolo_every_n skip-frame +
ByteTrack tracking). The InferenceWorker's built-in fan-out (see
InferenceWorker._run_inference) publishes annotated JPEG frames into the
registered DiagnosticFrameCache, so this worker only manages the pipeline
lifecycle and cache registration.
"""

from __future__ import annotations

import logging

from .diagnostic_frame_cache import DiagnosticFrameCache

logger = logging.getLogger(__name__)


class VisionStreamWorker:
    """Lifecycle manager for the diagnostic vision pipeline.

    Starts a PipelinedDetector and registers a DiagnosticFrameCache on the
    VisionSystem so that InferenceWorker's fan-out publishes each inferred
    frame. Stopping tears down the pipeline and unregisters the cache.
    """

    def __init__(
        self,
        vision,
        controller,
        camera_type: str,
        cache: DiagnosticFrameCache,
    ) -> None:
        """Configure the worker with its dependencies.

        Args:
            vision: VisionSystem instance (provides reset_tracking and
                drives CaptureWorker/InferenceWorker; _diagnostic_cache
                attribute is set/cleared by this worker).
            controller: Robot controller (reserved for future coordinate
                transforms; not used currently).
            camera_type: Camera identifier (reserved for metadata; the
                InferenceWorker fan-out does not currently include it).
            cache: DiagnosticFrameCache where annotated frames are published.
        """
        self._vision = vision
        self._controller = controller
        self._camera_type = camera_type
        self._cache = cache
        self._pipelined = None

    @property
    def is_running(self) -> bool:
        """Whether the pipeline is currently active."""
        return self._pipelined is not None and self._pipelined.is_pipelined

    def start(self) -> bool:
        """Register the cache, reset tracking, and start the pipeline.

        Returns:
            True if the pipeline started successfully, False otherwise.
            Calling start while already running is a no-op returning True.
        """
        if self.is_running:
            return True

        # 注册诊断缓存：InferenceWorker 的 fan-out 会检测此属性并每帧写入
        self._vision._diagnostic_cache = self._cache
        self._vision.reset_tracking()

        # Lazy import: 复用 flow_executor.py 的流水线模式（纯 Python 采集线程，
        # 无 Qt 依赖）。position_worker_enabled=False 保持位置计算在 InferenceWorker
        # 内单线程完成，避免 kalman_3d 等共享状态的并发风险。
        from ..vision.capture_worker import CaptureWorker
        from ..vision.vision_system import PipelinedDetector

        self._pipelined = PipelinedDetector(
            capture_worker_factory=lambda frame_queue: CaptureWorker(
                self._vision, frame_queue=frame_queue
            ),
            vision_system=self._vision,
            position_worker_enabled=False,
        )
        if not self._pipelined.start():
            logger.warning("vision-stream-worker: PipelinedDetector.start() 失败")
            # 启动失败要注销 cache，避免悬空引用
            self._vision._diagnostic_cache = None
            self._pipelined = None
            return False
        logger.info("vision-stream-worker: 流水线已启动，fan-out 将自动写入诊断缓存")
        return True

    def stop(self) -> None:
        """Stop the pipeline and unregister the cache.

        Idempotent: safe to call multiple times or when never started.
        """
        # 先注销 cache，防止停止过程中 InferenceWorker 再写入已关闭的流水线
        self._vision._diagnostic_cache = None
        if self._pipelined is not None:
            try:
                self._pipelined.stop()
            except Exception:
                logger.exception("vision-stream-worker: pipelined.stop 抛异常")
            self._pipelined = None
        logger.info("vision-stream-worker: 流水线已停止，诊断缓存已注销")
