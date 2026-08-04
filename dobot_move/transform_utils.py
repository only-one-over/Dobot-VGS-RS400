#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import numpy as np

try:
    import dobot_core
    DOBOT_CORE_AVAILABLE = True
except ImportError:
    DOBOT_CORE_AVAILABLE = False


def _euler2rot_py(rx, ry, rz, degree=True):
    if degree:
        rx, ry, rz = np.radians([rx, ry, rz])
    Rx = np.array([[1, 0, 0],
                   [0, np.cos(rx), -np.sin(rx)],
                   [0, np.sin(rx), np.cos(rx)]])
    Ry = np.array([[np.cos(ry), 0, np.sin(ry)],
                   [0, 1, 0],
                   [-np.sin(ry), 0, np.cos(ry)]])
    Rz = np.array([[np.cos(rz), -np.sin(rz), 0],
                   [np.sin(rz), np.cos(rz), 0],
                   [0, 0, 1]])
    R = Rz @ Ry @ Rx
    return R


def _pose2matrix_py(x, y, z, rx, ry, rz):
    R = euler2rot(rx, ry, rz)
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = [x, y, z]
    return T


def euler2rot(rx, ry, rz, degree=True):
    if DOBOT_CORE_AVAILABLE:
        try:
            return dobot_core.transforms.euler2rot(rx, ry, rz, degree)
        except Exception:
            pass
    return _euler2rot_py(rx, ry, rz, degree)


def pose2matrix(x, y, z, rx, ry, rz):
    if DOBOT_CORE_AVAILABLE:
        try:
            return dobot_core.transforms.pose2matrix(x, y, z, rx, ry, rz)
        except Exception:
            pass
    return _pose2matrix_py(x, y, z, rx, ry, rz)
