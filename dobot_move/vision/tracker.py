#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging

import numpy as np
from scipy.optimize import linear_sum_assignment

logger = logging.getLogger(__name__)


def iou_distance(atracks, btracks):
    if len(atracks) == 0 or len(btracks) == 0:
        return np.empty((len(atracks), len(btracks)), dtype=np.float64)
    abboxes = np.asarray([a.bbox for a in atracks], dtype=np.float64)
    bbboxes = np.asarray([b.bbox for b in btracks], dtype=np.float64)
    xx1 = np.maximum(abboxes[:, None, 0], bbboxes[None, :, 0])
    yy1 = np.maximum(abboxes[:, None, 1], bbboxes[None, :, 1])
    xx2 = np.minimum(abboxes[:, None, 2], bbboxes[None, :, 2])
    yy2 = np.minimum(abboxes[:, None, 3], bbboxes[None, :, 3])
    w = np.maximum(0.0, xx2 - xx1)
    h = np.maximum(0.0, yy2 - yy1)
    inter = w * h
    area_a = ((abboxes[:, 2] - abboxes[:, 0]) * (abboxes[:, 3] - abboxes[:, 1]))[:, None]
    area_b = ((bbboxes[:, 2] - bbboxes[:, 0]) * (bbboxes[:, 3] - bbboxes[:, 1]))[None, :]
    union = area_a + area_b - inter
    iou = inter / (union + 1e-6)
    return 1.0 - iou


def linear_assignment(cost_matrix, thresh):
    if cost_matrix.size == 0:
        return [], list(range(cost_matrix.shape[0])), list(range(cost_matrix.shape[1]))
    row_ind, col_ind = linear_sum_assignment(cost_matrix)
    matches, unmatched_a, unmatched_b = [], [], []
    for r, c in zip(row_ind, col_ind):
        if cost_matrix[r, c] > thresh:
            unmatched_a.append(r)
            unmatched_b.append(c)
        else:
            matches.append((r, c))
    unmatched_a += [a for a in range(cost_matrix.shape[0]) if a not in row_ind]
    unmatched_b += [b for b in range(cost_matrix.shape[1]) if b not in col_ind]
    return matches, unmatched_a, unmatched_b


class STrack:
    _id_counter = 0

    def __init__(self, bbox, score, mask=None, class_id=0):
        self.bbox = np.array(bbox, dtype=np.float64)
        self.score = score
        self.mask = mask
        self.class_id = class_id
        self.track_id = STrack._id_counter
        STrack._id_counter += 1
        self.state = "new"
        self.frame_id = 0
        self.start_frame = 0
        self.track_len = 0
        self.kalman = self._init_kalman()

    def _init_kalman(self):
        kf = _BBoxKalmanFilter()
        kf.update(self.bbox)
        return kf

    def predict(self):
        self.bbox = self.kalman.predict()
        return self.bbox

    def update(self, det):
        self.bbox = np.array(det['bbox'], dtype=np.float64)
        self.score = det['score']
        self.mask = det.get('mask', self.mask)
        self.kalman.update(self.bbox)
        self.state = "tracked"

    @staticmethod
    def reset_id_counter():
        STrack._id_counter = 0


class _BBoxKalmanFilter:
    def __init__(self):
        self.x = np.zeros(8)
        self.P = np.eye(8) * 10
        self.F = np.eye(8)
        for i in range(4):
            self.F[i, i + 4] = 1.0
        self.H = np.zeros((4, 8))
        for i in range(4):
            self.H[i, i] = 1.0
        self.Q = np.eye(8) * 0.01
        self.R = np.eye(4) * 1.0
        self.initialized = False

    def predict(self):
        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q
        return self.x[:4].copy()

    def update(self, z):
        z = np.array(z[:4], dtype=np.float64)
        if not self.initialized:
            self.x[:4] = z
            self.initialized = True
            return self.x[:4].copy()
        y = z - self.H @ self.x
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        self.x = self.x + K @ y
        self.P = (np.eye(8) - K @ self.H) @ self.P
        return self.x[:4].copy()


class BYTETracker:
    def __init__(self, track_thresh=0.5, match_thresh=0.8, track_buffer=30):
        self.track_thresh = track_thresh
        self.match_thresh = match_thresh
        self.track_buffer = track_buffer
        self.tracked_stracks = []
        self.lost_stracks = []
        self.removed_stracks = []
        self.frame_id = 0

    def update(self, detections, img_size):
        self.frame_id += 1
        img_w, img_h = img_size

        if not detections:
            for t in self.tracked_stracks:
                t.state = "lost"
                self.lost_stracks.append(t)
            self.tracked_stracks = []
            self._remove_lost()
            return []

        dets_high = []
        dets_low = []
        for det in detections:
            if det['score'] >= self.track_thresh:
                dets_high.append(det)
            else:
                dets_low.append(det)

        stracks_high = [STrack(d['bbox'], d['score'], d.get('mask'), d.get('class_id', 0)) for d in dets_high]

        for t in self.tracked_stracks:
            t.predict()

        if len(self.tracked_stracks) > 0 and len(stracks_high) > 0:
            cost = iou_distance(self.tracked_stracks, stracks_high)
            matches, u_track, u_det = linear_assignment(cost, self.match_thresh)
            for m_t, m_d in matches:
                if 0 <= m_t < len(self.tracked_stracks) and 0 <= m_d < len(dets_high):
                    self.tracked_stracks[m_t].update(dets_high[m_d])
                else:
                    logger.warning("忽略非法跟踪匹配索引: track=%s det=%s", m_t, m_d)
            for t_idx in u_track:
                if 0 <= t_idx < len(self.tracked_stracks):
                    self.tracked_stracks[t_idx].state = "lost"
                    self.lost_stracks.append(self.tracked_stracks[t_idx])
                else:
                    logger.warning("忽略非法未匹配track索引: track=%s", t_idx)
            new_tracks = []
            for d_idx in u_det:
                if 0 <= d_idx < len(stracks_high):
                    new_tracks.append(stracks_high[d_idx])
                else:
                    logger.warning("忽略非法未匹配检测索引: det=%s high_count=%s", d_idx, len(stracks_high))
        elif len(stracks_high) > 0:
            new_tracks = stracks_high
        else:
            for t in self.tracked_stracks:
                t.state = "lost"
                self.lost_stracks.append(t)
            new_tracks = []

        if len(self.lost_stracks) > 0 and len(dets_low) > 0:
            stracks_low = [STrack(d['bbox'], d['score'], d.get('mask'), d.get('class_id', 0)) for d in dets_low]
            cost_low = iou_distance(self.lost_stracks, stracks_low)
            matches_low, _, _ = linear_assignment(cost_low, self.match_thresh)
            for m_t, m_d in matches_low:
                if 0 <= m_t < len(self.lost_stracks) and 0 <= m_d < len(dets_low):
                    self.lost_stracks[m_t].update(dets_low[m_d])
                    self.lost_stracks[m_t].state = "tracked"
                    new_tracks.append(self.lost_stracks[m_t])
                else:
                    logger.warning("忽略非法低置信匹配索引: track=%s det=%s", m_t, m_d)
            self.lost_stracks = [t for i, t in enumerate(self.lost_stracks) if i not in set(m_t for m_t, _ in matches_low)]

        self.tracked_stracks = [t for t in self.tracked_stracks if t.state == "tracked"]
        self.tracked_stracks.extend(new_tracks)

        self._remove_lost()

        return [t for t in self.tracked_stracks if t.state == "tracked"]

    def _remove_lost(self):
        remain = []
        for t in self.lost_stracks:
            if self.frame_id - t.frame_id <= self.track_buffer:
                remain.append(t)
            else:
                self.removed_stracks.append(t)
        self.lost_stracks = remain

    def reset(self):
        self.tracked_stracks = []
        self.lost_stracks = []
        self.removed_stracks = []
        self.frame_id = 0
        STrack.reset_id_counter()
