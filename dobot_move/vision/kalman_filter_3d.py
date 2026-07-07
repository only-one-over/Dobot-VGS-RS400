#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time

import numpy as np


class KalmanFilter3D:
    def __init__(self, dt=1.0/30, process_noise=1.0, measurement_noise=5.0):
        self.dt = dt
        self.process_noise = process_noise
        self.measurement_noise = measurement_noise
        self.F = self._build_F(dt)
        self.H = np.array([
            [1, 0, 0, 0, 0, 0],
            [0, 1, 0, 0, 0, 0],
            [0, 0, 1, 0, 0, 0],
        ])
        self.Q = self._build_Q(dt, process_noise)
        self.R = np.eye(3) * measurement_noise
        self.x = np.zeros(6)
        self.P = np.eye(6) * 1000
        self.initialized = False
        # Task 8: tracking quality metrics & covariance gating
        self.prediction_age = 0.0  # seconds since last successful update
        self.miss_count = 0
        self.last_update_time = None  # time.perf_counter() value or None
        self.gate_threshold = 3.0  # Mahalanobis distance threshold (d^2 > gate^2 rejected)
        self.max_miss_count = 10

    def _build_F(self, dt):
        return np.array([
            [1, 0, 0, dt, 0,  0],
            [0, 1, 0, 0,  dt, 0],
            [0, 0, 1, 0,  0,  dt],
            [0, 0, 0, 1,  0,  0],
            [0, 0, 0, 0,  1,  0],
            [0, 0, 0, 0,  0,  1],
        ])

    def _build_Q(self, dt, process_noise):
        return np.eye(6) * process_noise * dt

    def predict(self, dt=None):
        if dt is None:
            dt = self.dt
        self.F = self._build_F(dt)
        self.Q = self._build_Q(dt, self.process_noise)
        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q
        if self.last_update_time is not None:
            self.prediction_age = time.perf_counter() - self.last_update_time
        return self.x[:3].copy()

    def update(self, z, dt=None):
        z = np.array(z[:3], dtype=np.float64)
        if not self.initialized:
            self.x[:3] = z
            self.initialized = True
            self.last_update_time = time.perf_counter()
            self.miss_count = 0
            self.prediction_age = 0.0
            return self.x[:3].copy()
        if dt is None:
            dt = self.dt
        # Mahalanobis gating on current state (before time update)
        y = z - self.H @ self.x
        S = self.H @ self.P @ self.H.T + self.R
        d_sq = float(y.T @ np.linalg.inv(S) @ y)
        if d_sq > self.gate_threshold ** 2:
            # Reject measurement as outlier; predict forward only
            self.miss_count += 1
            if self.miss_count >= self.max_miss_count:
                self.reset()
                return z[:3].copy()
            return self.predict(dt)
        # Normal Kalman update
        self.F = self._build_F(dt)
        self.Q = self._build_Q(dt, self.process_noise)
        K = self.P @ self.H.T @ np.linalg.inv(S)
        self.x = self.x + K @ y
        I_KH = np.eye(6) - K @ self.H
        self.P = I_KH @ self.P
        self.miss_count = 0
        self.last_update_time = time.perf_counter()
        self.prediction_age = 0.0
        return self.x[:3].copy()

    def get_confidence(self):
        pos_var = np.trace(self.P[:3, :3])
        return 1.0 / (1.0 + pos_var)

    def reset(self):
        self.x = np.zeros(6)
        self.P = np.eye(6) * 1000
        self.initialized = False
        self.prediction_age = 0.0
        self.miss_count = 0
        self.last_update_time = None
