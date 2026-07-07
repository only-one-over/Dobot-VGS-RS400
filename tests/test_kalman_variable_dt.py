#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import numpy as np

from dobot_move.vision.kalman_filter_3d import KalmanFilter3D


def test_predict_with_explicit_dt_updates_F_and_advances_state():
    kf = KalmanFilter3D(dt=1.0/30)
    kf.update([1.0, 2.0, 3.0])  # initialize state
    # impose a known velocity so dt propagation is observable in position
    kf.x[3] = 1.0  # vx = 1 unit/s
    pos_before = float(kf.x[0])

    predicted = kf.predict(dt=0.071)

    # F matrix should reflect the requested dt
    assert np.isclose(kf.F[0, 3], 0.071)
    # position should advance by dt * vx
    assert np.isclose(predicted[0], pos_before + 0.071 * 1.0)


def test_predict_without_dt_uses_default():
    kf = KalmanFilter3D(dt=1.0/30)
    kf.update([1.0, 2.0, 3.0])
    default_pred = kf.predict()

    kf2 = KalmanFilter3D(dt=1.0/30)
    kf2.update([1.0, 2.0, 3.0])
    explicit_pred = kf2.predict(dt=1.0/30)

    assert np.allclose(default_pred, explicit_pred)
    assert np.isclose(kf.F[0, 3], 1.0/30)


def test_update_first_call_initializes_state_with_dt():
    kf = KalmanFilter3D(dt=1.0/30)
    out = kf.update([1.0, 2.0, 3.0], dt=0.08)

    assert kf.initialized is True
    assert np.allclose(out, [1.0, 2.0, 3.0])
    assert np.allclose(kf.x[:3], [1.0, 2.0, 3.0])


def test_update_subsequent_with_different_dt_converges():
    kf = KalmanFilter3D(dt=1.0/30)
    kf.update([1.0, 2.0, 3.0])

    out = kf.update([1.1, 2.1, 3.1], dt=0.05)

    assert np.all(np.isfinite(out))
    # smoothed position should move toward the new measurement
    assert 1.0 < out[0] <= 1.1
    assert 2.0 < out[1] <= 2.1
    assert 3.0 < out[2] <= 3.1


def test_backward_compatible_calls_without_dt():
    kf = KalmanFilter3D()

    p = kf.predict()
    assert p.shape == (3,)

    out = kf.update([1.0, 2.0, 3.0])
    assert np.allclose(out, [1.0, 2.0, 3.0])

    out2 = kf.update([1.0, 2.0, 3.0])
    assert out2.shape == (3,)

    conf = kf.get_confidence()
    assert 0.0 < conf <= 1.0

    kf.reset()
    assert kf.initialized is False
