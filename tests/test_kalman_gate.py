#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Task 8: 跟踪质量指标与协方差门控单元测试。"""

import numpy as np

from dobot_move.vision.kalman_filter_3d import KalmanFilter3D


def test_normal_measurement_passes_gate():
    """正常测量通过门控：连续两次相近 update，miss_count=0，prediction_age≈0。"""
    kf = KalmanFilter3D()
    kf.update([0.0, 0.0, 0.0])  # initialize state at origin
    kf.update([0.01, 0.01, 0.01])  # close measurement, should pass gate

    assert kf.miss_count == 0
    assert kf.prediction_age >= 0.0
    # recently updated -> age should be tiny
    assert kf.prediction_age < 1.0


def test_outlier_measurement_rejected_by_gate():
    """测量被门控拒绝：远超 3σ 的测量被拒，miss_count=1，返回预测值而非测量值。"""
    kf = KalmanFilter3D(measurement_noise=5.0)
    kf.update([0.0, 0.0, 0.0])  # initialize at origin

    # Far outlier: d_sq ~ 1000^2/1005 ≈ 995 >> gate_threshold^2 = 9
    out = kf.update([1000.0, 0.0, 0.0])

    assert kf.miss_count == 1
    # Returned value should be the prediction (near origin), NOT the measurement
    assert out[0] < 100.0
    assert np.allclose(out, [0.0, 0.0, 0.0], atol=1e-6)


def test_max_miss_count_triggers_reset():
    """miss_count 累加到 max 触发 reset：连续多次被拒绝后 initialized 变 False。"""
    kf = KalmanFilter3D()
    kf.update([0.0, 0.0, 0.0])  # initialize

    max_miss = kf.max_miss_count
    for _ in range(max_miss):
        kf.update([1000.0, 0.0, 0.0])  # always gated as outlier

    # After max_miss_count gated updates, reset() should have been called
    assert kf.initialized is False
    assert kf.miss_count == 0  # reset clears miss_count
    assert kf.last_update_time is None


def test_metrics_readable():
    """指标可读：kf.prediction_age 和 kf.miss_count 可读取。"""
    kf = KalmanFilter3D()
    # Before init
    assert hasattr(kf, "prediction_age")
    assert hasattr(kf, "miss_count")
    assert kf.prediction_age == 0.0
    assert kf.miss_count == 0

    kf.update([1.0, 2.0, 3.0])
    age = kf.prediction_age
    miss = kf.miss_count
    assert isinstance(age, float)
    assert isinstance(miss, int)
    assert miss == 0


def test_update_with_dt_works():
    """传 dt 的 update 正常工作。"""
    kf = KalmanFilter3D()
    kf.update([0.0, 0.0, 0.0], dt=0.05)
    out = kf.update([0.1, 0.0, 0.0], dt=0.05)

    assert out.shape == (3,)
    assert np.all(np.isfinite(out))
    assert kf.miss_count == 0
    # smoothed position should move toward the new measurement (between 0 and 0.1)
    assert 0.0 <= out[0] <= 0.1
