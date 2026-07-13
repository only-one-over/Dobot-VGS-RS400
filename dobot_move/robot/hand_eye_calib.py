#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import numpy as np
from ..config import config_manager
from .transform_utils import euler2rot as _euler2rot, pose2matrix as _pose2matrix


def _rot2euler(R, degree=True):
    sy = np.sqrt(R[0, 0] ** 2 + R[1, 0] ** 2)
    singular = sy < 1e-6
    if not singular:
        rx = np.arctan2(R[2, 1], R[2, 2])
        ry = np.arctan2(-R[2, 0], sy)
        rz = np.arctan2(R[1, 0], R[0, 0])
    else:
        rx = np.arctan2(-R[1, 2], R[1, 1])
        ry = np.arctan2(-R[2, 0], sy)
        rz = 0.0
    if degree:
        rx, ry, rz = np.degrees([rx, ry, rz])
    return rx, ry, rz


def _matrix2pose(T, degree=True):
    x, y, z = T[:3, 3]
    rx, ry, rz = _rot2euler(T[:3, :3], degree)
    return [x, y, z, rx, ry, rz]


_DEFAULT_CALIBRATIONS = {
    "D435i": {
        "cam_to_flange_pose": [10.12, -278.82, -137.24, 0.0, 0.0, 0.0],
    },
    "D405": {
        "cam_to_flange_pose": [10.12, -278.82, -137.24, 0.0, 0.0, 0.0],
    },
}


class HandEyeCalibManager:
    def __init__(self):
        self._calibrations = config_manager.get_all_calibrations()

    def get_matrix(self, camera_type) -> np.ndarray:
        return config_manager.get_camera_handeye_matrix(camera_type)

    def set_matrix_from_poses(self, camera_type, cam_to_flange_pose) -> bool:
        result = config_manager.set_calibration(camera_type, cam_to_flange_pose)
        if result:
            self._calibrations = config_manager.get_all_calibrations()
        return result

    def set_matrix_direct(self, camera_type, matrix_4x4) -> bool:
        cam_to_flange_pose = _matrix2pose(matrix_4x4)
        result = config_manager.set_calibration(camera_type, cam_to_flange_pose)
        if result:
            self._calibrations = config_manager.get_all_calibrations()
        return result

    def reset_to_default(self, camera_type) -> bool:
        defaults = _DEFAULT_CALIBRATIONS.get(camera_type)
        if defaults is None:
            return False
        result = config_manager.set_calibration(
            camera_type,
            list(defaults["cam_to_flange_pose"]),
        )
        if result:
            self._calibrations = config_manager.get_all_calibrations()
        return result

    def get_all_camera_types(self) -> list:
        return list(self._calibrations.keys())

    def get_poses(self, camera_type) -> dict:
        calib = config_manager.get_calibration(camera_type)
        return {
            "cam_to_flange_pose": calib.get("cam_to_flange_pose", []),
        }
