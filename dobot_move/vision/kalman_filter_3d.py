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
        # tracking quality metrics & covariance gating
        self.prediction_age = 0.0  # accumulated dt since last successful update
        self.miss_count = 0
        self.last_update_time = None  # retained for backward compatibility
        self.gate_threshold = 3.0  # Mahalanobis distance threshold (d^2 > gate^2 rejected)
        self.max_miss_count = 10
        # Task 4: prediction gate — predictions older than this are unreliable
        self.prediction_gate = 0.5  # seconds

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
        # Task 1: Constant-velocity (CV) model discrete-time process noise matrix
        # Q = σ² × [[dt⁴/4, 0, 0, dt³/2, 0, 0],
        #           [0, dt⁴/4, 0, 0, dt³/2, 0],
        #           [0, 0, dt⁴/4, 0, 0, dt³/2],
        #           [dt³/2, 0, 0, dt², 0, 0],
        #           [0, dt³/2, 0, 0, dt², 0],
        #           [0, 0, dt³/2, 0, 0, dt²]]
        dt2 = dt * dt
        dt3 = dt2 * dt
        dt4 = dt2 * dt2
        q4 = dt4 / 4.0
        q3 = dt3 / 2.0
        q2 = dt2
        Q = np.array([
            [q4, 0,   0,   q3, 0,   0  ],
            [0,  q4,  0,   0,  q3,  0  ],
            [0,  0,   q4,  0,  0,   q3 ],
            [q3, 0,   0,   q2, 0,   0  ],
            [0,  q3,  0,   0,  q2,  0  ],
            [0,  0,   q3,  0,  0,   q2 ],
        ], dtype=np.float64) * process_noise
        return Q

    def predict(self, dt=None):
        if dt is None:
            dt = self.dt
        self.F = self._build_F(dt)
        self.Q = self._build_Q(dt, self.process_noise)
        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q
        # Task 3: accumulate prediction_age by dt (not wall clock)
        self.prediction_age += dt
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
        # Task 2: predict (time update) BEFORE gating
        self.predict(dt)
        # Mahalanobis gating based on predicted state
        y = z - self.H @ self.x
        S = self.H @ self.P @ self.H.T + self.R
        d_sq = float(y.T @ np.linalg.inv(S) @ y)
        if d_sq > self.gate_threshold ** 2:
            # Reject measurement as outlier; keep predicted state (no rollback)
            self.miss_count += 1
            if self.miss_count >= self.max_miss_count:
                self.reset()
                return z[:3].copy()
            return self.x[:3].copy()
        # Measurement update (Kalman gain, state correction, covariance update)
        K = self.P @ self.H.T @ np.linalg.inv(S)
        self.x = self.x + K @ y
        I_KH = np.eye(6) - K @ self.H
        self.P = I_KH @ self.P
        self.miss_count = 0
        self.last_update_time = time.perf_counter()
        self.prediction_age = 0.0
        return self.x[:3].copy()

    def is_prediction_reliable(self):
        # Task 4: prediction is reliable only within the prediction gate
        return self.prediction_age <= self.prediction_gate

    def get_covariance(self):
        """Return a copy of the 3×3 position covariance block P[:3, :3]."""
        return self.P[:3, :3].copy()

    def get_confidence(self):
        pos_var = np.trace(self.P[:3, :3])
        base = 1.0 / (1.0 + pos_var)
        # Task 4: attenuate confidence to 0 when prediction is no longer reliable
        if not self.is_prediction_reliable():
            return 0.0
        return base

    def reset(self):
        self.x = np.zeros(6)
        self.P = np.eye(6) * 1000
        self.initialized = False
        self.prediction_age = 0.0
        self.miss_count = 0
        self.last_update_time = None
