#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import numpy as np


class KalmanFilter3D:
    def __init__(self, dt=1.0/30, process_noise=1.0, measurement_noise=5.0):
        self.dt = dt
        self.F = np.array([
            [1, 0, 0, dt, 0,  0],
            [0, 1, 0, 0,  dt, 0],
            [0, 0, 1, 0,  0,  dt],
            [0, 0, 0, 1,  0,  0],
            [0, 0, 0, 0,  1,  0],
            [0, 0, 0, 0,  0,  1],
        ])
        self.H = np.array([
            [1, 0, 0, 0, 0, 0],
            [0, 1, 0, 0, 0, 0],
            [0, 0, 1, 0, 0, 0],
        ])
        self.Q = np.eye(6) * process_noise
        self.R = np.eye(3) * measurement_noise
        self.x = np.zeros(6)
        self.P = np.eye(6) * 1000
        self.initialized = False

    def predict(self):
        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q
        return self.x[:3].copy()

    def update(self, z):
        z = np.array(z[:3], dtype=np.float64)
        if not self.initialized:
            self.x[:3] = z
            self.initialized = True
            return self.x[:3].copy()
        y = z - self.H @ self.x
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        self.x = self.x + K @ y
        I_KH = np.eye(6) - K @ self.H
        self.P = I_KH @ self.P
        return self.x[:3].copy()

    def get_confidence(self):
        pos_var = np.trace(self.P[:3, :3])
        return 1.0 / (1.0 + pos_var)

    def reset(self):
        self.x = np.zeros(6)
        self.P = np.eye(6) * 1000
        self.initialized = False
