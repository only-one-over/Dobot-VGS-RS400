#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import numpy as np

logger = logging.getLogger(__name__)

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    cv2 = None
    HAS_CV2 = False

try:
    import pyrealsense2 as rs
    HAS_REALSENSE = True
except ImportError:
    HAS_REALSENSE = False


class DepthProcessor:
    def __init__(self, min_depth=0.5, max_depth=2.2, depth_scale=0.001,
                 enable_decimation=True, enable_spatial=True,
                 enable_temporal=True, enable_hole_filling=True,
                 decimation_magnitude=2,
                 spatial_alpha=0.5, spatial_delta=20, spatial_magnitude=2, spatial_holes_fill=0,
                 temporal_alpha=0.4, temporal_delta=20, temporal_persist_mode=2,
                 hole_filling_mode=1):
        self.min_depth = min_depth
        self.max_depth = max_depth
        self.depth_scale = depth_scale
        self.enable_decimation = enable_decimation
        self.enable_spatial = enable_spatial
        self.enable_temporal = enable_temporal
        self.enable_hole_filling = enable_hole_filling
        self.decimation_magnitude = decimation_magnitude
        self.spatial_alpha = spatial_alpha
        self.spatial_delta = spatial_delta
        self.spatial_magnitude = spatial_magnitude
        self.spatial_holes_fill = spatial_holes_fill
        self.temporal_alpha = temporal_alpha
        self.temporal_delta = temporal_delta
        self.temporal_persist_mode = temporal_persist_mode
        self.hole_filling_mode = hole_filling_mode
        self._filters = []
        self._init_realsense_filters()

    def _init_realsense_filters(self):
        if not HAS_REALSENSE:
            logger.warning("⚠️ pyrealsense2 未安装，深度滤波链不可用")
            return

        if self.enable_decimation:
            decimation = rs.decimation_filter()
            decimation.set_option(rs.option.filter_magnitude, self.decimation_magnitude)
            self._filters.append(("Decimation", decimation))

        if self.enable_spatial:
            spatial = rs.spatial_filter()
            spatial.set_option(rs.option.filter_magnitude, self.spatial_magnitude)
            spatial.set_option(rs.option.filter_smooth_alpha, self.spatial_alpha)
            spatial.set_option(rs.option.filter_smooth_delta, self.spatial_delta)
            spatial.set_option(rs.option.holes_fill, self.spatial_holes_fill)
            self._filters.append(("Spatial", spatial))

        if self.enable_temporal:
            temporal = rs.temporal_filter()
            temporal.set_option(rs.option.filter_smooth_alpha, self.temporal_alpha)
            temporal.set_option(rs.option.filter_smooth_delta, self.temporal_delta)
            temporal.set_option(rs.option.holes_fill, self.temporal_persist_mode)
            self._filters.append(("Temporal", temporal))

        if self.enable_hole_filling:
            hole_filling = rs.hole_filling_filter()
            hole_filling.set_option(rs.option.holes_fill, self.hole_filling_mode)
            self._filters.append(("HoleFilling", hole_filling))

        logger.info(f"✅ RealSense 滤波链已初始化: {' → '.join(name for name, _ in self._filters)}")

    def process_frame(self, depth_frame):
        if not HAS_REALSENSE or not self._filters:
            return depth_frame
        filtered = depth_frame
        for name, f in self._filters:
            try:
                filtered = f.process(filtered)
            except Exception as e:
                logger.warning(f"⚠️ {name} 滤波器处理失败: {e}")
        return filtered

    def process_depth_image(self, depth_image):
        if not HAS_CV2:
            logger.warning("⚠️ opencv-python 未安装，深度图像修补不可用")
            return depth_image
        mask_invalid = (depth_image == 0).astype(np.uint8)
        if np.sum(mask_invalid) == 0:
            return depth_image
        depth_filled = cv2.inpaint(depth_image, mask_invalid, 3, cv2.INPAINT_NS)
        return depth_filled
